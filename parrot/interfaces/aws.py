"""
AWS Interface for AI-Parrot
Provides async context manager for AWS service clients using aioboto3
"""
from typing import Optional, Dict, Any, AsyncIterator
from contextlib import asynccontextmanager
import aioboto3
from botocore.exceptions import ClientError, NoCredentialsError
from ..conf import (
    AWS_ACCESS_KEY,
    AWS_SECRET_KEY,
    AWS_REGION_NAME,
    AWS_CREDENTIALS
)


class AWSInterface:
    """
    Base interface for AWS services using aioboto3.
    
    Provides async context manager for creating service clients.
    Handles credential management and session lifecycle.
    
    Example:
        >>> aws = AWSInterface(aws_id='default')
        >>> async with aws.client('s3') as s3:
        ...     response = await s3.list_buckets()
    """
    
    def __init__(
        self,
        aws_id: str = 'default',
        region_name: Optional[str] = None,
        credentials: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        """
        Initialize AWS interface.
        
        Args:
            aws_id: Identifier for credentials in AWS_CREDENTIALS dict
            region_name: AWS region (overrides credentials config)
            credentials: Direct credential dict (overrides aws_id lookup)
            **kwargs: Additional boto3 session parameters
        """
        # Get credentials from config or direct input
        if credentials is None:
            credentials = AWS_CREDENTIALS.get(aws_id, {})
            if not credentials or credentials == 'default':
                credentials = AWS_CREDENTIALS.get('default', {
                    'aws_key': AWS_ACCESS_KEY,
                    'aws_secret': AWS_SECRET_KEY,
                    'region_name': AWS_REGION_NAME
                })
        
        # Build AWS config
        self.aws_config = {
            'aws_access_key_id': credentials.get('aws_key') or credentials.get('aws_access_key_id'),
            'aws_secret_access_key': credentials.get('aws_secret') or credentials.get('aws_secret_access_key'),
            'region_name': region_name or credentials.get('region_name', AWS_REGION_NAME),
        }
        
        # Add optional session token if present
        if 'aws_session_token' in credentials:
            self.aws_config['aws_session_token'] = credentials['aws_session_token']
        
        # Add any additional kwargs
        self.aws_config.update(kwargs)
        
        # Remove None values
        self.aws_config = {k: v for k, v in self.aws_config.items() if v is not None}
        
        # Create session
        self.session = aioboto3.Session(**self.aws_config)
        self._region = self.aws_config.get('region_name')
    
    @property
    def region(self) -> str:
        """Get configured AWS region"""
        return self._region
    
    @asynccontextmanager
    async def client(self, service_name: str, **kwargs) -> AsyncIterator[Any]:
        """
        Async context manager for AWS service client.
        
        Args:
            service_name: AWS service name (e.g., 's3', 'cloudwatch', 'logs')
            **kwargs: Additional client configuration
            
        Yields:
            AWS service client
            
        Example:
            >>> async with aws.client('cloudwatch') as cw:
            ...     metrics = await cw.list_metrics()
        """
        async with self.session.client(service_name, **kwargs) as client:
            yield client
    
    @asynccontextmanager
    async def resource(self, service_name: str, **kwargs) -> AsyncIterator[Any]:
        """
        Async context manager for AWS service resource.
        
        Args:
            service_name: AWS service name (e.g., 's3', 'dynamodb')
            **kwargs: Additional resource configuration
            
        Yields:
            AWS service resource
        """
        async with self.session.resource(service_name, **kwargs) as resource:
            yield resource
    
    async def validate_credentials(self) -> bool:
        """
        Validate AWS credentials by making a simple API call.
        
        Returns:
            True if credentials are valid, False otherwise
        """
        try:
            async with self.client('sts') as sts:
                await sts.get_caller_identity()
            return True
        except (ClientError, NoCredentialsError):
            return False
    
    async def get_caller_identity(self) -> Dict[str, Any]:
        """
        Get AWS caller identity information.
        
        Returns:
            Dict with UserId, Account, and Arn
        """
        async with self.client('sts') as sts:
            response = await sts.get_caller_identity()
            return {
                'user_id': response.get('UserId'),
                'account': response.get('Account'),
                'arn': response.get('Arn')
            }