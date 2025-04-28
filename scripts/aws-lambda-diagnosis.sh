#!/bin/bash

# AWS Lambda diagnosis script
# This script checks various AWS services to diagnose issues with Lambda execution
# Outputs results to a diagnostic file

# Set variables
DIAGNOSTICS_FILE="aws-lambda-diagnostics-$(date +"%Y%m%d-%H%M%S").txt"
DATA_INGESTION_FUNCTION="redis-data-ingestion-production"
CUR_FETCHER_FUNCTION="redis-cur-fetcher-production"
S3_BUCKET="redis-billing-reports-demo"
FAILED_RECORDS_DLQ="https://sqs.us-east-1.amazonaws.com/384876807807/redis-observe-failed-records-production"
WORK_QUEUE="https://sqs.us-east-1.amazonaws.com/384876807807/redis-data-ingestion-work-queue-production"

# Start with a clean file
echo "AWS Lambda Diagnostics - $(date)" > $DIAGNOSTICS_FILE
echo "=======================================" >> $DIAGNOSTICS_FILE

# Function to add section headers
add_section() {
    echo "" >> $DIAGNOSTICS_FILE
    echo "---------------------------------------" >> $DIAGNOSTICS_FILE
    echo "$1" >> $DIAGNOSTICS_FILE
    echo "---------------------------------------" >> $DIAGNOSTICS_FILE
}

# 1. Check CloudWatch Logs for Lambda functions
add_section "1. CloudWatch Logs for $DATA_INGESTION_FUNCTION"
echo "Log streams (most recent first):" >> $DIAGNOSTICS_FILE
aws logs describe-log-streams --log-group-name "/aws/lambda/$DATA_INGESTION_FUNCTION" --order-by LastEventTime --descending --max-items 5 >> $DIAGNOSTICS_FILE 2>&1

# Get the most recent log stream name
LATEST_LOG_STREAM=$(aws logs describe-log-streams --log-group-name "/aws/lambda/$DATA_INGESTION_FUNCTION" --order-by LastEventTime --descending --max-items 1 --query 'logStreams[0].logStreamName' --output text)

if [[ $LATEST_LOG_STREAM != "None" && -n $LATEST_LOG_STREAM ]]; then
    echo "" >> $DIAGNOSTICS_FILE
    echo "Most recent logs from $LATEST_LOG_STREAM:" >> $DIAGNOSTICS_FILE
    aws logs get-log-events --log-group-name "/aws/lambda/$DATA_INGESTION_FUNCTION" --log-stream-name "$LATEST_LOG_STREAM" --limit 100 --query 'events[*].message' --output text >> $DIAGNOSTICS_FILE 2>&1
else
    echo "No log streams found for $DATA_INGESTION_FUNCTION" >> $DIAGNOSTICS_FILE
fi

add_section "2. CloudWatch Logs for $CUR_FETCHER_FUNCTION"
echo "Log streams (most recent first):" >> $DIAGNOSTICS_FILE
aws logs describe-log-streams --log-group-name "/aws/lambda/$CUR_FETCHER_FUNCTION" --order-by LastEventTime --descending --max-items 5 >> $DIAGNOSTICS_FILE 2>&1

# Get the most recent log stream name
LATEST_LOG_STREAM=$(aws logs describe-log-streams --log-group-name "/aws/lambda/$CUR_FETCHER_FUNCTION" --order-by LastEventTime --descending --max-items 1 --query 'logStreams[0].logStreamName' --output text)

if [[ $LATEST_LOG_STREAM != "None" && -n $LATEST_LOG_STREAM ]]; then
    echo "" >> $DIAGNOSTICS_FILE
    echo "Most recent logs from $LATEST_LOG_STREAM:" >> $DIAGNOSTICS_FILE
    aws logs get-log-events --log-group-name "/aws/lambda/$CUR_FETCHER_FUNCTION" --log-stream-name "$LATEST_LOG_STREAM" --limit 100 --query 'events[*].message' --output text >> $DIAGNOSTICS_FILE 2>&1
