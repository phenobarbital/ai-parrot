"""Pydantic data models for CloudSploit security scanning toolkit."""
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, Union

from pydantic import BaseModel, Field

from parrot.conf import (
    AWS_ACCESS_KEY_ID,
    AWS_DEFAULT_REGION,
    AWS_SECRET_ACCESS_KEY,
)


class SeverityLevel(str, Enum):
    """CloudSploit finding severity levels."""
    OK = "OK"
    WARN = "WARN"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class ComplianceFramework(str, Enum):
    """Supported compliance frameworks for filtered scans."""
    HIPAA = "hipaa"
    CIS1 = "cis1"
    CIS2 = "cis2"
    PCI = "pci"


class CloudProvider(str, Enum):
    """Supported cloud providers for CloudSploit scans."""
    AWS = "aws"
    GCP = "google"
    AZURE = "azure"


class ScanFinding(BaseModel):
    """A single finding from a CloudSploit scan."""
    plugin: str = Field(..., description="Plugin identifier")
    category: str = Field(..., description="Service category (e.g., EC2, IAM, S3)")
    title: str = Field(..., description="Human-readable finding title")
    description: str = Field(default="", description="Detailed description")
    resource: Optional[str] = Field(default=None, description="AWS resource ARN/ID")
    region: str = Field(default="global", description="AWS region")
    status: SeverityLevel = Field(..., description="Finding severity")
    message: str = Field(default="", description="Detailed status message")


class ScanSummary(BaseModel):
    """Aggregated summary of a CloudSploit scan."""
    total_findings: int = Field(..., description="Total number of findings")
    ok_count: int = Field(..., description="Number of OK (passing) findings")
    warn_count: int = Field(..., description="Number of WARN findings")
    fail_count: int = Field(..., description="Number of FAIL findings")
    unknown_count: int = Field(..., description="Number of UNKNOWN findings")
    categories: dict[str, int] = Field(
        default_factory=dict, description="Finding count by service category"
    )
    scan_timestamp: datetime = Field(..., description="When the scan was performed")
    compliance_framework: Optional[str] = Field(
        default=None, description="Compliance framework used for filtering"
    )
    duration_seconds: Optional[float] = Field(
        default=None, description="Scan duration in seconds"
    )


class ScanResult(BaseModel):
    """Full scan result container."""
    findings: list[ScanFinding] = Field(..., description="List of scan findings")
    summary: ScanSummary = Field(..., description="Aggregated scan summary")
    raw_json: Optional[Union[dict, list]] = Field(
        default=None, description="Raw CloudSploit JSON output"
    )
    collection_data: Optional[dict] = Field(
        default=None, description="Raw collection data from cloud APIs"
    )


class CloudSploitConfig(BaseModel):
    """Configuration for CloudSploit execution.

    CloudSploit Docker Setup:
        git clone https://github.com/aquasecurity/cloudsploit.git
        cd cloudsploit
        docker build . -t cloudsploit:0.0.1
    """
    # Docker settings
    docker_image: str = Field(
        default="cloudsploit:0.0.1",
        description="Docker image to use for scanning (build from github.com/aquasecurity/cloudsploit)"
    )
    use_docker: bool = Field(
        default=True,
        description="Use Docker for execution. Set False for direct CLI mode."
    )
    cli_path: Optional[str] = Field(
        default=None,
        description="Path to CloudSploit CLI when not using Docker"
    )

    cloud_provider: CloudProvider = Field(
        default=CloudProvider.AWS,
        description="Cloud provider target for scans (aws, google, azure)"
    )

    # AWS credentials — explicit keys (defaults from parrot.conf)
    aws_access_key_id: Optional[str] = Field(
        default=AWS_ACCESS_KEY_ID,
        description="AWS access key ID (default from parrot.conf)"
    )
    aws_secret_access_key: Optional[str] = Field(
        default=AWS_SECRET_ACCESS_KEY,
        description="AWS secret access key (default from parrot.conf)"
    )
    aws_session_token: Optional[str] = Field(
        default=None,
        description="AWS session token for temporary credentials (optional)"
    )

    # AWS credentials — profile-based
    aws_profile: Optional[str] = Field(
        default=None,
        description="AWS profile name from ~/.aws/credentials"
    )

    aws_region: str = Field(
        default=AWS_DEFAULT_REGION or "us-east-1",
        description="Default AWS region (AWS_REGION)"
    )
    aws_default_region: str = Field(
        default=AWS_DEFAULT_REGION or "us-east-1",
        description="AWS default region (AWS_DEFAULT_REGION)"
    )
    aws_sdk_load_config: str = Field(
        default="1",
        description="Enable AWS SDK load config (AWS_SDK_LOAD_CONFIG=1 required)"
    )

    # GCP credentials
    gcp_project_id: Optional[str] = Field(
        default=None, description="Google Cloud project ID"
    )
    gcp_credentials_path: Optional[str] = Field(
        default=None,
        description="Path to GCP service account JSON file"
    )

    # Cross-provider config override — takes precedence over all env-var
    # credentials when set.  Accepts a string path; existence is validated
    # at scan time (not at model construction), so the file may be absent
    # until the Docker volume is mounted or the CLI is invoked.
    config_file: Optional[str] = Field(
        default=None,
        description=(
            "Path to a CloudSploit JS credentials file (string, passed as "
            "`--config=<path>` to the CLI). File existence is validated at "
            "scan time, not at config construction — the file may be mounted "
            "via Docker at scan invocation. Takes precedence over env-var "
            "credentials when set."
        ),
    )

    timeout_seconds: int = Field(
        default=600, description="Maximum scan duration in seconds"
    )
    govcloud: bool = Field(
        default=False, description="Enable AWS GovCloud mode"
    )

    # Persistence
    results_dir: Optional[str] = Field(
        default=None,
        description="Directory for storing scan results on filesystem"
    )

    # ECR collection plan — path validated at scan time, not at construction
    ecr_plan_file: Optional[str] = Field(
        default=None,
        description=(
            "Path to a YAML ECR collection plan file. Passed to "
            "`collect_ecr_findings(plan=...)` as the fallback when no "
            "per-call plan is given. File existence is validated at scan "
            "time, not at config construction — the file may be supplied "
            "by ops at invocation time."
        ),
    )


