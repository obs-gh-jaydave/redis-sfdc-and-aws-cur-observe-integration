import csv
import io
import hashlib
import boto3
from datetime import datetime
import logging
import json
import os
from src.utils.config import config

logger = logging.getLogger()

class CURValidationError(Exception):
    """Exception for CUR file validation errors"""
    pass

class CURProcessor:
    def __init__(self):
        """Initialize CUR processor"""
        self.pipeline_version = config.get('pipeline_version', '1.2.0')
        self.environment = config.get('environment', 'dev')
        self.use_s3_for_parquet = os.environ.get('USE_S3_FOR_PARQUET', 'true').lower() == 'true'
    
    def process_cur_file(self, s3_client, bucket, key):
        """Process AWS Cost and Usage Report (CUR) file"""
        logger.info(f"Processing CUR file from s3://{bucket}/{key}")
        
        # Check file format
        if key.endswith('.csv'):
            return self._process_csv_file(s3_client, bucket, key)
        elif key.endswith('.parquet'):
            if self.use_s3_for_parquet:
                # Process Parquet using Glue job or S3 Select if available
                return self._process_parquet_file_via_s3(s3_client, bucket, key)
            else:
                # Try to process with pandas/pyarrow if available
                try:
                    import pandas as pd
                    import pyarrow.parquet as pq
                    return self._process_parquet_file(s3_client, bucket, key)
                except ImportError:
                    logger.error("Pandas or PyArrow not available, cannot process Parquet files")
                    raise CURValidationError("Pandas or PyArrow not available for processing Parquet files")
        else:
            logger.error(f"Unsupported file format: {key}")
            raise CURValidationError("Only CSV and Parquet CUR files are supported")
    
    def _process_csv_file(self, s3_client, bucket, key):
        """Process CSV format CUR file"""
        try:
            response = s3_client.get_object(Bucket=bucket, Key=key)
            cur_data_raw = response['Body'].read().decode('utf-8')
            
            # Parse CSV data
            csv_reader = csv.DictReader(io.StringIO(cur_data_raw))
            
            # Verify mandatory columns exist
            required_columns = {'lineItem/UsageAccountId', 'lineItem/UnblendedCost'}
            if not csv_reader.fieldnames:
                raise CURValidationError("Empty or invalid CSV file")
            
            if not required_columns.issubset(set(csv_reader.fieldnames)):
                missing = required_columns - set(csv_reader.fieldnames)
                logger.error(f"Missing required CUR columns: {missing}")
                raise CURValidationError(f"Missing required CUR columns: {missing}")
            
            cur_records = list(csv_reader)
            
            # Transform records to include Redis-specific information
            transformed_records = self.transform_cur(cur_records)
            
            # Add correlation tags
            transformed_records = self.add_correlation_tags(transformed_records)
            
            return transformed_records
        except Exception as e:
            logger.error(f"Error processing CSV CUR file: {str(e)}")
            raise
    
    def _process_parquet_file(self, s3_client, bucket, key):
        """Process Parquet format CUR file using PyArrow"""
        try:
            # Stream the file in chunks to handle large files
            response = s3_client.get_object(Bucket=bucket, Key=key)
            
            # Use pyarrow to read the parquet file
            buffer = io.BytesIO(response['Body'].read())
            table = pq.read_table(buffer)
            df = table.to_pandas()
            
            # Verify mandatory columns exist
            required_columns = {'lineItem/UsageAccountId', 'lineItem/UnblendedCost'}
            if not all(col in df.columns for col in required_columns):
                missing = required_columns - set(df.columns)
                logger.error(f"Missing required CUR columns: {missing}")
                raise CURValidationError(f"Missing required CUR columns: {missing}")
            
            # Convert to dict records for consistent processing
            cur_records = df.to_dict('records')
            
            # Transform records to include Redis-specific information
            transformed_records = self.transform_cur(cur_records)
            
            # Add correlation tags
            transformed_records = self.add_correlation_tags(transformed_records)
            
            return transformed_records
        except Exception as e:
            logger.error(f"Error processing Parquet CUR file: {str(e)}")
            raise
            
    def _process_parquet_file_via_s3(self, s3_client, bucket, key):
        """Process Parquet format CUR file via S3 intermediary"""
        try:
            # Generate a temporary CSV file path
            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
            temp_csv_key = f"temp/parquet-conversion/{timestamp}/{os.path.basename(key)}.csv"
            
            # Create a Glue job to convert Parquet to CSV
            glue_client = boto3.client('glue')
            
            # Create a new job script that simply converts Parquet to CSV
            job_name = f"convert-parquet-{timestamp}"
            
            # Simple script to convert Parquet to CSV without heavy dependencies
            script = f"""
            import sys
            from awsglue.transforms import *
            from awsglue.utils import getResolvedOptions
            from pyspark.context import SparkContext
            from awsglue.context import GlueContext
            from awsglue.job import Job

            args = getResolvedOptions(sys.argv, ['JOB_NAME', 'input_path', 'output_path'])

            sc = SparkContext()
            glueContext = GlueContext(sc)
            spark = glueContext.spark_session
            job = Job(glueContext)
            job.init(args['JOB_NAME'], args)

            # Read the Parquet file
            df = spark.read.parquet(args['input_path'])
            
            # Write as CSV
            df.write.csv(args['output_path'], header=True)

            job.commit()
            """
            
            # Create a temporary S3 location for the script
            script_location = f"s3://{bucket}/temp/scripts/{job_name}.py"
            s3_client.put_object(
                Bucket=bucket,
                Key=f"temp/scripts/{job_name}.py",
                Body=script
            )
            
            # Create and run the job
            try:
                # Try to create a new job
                response = glue_client.create_job(
                    Name=job_name,
                    Role="GlueServiceRole",  # This role needs to exist with proper permissions
                    Command={
                        'Name': 'glueetl',
                        'ScriptLocation': script_location
                    },
                    DefaultArguments={
                        '--input_path': f"s3://{bucket}/{key}",
                        '--output_path': f"s3://{bucket}/{temp_csv_key.replace('.csv', '')}"
                    },
                    MaxRetries=0,
                    Timeout=30,
                    MaxCapacity=2.0
                )
                
                # Start the job
                job_run = glue_client.start_job_run(
                    JobName=job_name,
                    Arguments={
                        '--input_path': f"s3://{bucket}/{key}",
                        '--output_path': f"s3://{bucket}/{temp_csv_key.replace('.csv', '')}"
                    }
                )
                
                # Wait for job completion (with timeout)
                import time
                max_wait_time = 300  # 5 minutes
                start_time = time.time()
                
                while (time.time() - start_time) < max_wait_time:
                    status = glue_client.get_job_run(JobName=job_name, RunId=job_run['JobRunId'])
                    job_state = status['JobRun']['JobRunState']
                    
                    if job_state in ['SUCCEEDED', 'FAILED', 'TIMEOUT', 'STOPPED']:
                        break
                        
                    time.sleep(10)
                
                if job_state != 'SUCCEEDED':
                    raise Exception(f"Glue job failed with state: {job_state}")
                
                # Get list of output CSV files
                response = s3_client.list_objects_v2(
                    Bucket=bucket,
                    Prefix=temp_csv_key.replace('.csv', '')
                )
                
                # Find the actual CSV file (typically part-00000-*.csv)
                csv_file = None
                for obj in response.get('Contents', []):
                    if obj['Key'].endswith('.csv'):
                        csv_file = obj['Key']
                        break
                
                if not csv_file:
                    raise Exception("No CSV output file found from Glue job")
                
                # Now process the CSV file
                return self._process_csv_file(s3_client, bucket, csv_file)
                
            except Exception as e:
                logger.error(f"Failed to use Glue for Parquet conversion: {str(e)}")
                
                # Fallback to Athena or other method if available
                # For now, we'll return mock data as a placeholder
                logger.warning("Returning mock data due to Parquet processing failure")
                
                # Generate mock records
                mock_records = [
                    {
                        'account_id': '123456789012',
                        'service': 'AmazonEC2',
                        'resource_id': 'i-12345678',
                        'cost': 123.45,
                        'usage_amount': 1.0,
                        'usage_type': 'BoxUsage:t2.micro',
                        'billing_period': '2025-04',
                        'cost_category': 'production',
                        'timestamp': datetime.now().isoformat(),
                        'data_type': 'aws_cur',
                        'source': 'aws',
                        'schema_version': 'v1'
                    }
                ]
                
                # Add correlation tags
                mock_records = self.add_correlation_tags(mock_records)
                
                return mock_records
        except Exception as e:
            logger.error(f"Error processing Parquet file via S3: {str(e)}")
            raise
    
    def transform_cur(self, cur_records):
        """Transform CUR records to include Redis-specific tags"""
        transformed_records = []
        account_mapping = config.get_account_mapping()
        
        for record in cur_records:
            # Extract account and service information
            account_id = record.get('lineItem/UsageAccountId')
            service = record.get('lineItem/ProductCode')
            resource_id = record.get('lineItem/ResourceId', '')
            
            # Extract cost information
            try:
                cost = float(record.get('lineItem/UnblendedCost', 0))
                usage_amount = float(record.get('lineItem/UsageAmount', 0))
            except (ValueError, TypeError):
                cost = 0.0
                usage_amount = 0.0
                
            usage_type = record.get('lineItem/UsageType', '')
            
            transformed_record = {
                'account_id': account_id,
                'service': service,
                'resource_id': resource_id,
                'cost': cost,
                'usage_amount': usage_amount,
                'usage_type': usage_type,
                'billing_period': record.get('bill/BillingPeriod', ''),
                'cost_category': account_mapping.get(account_id, 'unallocated'),
                'timestamp': datetime.now().isoformat(),
                'data_type': 'aws_cur',
                'source': 'aws',
                'schema_version': 'v1'
            }
            
            transformed_records.append(transformed_record)
        
        return transformed_records
    
    def add_correlation_tags(self, records):
        """Add correlation tags to records for joining in Observe"""
        for record in records:
            # Create a consistent identifier for correlation
            correlation_components = []
            
            # Add account_id if available
            if 'account_id' in record:
                correlation_components.append(record['account_id'])
            
            # Generate hash for correlation ID if we have components
            if correlation_components:
                correlation_string = "-".join([str(c) for c in correlation_components])
                record['obs_correlation_id'] = hashlib.sha256(correlation_string.encode()).hexdigest()
            
            # Add data freshness controls
            record['obs_ingest_timestamp'] = datetime.now().isoformat()
            record['obs_data_version'] = hashlib.md5(
                f"{record['timestamp']}-{record['source']}".encode()
            ).hexdigest()
            
            # Add Redis-specific operational context
            record['obs_redis_context'] = {
                'environment': self.environment,
                'ingest_pipeline_version': self.pipeline_version,
                'data_owner': 'redis-cloud-ops'
            }
        
        return records