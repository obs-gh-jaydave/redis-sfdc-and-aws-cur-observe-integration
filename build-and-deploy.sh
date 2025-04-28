#!/bin/bash
# build-and-deploy.sh - One-click build and deployment script for Redis SFDC Observe Integration

# Colors for better readability
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default configuration
ENVIRONMENT="dev"
S3_BUCKET="redis-lambda-code-bucket"
CUR_BUCKET_BASE="redis-billing-reports"
USE_S3_PARQUET="true"
BUILD_ONLY="false"
DEPLOY_ONLY="false"
SKIP_TEST="false"
TEST_DELAY=30  # Seconds to wait after deployment before testing
TRIGGER_IMMEDIATE_EXECUTION="true" # Parameter for immediate execution
SKIP_BUCKET_CREATION="false" 

# Print banner
echo -e "${BLUE}===================================================${NC}"
echo -e "${BLUE}Redis Salesforce to Observe Integration - Build & Deploy${NC}"
echo -e "${BLUE}===================================================${NC}"

# Parse command line arguments
while [[ $# -gt 0 ]]; do
  key="$1"
  case $key in
    --env)
      ENVIRONMENT="$2"
      shift 2
      ;;
    --build-only)
      BUILD_ONLY="true"
      shift
      ;;
    --deploy-only)
      DEPLOY_ONLY="true"
      shift
      ;;
    --lambda-bucket)
      S3_BUCKET="$2"
      shift 2
      ;;
    --cur-bucket)
      CUR_BUCKET_BASE="$2"
      shift 2
      ;;
    --use-s3-parquet)
      if [[ "$2" == "true" || "$2" == "false" ]]; then
        USE_S3_PARQUET="$2"
      else
        echo -e "${RED}Invalid value for --use-s3-parquet. Must be 'true' or 'false'.${NC}"
        exit 1
      fi
      shift 2
      ;;
    --skip-test)
      SKIP_TEST="true"
      shift
      ;;
    --test-delay)
      TEST_DELAY="$2"
      shift 2
      ;;
    --immediate-execution)
      if [[ "$2" == "true" || "$2" == "false" ]]; then
        TRIGGER_IMMEDIATE_EXECUTION="$2"
      else
        echo -e "${RED}Invalid value for --immediate-execution. Must be 'true' or 'false'.${NC}"
        exit 1
      fi
      shift 2
      ;;
    --skip-bucket-creation)
      if [[ "$2" == "true" || "$2" == "false" ]]; then
        SKIP_BUCKET_CREATION="$2"
      else
        echo -e "${RED}Invalid value for --skip-bucket-creation. Must be 'true' or 'false'.${NC}"
        exit 1
      fi
      shift 2
      ;;
    --help)
      echo "Usage: $0 [options]"
      echo ""
      echo "Options:"
      echo "  --env <environment>      Deployment environment (dev, staging, production)"
      echo "  --build-only             Only build the Lambda packages, don't deploy"
      echo "  --deploy-only            Only deploy (skip building packages)"
      echo "  --lambda-bucket <name>   S3 bucket for Lambda code"
      echo "  --cur-bucket <name>      Base name for S3 bucket for AWS Cost and Usage Reports"
      echo "  --use-s3-parquet <t|f>   Use S3 for parquet processing"
      echo "  --skip-test              Skip the post-deployment test"
      echo "  --test-delay <seconds>   Seconds to wait before testing (default: 30)"
      echo "  --immediate-execution <t|f> Trigger CUR fetcher immediately after deployment (default: true)"
      echo "  --skip-bucket-creation <t|f> Skip S3 bucket creation in CloudFormation (default: false)"
      echo "  --help                   Show this help message"
      exit 0
      ;;
    *)
      echo -e "${RED}Unknown option: $1${NC}"
      echo "Run '$0 --help' for usage information."
      exit 1
      ;;
  esac
done

