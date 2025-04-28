import logging
import re

logger = logging.getLogger()

class ValidationError(Exception):
    """Exception for data validation errors"""
    pass

# Schema version tracking
SCHEMA_VERSIONS = {
    'salesforce_arr': {
        'v1': {
            'required_fields': ['account_id', 'account_name', 'arr', 'timestamp', 'data_type', 'source'],
            'optional_fields': ['health_score', 'industry', 'customer_type', 'csm']
        },
        'v2': {
            'required_fields': ['account_id', 'account_name', 'arr', 'timestamp', 'data_type', 'source'],
            'optional_fields': ['health_score', 'industry', 'customer_type', 'csm', 'account_owner', 'renewal_date']
        }
    },
    'salesforce_opportunity': {
        'v1': {
            'required_fields': ['opportunity_id', 'account_id', 'amount', 'timestamp', 'data_type', 'source'],
            'optional_fields': ['opportunity_name', 'stage', 'close_date', 'type', 'probability', 'is_closed', 'is_won']
        }
    },
    'aws_cur': {
        'v1': {
            'required_fields': ['account_id', 'cost', 'timestamp', 'data_type', 'source'],
            'optional_fields': ['service', 'resource_id', 'usage_amount', 'usage_type', 'billing_period']
        }
    }
}

def get_latest_schema_version(data_type):
    """Get the latest schema version for a data type."""
    versions = list(SCHEMA_VERSIONS.get(data_type, {}).keys())
    if not versions:
        return None
    return sorted(versions)[-1]  # Return the highest version

def validate_record(record, schema_version=None):
    """Validate a record before sending to Observe with schema versioning."""
    if 'data_type' not in record:
        raise ValidationError("Missing required field: data_type")
    
    data_type = record['data_type']
    
    # If no schema version specified, use the latest one or the one in the record
    if not schema_version:
        schema_version = record.get('schema_version')
        if not schema_version:
            schema_version = get_latest_schema_version(data_type)
            if not schema_version:
                logger.warning(f"No schema definition found for data type: {data_type}")
                schema_version = 'v1'  # Default to v1
    
    # Get schema definition
    schema = SCHEMA_VERSIONS.get(data_type, {}).get(schema_version)
    if schema:
        # Validate required fields
        for field in schema['required_fields']:
            if field not in record:
                raise ValidationError(f"Missing required field: {field}")
        
        # Add schema version to record if not already present
        if 'schema_version' not in record:
            record['schema_version'] = schema_version
    else:
        # Fall back to basic validation
        if 'timestamp' not in record:
            raise ValidationError("Missing required field: timestamp")
        
        if 'source' not in record:
            raise ValidationError("Missing required field: source")
    
    # Type-specific validation still needed even with schema
    if data_type == 'salesforce_arr':
        validate_arr_record(record)
    elif data_type == 'salesforce_opportunity':
        validate_opportunity_record(record)
    elif data_type == 'aws_cur':
        validate_cur_record(record)
    else:
        logger.warning(f"Unknown data_type: {data_type}")

def validate_arr_record(record):
    """Validate Salesforce ARR record"""
    if 'account_id' not in record:
        raise ValidationError("Missing required field in ARR record: account_id")
    
    if 'account_name' not in record:
        raise ValidationError("Missing required field in ARR record: account_name")
    
    if 'arr' not in record:
        raise ValidationError("Missing required field in ARR record: arr")
    
    # Validate ARR is a number and not negative
    try:
        arr = float(record['arr'])
        if arr < 0:
            raise ValidationError(f"ARR cannot be negative: {arr}")
    except (ValueError, TypeError):
        raise ValidationError(f"ARR must be a number: {record['arr']}")
    
    # Validate ID format (Salesforce IDs are 15 or 18 chars)
    if not re.match(r'^[a-zA-Z0-9]{15,18}$', record['account_id']):
        logger.warning(f"Account ID may not be valid Salesforce ID: {record['account_id']}")

def validate_opportunity_record(record):
    """Validate Salesforce Opportunity record"""
    if 'opportunity_id' not in record:
        raise ValidationError("Missing required field in Opportunity record: opportunity_id")
    
    if 'account_id' not in record:
        raise ValidationError("Missing required field in Opportunity record: account_id")
    
    # Set default amount of 0 if amount is None
    if 'amount' not in record or record['amount'] is None:
        record['amount'] = 0.0
    else:
        # Validate amount is a number and not negative
        try:
            amount = float(record['amount'])
            if amount < 0:
                raise ValidationError(f"Amount cannot be negative: {amount}")
            record['amount'] = amount  # Ensure it's a float
        except (ValueError, TypeError):
            raise ValidationError(f"Amount must be a number: {record['amount']}")
    
    # Validate ID formats
    if not re.match(r'^[a-zA-Z0-9]{15,18}$', record['opportunity_id']):
        logger.warning(f"Opportunity ID may not be valid Salesforce ID: {record['opportunity_id']}")
    
    if not re.match(r'^[a-zA-Z0-9]{15,18}$', record['account_id']):
        logger.warning(f"Account ID may not be valid Salesforce ID: {record['account_id']}")

def validate_cur_record(record):
    """Validate AWS CUR record"""
    if 'account_id' not in record:
        raise ValidationError("Missing required field in CUR record: account_id")
    
    if 'cost' not in record:
        raise ValidationError("Missing required field in CUR record: cost")
    
    # Validate cost is a number
    try:
        cost = float(record['cost'])
        if cost < 0:
            logger.warning(f"Negative cost value in CUR record: {cost}")
            # We don't fail on negative costs as they could be valid (credits, refunds)
    except (ValueError, TypeError):
        raise ValidationError(f"Cost must be a number: {record['cost']}")
    
    # Validate AWS account ID format (12 digits)
    if not re.match(r'^\d{12}$', record['account_id']):
        logger.warning(f"Account ID may not be valid AWS account ID: {record['account_id']}")