# Redis SFDC-Observe Integration

A data integration pipeline for sending Salesforce CRM data and AWS Cost and Usage Reports to Observe.io for monitoring and analytics.

## Overview

This project provides an automated solution for:

- Fetching Salesforce data (Accounts, Opportunities) 
- Processing AWS Cost and Usage Reports (CUR)
- Transforming and standardizing the data
- Sending the data to Observe.io for analytics and monitoring

## Architecture

- AWS Lambda functions handle data processing in a serverless architecture
- S3 buckets store CUR reports and checkpoint files
- CloudWatch Events trigger scheduled runs
- SQS queues manage workload distribution for larger datasets
- Lambda layers for dependencies

## Prerequisites

- AWS CLI configured with appropriate permissions
- Python 3.9+
- Salesforce credentials with API access
- Observe.io credentials
- AWS account with Cost Explorer access

## Installation

### One-Click Deployment

The project includes a build-and-deploy script that handles:
- Building Lambda packages
- Creating S3 buckets
- Creating Lambda functions and layers
- Setting up CloudWatch Event schedules
- Configuring IAM roles and policies

```bash
./build-and-deploy.sh --env dev --lambda-bucket your-lambda-bucket-name --cur-bucket your-cur-bucket-name
```

### Manual Configuration

1. Create an `.env` file with your credentials:

```
# Deployment environment
DEPLOY_ENV=dev

# Salesforce credentials
SALESFORCE_USERNAME="your_username"
SALESFORCE_PASSWORD="your_password"
SALESFORCE_TOKEN="your_security_token"
SALESFORCE_SANDBOX=true

# Observe credentials
OBSERVE_URL="https://your-customer-id.collect.observeinc.com/v1/http"
OBSERVE_TOKEN="your_token"
OBSERVE_CUSTOMER_ID="your_customer_id"

# AWS account mapping (JSON string)
AWS_ACCOUNT_MAPPING={"123456789012":"production","234567890123":"staging","345678901234":"development"}
```

2. Run the build script:

```bash
./build-and-deploy.sh
```

## Testing

The project includes comprehensive test scripts:

```bash
# Run all tests
./run_tests.sh

# Run specific tests
python tests/test_salesforce.py
python tests/test_cur.py
python tests/test_observe.py
python tests/test_integration.py salesforce
```

## Diagnosing Issues

For troubleshooting deployment or runtime issues:

```bash
./scripts/aws-lambda-diagnosis.sh
```

This generates a diagnostic report with CloudWatch logs, Lambda configuration, and other relevant information.

## Directory Structure

- `src/` - Source code for the Lambda functions
  - `lambda_functions/` - Individual Lambda handlers
  - `utils/` - Shared utility functions
- `tests/` - Test scripts and mock data
- `infrastructure/` - CloudFormation templates
- `scripts/` - Helper scripts for deployment and diagnostics
- `samples/` - Sample data files for testing

## License

This project is proprietary and confidential.

## Contributors

- Redis Cloud Operations Team