import boto3
import json
import logging
import os
import time
from src.utils.config import config

logger = logging.getLogger()

def get_account_mapping():
    """Get account mapping from different sources"""
    return config.get_account_mapping()

def get_account_mapping_from_ssm():
    """Get account mapping from Parameter Store"""
    try:
        ssm = boto3.client('ssm')
        response = ssm.get_parameter(Name='/redis/account_mapping')
        return json.loads(response['Parameter']['Value'])
    except Exception as e:
        logger.warning(f"Failed to get account mapping from SSM: {str(e)}")
        return None

def get_account_mapping_from_dynamodb():
    """Get account mapping from DynamoDB"""
    try:
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table('redis-account-mapping')
        response = table.scan()
        
        # Convert from list of items to dictionary
        mapping = {}
        for item in response.get('Items', []):
            if 'account_id' in item and 'business_unit' in item:
                mapping[item['account_id']] = item['business_unit']
        
        return mapping if mapping else None
    except Exception as e:
        logger.warning(f"Failed to get account mapping from DynamoDB: {str(e)}")
        return None

def write_to_dlq(records, queue_url=None):
    """Write failed records to Dead Letter Queue"""
    if not queue_url:
        queue_url = os.environ.get('FAILED_RECORDS_QUEUE_URL')
        if not queue_url:
            logger.error("No DLQ URL provided")
            return False
    
    try:
        sqs = boto3.client('sqs')
        
        # SQS has message size limits, so we may need to break this into chunks
        chunk_size = 10
        chunks = [records[i:i+chunk_size] for i in range(0, len(records), chunk_size)]
        
        for chunk in chunks:
            sqs.send_message(
                QueueUrl=queue_url,
                MessageBody=json.dumps({
                    'records': chunk,
                    'timestamp': time.time()
                })
            )
        
        logger.info(f"Successfully wrote {len(records)} records to DLQ")
        return True
    except Exception as e:
        logger.error(f"Failed to write to DLQ: {str(e)}")
        return False