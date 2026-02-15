"""AWS S3 Toolkit for AI-Parrot.

Provides inspection and security analysis of S3 buckets.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from botocore.exceptions import ClientError
from pydantic import BaseModel, Field

from ...interfaces.aws import AWSInterface
from ..decorators import tool_schema
from ..toolkit import AbstractToolkit


# ------------------------------------------------------------------
# Input Schemas
# ------------------------------------------------------------------


class ListBucketsInput(BaseModel):
    """Input for listing S3 buckets."""


class GetBucketDetailsInput(BaseModel):
    """Input for getting detailed S3 bucket information."""

    bucket_name: str = Field(
        ..., description="Name of the S3 bucket"
    )


class AnalyzeBucketSecurityInput(BaseModel):
    """Input for analyzing S3 bucket security configuration."""

    bucket_name: str = Field(
        ..., description="Name of the S3 bucket to analyze"
    )


class FindPublicBucketsInput(BaseModel):
    """Input for finding publicly accessible S3 buckets."""


# ------------------------------------------------------------------
# Toolkit
# ------------------------------------------------------------------


class S3Toolkit(AbstractToolkit):
    """Toolkit for inspecting and analyzing AWS S3 buckets.

    Available Operations:
    - aws_s3_list_buckets: List all S3 buckets
    - aws_s3_get_bucket_details: Get detailed bucket information
    - aws_s3_analyze_bucket_security: Analyze bucket security config
    - aws_s3_find_public_buckets: Find publicly accessible buckets
    """

    def __init__(
        self,
        aws_id: str = "default",
        region_name: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.aws = AWSInterface(
            aws_id=aws_id,
            region_name=region_name,
            **kwargs,
        )

    # ------------------------------------------------------------------
    # List Buckets
    # ------------------------------------------------------------------

    @tool_schema(ListBucketsInput)
    async def aws_s3_list_buckets(self) -> Dict[str, Any]:
        """List all S3 buckets in the AWS account."""
        try:
            async with self.aws.client("s3") as s3:
                response = await s3.list_buckets()
                buckets = [
                    {
                        "name": b["Name"],
                        "creation_date": (
                            b["CreationDate"].isoformat()
                            if b.get("CreationDate")
                            else None
                        ),
                    }
                    for b in response.get("Buckets", [])
                ]
                return {"buckets": buckets, "count": len(buckets)}
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS S3 error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # Get Bucket Details
    # ------------------------------------------------------------------

    @tool_schema(GetBucketDetailsInput)
    async def aws_s3_get_bucket_details(
        self, bucket_name: str
    ) -> Dict[str, Any]:
        """Get detailed information about a specific S3 bucket."""
        try:
            details: Dict[str, Any] = {"bucket_name": bucket_name}

            async with self.aws.client("s3") as s3:
                # Location
                try:
                    loc = await s3.get_bucket_location(
                        Bucket=bucket_name
                    )
                    details["region"] = (
                        loc.get("LocationConstraint") or "us-east-1"
                    )
                except ClientError:
                    details["region"] = "unknown"

                # Versioning
                try:
                    ver = await s3.get_bucket_versioning(
                        Bucket=bucket_name
                    )
                    details["versioning"] = ver.get(
                        "Status", "Disabled"
                    )
                except ClientError:
                    details["versioning"] = "unknown"

                # Encryption
                try:
                    enc = await s3.get_bucket_encryption(
                        Bucket=bucket_name
                    )
                    rules = enc.get(
                        "ServerSideEncryptionConfiguration", {}
                    ).get("Rules", [])
                    details["encryption"] = [
                        {
                            "sse_algorithm": r.get(
                                "ApplyServerSideEncryptionByDefault",
                                {},
                            ).get("SSEAlgorithm"),
                            "kms_key_id": r.get(
                                "ApplyServerSideEncryptionByDefault",
                                {},
                            ).get("KMSMasterKeyID"),
                        }
                        for r in rules
                    ]
                except ClientError as enc_err:
                    code = enc_err.response["Error"].get("Code", "")
                    if code == "ServerSideEncryptionConfigurationNotFoundError":
                        details["encryption"] = "none"
                    else:
                        details["encryption"] = "unknown"

                # Public access block
                try:
                    pab = await s3.get_public_access_block(
                        Bucket=bucket_name
                    )
                    config = pab.get(
                        "PublicAccessBlockConfiguration", {}
                    )
                    details["public_access_block"] = {
                        "block_public_acls": config.get(
                            "BlockPublicAcls", False
                        ),
                        "ignore_public_acls": config.get(
                            "IgnorePublicAcls", False
                        ),
                        "block_public_policy": config.get(
                            "BlockPublicPolicy", False
                        ),
                        "restrict_public_buckets": config.get(
                            "RestrictPublicBuckets", False
                        ),
                    }
                except ClientError as pab_err:
                    code = pab_err.response["Error"].get("Code", "")
                    if code == "NoSuchPublicAccessBlockConfiguration":
                        details["public_access_block"] = "none"
                    else:
                        details["public_access_block"] = "unknown"

                # Bucket policy
                try:
                    pol = await s3.get_bucket_policy(
                        Bucket=bucket_name
                    )
                    details["policy"] = json.loads(
                        pol.get("Policy", "{}")
                    )
                except ClientError as pol_err:
                    code = pol_err.response["Error"].get("Code", "")
                    if code == "NoSuchBucketPolicy":
                        details["policy"] = None
                    else:
                        details["policy"] = "unknown"

                # Lifecycle
                try:
                    lc = await s3.get_bucket_lifecycle_configuration(
                        Bucket=bucket_name
                    )
                    details["lifecycle_rules"] = len(
                        lc.get("Rules", [])
                    )
                except ClientError:
                    details["lifecycle_rules"] = 0

                # Tagging
                try:
                    tags = await s3.get_bucket_tagging(
                        Bucket=bucket_name
                    )
                    details["tags"] = {
                        t["Key"]: t["Value"]
                        for t in tags.get("TagSet", [])
                    }
                except ClientError:
                    details["tags"] = {}

            return details
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS S3 error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # Analyze Bucket Security
    # ------------------------------------------------------------------

    @tool_schema(AnalyzeBucketSecurityInput)
    async def aws_s3_analyze_bucket_security(
        self, bucket_name: str
    ) -> Dict[str, Any]:
        """Analyze the security configuration of an S3 bucket."""
        try:
            details = await self.aws_s3_get_bucket_details(bucket_name)
            findings: List[Dict[str, str]] = []

            # Check encryption
            if details.get("encryption") in ("none", "unknown"):
                findings.append(
                    {
                        "severity": "HIGH",
                        "finding": "Bucket does not have server-side encryption enabled",
                    }
                )

            # Check public access block
            pab = details.get("public_access_block")
            if pab == "none":
                findings.append(
                    {
                        "severity": "HIGH",
                        "finding": "No public access block configuration",
                    }
                )
            elif isinstance(pab, dict):
                for key, label in [
                    ("block_public_acls", "BlockPublicAcls"),
                    ("ignore_public_acls", "IgnorePublicAcls"),
                    ("block_public_policy", "BlockPublicPolicy"),
                    ("restrict_public_buckets", "RestrictPublicBuckets"),
                ]:
                    if not pab.get(key, False):
                        findings.append(
                            {
                                "severity": "MEDIUM",
                                "finding": f"{label} is not enabled",
                            }
                        )

            # Check versioning
            if details.get("versioning") != "Enabled":
                findings.append(
                    {
                        "severity": "LOW",
                        "finding": "Bucket versioning is not enabled",
                    }
                )

            # Check policy for public access
            policy = details.get("policy")
            if isinstance(policy, dict):
                for stmt in policy.get("Statement", []):
                    principal = stmt.get("Principal", "")
                    if principal == "*" or principal == {"AWS": "*"}:
                        if stmt.get("Effect") == "Allow":
                            findings.append(
                                {
                                    "severity": "CRITICAL",
                                    "finding": (
                                        "Bucket policy allows public access "
                                        f"(Action: {stmt.get('Action')})"
                                    ),
                                }
                            )

            score = max(0, 100 - len(findings) * 15)
            return {
                "bucket_name": bucket_name,
                "security_score": score,
                "findings": findings,
                "findings_count": len(findings),
                "details": details,
            }
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS S3 error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # Find Public Buckets
    # ------------------------------------------------------------------

    @tool_schema(FindPublicBucketsInput)
    async def aws_s3_find_public_buckets(self) -> Dict[str, Any]:
        """Find all publicly accessible S3 buckets in the account."""
        try:
            buckets_result = await self.aws_s3_list_buckets()
            public_buckets: List[Dict[str, Any]] = []

            for bucket in buckets_result.get("buckets", []):
                name = bucket["name"]
                try:
                    analysis = await self.aws_s3_analyze_bucket_security(
                        name
                    )
                    critical = [
                        f
                        for f in analysis.get("findings", [])
                        if f.get("severity") == "CRITICAL"
                    ]
                    high = [
                        f
                        for f in analysis.get("findings", [])
                        if f.get("severity") == "HIGH"
                    ]
                    if critical or high:
                        public_buckets.append(
                            {
                                "bucket_name": name,
                                "critical_findings": len(critical),
                                "high_findings": len(high),
                                "security_score": analysis.get(
                                    "security_score"
                                ),
                            }
                        )
                except (ClientError, RuntimeError):
                    continue

            return {
                "public_buckets": public_buckets,
                "count": len(public_buckets),
                "total_buckets": buckets_result.get("count", 0),
            }
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS S3 error ({error_code}): {e}"
            ) from e
