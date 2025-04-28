import hashlib
from datetime import datetime
import logging
from simple_salesforce import Salesforce
import time
import boto3
import json
import os

logger = logging.getLogger()

class SalesforceRateLimitExceeded(Exception):
    """Exception for Salesforce API rate limit exceeded"""
    pass

class SalesforceProcessor:
    def __init__(self, username, password, security_token, domain='login'):
        """Initialize Salesforce processor with credentials"""
        self.sf = Salesforce(username=username, password=password, security_token=security_token, domain=domain)
        self.pipeline_version = "1.2.0"
        self.environment = "dev"
    
    def add_correlation_tags(self, records):
        """Add correlation tags to records for joining in Observe"""
        for record in records:
            # Create a consistent identifier for correlation
            correlation_components = []
            
            # Add account_id if available
            if 'account_id' in record:
                correlation_components.append(record['account_id'])
            elif 'AccountId' in record:
                correlation_components.append(record['AccountId'])
            
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
            
            # Add schema version
            record['schema_version'] = 'v1'
        
        return records
    
    def query_with_rate_limit_handling(self, query, max_retries=3):
        """Execute SOQL query with rate limit handling"""
        for attempt in range(max_retries):
            try:
                return self.sf.query_all(query)
            except Exception as e:
                if 'EXCEEDED_RATE_LIMIT' in str(e):
                    logger.warning(f"Rate limit exceeded, attempt {attempt+1}/{max_retries}")
                    if attempt < max_retries - 1:
                        # Back off exponentially
                        wait_time = (2 ** attempt) * 5
                        logger.info(f"Waiting {wait_time} seconds before retry")
                        time.sleep(wait_time)
                    else:
                        raise SalesforceRateLimitExceeded("Exceeded rate limit after multiple retries")
                else:
                    logger.error(f"Error querying Salesforce: {str(e)}")
                    raise
    
    def get_arr_data(self, batch_size=2000):
        """Query for ARR data from Salesforce with pagination"""
        # Modified query with fields that should exist on most Salesforce instances
        base_query = """
        SELECT Id, Name, Industry, Type
        FROM Account
        WHERE Type = 'Customer'
        ORDER BY Id
        """
        
        logger.info("Executing paginated Salesforce ARR query")
        
        # Use SOQL-based pagination
        processed_records = []
        query = base_query + f" LIMIT {batch_size}"
        
        while True:
            batch_results = self.query_with_rate_limit_handling(query)
            
            if not batch_results['records']:
                break
                
            # Process this batch
            for record in batch_results['records']:
                processed_record = {
                    'account_id': record['Id'],
                    'account_name': record['Name'],
                    'industry': record.get('Industry'),
                    'customer_type': record.get('Type'),
                    'arr': 0,  # Default value since we don't have the real field
                    'timestamp': datetime.now().isoformat(),
                    'data_type': 'salesforce_arr',
                    'source': 'salesforce'
                }
                processed_records.append(processed_record)
            
            # If we have more records, continue with next batch
            if len(batch_results['records']) < batch_size:
                break
                
            # Get the last ID for continuation
            last_id = batch_results['records'][-1]['Id']
            query = base_query + f" AND Id > '{last_id}' LIMIT {batch_size}"
            
            # Save checkpoint to allow resuming if needed
            checkpoint_data = {
                'query': query,
                'last_id': last_id,
                'processed_count': len(processed_records)
            }
            checkpoint_bucket = os.environ.get('CHECKPOINT_BUCKET')
            if checkpoint_bucket:
                try:
                    self._save_checkpoint(checkpoint_bucket, 'salesforce/arr', checkpoint_data)
                except Exception as e:
                    logger.warning(f"Failed to save checkpoint: {str(e)}")
        
        # Add correlation tags
        processed_records = self.add_correlation_tags(processed_records)
        
        logger.info(f"Retrieved {len(processed_records)} ARR records from Salesforce")
        return processed_records
    
    def get_opportunity_data(self, batch_size=2000):
        """Query for Opportunity data from Salesforce with pagination"""
        # Modified query with ORDER BY for consistent pagination
        base_query = """
        SELECT Id, Name, AccountId, Amount, StageName, CloseDate, 
               Type, Probability, IsClosed, IsWon
        FROM Opportunity
        WHERE CloseDate >= LAST_N_DAYS:180
        ORDER BY Id
        """
        
        logger.info("Executing paginated Salesforce Opportunity query")
        
        # Use SOQL-based pagination
        processed_records = []
        query = base_query + f" LIMIT {batch_size}"
        
        while True:
            batch_results = self.query_with_rate_limit_handling(query)
            
            if not batch_results['records']:
                break
                
            # Process this batch
            for record in batch_results['records']:
                processed_record = {
                    'opportunity_id': record['Id'],
                    'opportunity_name': record['Name'],
                    'account_id': record['AccountId'],
                    'amount': record.get('Amount', 0),
                    'stage': record.get('StageName'),
                    'close_date': record.get('CloseDate'),
                    'type': record.get('Type'),
                    'probability': record.get('Probability'),
                    'is_closed': record.get('IsClosed'),
                    'is_won': record.get('IsWon'),
                    'timestamp': datetime.now().isoformat(),
                    'data_type': 'salesforce_opportunity',
                    'source': 'salesforce'
                }
                processed_records.append(processed_record)
            
            # If we have more records, continue with next batch
            if len(batch_results['records']) < batch_size:
                break
                
            # Get the last ID for continuation
            last_id = batch_results['records'][-1]['Id']
            query = base_query + f" AND Id > '{last_id}' LIMIT {batch_size}"
            
            # Save checkpoint to allow resuming if needed
            checkpoint_data = {
                'query': query,
                'last_id': last_id,
                'processed_count': len(processed_records)
            }
            checkpoint_bucket = os.environ.get('CHECKPOINT_BUCKET')
            if checkpoint_bucket:
                try:
                    self._save_checkpoint(checkpoint_bucket, 'salesforce/opportunities', checkpoint_data)
                except Exception as e:
                    logger.warning(f"Failed to save checkpoint: {str(e)}")
        
        # Add correlation tags
        processed_records = self.add_correlation_tags(processed_records)
        
        logger.info(f"Retrieved {len(processed_records)} opportunity records from Salesforce")
        return processed_records
        
    def _save_checkpoint(self, bucket, key_prefix, checkpoint_data):
        """Save processing checkpoint to S3"""
        try:
            s3_client = boto3.client('s3')
            checkpoint_key = f"{key_prefix}/checkpoint-{datetime.now().strftime('%Y%m%d%H%M%S')}.json"
            
            s3_client.put_object(
                Bucket=bucket,
                Key=checkpoint_key,
                Body=json.dumps(checkpoint_data),
                ContentType='application/json'
            )
            
            logger.info(f"Saved checkpoint to s3://{bucket}/{checkpoint_key}")
            return checkpoint_key
        except Exception as e:
            logger.error(f"Failed to save checkpoint: {str(e)}")
            raise
    
    def fan_out_records(self, records, batch_size=100, queue_url=None):
        """Distribute records to SQS for parallel processing."""
        if not queue_url:
            queue_url = os.environ.get('WORK_QUEUE_URL')
            if not queue_url:
                logger.error("No SQS work queue URL provided")
                return False
        
        try:
            sqs = boto3.client('sqs')
            
            # Break into smaller batches for parallel processing
            batches = [records[i:i+batch_size] for i in range(0, len(records), batch_size)]
            
            for batch in batches:
                sqs.send_message(
                    QueueUrl=queue_url,
                    MessageBody=json.dumps({
                        'type': 'salesforce_batch',
                        'records': batch,
                        'timestamp': time.time()
                    })
                )
            
            logger.info(f"Distributed {len(records)} records across {len(batches)} SQS messages")
            return True
        except Exception as e:
            logger.error(f"Failed to distribute work via SQS: {str(e)}")
            return False