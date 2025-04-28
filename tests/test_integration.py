#!/usr/bin/env python3
"""
Integration test script for the complete pipeline.
"""
# Add project root to Python path
from context import *

import os
import sys
import json
import logging
from datetime import datetime

parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

# Import local testing config and mocks
try:
    from local_config import SALESFORCE_CONFIG, OBSERVE_CONFIG, ENVIRONMENT
    from mock_aws import MockS3Client, MockSSMClient
except ImportError:
    logger.error("local_config.py or mock_aws.py not found. Please create these files.")
    sys.exit(1)

# Create a context object for testing
class MockContext:
    def __init__(self):
        self.function_name = "test-function"
        self.aws_request_id = "test-request-id"
        self.log_group_name = "test-log-group"
        self.log_stream_name = "test-log-stream"

def test_integration(action='salesforce', dry_run=True):
    """Test the complete integration pipeline"""
    logger.info(f"Testing integration with action: {action}")
    
    try:
        # Import the lambda handler
        from src.lambda_functions.index import lambda_handler
        
        # Set environment variables
        os.environ['DEPLOY_ENV'] = ENVIRONMENT
        os.environ['LOG_LEVEL'] = 'INFO'
        
        # Create mock clients
        import boto3
        
        # Create mock parameters
        ssm_params = {
            '/redis/sfdc/username': SALESFORCE_CONFIG['username'],
            '/redis/sfdc/password': SALESFORCE_CONFIG['password'],
            '/redis/sfdc/token': SALESFORCE_CONFIG['security_token'],
            '/redis/observe/token': OBSERVE_CONFIG['token'],
            '/redis/observe/customer_id': OBSERVE_CONFIG['customer_id'],
            '/redis/observe/url': OBSERVE_CONFIG['url']
        }
        
        ssm_client = MockSSMClient(ssm_params)
        
        # Create test event based on action
        if action == 'salesforce':
            event = {'action': 'salesforce'}
        elif action == 'cur':
            # Test with sample CUR file
            sample_file = os.path.join(parent_dir, 'samples', 'sample-cur.csv')
            if not os.path.exists(sample_file):
                logger.error(f"Sample CUR file not found: {sample_file}")
                return False
            
            s3_client = MockS3Client(sample_file)
            event = {
                'action': 'cur',
                'bucket': 'test-bucket',
                'key': 'aws-cur/test.csv'
            }
        else:
            logger.error(f"Unsupported action: {action}")
            return False
        
        # Create context
        context = MockContext()
        
        # If dry run, don't actually call the handler
        if dry_run:
            logger.info("Dry run mode: Not calling lambda_handler")
            return True
        
        # Mock boto3.client to return our mock clients
        def mock_boto3_client(service_name, *args, **kwargs):
            if service_name == 'ssm':
                return ssm_client
            elif service_name == 's3' and action == 'cur':
                return s3_client
            else:
                # For other services, use real clients
                return original_boto3_client(service_name, *args, **kwargs)
        
        # Save original and patch
        original_boto3_client = boto3.client
        boto3.client = mock_boto3_client
        
        try:
            # Call the lambda handler
            logger.info("Calling lambda_handler...")
            result = lambda_handler(event, context)
            
            # Check result
            if result['statusCode'] != 200:
                logger.error(f"Lambda handler returned non-200 status: {result}")
                return False
            
            logger.info("Lambda handler result:")
            print(json.dumps(result, indent=2))
            
            logger.info("Integration test completed successfully!")
            return True
        finally:
            # Restore original boto3.client
            boto3.client = original_boto3_client
        
    except Exception as e:
        logger.error(f"Integration test failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    # Default to salesforce action and dry run
    action = 'salesforce'
    dry_run = True
    
    # Parse command line arguments
    if len(sys.argv) > 1:
        action = sys.argv[1]
    
    if len(sys.argv) > 2 and sys.argv[2].lower() == '--send':
        dry_run = False
        logger.info("Sending mode activated - will call lambda_handler")
    
    success = test_integration(action, dry_run)
    sys.exit(0 if success else 1)