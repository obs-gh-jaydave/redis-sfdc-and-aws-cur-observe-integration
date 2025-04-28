#!/bin/bash
# Script to create SSM parameters for the Redis Salesforce to Observe integration

# Configuration
SF_USERNAME=""
SF_PASSWORD=""
SF_TOKEN=""
OBSERVE_TOKEN=""
OBSERVE_CUSTOMER_ID=""
OBSERVE_URL="https://api.observeinc.com"
ENVIRONMENT="dev"

# Parse command line arguments
while [[ $# -gt 0 ]]; do
  key="$1"
  case $key in
    --env)
      ENVIRONMENT="$2"
      shift 2
      ;;
    --sf-username)
      SF_USERNAME="$2"
      shift 2
      ;;
    --sf-password)
      SF_PASSWORD="$2"
      shift 2
      ;;
    --sf-token)
      SF_TOKEN="$2"
      shift 2
      ;;
    --obs-token)
      OBSERVE_TOKEN="$2"
      shift 2
      ;;
    --obs-customer)
      OBSERVE_CUSTOMER_ID="$2"
      shift 2
      ;;
    --obs-url)
      OBSERVE_URL="$2"
      shift 2
      ;;
    --help)
      echo "Usage: $0 [--env <dev|staging|production>] [--sf-username <username>] [--sf-password <password>] [--sf-token <token>] [--obs-token <token>] [--obs-customer <id>] [--obs-url <url>]"
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      echo "Usage: $0 [--env <dev|staging|production>] [--sf-username <username>] [--sf-password <password>] [--sf-token <token>] [--obs-token <token>] [--obs-customer <id>] [--obs-url <url>]"
      exit 1
      ;;
  esac
done

echo "Creating parameters for environment: $ENVIRONMENT"

# Prompt for credentials if not set
if [ -z "$SF_USERNAME" ]; then
    read -p "Salesforce Username: " SF_USERNAME
fi

if [ -z "$SF_PASSWORD" ]; then
    read -s -p "Salesforce Password: " SF_PASSWORD
    echo
fi

if [ -z "$SF_TOKEN" ]; then
    read -s -p "Salesforce Security Token: " SF_TOKEN
    echo
fi

if [ -z "$OBSERVE_TOKEN" ]; then
    read -s -p "Observe API Token: " OBSERVE_TOKEN
    echo
fi

if [ -z "$OBSERVE_CUSTOMER_ID" ]; then
    read -p "Observe Customer ID: " OBSERVE_CUSTOMER_ID
fi

# Create SSM parameters
echo "Creating SSM parameters..."

# Salesforce credentials
aws ssm put-parameter \
    --name "/redis/sfdc/username" \
    --value "$SF_USERNAME" \
    --type SecureString \
    --overwrite

aws ssm put-parameter \
    --name "/redis/sfdc/password" \
    --value "$SF_PASSWORD" \
    --type SecureString \
    --overwrite

aws ssm put-parameter \
    --name "/redis/sfdc/token" \
    --value "$SF_TOKEN" \
    --type SecureString \
    --overwrite

# Observe credentials
aws ssm put-parameter \
    --name "/redis/observe/token" \
    --value "$OBSERVE_TOKEN" \
    --type SecureString \
    --overwrite

aws ssm put-parameter \
    --name "/redis/observe/customer_id" \
    --value "$OBSERVE_CUSTOMER_ID" \
    --type String \
    --overwrite

aws ssm put-parameter \
    --name "/redis/observe/url" \
    --value "$OBSERVE_URL" \
    --type String \
    --overwrite

# Create account mapping parameter
echo "Creating account mapping parameter..."
ACCOUNT_MAPPING='{
    "123456789012": "production",
    "234567890123": "staging",
    "345678901234": "development"
}'

aws ssm put-parameter \
    --name "/redis/account_mapping" \
    --value "$ACCOUNT_MAPPING" \
    --type String \
    --overwrite

echo "SSM parameters created successfully."