#!/usr/bin/env python3
"""
Test script for Salesforce integration.
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
    from local_config import SALESFORCE_CONFIG, ENVIRONMENT
except ImportError:
    logger.error("local_config.py not found. Please create this file with your test credentials.")
    sys.exit(1)

# Import source modules
from src.lambda_functions.salesforce import SalesforceProcessor

def test_salesforce_connection():
    """Test the connection to Salesforce and retrieve data"""
    logger.info("Testing Salesforce connection...")
    
    try:
        # Initialize Salesforce processor with test credentials
        sf_processor = SalesforceProcessor(
            SALESFORCE_CONFIG['username'],
            SALESFORCE_CONFIG['password'],
            SALESFORCE_CONFIG['security_token'],
            domain=SALESFORCE_CONFIG.get('domain', 'login')
        )
        
        # Set environment for testing
        sf_processor.environment = ENVIRONMENT
        
        # Test ARR data retrieval
        logger.info("Retrieving ARR data...")
        arr_data = sf_processor.get_arr_data()
        logger.info(f"Successfully retrieved {len(arr_data)} ARR records")
        
        # Show sample record
        if arr_data:
            logger.info("Sample ARR record:")
            print(json.dumps(arr_data[0], indent=2))
        
        # Test opportunity data retrieval
        logger.info("Retrieving opportunity data...")
        opp_data = sf_processor.get_opportunity_data()
        logger.info(f"Successfully retrieved {len(opp_data)} opportunity records")
        
        # Show sample record
        if opp_data:
            logger.info("Sample opportunity record:")
            print(json.dumps(opp_data[0], indent=2))
        
        logger.info("Salesforce connection test completed successfully!")
        return True
        
    except Exception as e:
        logger.error(f"Salesforce connection test failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_salesforce_connection()
    sys.exit(0 if success else 1)