# Check if both build-only and deploy-only are set
if [[ "$BUILD_ONLY" == "true" && "$DEPLOY_ONLY" == "true" ]]; then
  echo -e "${RED}Error: Cannot use both --build-only and --deploy-only together${NC}"
  exit 1
fi

# Ensure AWS CLI is available
if ! command -v aws &> /dev/null; then
  echo -e "${RED}Error: AWS CLI is not installed or not in PATH${NC}"
  echo "Please install AWS CLI before continuing: https://aws.amazon.com/cli/"
  exit 1
fi

# Ensure AWS credentials are configured
if ! aws sts get-caller-identity &> /dev/null; then
  echo -e "${RED}Error: AWS CLI not configured with valid credentials${NC}"
  echo "Please run 'aws configure' to set up your AWS credentials"
  exit 1
fi

# Function to load environment variables from .env file
load_env_file() {
  local env_file=$1
  if [ -f "$env_file" ]; then
    echo -e "${YELLOW}Loading environment variables from $env_file${NC}"
    
    # Read each line from .env file
    while IFS= read -r line || [[ -n "$line" ]]; do
      # Skip comments and empty lines
      [[ "$line" =~ ^#.*$ || -z "$line" ]] && continue
      
      # Extract variable and value
      if [[ "$line" =~ ^([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]]; then
        var_name="${BASH_REMATCH[1]}"
        var_value="${BASH_REMATCH[2]}"
        
        # Remove surrounding quotes if present
        if [[ "$var_value" =~ ^\"(.*)\"$ ]]; then
          var_value="${BASH_REMATCH[1]}"
        elif [[ "$var_value" =~ ^\'(.*)\'$ ]]; then
          var_value="${BASH_REMATCH[1]}"
        fi
        
        # Export variable to environment
        export "$var_name"="$var_value"
        
        # Show loaded variables (mask sensitive ones)
        if [[ "$var_name" == *"PASSWORD"* || "$var_name" == *"TOKEN"* || "$var_name" == *"SECRET"* ]]; then
          echo -e "  Loaded: ${var_name}=********"
        else
          echo -e "  Loaded: ${var_name}=${var_value}"
        fi
      fi
    done < "$env_file"
    
    return 0
  else
    echo -e "${YELLOW}No $env_file file found, skipping...${NC}"
    return 1
  fi
}

# Load environment variables from .env file
load_env_file ".env"

# Check and map variables from .env file
if [[ -f ".env" ]]; then
  # If .env exists, map variables to expected names
  if [[ -n "$DEPLOY_ENV" ]]; then
    ENVIRONMENT="$DEPLOY_ENV"
    echo -e "${GREEN}Using DEPLOY_ENV=$DEPLOY_ENV from .env file${NC}"
  fi
  
  # Print loaded environment variables for debugging
  echo -e "${YELLOW}Loaded environment variables:${NC}"
  if [[ -n "$SALESFORCE_USERNAME" ]]; then echo -e "  SALESFORCE_USERNAME is set"; fi
  if [[ -n "$SALESFORCE_PASSWORD" ]]; then echo -e "  SALESFORCE_PASSWORD is set"; fi
  if [[ -n "$SALESFORCE_TOKEN" ]]; then echo -e "  SALESFORCE_TOKEN is set"; fi
  if [[ -n "$OBSERVE_URL" ]]; then echo -e "  OBSERVE_URL=$OBSERVE_URL"; fi
  if [[ -n "$OBSERVE_TOKEN" ]]; then echo -e "  OBSERVE_TOKEN is set"; fi
  if [[ -n "$OBSERVE_CUSTOMER_ID" ]]; then echo -e "  OBSERVE_CUSTOMER_ID=$OBSERVE_CUSTOMER_ID"; fi
  if [[ -n "$AWS_ACCOUNT_MAPPING" ]]; then echo -e "  AWS_ACCOUNT_MAPPING is set"; fi
else
  echo -e "${YELLOW}No .env file found in current directory. Will use command line parameters or defaults.${NC}"
fi

# Set environment-specific resource names
CUR_BUCKET_NAME="${CUR_BUCKET_BASE}-${ENVIRONMENT}"

# Show configuration
echo -e "${YELLOW}Build & Deploy Configuration:${NC}"
echo -e "  Environment: ${GREEN}$ENVIRONMENT${NC}"
echo -e "  Lambda Code S3 Bucket: ${GREEN}$S3_BUCKET${NC}"
echo -e "  CUR S3 Bucket: ${GREEN}$CUR_BUCKET_NAME${NC}"
echo -e "  Use S3 for Parquet: ${GREEN}$USE_S3_PARQUET${NC}"
if [[ "$BUILD_ONLY" == "true" ]]; then
  echo -e "  ${YELLOW}Build Only Mode${NC}"
elif [[ "$DEPLOY_ONLY" == "true" ]]; then
  echo -e "  ${YELLOW}Deploy Only Mode${NC}"
fi
if [[ "$SKIP_TEST" == "true" ]]; then
  echo -e "  ${YELLOW}Post-deployment test skipped${NC}"
else
  echo -e "  ${YELLOW}Post-deployment test will run after ${TEST_DELAY}s delay${NC}"
fi
if [[ "$TRIGGER_IMMEDIATE_EXECUTION" == "true" ]]; then
  echo -e "  ${YELLOW}CUR fetcher will be triggered immediately after deployment${NC}"
fi
if [[ "$SKIP_BUCKET_CREATION" == "true" ]]; then
  echo -e "  ${YELLOW}S3 bucket creation will be skipped in CloudFormation${NC}"
fi
echo ""

# Check if Docker is available (for build)
if [[ "$DEPLOY_ONLY" != "true" ]]; then
  if ! command -v docker &> /dev/null; then
    echo -e "${RED}Error: Docker is not installed or not in PATH${NC}"
    echo "Please install Docker before continuing: https://docs.docker.com/get-docker/"
    exit 1
  fi
fi

# Function to create S3 bucket if it doesn't exist
create_bucket_if_not_exists() {
  local bucket_name=$1
  
  # Check if bucket exists
  if ! aws s3api head-bucket --bucket "$bucket_name" 2>/dev/null; then
    echo -e "${YELLOW}Creating S3 bucket: $bucket_name${NC}"
    if aws s3 mb "s3://$bucket_name"; then
      echo -e "${GREEN}Successfully created bucket: $bucket_name${NC}"
    else
      echo -e "${RED}Failed to create bucket: $bucket_name${NC}"
      return 1
    fi
  else
    echo -e "${GREEN}S3 bucket already exists: $bucket_name${NC}"
    # Set the skip bucket creation flag if the bucket already exists
    SKIP_BUCKET_CREATION="true"
  fi
  return 0
}

# Function to test Lambda function
test_lambda_function() {
  local function_name=$1
  local test_output_file="lambda-test-output.json"
  
  echo -e "${BLUE}Step 3: Testing Lambda Function${NC}"
  echo -e "${YELLOW}Waiting ${TEST_DELAY} seconds for Lambda to be ready...${NC}"
  sleep $TEST_DELAY
  
  echo -e "${YELLOW}Invoking Lambda function: $function_name${NC}"
  if aws lambda invoke \
    --function-name "$function_name" \
    --payload '{"action":"salesforce"}' \
    --cli-binary-format raw-in-base64-out \
    "$test_output_file"; then
    
    echo -e "${GREEN}Lambda invocation successful!${NC}"
    echo -e "${YELLOW}Function response:${NC}"
    cat "$test_output_file"
    
    # Check if the response contains a successful status code
    if grep -q '"statusCode": 200' "$test_output_file"; then
      echo -e "${GREEN}Test passed: Lambda function returned status code 200${NC}"
      return 0
    else
      echo -e "${RED}Test failed: Lambda function did not return status code 200${NC}"
      return 1
    fi
  else
    echo -e "${RED}Failed to invoke Lambda function${NC}"
    return 1
  fi
}

# Function to trigger immediate execution of CUR fetcher
trigger_cur_fetcher() {
  local cur_fetcher_function="redis-cur-fetcher-${ENVIRONMENT}"
  local response_file="cur-fetcher-response.json"
  
  echo -e "${YELLOW}Triggering immediate execution of CUR Fetcher Lambda...${NC}"
  if aws lambda invoke \
    --function-name "$cur_fetcher_function" \
    --invocation-type Event \
    --cli-binary-format raw-in-base64-out \
    "$response_file"; then
    
    echo -e "${GREEN}Successfully triggered immediate execution of CUR Fetcher Lambda${NC}"
    return 0
  else
    echo -e "${RED}Failed to trigger CUR Fetcher Lambda${NC}"
    return 1
  fi
}

# Build the Lambda package if not in deploy-only mode
if [[ "$DEPLOY_ONLY" != "true" ]]; then
  echo -e "${BLUE}Step 1: Building Lambda packages using Docker${NC}"
  
  # Create temp directory for output
  echo -e "${YELLOW}Creating temporary build directories...${NC}"
  
  # Clean up any previous builds
  rm -rf build-output
  mkdir -p build-output
  
  # Run Docker to build the Lambda package
  echo -e "${YELLOW}Running Docker build container...${NC}"
  docker run --platform linux/amd64 --rm \
    -v "$(pwd):/var/task" \
    -v "$(pwd)/build-output:/var/output" \
    -w /var/task \
    --entrypoint bash \
    amazon/aws-lambda-python:3.9 -c "\
    yum update -y && yum install -y zip && \
    pip install --upgrade pip && \
    mkdir -p /var/output/package/src && \
    cp -r src/* /var/output/package/src/ && \
    echo 'import os, sys' > /var/output/package/index.py && \
    echo 'from src.lambda_functions.index import lambda_handler' >> /var/output/package/index.py && \
    cd /var/output/package && find . -name '*.pyc' -delete && \
    find . -name '__pycache__' -delete && \
    zip -r9 ../redis-data-ingestion.zip . && \
    cd /var/task"
  
  if [ $? -ne 0 ]; then
    echo -e "${RED}Docker build failed${NC}"
    exit 1
  fi
  
  # Create core layer - keep it lightweight
  echo -e "${YELLOW}Creating core Lambda layer...${NC}"
  
  CORE_DEPENDENCIES="boto3==1.26.135 simple-salesforce==1.12.4 requests==2.30.0 aws-lambda-powertools==2.16.2 python-dotenv==1.0.0"
  
  docker run --platform linux/amd64 --rm \
    -v "$(pwd):/var/task" \
    -v "$(pwd)/build-output:/var/output" \
    -w /var/task \
    --entrypoint bash \
    amazon/aws-lambda-python:3.9 -c "\
    yum update -y && yum install -y zip && \
    mkdir -p /var/output/layer-core/python && \
    pip install $CORE_DEPENDENCIES -t /var/output/layer-core/python && \
    cd /var/output/layer-core && \
    zip -r9 ../data-processing-core-layer.zip ."
  
  if [ $? -ne 0 ]; then
    echo -e "${RED}Core layer build failed${NC}"
    exit 1
  fi
  
  # Create pandas layer
  echo -e "${YELLOW}Creating pandas Lambda layer...${NC}"
  docker run --platform linux/amd64 --rm \
    -v "$(pwd):/var/task" \
    -v "$(pwd)/build-output:/var/output" \
    -w /var/task \
    --entrypoint bash \
    amazon/aws-lambda-python:3.9 -c "\
    yum update -y && yum install -y zip && \
    mkdir -p /var/output/layer-pandas/python && \
    pip install pandas==1.5.3 numpy==1.24.3 -t /var/output/layer-pandas/python && \
    cd /var/output/layer-pandas && \
    zip -r9 ../pandas-layer.zip ."
  
  if [ $? -ne 0 ]; then
    echo -e "${RED}Pandas layer build failed${NC}"
    exit 1
  fi
  
  # Print package sizes
  echo -e "${GREEN}Successfully created Lambda packages:${NC}"
  echo -e "  Function Package: $(du -h build-output/redis-data-ingestion.zip | cut -f1)"
  echo -e "  Core Layer: $(du -h build-output/data-processing-core-layer.zip | cut -f1)"
  echo -e "  Pandas Layer: $(du -h build-output/pandas-layer.zip | cut -f1)"
fi

# If build-only mode, exit here
if [[ "$BUILD_ONLY" == "true" ]]; then
  echo -e "${GREEN}Build completed successfully.${NC}"
  echo -e "Lambda packages are available in the ${BLUE}build-output${NC} directory."
  exit 0
fi

# Deploy to AWS if not in build-only mode
echo -e "${BLUE}Step 2: Deploying to AWS (Environment: $ENVIRONMENT)${NC}"

# Create S3 buckets if they don't exist
echo -e "${YELLOW}Checking S3 buckets...${NC}"
create_bucket_if_not_exists "$S3_BUCKET" || exit 1
create_bucket_if_not_exists "$CUR_BUCKET_NAME" || exit 1

# Upload Lambda packages to S3 bucket if not in deploy-only mode
if [[ "$DEPLOY_ONLY" != "true" ]]; then
  echo -e "${YELLOW}Uploading Lambda packages to S3...${NC}"
  aws s3 cp build-output/redis-data-ingestion.zip "s3://$S3_BUCKET/"
  aws s3 cp build-output/data-processing-core-layer.zip "s3://$S3_BUCKET/"
  aws s3 cp build-output/pandas-layer.zip "s3://$S3_BUCKET/"
fi

# Construct stack name
STACK_NAME="redis-data-ingestion-${ENVIRONMENT}"

# Check if stack exists and is in ROLLBACK_COMPLETE state
echo -e "${YELLOW}Checking CloudFormation stack status...${NC}"
STACK_STATUS=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --query "Stacks[0].StackStatus" --output text 2>/dev/null || echo "STACK_NOT_FOUND")

if [ "$STACK_STATUS" == "ROLLBACK_COMPLETE" ]; then
  echo -e "${YELLOW}Stack is in ROLLBACK_COMPLETE state. Deleting stack before redeploying...${NC}"
  aws cloudformation delete-stack --stack-name "$STACK_NAME"
  echo -e "${YELLOW}Waiting for stack deletion to complete...${NC}"
  aws cloudformation wait stack-delete-complete --stack-name "$STACK_NAME"
  echo -e "${GREEN}Stack deletion completed successfully.${NC}"
fi

# Set up parameter overrides for CloudFormation deployment
PARAM_OVERRIDES="LambdaCodeS3Bucket=\"$S3_BUCKET\" \
  LambdaCodeS3Key=\"redis-data-ingestion.zip\" \
  CoreLayerCodeS3Key=\"data-processing-core-layer.zip\" \
  PandasLayerCodeS3Key=\"pandas-layer.zip\" \
  CURBucketName=\"$CUR_BUCKET_NAME\" \
  Environment=\"$ENVIRONMENT\" \
  UseS3ForParquet=\"$USE_S3_PARQUET\""

# Add the SkipBucketCreation parameter if needed
if [[ "$SKIP_BUCKET_CREATION" == "true" ]]; then
  PARAM_OVERRIDES="$PARAM_OVERRIDES SkipBucketCreation=\"true\""
fi

# Deploy CloudFormation stack
echo -e "${YELLOW}Deploying CloudFormation stack: $STACK_NAME${NC}"
aws cloudformation deploy \
  --template-file infrastructure/cloudformation.yaml \
  --stack-name "$STACK_NAME" \
  --parameter-overrides \
    "LambdaCodeS3Bucket=$S3_BUCKET" \
    "LambdaCodeS3Key=redis-data-ingestion.zip" \
    "CoreLayerCodeS3Key=data-processing-core-layer.zip" \
    "PandasLayerCodeS3Key=pandas-layer.zip" \
    "CURBucketName=$CUR_BUCKET_NAME" \
    "Environment=$ENVIRONMENT" \
    "UseS3ForParquet=$USE_S3_PARQUET" \
    "SkipBucketCreation=$SKIP_BUCKET_CREATION" \
  --capabilities CAPABILITY_IAM

if [ $? -ne 0 ]; then
  echo -e "${RED}CloudFormation deployment failed${NC}"
  exit 1
fi

# Display CloudFormation outputs
echo -e "${GREEN}CloudFormation deployment completed successfully!${NC}"
echo -e "${YELLOW}Stack outputs:${NC}"
aws cloudformation describe-stacks --stack-name "$STACK_NAME" --query "Stacks[0].Outputs" --output table

# Trigger immediate execution of CUR fetcher if enabled
if [[ "$TRIGGER_IMMEDIATE_EXECUTION" == "true" ]]; then
  # Wait a moment for the Lambda function to be fully operational
  echo -e "${YELLOW}Waiting 5 seconds for Lambda functions to be fully initialized...${NC}"
  sleep 5
  
  # Trigger the CUR fetcher
  trigger_cur_fetcher
fi

# Set up parameter store entries using environment variables
echo -e "${YELLOW}Setting up parameter store entries in AWS SSM...${NC}"

# Check if create-params.sh script exists
if [ -f "./scripts/create-params.sh" ] && [ "$USE_CREATE_PARAMS_SCRIPT" = "true" ]; then
  echo -e "${YELLOW}Found create-params.sh script. Running it with environment: $ENVIRONMENT${NC}"
  ./scripts/create-params.sh --env "$ENVIRONMENT"
else
  echo -e "${YELLOW}Parameter script not found. Creating SSM parameters from environment variables...${NC}"
  
  # Create AWS account mapping parameter
  if [ -n "$AWS_ACCOUNT_MAPPING" ]; then
    ACCOUNT_MAPPING=$AWS_ACCOUNT_MAPPING
  else
    ACCOUNT_MAPPING='{"123456789012":"production","234567890123":"staging","345678901234":"development"}'
  fi
  
  # Create SSM parameters using values from environment variables if available
  aws ssm put-parameter \
    --name "/redis/sfdc/username" \
    --type "String" \
    --value "${SALESFORCE_USERNAME:-PLACEHOLDER_USERNAME}" \
    --overwrite
  
  aws ssm put-parameter \
    --name "/redis/sfdc/password" \
    --type "SecureString" \
    --value "${SALESFORCE_PASSWORD:-PLACEHOLDER_PASSWORD}" \
    --overwrite
  
  aws ssm put-parameter \
    --name "/redis/sfdc/token" \
    --type "SecureString" \
    --value "${SALESFORCE_TOKEN:-PLACEHOLDER_TOKEN}" \
    --overwrite
  
  aws ssm put-parameter \
    --name "/redis/observe/url" \
    --type "String" \
    --value "${OBSERVE_URL:-https://collect.observeinc.com}" \
    --overwrite
  
  aws ssm put-parameter \
    --name "/redis/observe/token" \
    --type "SecureString" \
    --value "${OBSERVE_TOKEN:-PLACEHOLDER_TOKEN}" \
    --overwrite
  
  aws ssm put-parameter \
    --name "/redis/observe/customer_id" \
    --type "String" \
    --value "${OBSERVE_CUSTOMER_ID:-PLACEHOLDER_ID}" \
    --overwrite
  
  aws ssm put-parameter \
    --name "/redis/account_mapping" \
    --type "String" \
    --value "$ACCOUNT_MAPPING" \
    --overwrite
  
  echo -e "${GREEN}Created SSM parameters using values from environment variables.${NC}"
  
  # Check for placeholder values
  if [[ -z "$SALESFORCE_USERNAME" || -z "$SALESFORCE_PASSWORD" || -z "$SALESFORCE_TOKEN" ||
         -z "$OBSERVE_TOKEN" || -z "$OBSERVE_CUSTOMER_ID" ]]; then
    echo -e "${YELLOW}Some parameters were set with placeholder values. Please update them with your real values:${NC}"
    
    if [ -z "$SALESFORCE_USERNAME" ]; then
      echo -e "${GREEN}aws ssm put-parameter --name \"/redis/sfdc/username\" --type \"String\" --value \"YOUR_USERNAME\" --overwrite${NC}"
    fi
    
    if [ -z "$SALESFORCE_PASSWORD" ]; then
      echo -e "${GREEN}aws ssm put-parameter --name \"/redis/sfdc/password\" --type \"SecureString\" --value \"YOUR_PASSWORD\" --overwrite${NC}"
    fi
    
    if [ -z "$SALESFORCE_TOKEN" ]; then
      echo -e "${GREEN}aws ssm put-parameter --name \"/redis/sfdc/token\" --type \"SecureString\" --value \"YOUR_TOKEN\" --overwrite${NC}"
    fi
    
    if [ -z "$OBSERVE_TOKEN" ]; then
      echo -e "${GREEN}aws ssm put-parameter --name \"/redis/observe/token\" --type \"SecureString\" --value \"YOUR_TOKEN\" --overwrite${NC}"
    fi
    
    if [ -z "$OBSERVE_CUSTOMER_ID" ]; then
      echo -e "${GREEN}aws ssm put-parameter --name \"/redis/observe/customer_id\" --type \"String\" --value \"YOUR_CUSTOMER_ID\" --overwrite${NC}"
    fi
  else
    echo -e "${GREEN}All required parameters were populated from environment variables.${NC}"
  fi
fi

# Test Lambda function if not in build-only mode and not skipping test
if [[ "$SKIP_TEST" != "true" ]]; then
  # Define Lambda function name
  LAMBDA_FUNCTION="redis-data-ingestion-${ENVIRONMENT}"
  
  # Test Lambda function
  test_lambda_function "$LAMBDA_FUNCTION"
  TEST_RESULT=$?
  
  if [ $TEST_RESULT -eq 0 ]; then
    echo -e "${GREEN}Lambda function test passed successfully!${NC}"
  else
    echo -e "${YELLOW}Lambda function test did not pass. This might be due to:${NC}"
    echo -e "  - Lambda function is still initializing (cold start)"
    echo -e "  - Missing or incorrect parameters in SSM Parameter Store"
    echo -e "  - Permissions issues with IAM roles"
    echo -e ""
    echo -e "${YELLOW}Try running the test again manually after updating parameters:${NC}"
    echo -e "${GREEN}aws lambda invoke --function-name $LAMBDA_FUNCTION --payload '{\"action\":\"salesforce\"}' output.txt && cat output.txt${NC}"
  fi
fi

# Clean up if not in deploy-only mode
if [[ "$DEPLOY_ONLY" != "true" ]]; then
  echo -e "${YELLOW}Cleaning up build artifacts...${NC}"
  rm -rf build-output
  rm -f lambda-test-output.json
  rm -f cur-fetcher-response.json
fi

# Done!
echo -e "${GREEN}===========================================${NC}"
echo -e "${GREEN}Deployment Completed Successfully!${NC}"
echo -e "${GREEN}Environment: $ENVIRONMENT${NC}"
echo -e "${GREEN}===========================================${NC}"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
if [[ -z "$SALESFORCE_USERNAME" || -z "$SALESFORCE_PASSWORD" || -z "$SALESFORCE_TOKEN" ||
       -z "$OBSERVE_TOKEN" || -z "$OBSERVE_CUSTOMER_ID" ]]; then
  echo "1. Update SSM parameters with your actual credentials"
  echo "2. Run a test execution with:"
else
  echo "Run a test execution with:"
fi
echo "   aws lambda invoke --function-name redis-data-ingestion-$ENVIRONMENT --payload '{\"action\":\"salesforce\"}' output.txt && cat output.txt"
echo ""
echo -e "${BLUE}Thank you for using the Redis SFDC-Observe build and deploy script!${NC}"