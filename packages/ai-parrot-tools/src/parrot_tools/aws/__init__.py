"""AWS Toolkits for AI-Parrot.

This package provides toolkits for interacting with AWS services,
including Route53, ECS/EKS, CloudWatch, S3, IAM, EC2, ECR,
GuardDuty, SecurityHub, RDS, DocumentDB, Lambda, EKS, and Inspector v2.

IAM policy sidecars for each toolkit are shipped alongside the code under
the ``policies/`` directory (e.g. ``policies/inspector_toolkit_policy.json``).
"""
from .cloudwatch import CloudWatchToolkit
from .documentdb import DocumentDBToolkit
from .ec2 import EC2Toolkit
from .ecr import ECRToolkit
from .ecs import ECSToolkit
from .eks import EKSToolkit
from .guardduty import GuardDutyToolkit
from .iam import IAMToolkit
from .inspector import InspectorToolkit
from .lambda_func import LambdaToolkit
from .rds import RDSToolkit
from .route53 import Route53Toolkit
from .s3 import S3Toolkit
from .securityhub import SecurityHubToolkit

__all__ = [
    "CloudWatchToolkit",
    "DocumentDBToolkit",
    "EC2Toolkit",
    "ECRToolkit",
    "ECSToolkit",
    "EKSToolkit",
    "GuardDutyToolkit",
    "IAMToolkit",
    "InspectorToolkit",
    "LambdaToolkit",
    "RDSToolkit",
    "Route53Toolkit",
    "S3Toolkit",
    "SecurityHubToolkit",
]
