#!/usr/bin/env python3
"""
Test script for CUR fetcher.
"""
# Add project root to Python path
from context import *

import os
import sys
import json
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

# Import mock AWS
try:
    from mock_aws import MockCostExplorerClient, MockS3Client, MockLambdaClient
except ImportError:
    logger.error("mock_aws.py not found. Please create this file.")
    sys.exit(1)

# Create a context object for testing
class MockContext:
    def __init__(self):
        self.function_name = "test-function"
        self.aws_request_id = "test-request-id"
        self.log_group_name = "test-log-group"
        self.log_stream_name = "test-log-stream"

def test_cur_fetcher():
    """Test the CUR fetcher"""
    logger.info("Testing CUR fetcher...")
    
    try:
        # Import the lambda handler
        from src.lambda_functions.cur_fetcher import lambda_handler
        
        # Set environment variables
        os.environ['TARGET_S3_BUCKET'] = 'test-bucket'
        os.environ['DATA_INGESTION_FUNCTION'] = 'test-function'
        
        # Create mock clients
        import boto3
        
        # Create mock AWS clients
        ce_client = MockCostExplorerClient()
        s3_client = MockS3Client()
        lambda_client = MockLambdaClient()
        
        # Mock boto3.client to return our mock clients
        def mock_boto3_client(service_name, *args, **kwargs):
            if service_name == 'ce':
                return ce_client
            elif service_name == 's3':
                return s3_client
            elif service_name == 'lambda':
                return lambda_client
            else:
                raise ValueError(f"Unexpected service: {service_name}")
        
        # Save original and patch
        original_boto3_client = boto3.client
        boto3.client = mock_boto3_client
        
        try:
            # Mock event and context
            event = {}
            context = MockContext()
            
            # Call the lambda handler
            logger.info("Calling lambda_handler...")
            result = lambda_handler(event, context)
            
            # Check result
            if result['statusCode'] != 200:
                logger.error(f"Lambda handler returned non-200 status: {result}")
                return False
            
            logger.info("Lambda handler result:")
            print(json.dumps(result, indent=2))
            
            # Check that S3 was called
            if not s3_client.put_object_called:
                logger.error("S3 put_object was not called")
                return False
            
            # Check that Lambda was called
            if not lambda_client.invoke_called:
                logger.error("Lambda invoke was not called")
                return False
            
            logger.info("CUR fetcher test completed successfully!")
            return True
        finally:
            # Restore original boto3.client
            boto3.client = original_boto3_client
        
    except Exception as e:
        logger.error(f"CUR fetcher test failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_cur_fetcher()
    sys.exit(0 if success else 1)