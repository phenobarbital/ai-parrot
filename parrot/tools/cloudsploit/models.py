"""Pydantic data models for CloudSploit security scanning toolkit."""
from datetime import datetime
from enum import Enum
from typing import Optional, Union

from pydantic import BaseModel, Field


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
    """Configuration for CloudSploit execution."""
    # Docker settings
    docker_image: str = Field(
        default="cloudsploit:0.0.1",
        description="Docker image to use for scanning"
    )
    use_docker: bool = Field(
        default=True,
        description="Use Docker for execution. Set False for direct CLI mode."
    )
    cli_path: Optional[str] = Field(
        default=None,
        description="Path to CloudSploit CLI when not using Docker"
    )

    # AWS credentials — explicit keys
    aws_access_key_id: Optional[str] = Field(
        default=None, description="AWS access key ID"
    )
    aws_secret_access_key: Optional[str] = Field(
        default=None, description="AWS secret access key"
    )
    aws_session_token: Optional[str] = Field(
        default=None, description="AWS session token for temporary credentials"
    )

    # AWS credentials — profile-based
    aws_profile: Optional[str] = Field(
        default=None,
        description="AWS profile name from ~/.aws/credentials"
    )

    aws_region: str = Field(
        default="us-east-1", description="Default AWS region (AWS_REGION)"
    )
    aws_default_region: str = Field(
        default="us-east-2", description="AWS default region (AWS_DEFAULT_REGION)"
    )
    aws_sdk_load_config: str = Field(
        default="1", description="Enable AWS SDK load config (AWS_SDK_LOAD_CONFIG)"
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
