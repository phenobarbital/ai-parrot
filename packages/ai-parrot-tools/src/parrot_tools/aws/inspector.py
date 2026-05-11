"""AWS Inspector v2 Toolkit for AI-Parrot.

Provides stateless read-only access to Amazon Inspector v2 (inspector2) findings,
aggregations, coverage, and async export operations.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from parrot.interfaces.aws import AWSInterface
from ..decorators import tool_schema
from ..toolkit import AbstractToolkit


# ------------------------------------------------------------------
# Input Schemas
# ------------------------------------------------------------------


class ListFindingsInput(BaseModel):
    """Input for listing Inspector v2 findings."""

    limit: int = Field(20, description="Max findings (capped at 100 by Inspector)")
    severity: str = Field(
        "ALL",
        description="CRITICAL|HIGH|MEDIUM|LOW|INFORMATIONAL|UNTRIAGED|ALL",
    )
    resource_type: Optional[str] = Field(
        None,
        description=(
            "AWS_EC2_INSTANCE|AWS_ECR_CONTAINER_IMAGE|AWS_ECR_REPOSITORY"
            "|AWS_LAMBDA_FUNCTION|CODE_REPOSITORY"
        ),
    )
    status: str = Field("ACTIVE", description="ACTIVE|SUPPRESSED|CLOSED|ALL")
    fix_available: Optional[str] = Field(None, description="YES|NO|PARTIAL")
    repository_name: Optional[str] = Field(
        None, description="ECR repository name filter"
    )
    search_term: Optional[str] = Field(
        None, description="Substring match on title / vulnerabilityId"
    )
    next_token: Optional[str] = Field(
        None, description="Pagination cursor from prior call"
    )


class AggregateFindingsInput(BaseModel):
    """Input for aggregating Inspector v2 findings."""

    aggregation_type: str = Field(
        "REPOSITORY",
        description=(
            "ACCOUNT|AMI|AWS_EC2_INSTANCE|AWS_ECR_CONTAINER|FINDING_TYPE|"
            "IMAGE_LAYER|LAMBDA_FUNCTION|LAMBDA_LAYER|PACKAGE|REPOSITORY|TITLE"
        ),
    )
    limit: int = Field(25, description="Max aggregation rows")
    severity: Optional[str] = Field(
        None, description="Pre-filter findings before aggregating"
    )
    resource_type: Optional[str] = Field(None)


class GetEcrImageFindingsInput(BaseModel):
    """Input for getting Inspector findings for a specific ECR image."""

    repository_name: str = Field(..., description="ECR repository name")
    image_digest: Optional[str] = Field(
        None, description="sha256:... — preferred over tag"
    )
    image_tag: Optional[str] = Field(
        None, description="Image tag (if digest not supplied)"
    )
    severity: str = Field("ALL")
    limit: int = Field(50)


class ListCoverageInput(BaseModel):
    """Input for listing Inspector v2 coverage resources."""

    resource_type: Optional[str] = Field(None)
    scan_status: Optional[str] = Field(None, description="ACTIVE|INACTIVE")
    scan_status_reason: Optional[str] = Field(
        None,
        description="e.g. SCAN_ELIGIBILITY_EXPIRED, IMAGE_PULLED_WITH_INVALID_SCAN_TYPE",
    )
    repository_name: Optional[str] = Field(None)
    limit: int = Field(50)
    next_token: Optional[str] = Field(None)


class GetSecurityPostureInput(BaseModel):
    """Input for computing the account-level Inspector security posture."""

    weights: Optional[Dict[str, int]] = Field(
        None,
        description=(
            "Override default severity weights: "
            "{CRITICAL: 10, HIGH: 5, MEDIUM: 2, LOW: 1}"
        ),
    )


class ListTopVulnerableResourcesInput(BaseModel):
    """Input for listing the most vulnerable resources by weighted severity."""

    resource_type: Optional[str] = Field(None)
    limit: int = Field(10)
    weights: Optional[Dict[str, int]] = Field(None)


class CreateFindingsReportInput(BaseModel):
    """Input for creating an async Inspector findings report in S3."""

    s3_bucket: str = Field(...)
    s3_key_prefix: str = Field("inspector-reports/")
    kms_key_arn: str = Field(..., description="Required by Inspector for findings reports")
    report_format: str = Field("JSON", description="CSV|JSON")
    severity: Optional[str] = Field(None)
    resource_type: Optional[str] = Field(None)


class CreateSbomExportInput(BaseModel):
    """Input for creating an async SBOM export in S3."""

    s3_bucket: str = Field(...)
    s3_key_prefix: str = Field("inspector-sboms/")
    kms_key_arn: str = Field(...)
    report_format: str = Field("CYCLONEDX_1_4", description="CYCLONEDX_1_4|SPDX_2_3")
    resource_type: Optional[str] = Field(None)
    repository_name: Optional[str] = Field(None)


# ------------------------------------------------------------------
# Default severity weights
# ------------------------------------------------------------------

_DEFAULT_WEIGHTS: Dict[str, int] = {
    "CRITICAL": 10,
    "HIGH": 5,
    "MEDIUM": 2,
    "LOW": 1,
}


# ------------------------------------------------------------------
# Toolkit
# ------------------------------------------------------------------


class InspectorToolkit(AbstractToolkit):
    """Stateless toolkit wrapping Amazon Inspector v2 (inspector2).

    Available Operations (read-only, no mutation):

    Direct reads:
    - aws_inspector_list_findings: List findings with optional filters
    - aws_inspector_aggregate_findings: Aggregate findings by dimension
    - aws_inspector_get_ecr_image_findings: Convenience ECR image finder
    - aws_inspector_list_coverage: List scanned resources
    - aws_inspector_get_coverage_statistics: Coverage stats summary
    - aws_inspector_batch_get_account_status: Scan type enablement

    Composite reads:
    - aws_inspector_get_security_posture: Weighted security score + coverage
    - aws_inspector_list_top_vulnerable_resources: Top N by weighted severity

    Async exports:
    - aws_inspector_create_findings_report: Start S3 findings export
    - aws_inspector_get_findings_report_status: Poll export status
    - aws_inspector_create_sbom_export: Start S3 SBOM export
    - aws_inspector_get_sbom_export: Poll SBOM export status
    """

    def __init__(
        self,
        aws_id: str = "default",
        region_name: Optional[str] = None,
        **kwargs,
    ) -> None:
        """Initialize InspectorToolkit.

        Args:
            aws_id: AWS credential profile identifier.
            region_name: AWS region name override.
            **kwargs: Additional kwargs forwarded to AbstractToolkit and AWSInterface.
        """
        super().__init__(**kwargs)
        self.aws = AWSInterface(aws_id=aws_id, region_name=region_name, **kwargs)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_filter_criteria(self, **kwargs: Any) -> Dict[str, Any]:
        """Build an inspector2 filterCriteria dict from simple kwargs.

        Rules:
        - Drop kwargs that are None or "ALL".
        - severity, resource_type, fix_available → EQUALS comparison.
        - status → mapped to findingStatus key with EQUALS comparison.
        - repository_name ending in '*' → PREFIX comparison (strip the '*').
        - repository_name without '*' → EQUALS comparison.
        - search_term → title filter with CONTAINS comparison.

        Args:
            **kwargs: Simple filter kwargs.

        Returns:
            filterCriteria dict suitable for inspector2 API calls.
        """
        criteria: Dict[str, Any] = {}

        # severity
        severity = kwargs.get("severity")
        if severity and severity.upper() != "ALL":
            criteria["severity"] = [{"comparison": "EQUALS", "value": severity.upper()}]

        # resource_type
        resource_type = kwargs.get("resource_type")
        if resource_type and resource_type.upper() != "ALL":
            criteria["resourceType"] = [
                {"comparison": "EQUALS", "value": resource_type.upper()}
            ]

        # status → findingStatus
        status = kwargs.get("status")
        if status and status.upper() != "ALL":
            criteria["findingStatus"] = [
                {"comparison": "EQUALS", "value": status.upper()}
            ]

        # fix_available
        fix_available = kwargs.get("fix_available")
        if fix_available is not None:
            criteria["fixAvailable"] = [
                {"comparison": "EQUALS", "value": fix_available.upper()}
            ]

        # repository_name
        repository_name = kwargs.get("repository_name")
        if repository_name is not None:
            if repository_name.endswith("*"):
                criteria["ecrImageRepositoryName"] = [
                    {"comparison": "PREFIX", "value": repository_name[:-1]}
                ]
            else:
                criteria["ecrImageRepositoryName"] = [
                    {"comparison": "EQUALS", "value": repository_name}
                ]

        # search_term → title CONTAINS
        search_term = kwargs.get("search_term")
        if search_term is not None:
            criteria["title"] = [{"comparison": "CONTAINS", "value": search_term}]

        # ecr image filters (used by get_ecr_image_findings)
        image_digest = kwargs.get("image_digest")
        if image_digest is not None:
            criteria["ecrImageHash"] = [
                {"comparison": "EQUALS", "value": image_digest}
            ]

        image_tag = kwargs.get("image_tag")
        if image_tag is not None:
            criteria["ecrImageTags"] = [
                {"comparison": "EQUALS", "value": image_tag}
            ]

        return criteria

    def _normalize_finding(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize a single raw Inspector finding dict.

        Args:
            raw: Raw finding dict from inspector2:ListFindings response.

        Returns:
            Normalized finding dict per spec §2 output shape.
        """
        # Basic fields
        description = raw.get("description", "") or ""
        if len(description) > 500:
            description = description[:500] + "…"

        # Timestamps
        first_observed = raw.get("firstObservedAt")
        last_observed = raw.get("lastObservedAt")
        if isinstance(first_observed, datetime):
            first_observed = first_observed.isoformat()
        if isinstance(last_observed, datetime):
            last_observed = last_observed.isoformat()

        # EPSS score
        epss_score: Optional[float] = None
        epss = raw.get("epss") or {}
        if epss:
            epss_score = epss.get("score")

        # Package vulnerability details
        pkg_details = raw.get("packageVulnerabilityDetails") or {}
        vulnerability_id = pkg_details.get("vulnerabilityId", "")
        raw_packages: List[Dict[str, Any]] = pkg_details.get("vulnerablePackages") or []
        truncated = len(raw_packages) > 5
        packages = [
            {
                "name": p.get("name", ""),
                "version": p.get("version", ""),
                "fixed_in_version": p.get("fixedVersion"),
                "package_manager": p.get("packageManager", ""),
                "file_path": p.get("filePath"),
            }
            for p in raw_packages[:5]
        ]

        # Resources
        resources: List[Dict[str, Any]] = raw.get("resources") or []
        multi_resource = len(resources) > 1
        resource_raw = resources[0] if resources else {}
        details = resource_raw.get("details") or {}
        ecr_raw = details.get("awsEcrContainerImage")
        ecr_image: Optional[Dict[str, Any]] = None
        if ecr_raw:
            last_in_use = ecr_raw.get("lastInUseAt")
            if isinstance(last_in_use, datetime):
                last_in_use = last_in_use.isoformat()
            ecr_image = {
                "repository_name": ecr_raw.get("repositoryName", ""),
                "image_digest": ecr_raw.get("imageDigest", ""),
                "image_tags": ecr_raw.get("imageTags") or [],
                "registry_id": ecr_raw.get("registryId", ""),
                "platform": ecr_raw.get("platform", ""),
                "in_use_count": ecr_raw.get("inUseCount", 0),
                "last_in_use_at": last_in_use,
            }

        resource: Dict[str, Any] = {
            "id": resource_raw.get("id", ""),
            "type": resource_raw.get("type", ""),
            "region": resource_raw.get("region", ""),
            "ecr_image": ecr_image,
        }
        if multi_resource:
            resource["_multi_resource"] = True

        normalized: Dict[str, Any] = {
            "finding_arn": raw.get("findingArn", ""),
            "vulnerability_id": vulnerability_id,
            "severity": raw.get("severity", ""),
            "title": raw.get("title", ""),
            "description": description,
            "status": raw.get("status", ""),
            "fix_available": raw.get("fixAvailable", ""),
            "exploit_available": raw.get("exploitAvailable", ""),
            "inspector_score": raw.get("inspectorScore", 0.0),
            "epss_score": epss_score,
            "first_observed_at": first_observed,
            "last_observed_at": last_observed,
            "resource": resource,
            "vulnerable_packages": packages,
            "vulnerable_packages_truncated": truncated,
        }
        # Drop networkReachabilityDetails — already excluded by not including it
        return normalized

    # ------------------------------------------------------------------
    # Direct read operations (stubs — implemented in TASK-1080)
    # ------------------------------------------------------------------

    @tool_schema(ListFindingsInput)
    async def aws_inspector_list_findings(
        self,
        limit: int = 20,
        severity: str = "ALL",
        resource_type: Optional[str] = None,
        status: str = "ACTIVE",
        fix_available: Optional[str] = None,
        repository_name: Optional[str] = None,
        search_term: Optional[str] = None,
        next_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List Amazon Inspector v2 findings with optional filters.

        Returns one page of normalized findings plus a next_token for pagination.
        The agent is responsible for deciding whether to continue paginating.
        """
        raise NotImplementedError("Implemented in TASK-1080")

    @tool_schema(AggregateFindingsInput)
    async def aws_inspector_aggregate_findings(
        self,
        aggregation_type: str = "REPOSITORY",
        limit: int = 25,
        severity: Optional[str] = None,
        resource_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Aggregate Inspector v2 findings by a chosen dimension.

        Returns aggregation rows with severity_counts per group.
        """
        raise NotImplementedError("Implemented in TASK-1080")

    @tool_schema(GetEcrImageFindingsInput)
    async def aws_inspector_get_ecr_image_findings(
        self,
        repository_name: str,
        image_digest: Optional[str] = None,
        image_tag: Optional[str] = None,
        severity: str = "ALL",
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Get Inspector v2 findings for a specific ECR container image.

        Adds a top-level severity summary over the returned findings.
        """
        raise NotImplementedError("Implemented in TASK-1080")

    @tool_schema(ListCoverageInput)
    async def aws_inspector_list_coverage(
        self,
        resource_type: Optional[str] = None,
        scan_status: Optional[str] = None,
        scan_status_reason: Optional[str] = None,
        repository_name: Optional[str] = None,
        limit: int = 50,
        next_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List resources covered by Amazon Inspector v2 scanning.

        Returns one page of coverage entries plus a next_token.
        """
        raise NotImplementedError("Implemented in TASK-1080")

    async def aws_inspector_get_coverage_statistics(self) -> Dict[str, Any]:
        """Get Amazon Inspector v2 coverage statistics summary.

        Returns counts of scanned resources grouped by resource type and scan status.
        """
        raise NotImplementedError("Implemented in TASK-1080")

    async def aws_inspector_batch_get_account_status(self) -> Dict[str, Any]:
        """Get Inspector v2 scan type enablement status for the current account.

        Returns the enablement status for EC2, ECR, Lambda, Lambda Code, and Code Repository.
        """
        raise NotImplementedError("Implemented in TASK-1080")

    # ------------------------------------------------------------------
    # Composite read operations (stubs — implemented in TASK-1081)
    # ------------------------------------------------------------------

    @tool_schema(GetSecurityPostureInput)
    async def aws_inspector_get_security_posture(
        self,
        weights: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        """Get the overall Inspector v2 security posture for the account.

        Orchestrates multiple API calls and computes a weighted security score (0-100).
        Score formula: 100 - (CRITICAL*10 + HIGH*5 + MEDIUM*2 + LOW*1), clamped to [0, 100].
        """
        raise NotImplementedError("Implemented in TASK-1081")

    @tool_schema(ListTopVulnerableResourcesInput)
    async def aws_inspector_list_top_vulnerable_resources(
        self,
        resource_type: Optional[str] = None,
        limit: int = 10,
        weights: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        """List the most vulnerable resources by weighted Inspector severity.

        Aggregates findings by resource ARN, sorts by weighted severity descending,
        and returns the top N resources.
        """
        raise NotImplementedError("Implemented in TASK-1081")

    # ------------------------------------------------------------------
    # Async export operations (stubs — implemented in TASK-1082)
    # ------------------------------------------------------------------

    @tool_schema(CreateFindingsReportInput)
    async def aws_inspector_create_findings_report(
        self,
        s3_bucket: str,
        s3_key_prefix: str = "inspector-reports/",
        kms_key_arn: str = "",
        report_format: str = "JSON",
        severity: Optional[str] = None,
        resource_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Start an async Amazon Inspector findings report export to S3.

        Returns a report_id that can be polled with aws_inspector_get_findings_report_status.
        """
        raise NotImplementedError("Implemented in TASK-1082")

    async def aws_inspector_get_findings_report_status(
        self, report_id: str
    ) -> Dict[str, Any]:
        """Poll the status of an Inspector findings report export.

        Returns {status: "NOT_FOUND"} if the report ID is unknown (expected during polling).
        """
        raise NotImplementedError("Implemented in TASK-1082")

    @tool_schema(CreateSbomExportInput)
    async def aws_inspector_create_sbom_export(
        self,
        s3_bucket: str,
        s3_key_prefix: str = "inspector-sboms/",
        kms_key_arn: str = "",
        report_format: str = "CYCLONEDX_1_4",
        resource_type: Optional[str] = None,
        repository_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Start an async Amazon Inspector SBOM export to S3.

        Returns a report_id that can be polled with aws_inspector_get_sbom_export.
        """
        raise NotImplementedError("Implemented in TASK-1082")

    async def aws_inspector_get_sbom_export(self, report_id: str) -> Dict[str, Any]:
        """Poll the status of an Inspector SBOM export.

        Returns {status: "NOT_FOUND"} if the report ID is unknown (expected during polling).
        """
        raise NotImplementedError("Implemented in TASK-1082")
