#!/usr/bin/env python3
"""
Test script for CUR processing.
"""
# Add project root to Python path
from context import *

import os
import sys
import json
import logging
import boto3
from datetime import datetime
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

# Import local testing config
try:
    from local_config import ENVIRONMENT, AWS_ACCOUNT_MAPPING
    from mock_aws import MockS3Client
except ImportError:
    logger.error("local_config.py or mock_aws.py not found. Please create these files.")
    sys.exit(1)

# Import source modules
from src.lambda_functions.cur_processor import CURProcessor
from src.lambda_functions.validation import validate_record

def test_cur_processing():
    """Test CUR file processing with sample data"""
    logger.info("Testing CUR file processing...")
    
    try:
        # Initialize CUR processor
        cur_proc = CURProcessor()
        
        # Set environment for testing
        cur_proc.environment = ENVIRONMENT
        
        # Create mock S3 client
        sample_file = os.path.join(parent_dir, 'samples', 'sample-cur.csv')
        if not os.path.exists(sample_file):
            logger.error(f"Sample CUR file not found: {sample_file}")
            return False
        
        s3_client = MockS3Client(sample_file)
        
        # Process sample CUR file
        logger.info(f"Processing sample CUR file: {sample_file}")
        cur_data = cur_proc.process_cur_file(s3_client, 'test-bucket', sample_file)
        logger.info(f"Successfully processed {len(cur_data)} CUR records")
        
        # Show sample record
        if cur_data:
            logger.info("Sample CUR record:")
            print(json.dumps(cur_data[0], indent=2))
        
        # Validate records
        valid_records = 0
        invalid_records = 0
        for record in cur_data:
            try:
                validate_record(record)
                valid_records += 1
            except Exception as e:
                logger.warning(f"Invalid record: {str(e)}")
                invalid_records += 1
        
        logger.info(f"Validation results: {valid_records} valid, {invalid_records} invalid")
        logger.info("CUR processing test completed successfully!")
        return True
        
    except Exception as e:
        logger.error(f"CUR processing test failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_cur_processing()
    sys.exit(0 if success else 1)