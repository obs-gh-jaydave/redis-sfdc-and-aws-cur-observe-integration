import os
import json
import boto3
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Union
from dotenv import load_dotenv

logger = logging.getLogger()

class Config:
    """Centralized configuration management for the Redis data ingestion pipeline.
    
    Supports loading configuration from:
    - Environment variables
    - .env files
    - AWS SSM Parameter Store
    - AWS Secrets Manager
    """
    
    _instance = None
    
    def __new__(cls):
        """Implement singleton pattern."""
        if cls._instance is None:
            cls._instance = super(Config, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        """Initialize the configuration system."""
        if self._initialized:
            return
            
        # Store the loaded configuration
        self._config = {}
        
        # Load environment configuration
        self._load_environment()
        
        # Load from AWS Parameter Store in Lambda environments
        if 'AWS_LAMBDA_FUNCTION_NAME' in os.environ:
            try:
                # Try Secrets Manager first
                self._load_from_secrets_manager()
            except Exception as e:
                logger.warning(f"Failed to load from Secrets Manager, falling back to SSM: {str(e)}")
                # Fall back to SSM
                self._load_from_ssm()
        
        self._initialized = True
    
    def _load_environment(self):
        """Load configuration from environment variables and .env files."""
        # First, try to find and load .env file
        env_path = Path(os.getcwd()) / '.env'
        if env_path.exists():
            logger.info(f"Loading configuration from {env_path}")
            load_dotenv(dotenv_path=env_path)
        
        # Load core environment variables
        self._config['environment'] = os.environ.get('DEPLOY_ENV', 'dev')
        self._config['pipeline_version'] = os.environ.get('PIPELINE_VERSION', '1.2.0')
        self._config['log_level'] = os.environ.get('LOG_LEVEL', 'INFO')
        
        # Load Salesforce configuration
        self._config['salesforce'] = {
            'username': os.environ.get('SALESFORCE_USERNAME'),
            'password': os.environ.get('SALESFORCE_PASSWORD'),
            'security_token': os.environ.get('SALESFORCE_TOKEN')
        }
        
        # Load Observe configuration
        self._config['observe'] = {
            'url': os.environ.get('OBSERVE_URL'),
            'token': os.environ.get('OBSERVE_TOKEN'),
            'customer_id': os.environ.get('OBSERVE_CUSTOMER_ID')
        }
        
        # Parse AWS account mapping from environment if available
        aws_account_mapping = os.environ.get('AWS_ACCOUNT_MAPPING')
        if aws_account_mapping:
            try:
                self._config['aws_account_mapping'] = json.loads(aws_account_mapping)
            except json.JSONDecodeError:
                logger.error("Failed to parse AWS_ACCOUNT_MAPPING environment variable as JSON")

    def _load_from_secrets_manager(self):
        """Load sensitive configuration from AWS Secrets Manager."""
        try:
            # Initialize Secrets Manager client
            secrets_client = boto3.client('secretsmanager')
            
            # Load Salesforce credentials
            try:
                sf_secret = secrets_client.get_secret_value(SecretId='redis/salesforce')
                sf_creds = json.loads(sf_secret['SecretString'])
                self._config['salesforce'] = {
                    'username': sf_creds.get('username'),
                    'password': sf_creds.get('password'),
                    'security_token': sf_creds.get('security_token')
                }
            except secrets_client.exceptions.ResourceNotFoundException:
                logger.warning("Salesforce credentials not found in Secrets Manager")
            except Exception as e:
                logger.error(f"Error loading Salesforce credentials from Secrets Manager: {str(e)}")
            
            # Load Observe credentials
            try:
                observe_secret = secrets_client.get_secret_value(SecretId='redis/observe')
                observe_creds = json.loads(observe_secret['SecretString'])
                self._config['observe'] = {
                    'url': observe_creds.get('url'),
                    'token': observe_creds.get('token'),
                    'customer_id': observe_creds.get('customer_id')
                }
            except secrets_client.exceptions.ResourceNotFoundException:
                logger.warning("Observe credentials not found in Secrets Manager")
            except Exception as e:
                logger.error(f"Error loading Observe credentials from Secrets Manager: {str(e)}")
                
        except Exception as e:
            logger.error(f"Error loading configuration from Secrets Manager: {str(e)}")
            raise
    
    def _load_from_ssm(self):
        """Load configuration from AWS SSM Parameter Store."""
        try:
            ssm = boto3.client('ssm')
            
            # Load Salesforce credentials from SSM
            for param_name, config_key in [
                ('/redis/sfdc/username', 'username'),
                ('/redis/sfdc/password', 'password'),
                ('/redis/sfdc/token', 'security_token')
            ]:
                try:
                    param = ssm.get_parameter(Name=param_name, WithDecryption=True)
                    self._config['salesforce'][config_key] = param['Parameter']['Value']
                except ssm.exceptions.ParameterNotFound:
                    logger.warning(f"SSM Parameter {param_name} not found")
                except Exception as e:
                    logger.error(f"Error loading SSM parameter {param_name}: {str(e)}")
            
            # Load Observe credentials from SSM
            for param_name, config_key in [
                ('/redis/observe/url', 'url'),
                ('/redis/observe/token', 'token'),
                ('/redis/observe/customer_id', 'customer_id')
            ]:
                try:
                    param = ssm.get_parameter(Name=param_name, WithDecryption=True)
                    self._config['observe'][config_key] = param['Parameter']['Value']
                except ssm.exceptions.ParameterNotFound:
                    logger.warning(f"SSM Parameter {param_name} not found")
                except Exception as e:
                    logger.error(f"Error loading SSM parameter {param_name}: {str(e)}")
            
            # Load AWS account mapping from SSM
            try:
                param = ssm.get_parameter(Name='/redis/account_mapping')
                self._config['aws_account_mapping'] = json.loads(param['Parameter']['Value'])
            except ssm.exceptions.ParameterNotFound:
                logger.warning("SSM Parameter /redis/account_mapping not found")
            except json.JSONDecodeError:
                logger.error("Failed to parse /redis/account_mapping parameter as JSON")
            except Exception as e:
                logger.error(f"Error loading SSM parameter /redis/account_mapping: {str(e)}")
                
        except Exception as e:
            logger.error(f"Error loading configuration from SSM: {str(e)}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value by key.
        
        Args:
            key: The configuration key in dot notation (e.g., 'salesforce.username')
            default: Default value if key is not found
            
        Returns:
            The configuration value or default
        """
        keys = key.split('.')
        value = self._config
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
                
        return value
    
    def get_all(self) -> Dict[str, Any]:
        """Get all configuration values.
        
        Returns:
            Dictionary with all configuration values (sensitive values redacted)
        """
        # Create a copy of the config with sensitive values redacted
        redacted_config = json.loads(json.dumps(self._config))
        
        # Redact sensitive values
        sensitive_keys = [
            'password', 'token', 'security_token', 'secret'
        ]
        
        def redact_sensitive_values(obj, keys_to_redact):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if any(sensitive in k.lower() for sensitive in keys_to_redact):
                        obj[k] = '********' if v else None
                    elif isinstance(v, (dict, list)):
                        redact_sensitive_values(v, keys_to_redact)
            elif isinstance(obj, list):
                for item in obj:
                    if isinstance(item, (dict, list)):
                        redact_sensitive_values(item, keys_to_redact)
                        
        redact_sensitive_values(redacted_config, sensitive_keys)
        return redacted_config
    
    def get_account_mapping(self) -> Dict[str, str]:
        """Get AWS account mapping.
        
        Returns:
            Dictionary mapping AWS account IDs to business units
        """
        mapping = self.get('aws_account_mapping')
        
        if not mapping:
            # Fall back to default mapping
            return {
                '123456789012': 'production',
                '234567890123': 'staging',
                '345678901234': 'development'
            }
            
        return mapping

# Create a singleton instance
config = Config()