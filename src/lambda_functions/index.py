import json
import re
import boto3
import os
import logging
from datetime import datetime
import traceback
from . import salesforce
from . import cur_processor
from . import observe
from . import validation
from src.utils.config import config

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Version tracking
PIPELINE_VERSION = config.get('pipeline_version', '1.2.0')
ENVIRONMENT = config.get('environment', 'dev')

# Make pipeline version available to other modules
os.environ['PIPELINE_VERSION'] = PIPELINE_VERSION
os.environ['SERVICE_NAME'] = 'redis-data-ingestion'

def validate_event(event):
    """Validate and sanitize the Lambda event."""
    if not isinstance(event, dict):
        raise ValueError("Event must be a dictionary")
    
    # Validate Salesforce action
    if event.get('action') == 'salesforce':
        # No additional fields required for this action
        return event
    
    # Validate CUR action
    elif event.get('action') == 'cur':
        if 'bucket' not in event:
            raise ValueError("Missing required field 'bucket' for CUR action")
        if 'key' not in event:
            raise ValueError("Missing required field 'key' for CUR action")
        
        # Sanitize bucket name
        bucket = event['bucket']
        if not isinstance(bucket, str) or not re.match(r'^[a-z0-9][a-z0-9\.\-]{1,61}[a-z0-9]$', bucket):
            raise ValueError(f"Invalid S3 bucket name: {bucket}")
        
        # Sanitize key
        key = event['key']
        if not isinstance(key, str) or len(key) > 1024:
            raise ValueError(f"Invalid S3 key: {key}")
        
        return event
    
    # Validate S3 event
    elif 'Records' in event and len(event['Records']) > 0:
        if event['Records'][0].get('eventSource') == 'aws:s3':
            return event
    
    # Validate SQS event
    elif 'Records' in event and len(event['Records']) > 0:
        if event['Records'][0].get('eventSource') == 'aws:sqs':
            return event
    
    raise ValueError(f"Unsupported event type: {event}")

def get_parameter_with_retry(ssm, name, max_attempts=3):
    """Retrieve parameters from SSM with retry logic"""
    import time
    
    for attempt in range(max_attempts):
        try:
            return ssm.get_parameter(Name=name, WithDecryption=True)['Parameter']['Value']
        except ssm.exceptions.ParameterNotFound:
            logger.error(f"Parameter {name} not found")
            raise
        except Exception as e:
            logger.error(f"Error getting parameter {name}: {str(e)}")
            if attempt == max_attempts - 1:
                raise
            time.sleep(2 ** attempt)

def save_checkpoint(bucket, key_prefix, checkpoint_data):
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
        return None

def load_checkpoint(bucket, checkpoint_key):
    """Load processing checkpoint from S3"""
    try:
        s3_client = boto3.client('s3')
        response = s3_client.get_object(Bucket=bucket, Key=checkpoint_key)
        checkpoint_data = json.loads(response['Body'].read().decode('utf-8'))
        
        logger.info(f"Loaded checkpoint from s3://{bucket}/{checkpoint_key}")
        return checkpoint_data
    except Exception as e:
        logger.error(f"Failed to load checkpoint: {str(e)}")
        return None

