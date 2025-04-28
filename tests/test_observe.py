#!/usr/bin/env python3
"""
Test script for Observe integration.
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

# Import local testing config
try:
    from local_config import OBSERVE_CONFIG, ENVIRONMENT
except ImportError:
    logger.error("local_config.py not found. Please create this file with your test credentials.")
    sys.exit(1)

# Import source modules
from src.lambda_functions.observe import ObserveBatchSender

def test_observe_connection(dry_run=True):
    """Test the connection to Observe and send test data"""
    logger.info("Testing Observe connection...")
    
    try:
        # Initialize Observe sender with test credentials
        observe_sender = ObserveBatchSender(
            OBSERVE_CONFIG['url'],
            OBSERVE_CONFIG['token'],
            OBSERVE_CONFIG['customer_id']
        )
        
        # Create a test record
        test_record = {
            'id': f"test-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            'name': 'Test Record',
            'value': 123.45,
            'tags': ['test', 'integration'],
            'timestamp': datetime.now().isoformat(),
            'data_type': 'test_record',
            'source': 'local_testing',
            'environment': ENVIRONMENT
        }
        
        logger.info("Test record:")
        print(json.dumps(test_record, indent=2))
        
        # If dry_run, don't actually send the data
        if dry_run:
            logger.info("Dry run mode: Not sending data to Observe")
            return True
        
        # Send the test record
        logger.info("Sending test record to Observe...")
        observe_sender.add_record(test_record)
        observe_sender.flush()
        
        if observe_sender.failed_records:
            logger.error(f"Failed to send {len(observe_sender.failed_records)} records to Observe")
            return False
        
        logger.info("Observe connection test completed successfully!")
        return True
        
    except Exception as e:
        logger.error(f"Observe connection test failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    # Default to dry run to avoid unintentionally sending data
    dry_run = True
    if len(sys.argv) > 1 and sys.argv[1].lower() == '--send':
        dry_run = False
        logger.info("Sending mode activated - data will be sent to Observe")
    
    success = test_observe_connection(dry_run)
    sys.exit(0 if success else 1)