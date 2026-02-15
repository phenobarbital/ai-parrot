"""AWS Toolkits for AI-Parrot.

This package provides toolkits for interacting with AWS services,
including Route53, ECS/EKS, CloudWatch, S3, IAM, EC2, ECR,
GuardDuty, and SecurityHub.
"""
from .route53 import Route53Toolkit
from .ecs import ECSToolkit
from .cloudwatch import CloudWatchToolkit
from .s3 import S3Toolkit
from .guardduty import GuardDutyToolkit
from .ec2 import EC2Toolkit
from .ecr import ECRToolkit
from .iam import IAMToolkit
from .securityhub import SecurityHubToolkit
from .rds import RDSToolkit
from .lambda_func import LambdaToolkit
from .eks import EKSToolkit

__all__ = [
    "Route53Toolkit",
    "ECSToolkit",
    "CloudWatchToolkit",
    "S3Toolkit",
    "GuardDutyToolkit",
    "EC2Toolkit",
    "ECRToolkit",
    "IAMToolkit",
    "SecurityHubToolkit",
    "RDSToolkit",
    "LambdaToolkit",
    "EKSToolkit",
]
