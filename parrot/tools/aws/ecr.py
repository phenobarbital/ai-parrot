"""AWS ECR Toolkit for AI-Parrot.

Provides inspection of ECR repositories, images, policies, and scan findings.
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


class ListRepositoriesInput(BaseModel):
    """Input for listing ECR repositories."""

    max_results: int = Field(
        100, description="Maximum number of repositories"
    )
    next_token: Optional[str] = Field(
        None, description="Pagination token"
    )


class GetRepositoryPolicyInput(BaseModel):
    """Input for getting an ECR repository IAM policy."""

    repository_name: str = Field(
        ..., description="Name of the ECR repository"
    )


class GetImageScanFindingsInput(BaseModel):
    """Input for getting vulnerability scan findings."""

    repository_name: str = Field(
        ..., description="Name of the ECR repository"
    )
    image_tag: str = Field(
        "latest", description="Image tag to check"
    )


class ListRepositoryImagesInput(BaseModel):
    """Input for listing images in an ECR repository."""

    repository_name: str = Field(
        ..., description="Name of the ECR repository"
    )
    max_results: int = Field(
        100, description="Maximum number of images"
    )


# ------------------------------------------------------------------
# Toolkit
# ------------------------------------------------------------------


class ECRToolkit(AbstractToolkit):
    """Toolkit for inspecting AWS ECR repositories and container images.

    Available Operations:
    - aws_ecr_list_repositories: List ECR repositories
    - aws_ecr_get_repository_policy: Get repository IAM policy
    - aws_ecr_get_image_scan_findings: Get vulnerability scan findings
    - aws_ecr_list_repository_images: List images in a repository
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
    # List Repositories
    # ------------------------------------------------------------------

    @tool_schema(ListRepositoriesInput)
    async def aws_ecr_list_repositories(
        self,
        max_results: int = 100,
        next_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List all ECR repositories in the AWS account."""
        try:
            params: Dict[str, Any] = {
                "maxResults": max_results
            }
            if next_token:
                params["nextToken"] = next_token

            async with self.aws.client("ecr") as ecr:
                response = await ecr.describe_repositories(
                    **params
                )
                repos = [
                    {
                        "repository_name": r.get(
                            "repositoryName"
                        ),
                        "repository_arn": r.get(
                            "repositoryArn"
                        ),
                        "repository_uri": r.get(
                            "repositoryUri"
                        ),
                        "created_at": (
                            r.get("createdAt").isoformat()
                            if r.get("createdAt")
                            else None
                        ),
                        "image_tag_mutability": r.get(
                            "imageTagMutability"
                        ),
                        "scan_on_push": r.get(
                            "imageScanningConfiguration", {}
                        ).get("scanOnPush", False),
                        "encryption_type": r.get(
                            "encryptionConfiguration", {}
                        ).get("encryptionType"),
                    }
                    for r in response.get("repositories", [])
                ]

                return {
                    "repositories": repos,
                    "count": len(repos),
                    "next_token": response.get("nextToken"),
                }
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS ECR error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # Get Repository Policy
    # ------------------------------------------------------------------

    @tool_schema(GetRepositoryPolicyInput)
    async def aws_ecr_get_repository_policy(
        self, repository_name: str
    ) -> Dict[str, Any]:
        """Get the IAM policy for an ECR repository."""
        try:
            async with self.aws.client("ecr") as ecr:
                response = await ecr.get_repository_policy(
                    repositoryName=repository_name
                )
                policy_text = response.get("policyText", "{}")
                return {
                    "repository_name": repository_name,
                    "registry_id": response.get("registryId"),
                    "policy": json.loads(policy_text),
                }
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            if error_code == "RepositoryPolicyNotFoundException":
                return {
                    "repository_name": repository_name,
                    "policy": None,
                    "message": "No policy set for this repository",
                }
            raise RuntimeError(
                f"AWS ECR error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # Get Image Scan Findings
    # ------------------------------------------------------------------

    @tool_schema(GetImageScanFindingsInput)
    async def aws_ecr_get_image_scan_findings(
        self,
        repository_name: str,
        image_tag: str = "latest",
    ) -> Dict[str, Any]:
        """Get vulnerability scan findings for a container image."""
        try:
            async with self.aws.client("ecr") as ecr:
                response = await ecr.describe_image_scan_findings(
                    repositoryName=repository_name,
                    imageId={"imageTag": image_tag},
                )
                scan = response.get(
                    "imageScanFindings", {}
                )
                severity_counts = scan.get(
                    "findingSeverityCounts", {}
                )
                findings = [
                    {
                        "name": f.get("name"),
                        "severity": f.get("severity"),
                        "description": f.get("description"),
                        "uri": f.get("uri"),
                    }
                    for f in scan.get("findings", [])
                ]

                return {
                    "repository_name": repository_name,
                    "image_tag": image_tag,
                    "scan_status": response.get(
                        "imageScanStatus", {}
                    ).get("status"),
                    "severity_counts": severity_counts,
                    "findings": findings,
                    "findings_count": len(findings),
                    "total_vulnerabilities": sum(
                        severity_counts.values()
                    ),
                }
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            if error_code == "ScanNotFoundException":
                return {
                    "repository_name": repository_name,
                    "image_tag": image_tag,
                    "scan_status": "NOT_FOUND",
                    "message": "No scan found for this image",
                }
            raise RuntimeError(
                f"AWS ECR error ({error_code}): {e}"
            ) from e

    # ------------------------------------------------------------------
    # List Repository Images
    # ------------------------------------------------------------------

    @tool_schema(ListRepositoryImagesInput)
    async def aws_ecr_list_repository_images(
        self,
        repository_name: str,
        max_results: int = 100,
    ) -> Dict[str, Any]:
        """List container images in an ECR repository."""
        try:
            async with self.aws.client("ecr") as ecr:
                response = await ecr.describe_images(
                    repositoryName=repository_name,
                    maxResults=max_results,
                )
                images = [
                    {
                        "image_digest": img.get("imageDigest"),
                        "image_tags": img.get(
                            "imageTags", []
                        ),
                        "pushed_at": (
                            img.get("imagePushedAt").isoformat()
                            if img.get("imagePushedAt")
                            else None
                        ),
                        "size_bytes": img.get(
                            "imageSizeInBytes"
                        ),
                        "scan_status": img.get(
                            "imageScanStatus", {}
                        ).get("status"),
                        "scan_findings_count": img.get(
                            "imageScanFindingsSummary", {}
                        ).get("findingSeverityCounts"),
                    }
                    for img in response.get(
                        "imageDetails", []
                    )
                ]

                return {
                    "repository_name": repository_name,
                    "images": images,
                    "count": len(images),
                }
        except ClientError as e:
            error_code = e.response["Error"].get("Code", "Unknown")
            raise RuntimeError(
                f"AWS ECR error ({error_code}): {e}"
            ) from e