else
    echo "No log streams found for $CUR_FETCHER_FUNCTION" >> $DIAGNOSTICS_FILE
fi

# 2. Check CloudWatch Events/EventBridge Rules
add_section "3. CloudWatch Event Rules"
echo "RedisSalesforceDailySync-production rule:" >> $DIAGNOSTICS_FILE
aws events describe-rule --name RedisSalesforceDailySync-production >> $DIAGNOSTICS_FILE 2>&1

echo "" >> $DIAGNOSTICS_FILE
echo "RedisCURFetchSchedule-production rule:" >> $DIAGNOSTICS_FILE
aws events describe-rule --name RedisCURFetchSchedule-production >> $DIAGNOSTICS_FILE 2>&1

# 3. Check Lambda Function Configurations
add_section "4. Lambda Function Configurations"
echo "$DATA_INGESTION_FUNCTION configuration:" >> $DIAGNOSTICS_FILE
aws lambda get-function --function-name $DATA_INGESTION_FUNCTION >> $DIAGNOSTICS_FILE 2>&1

echo "" >> $DIAGNOSTICS_FILE
echo "$CUR_FETCHER_FUNCTION configuration:" >> $DIAGNOSTICS_FILE
aws lambda get-function --function-name $CUR_FETCHER_FUNCTION >> $DIAGNOSTICS_FILE 2>&1

# 4. Check for recent Lambda invocations
add_section "5. Recent Lambda Invocations (last 24 hours)"
START_TIME=$(date -u -d '24 hours ago' +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date -u -v-1d +"%Y-%m-%dT%H:%M:%SZ")
aws cloudtrail lookup-events --lookup-attributes AttributeKey=EventName,AttributeValue=Invoke --start-time "$START_TIME" >> $DIAGNOSTICS_FILE 2>&1

# 5. Check S3 Bucket for files
add_section "6. S3 Bucket Contents"
echo "Listing objects in $S3_BUCKET:" >> $DIAGNOSTICS_FILE
aws s3 ls s3://$S3_BUCKET/ --recursive >> $DIAGNOSTICS_FILE 2>&1

# 6. Check SQS Queues
add_section "7. SQS Queue Status"
echo "Failed Records DLQ:" >> $DIAGNOSTICS_FILE
aws sqs get-queue-attributes \
  --queue-url $FAILED_RECORDS_DLQ \
  --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible >> $DIAGNOSTICS_FILE 2>&1

echo "" >> $DIAGNOSTICS_FILE
echo "Work Queue:" >> $DIAGNOSTICS_FILE
aws sqs get-queue-attributes \
  --queue-url $WORK_QUEUE \
  --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible >> $DIAGNOSTICS_FILE 2>&1

# 7. Test connectivity to Observe by manually invoking Lambda
add_section "8. Testing Lambda Connectivity"
echo "Creating test event for Observe connectivity..." >> $DIAGNOSTICS_FILE

# Create a test event file
cat > test-observe-event.json << EOF
{
  "action": "test",
  "test_connectivity": true
}
EOF

echo "Invoking $DATA_INGESTION_FUNCTION with test event..." >> $DIAGNOSTICS_FILE
aws lambda invoke --function-name $DATA_INGESTION_FUNCTION --payload file://test-observe-event.json test-output.txt >> $DIAGNOSTICS_FILE 2>&1

echo "" >> $DIAGNOSTICS_FILE
echo "Response from Lambda:" >> $DIAGNOSTICS_FILE
cat test-output.txt >> $DIAGNOSTICS_FILE 2>&1

# Clean up temporary files
rm -f test-observe-event.json test-output.txt

# 8. Summary
add_section "9. Summary"
echo "Diagnosis completed at $(date)" >> $DIAGNOSTICS_FILE
echo "For detailed analysis, examine the logs and configurations above." >> $DIAGNOSTICS_FILE
echo "Check especially for error messages and confirm that the scheduled events are enabled." >> $DIAGNOSTICS_FILE

echo "Diagnostics completed. Results saved to $DIAGNOSTICS_FILE"