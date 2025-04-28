import requests
import time
import json
import boto3
import os
import logging
from datetime import datetime

logger = logging.getLogger()

class ObserveAPIError(Exception):
    """Base class for Observe API errors."""
    pass

class ObserveRetryableError(ObserveAPIError):
    """Error that can be retried."""
    pass

class ObserveNonRetryableError(ObserveAPIError):
    """Error that should not be retried."""
    pass

class ObserveRateLimitError(ObserveRetryableError):
    """Error due to rate limiting."""
    def __init__(self, retry_after=None):
        self.retry_after = retry_after
        super().__init__(f"Rate limit exceeded, retry after {retry_after} seconds")

class CircuitBreaker:
    """Circuit breaker pattern implementation for API calls."""
    
    CLOSED = 'closed'  # Normal operation
    OPEN = 'open'      # Failing, no requests allowed
    HALF_OPEN = 'half-open'  # Testing if service is back
    
    def __init__(self, failure_threshold=5, recovery_timeout=30, retry_timeout=60):
        self.state = self.CLOSED
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.retry_timeout = retry_timeout
        self.last_failure_time = 0
        self.last_success_time = 0
    
    def record_success(self):
        """Record a successful API call."""
        self.failure_count = 0
        self.last_success_time = time.time()
        if self.state == self.HALF_OPEN:
            self.state = self.CLOSED
            logger.info("Circuit breaker returned to CLOSED state")
    
    def record_failure(self):
        """Record a failed API call."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.state == self.CLOSED and self.failure_count >= self.failure_threshold:
            self.state = self.OPEN
            logger.warning(f"Circuit breaker tripped to OPEN state after {self.failure_count} failures")
    
    def allow_request(self):
        """Check if request should be allowed based on circuit state."""
        if self.state == self.CLOSED:
            return True
        
        if self.state == self.OPEN:
            now = time.time()
            if now - self.last_failure_time >= self.recovery_timeout:
                self.state = self.HALF_OPEN
                logger.info("Circuit breaker moved to HALF-OPEN state")
                return True
            return False
        
        if self.state == self.HALF_OPEN:
            return True
            
        return False

def categorize_observe_error(response):
    """Categorize Observe API errors."""
    status_code = response.status_code
    
    if status_code == 429:
        # Rate limiting
        retry_after = int(response.headers.get('Retry-After', 5))
        return ObserveRateLimitError(retry_after)
    
    if status_code >= 500:
        # Server errors are retryable
        return ObserveRetryableError(f"Server error: {status_code}, {response.text}")
    
    if status_code == 400:
        # Bad request, likely not retryable
        return ObserveNonRetryableError(f"Bad request: {response.text}")
    
    if status_code == 401 or status_code == 403:
        # Authentication or authorization error
        return ObserveNonRetryableError(f"Authentication error: {status_code}, {response.text}")
    
    # Default to retryable for unknown errors
    return ObserveRetryableError(f"Unknown error: {status_code}, {response.text}")

class ObserveBatchSender:
    def __init__(self, observe_url, observe_token, observe_customer_id, batch_size=1000, max_retries=3):
        """Initialize Observe batch sender"""
        self._batch = []
        self.failed_records = []
        self.batch_size = batch_size
        self.max_retries = max_retries
        self.observe_url = observe_url
        self.observe_token = observe_token
        self.observe_customer_id = observe_customer_id
        self.headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {observe_token}'
        }
        self.circuit_breaker = CircuitBreaker()

    def add_record(self, record):
        """Add a single record to the batch, flush if batch size reached"""
        self._batch.append(record)
        if len(self._batch) >= self.batch_size:
            self.flush()

    def add_records(self, records):
        """Add multiple records to the batch"""
        for record in records:
            self.add_record(record)
        if self._batch:  # Flush any remaining records
            self.flush()

    def flush(self):
        """Send the current batch to Observe with enhanced error handling and circuit breaker"""
        if not self._batch:
            return
            
        # Debug logging
        logger.info(f"Attempting to send {len(self._batch)} records to Observe")
        
        # Check that Observe URL is properly set
        if not self.observe_url:
            logger.error("Observe URL is not set")
            self.failed_records.extend(self._batch)
            self._batch = []
            return
        
        # Check circuit breaker before attempting request
        if not self.circuit_breaker.allow_request():
            logger.warning("Circuit breaker is OPEN, skipping API call to Observe")
            self.failed_records.extend(self._batch)
            self._batch = []
            return
            
        attempts = 0
        while attempts < self.max_retries:
            try:
                payload = {
                    'customer_id': self.observe_customer_id,
                    'data': self._batch
                }
                
                # Use the complete URL directly from the configuration
                url = self.observe_url
                logger.info(f"Making request to: {url}")
                logger.info(f"Headers: Authorization: Bearer ****{self.observe_token[-4:]}")
                
                # Log a sample of the payload (be careful not to log sensitive data)
                sample_record = self._batch[0] if self._batch else {}
                logger.info(f"Sample record keys: {list(sample_record.keys())}")
                
                response = requests.post(
                    url,
                    headers=self.headers,
                    json=payload,
                    timeout=10
                )
                
                logger.info(f"Response status code: {response.status_code}")
                logger.info(f"Response headers: {dict(response.headers)}")
                
                if 200 <= response.status_code < 300:
                    logger.info(f"Successfully sent {len(self._batch)} records to Observe")
                    self.circuit_breaker.record_success()
                    self._batch = []
                    return
                else:
                    # Log the full response text for debugging
                    logger.error(f"Response body: {response.text}")
                    error = categorize_observe_error(response)
                    
                    if isinstance(error, ObserveRateLimitError):
                        logger.warning(f"Observe API rate limit exceeded, retry after {error.retry_after}s")
                        time.sleep(error.retry_after)
                    elif isinstance(error, ObserveRetryableError):
                        logger.error(f"Retryable error: {str(error)}")
                        self.circuit_breaker.record_failure()
                        attempts += 1
                        time.sleep(2 ** attempts)
                    else:  # Non-retryable error
                        logger.error(f"Non-retryable error: {str(error)}")
                        self.circuit_breaker.record_failure()
                        attempts = self.max_retries  # Skip to failure handling
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                logger.error(f"Network error sending to Observe: {str(e)}")
                self.circuit_breaker.record_failure()
                attempts += 1
                time.sleep(2 ** attempts)
            except Exception as e:
                logger.error(f"Batch send failed: {str(e)}")
                self.circuit_breaker.record_failure()
                attempts += 1
                time.sleep(2 ** attempts)
        
        # If we get here, we've failed all retries
        logger.error(f"Failed to send batch after {self.max_retries} attempts")
        
        # Save failed records for potential replay
        self.failed_records.extend(self._batch)
        logger.warning(f"Added {len(self._batch)} records to failed_records list (total: {len(self.failed_records)})")
        
        # Write to DLQ
        self._write_to_dlq(self._batch)
        
        # Clear the batch after recording failures
        self._batch = []
    
    def _write_to_dlq(self, records):
        """Write failed records to Dead Letter Queue"""
        try:
            if 'AWS_LAMBDA_FUNCTION_NAME' in os.environ:
                # We're running in Lambda, can use SQS
                sqs = boto3.client('sqs')
                queue_url = os.environ.get('FAILED_RECORDS_QUEUE_URL')
                if queue_url:
                    # Break into smaller chunks for SQS size limits
                    chunk_size = 10  # SQS messages have a size limit
                    for i in range(0, len(records), chunk_size):
                        chunk = records[i:i+chunk_size]
                        sqs.send_message(
                            QueueUrl=queue_url,
                            MessageBody=json.dumps({
                                'records': chunk,
                                'timestamp': time.time(),
                                'customer_id': self.observe_customer_id,
                                'failed_timestamp': datetime.now().isoformat()
                            })
                        )
                    logger.info(f"Sent {len(records)} failed records to SQS DLQ")
                    return True
        except Exception as e:
            logger.error(f"Failed to write to DLQ: {str(e)}")
        return False