def lambda_handler(event, context):
    """Main Lambda handler function"""
    try:
        # Validate and sanitize the event
        try:
            event = validate_event(event)
        except ValueError as e:
            logger.error(f"Invalid event: {str(e)}")
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'error': f"Invalid event: {str(e)}"
                })
            }
        
        # Record execution context
        execution_context = {
            'function_name': context.function_name if context else 'local',
            'aws_request_id': context.aws_request_id if context else 'local',
            'log_group_name': context.log_group_name if context else 'local',
            'log_stream_name': context.log_stream_name if context else 'local',
            'pipeline_version': PIPELINE_VERSION,
            'environment': ENVIRONMENT,
            'timestamp': datetime.now().isoformat()
        }
        logger.info(f"Execution context: {json.dumps(execution_context)}")
        
        # Initialize AWS clients
        ssm = boto3.client('ssm')
        
        # Check if the event is an SQS event
        if 'Records' in event and event['Records'][0].get('eventSource') == 'aws:sqs':
            # This is an SQS message, process the batch
            logger.info(f"Processing {len(event['Records'])} SQS messages")
            
            # Get Observe credentials
            observe_token = config.get('observe.token')
            observe_customer_id = config.get('observe.customer_id')
            observe_url = config.get('observe.url')
            
            # Fall back to SSM if not in config
            if not observe_token:
                observe_token = get_parameter_with_retry(ssm, '/redis/observe/token')
            if not observe_customer_id:
                observe_customer_id = get_parameter_with_retry(ssm, '/redis/observe/customer_id')
            if not observe_url:
                observe_url = get_parameter_with_retry(ssm, '/redis/observe/url')
            
            # Initialize Observe sender
            observe_sender = observe.ObserveBatchSender(observe_url, observe_token, observe_customer_id)
            
            total_records = 0
            failed_records = 0
            
            # Process each SQS message
            for record in event['Records']:
                try:
                    # Parse the message body
                    message = json.loads(record['body'])
                    
                    # Process the batch based on type
                    if message.get('type') == 'salesforce_batch':
                        # Process Salesforce batch
                        sf_records = message.get('records', [])
                        
                        # Validate records
                        validated_records = []
                        for sf_record in sf_records:
                            try:
                                validation.validate_record(sf_record)
                                validated_records.append(sf_record)
                                total_records += 1
                            except validation.ValidationError as e:
                                logger.warning(f"Validation error: {str(e)}")
                                failed_records += 1
                        
                        # Send to Observe
                        observe_sender.add_records(validated_records)
                        
                    elif message.get('type') == 'cur_batch':
                        # Process CUR batch
                        cur_records = message.get('records', [])
                        
                        # Validate records
                        validated_records = []
                        for cur_record in cur_records:
                            try:
                                validation.validate_record(cur_record)
                                validated_records.append(cur_record)
                                total_records += 1
                            except validation.ValidationError as e:
                                logger.warning(f"Validation error: {str(e)}")
                                failed_records += 1
                        
                        # Send to Observe
                        observe_sender.add_records(validated_records)
                        
                except Exception as e:
                    logger.error(f"Error processing SQS message: {str(e)}")
                    failed_records += 1
            
            # Return processing results
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': 'Successfully processed SQS batch',
                    'total_records': total_records,
                    'processed_records': total_records - failed_records,
                    'failed_records': failed_records
                })
            }
        
        # Get Observe credentials
        observe_token = config.get('observe.token')
        observe_customer_id = config.get('observe.customer_id')
        observe_url = config.get('observe.url')
        
        # Fall back to SSM if not in config
        if not observe_token:
            observe_token = get_parameter_with_retry(ssm, '/redis/observe/token')
        if not observe_customer_id:
            observe_customer_id = get_parameter_with_retry(ssm, '/redis/observe/customer_id')
        if not observe_url:
            observe_url = get_parameter_with_retry(ssm, '/redis/observe/url')
        
        # Initialize Observe sender
        observe_sender = observe.ObserveBatchSender(observe_url, observe_token, observe_customer_id)
        
        # Track success metrics
        total_records = 0
        failed_records = 0
        
        # Check event type to determine action
        if event.get('action') == 'salesforce':
            # Get Salesforce credentials
            sf_username = config.get('salesforce.username')
            sf_password = config.get('salesforce.password')
            sf_token = config.get('salesforce.security_token')
            
            # Fall back to SSM if not in config
            if not sf_username:
                sf_username = get_parameter_with_retry(ssm, '/redis/sfdc/username')
            if not sf_password:
                sf_password = get_parameter_with_retry(ssm, '/redis/sfdc/password')
            if not sf_token:
                sf_token = get_parameter_with_retry(ssm, '/redis/sfdc/token')
            
            # Process Salesforce data
            logger.info("Processing Salesforce data")
            sf_processor = salesforce.SalesforceProcessor(
                sf_username, 
                sf_password, 
                sf_token,
                domain='test'
            )
            sf_processor.environment = ENVIRONMENT
            sf_processor.pipeline_version = PIPELINE_VERSION
            
            # Get ARR data from Salesforce with pagination
            arr_data = sf_processor.get_arr_data(batch_size=2000)
            total_records += len(arr_data)
            
            # Get opportunity data from Salesforce with pagination
            opp_data = sf_processor.get_opportunity_data(batch_size=2000)
            total_records += len(opp_data)
            
            # Check if we should use fan-out pattern for large datasets
            work_queue_url = os.environ.get('WORK_QUEUE_URL')
            if work_queue_url and (len(arr_data) + len(opp_data) > 5000):
                logger.info(f"Using fan-out pattern for {len(arr_data) + len(opp_data)} records")
                
                # Distribute ARR data
                if arr_data:
                    success = sf_processor.fan_out_records(arr_data, queue_url=work_queue_url)
                    if not success:
                        logger.error("Failed to distribute ARR data via SQS")
                
                # Distribute opportunity data
                if opp_data:
                    success = sf_processor.fan_out_records(opp_data, queue_url=work_queue_url)
                    if not success:
                        logger.error("Failed to distribute opportunity data via SQS")
                
                return {
                    'statusCode': 202,
                    'body': json.dumps({
                        'message': 'Salesforce data distributed for parallel processing',
                        'total_records': len(arr_data) + len(opp_data)
                    })
                }
            
            # Process normally for smaller datasets
            # Validate data before sending
            validated_arr_data = []
            for record in arr_data:
                try:
                    validation.validate_record(record)
                    validated_arr_data.append(record)
                except validation.ValidationError as e:
                    logger.warning(f"Validation error in ARR record: {str(e)}")
                    failed_records += 1
            
            validated_opp_data = []
            for record in opp_data:
                try:
                    validation.validate_record(record)
                    validated_opp_data.append(record)
                except validation.ValidationError as e:
                    logger.warning(f"Validation error in opportunity record: {str(e)}")
                    failed_records += 1
            
            # Send data to Observe
            logger.info(f"Sending {len(validated_arr_data)} ARR records to Observe")
            observe_sender.add_records(validated_arr_data)
                
            logger.info(f"Sending {len(validated_opp_data)} opportunity records to Observe")
            observe_sender.add_records(validated_opp_data)
            
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': 'Successfully processed Salesforce data',
                    'total_records': total_records,
                    'processed_records': total_records - failed_records,
                    'failed_records': failed_records
                })
            }
        
        elif event.get('action') == 'cur' or ('Records' in event and event['Records'][0].get('eventSource') == 'aws:s3'):
            # Process CUR file
            s3_client = boto3.client('s3')
            
            # Get bucket and key from event
            if 'Records' in event:
                bucket = event['Records'][0]['s3']['bucket']['name']
                key = event['Records'][0]['s3']['object']['key']
            else:
                bucket = event.get('bucket')
                key = event.get('key')
            
            # Process CUR file
            logger.info(f"Processing CUR file from S3: s3://{bucket}/{key}")
            cur_proc = cur_processor.CURProcessor()
            cur_proc.environment = ENVIRONMENT
            cur_proc.pipeline_version = PIPELINE_VERSION
            
            cur_data = cur_proc.process_cur_file(s3_client, bucket, key)
            total_records += len(cur_data)
            
            # Check if we should use fan-out pattern for large datasets
            work_queue_url = os.environ.get('WORK_QUEUE_URL')
            if work_queue_url and len(cur_data) > 5000:
                logger.info(f"Using fan-out pattern for {len(cur_data)} CUR records")
                
                # Create batches and send to SQS
                batch_size = 1000
                batches = [cur_data[i:i+batch_size] for i in range(0, len(cur_data), batch_size)]
                
                sqs = boto3.client('sqs')
                for i, batch in enumerate(batches):
                    sqs.send_message(
                        QueueUrl=work_queue_url,
                        MessageBody=json.dumps({
                            'type': 'cur_batch',
                            'records': batch,
                            'timestamp': datetime.now().isoformat(),
                            'batch_number': i + 1,
                            'total_batches': len(batches)
                        })
                    )
                
                return {
                    'statusCode': 202,
                    'body': json.dumps({
                        'message': 'CUR data distributed for parallel processing',
                        'total_records': len(cur_data),
                        'batches': len(batches)
                    })
                }
            
            # Validate data before sending
            validated_cur_data = []
            for record in cur_data:
                try:
                    validation.validate_record(record)
                    validated_cur_data.append(record)
                except validation.ValidationError as e:
                    logger.warning(f"Validation error in CUR record: {str(e)}")
                    failed_records += 1
            
            # Send data to Observe
            logger.info(f"Sending {len(validated_cur_data)} CUR records to Observe")
            observe_sender.add_records(validated_cur_data)
            
            # Record failed records
            if observe_sender.failed_records:
                logger.warning(f"Failed to send {len(observe_sender.failed_records)} records to Observe")
                
                # Write failed records to S3 for retry
                failed_records_key = f"failed-records/{datetime.now().strftime('%Y-%m-%d')}/{context.aws_request_id if context else 'local'}.json"
                s3_client.put_object(
                    Bucket=bucket,
                    Key=failed_records_key,
                    Body=json.dumps(observe_sender.failed_records),
                    ContentType='application/json'
                )
                logger.info(f"Failed records written to s3://{bucket}/{failed_records_key}")
            
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': 'Successfully processed CUR file',
                    'total_records': total_records,
                    'processed_records': total_records - failed_records,
                    'failed_records': failed_records,
                    'failed_records_location': f"s3://{bucket}/{failed_records_key}" if observe_sender.failed_records else None
                })
            }
        
        else:
            logger.error(f"Unsupported event type: {event}")
            return {
                'statusCode': 400,
                'body': json.dumps('Unsupported event type. Use action="salesforce" or action="cur"')
            }
    
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}")
        logger.error(traceback.format_exc())
        
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e),
                'traceback': traceback.format_exc()
            })
        }