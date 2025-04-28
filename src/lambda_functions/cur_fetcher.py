import boto3
import os
import json
import logging
import time
import re
from datetime import datetime, timedelta

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    """Lambda function to fetch AWS CUR data and place it in S3 bucket"""
    try:
        # Get configuration
        target_bucket = os.environ.get('TARGET_S3_BUCKET')
        target_prefix = 'aws-cur/'
        
        # Validate parameters
        if not target_bucket:
            raise ValueError("TARGET_S3_BUCKET environment variable is required")
        
        # Validate bucket name
        if not re.match(r'^[a-z0-9][a-z0-9\.\-]{1,61}[a-z0-9]$', target_bucket):
            raise ValueError(f"Invalid S3 bucket name: {target_bucket}")
        
        # Get the current date for file naming
        current_date = datetime.now()
        yesterday = current_date - timedelta(days=1)
        year = yesterday.strftime('%Y')
        month = yesterday.strftime('%m')
        day = yesterday.strftime('%d')
        
        logger.info(f"Fetching cost data for {yesterday.strftime('%Y-%m-%d')}")
        
        # Use Cost Explorer API to get cost data
        ce_client = boto3.client('ce')
        start_date = yesterday.strftime('%Y-%m-%d')
        end_date = current_date.strftime('%Y-%m-%d')
        
        # Request cost data from Cost Explorer
        response = ce_client.get_cost_and_usage(
            TimePeriod={
                'Start': start_date,
                'End': end_date
            },
            Granularity='DAILY',
            Metrics=['UnblendedCost'],
            GroupBy=[
                {
                    'Type': 'DIMENSION',
                    'Key': 'SERVICE'
                },
                {
                    'Type': 'DIMENSION',
                    'Key': 'LINKED_ACCOUNT'
                }
            ]
        )
        
        # Format data as CSV
        csv_data = "identity/LineItemId,identity/TimeInterval,lineItem/UsageAccountId,lineItem/ProductCode,lineItem/UnblendedCost,bill/BillingPeriod,lineItem/UsageAmount\n"
        
        record_count = 0
        for result in response['ResultsByTime']:
            date = result['TimePeriod']['Start']
            for group in result['Groups']:
                dimensions = group['Keys']
                service = dimensions[0]
                account_id = dimensions[1]
                cost = group['Metrics']['UnblendedCost']['Amount']
                
                # Create required fields
                line_item_id = f"ce-{date}-{service}-{account_id}"
                time_interval = f"{date}T00:00:00Z/{date}T23:59:59Z"
                billing_period = f"{year}-{month}"
                # Default usage amount to 1 as Cost Explorer doesn't provide this detail
                usage_amount = "1"
                
                csv_data += f"{line_item_id},{time_interval},{account_id},{service},{cost},{billing_period},{usage_amount}\n"
                record_count += 1
        
        # Create file path in S3 - using partitioned path for better query performance
        file_key = f"{target_prefix}year={year}/month={month}/day={day}/cost-report-{year}{month}{day}.csv"
        
        # Upload CSV to S3
        s3_client = boto3.client('s3')
        s3_client.put_object(
            Bucket=target_bucket,
            Key=file_key,
            Body=csv_data.encode('utf-8'),
            ContentType='text/csv',
            Metadata={
                'record-count': str(record_count),
                'cost-date': yesterday.strftime('%Y-%m-%d')
            }
        )
        
        logger.info(f"Successfully uploaded {record_count} cost records to s3://{target_bucket}/{file_key}")
        
        # Optionally trigger the CUR processor Lambda
        data_ingestion_function = os.environ.get('DATA_INGESTION_FUNCTION')
        
        if data_ingestion_function:
            # Invoke the data ingestion Lambda with the S3 info
            lambda_client = boto3.client('lambda')
            lambda_client.invoke(
                FunctionName=data_ingestion_function,
                InvocationType='Event',
                Payload=json.dumps({
                    'action': 'cur',
                    'bucket': target_bucket,
                    'key': file_key
                })
            )
            logger.info(f"Triggered data ingestion Lambda to process the CUR file")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Successfully fetched and uploaded cost data',
                'records': record_count,
                'location': f"s3://{target_bucket}/{file_key}"
            })
        }
        
    except Exception as e:
        logger.error(f"Error fetching and uploading cost data: {str(e)}")
        
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e)
            })
        }