class ComparisonReport(BaseModel):
    """Result of comparing two CloudSploit scans."""
    new_findings: list[ScanFinding] = Field(
        default_factory=list,
        description="Findings in current scan but not in baseline"
    )
    resolved_findings: list[ScanFinding] = Field(
        default_factory=list,
        description="Findings in baseline but not in current scan"
    )
    unchanged_findings: list[ScanFinding] = Field(
        default_factory=list,
        description="Findings present in both scans"
    )
    severity_changed: list[dict] = Field(
        default_factory=list,
        description="Findings where severity changed between scans"
    )
    baseline_timestamp: Optional[datetime] = Field(
        default=None, description="Timestamp of baseline scan"
    )
    current_timestamp: Optional[datetime] = Field(
        default=None, description="Timestamp of current scan"
    )


# ---------------------------------------------------------------------------
# ECR Image-Scan domain models (FEAT-165)
# These are independent of the CSPM SeverityLevel/ScanFinding types above.
# ---------------------------------------------------------------------------


class EcrSeverity(str, Enum):
    """ECR / vulnerability scan severities (distinct from SeverityLevel).

    Maps to the severity strings returned by ECR Basic Scanning via
    ``describe_image_scan_findings``.  NOT compatible with
    ``SeverityLevel(OK/WARN/FAIL/UNKNOWN)`` — that enum is for CSPM.
    """

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFORMATIONAL = "INFORMATIONAL"
    UNTRIAGED = "UNTRIAGED"


class EcrRepoPlan(BaseModel):
    """One ECR repository plus its tag priority order."""

    name: str = Field(..., description="ECR repository name")
    tags: list[str] = Field(
        ...,
        min_length=1,
        description="Tags to try in priority order; first match wins",
    )


class EcrCollectionPlan(BaseModel):
    """Plan for ``collect_ecr_findings``.  Loaded from a YAML file at runtime."""

    region: str = Field(..., description="AWS region to query")
    aws_id: str = Field(
        default="default",
        description="Credential identifier resolved by AWSInterface",
    )
    concurrency: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Max concurrent describe-image-scan-findings calls",
    )
    repos: list[EcrRepoPlan] = Field(
        ..., min_length=1, description="Repositories to scan in plan order"
    )

    @classmethod
    def from_yaml(cls, path: Union[str, "Path"]) -> "EcrCollectionPlan":
        """Load and validate a plan from a YAML file.

        Args:
            path: Path to the YAML file on disk.

        Returns:
            Validated ``EcrCollectionPlan`` instance.

        Raises:
            FileNotFoundError: If ``path`` does not point to an existing file.
            pydantic.ValidationError: If the parsed YAML does not match the
                expected schema.
        """
        import yaml  # deferred to avoid hard-failing if yaml is absent

        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(f"ECR collection plan not found: {p}")
        data = yaml.safe_load(p.read_text())
        return cls.model_validate(data)


class EcrScanFinding(BaseModel):
    """One vulnerability finding from ECR Basic Scanning."""

    name: str = Field(..., description="CVE identifier or finding name")
    severity: EcrSeverity = Field(..., description="ECR vulnerability severity")
    description: str = Field(default="", description="Finding description text")
    uri: str = Field(default="", description="URL to the CVE or advisory")
    package_name: Optional[str] = Field(
        default=None, description="Affected package name (from ECR attributes)"
    )
    package_version: Optional[str] = Field(
        default=None, description="Affected package version (from ECR attributes)"
    )
    fixed_in_versions: Optional[str] = Field(
        default=None, description="Version(s) with the fix (from ECR attributes)"
    )
    cvss: Optional[str] = Field(
        default=None,
        description=(
            "CVSS score string. Prefers CVSS4_SCORE when available, "
            "falls back to CVSS3_SCORE."
        ),
    )


class EcrRepoFindings(BaseModel):
    """Aggregated findings for a single (repo, tag) pair."""

    repo: str = Field(..., description="ECR repository name")
    tag: str = Field(..., description="Image tag that returned scan findings")
    scan_time: Optional[datetime] = Field(
        default=None, description="Timestamp of the ECR scan"
    )
    counts: dict[EcrSeverity, int] = Field(
        default_factory=dict,
        description="Finding count per ECR severity level",
    )
    findings: list[EcrScanFinding] = Field(
        default_factory=list, description="Individual vulnerability findings"
    )


class EcrCollectionResult(BaseModel):
    """Top-level container — mirrors the JSON output of collect_ecr_findings.js.

    Shape::

        {
            "generated_at": "<ISO-8601 UTC>",
            "region": "<AWS region>",
            "repos": [ <EcrRepoFindings>, ... ],
            "skipped": [ {"repo": ..., "reason": ...}, ... ],
        }
    """

    generated_at: datetime = Field(
        ..., description="UTC timestamp when the collection was produced"
    )
    region: str = Field(..., description="AWS region queried")
    repos: list[EcrRepoFindings] = Field(
        default_factory=list,
        description="Repos for which at least one tag returned scan findings",
    )
    skipped: list[dict] = Field(
        default_factory=list,
        description=(
            "Per-repo skip records when no tag returned a scan "
            "(e.g. ScanNotFoundException on every tag)"
        ),
    )
