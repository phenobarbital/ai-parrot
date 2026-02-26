"""Unified security data models for the Security Toolkits Suite.

These models normalize findings from multiple security scanners (Prowler, Trivy, Checkov)
into a unified format for cross-tool aggregation and compliance reporting.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class SeverityLevel(str, Enum):
    """Normalized severity levels across all scanners."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"
    PASS = "PASS"
    UNKNOWN = "UNKNOWN"


class FindingSource(str, Enum):
    """Security scanner sources."""

    PROWLER = "prowler"
    TRIVY = "trivy"
    CHECKOV = "checkov"
    CLOUDSPLOIT = "cloudsploit"
    MANUAL = "manual"


class ComplianceFramework(str, Enum):
    """Supported compliance frameworks for mapping findings."""

    SOC2 = "soc2"
    HIPAA = "hipaa"
    PCI_DSS = "pci_dss"
    GDPR = "gdpr"
    NIST_800_53 = "nist_800_53"
    CIS = "cis"
    ISO_27001 = "iso_27001"
    AWS_WELL_ARCHITECTED = "aws_well_architected"
    CUSTOM = "custom"


class CloudProvider(str, Enum):
    """Cloud providers supported by scanners."""

    AWS = "aws"
    GCP = "gcp"
    AZURE = "azure"
    KUBERNETES = "kubernetes"
    LOCAL = "local"
    MULTI = "multi"


class SecurityFinding(BaseModel):
    """Unified security finding from any scanner.

    This model normalizes findings from Prowler, Trivy, and Checkov into a
    consistent format for aggregation and reporting.
    """

    id: str = Field(..., description="Unique finding identifier")
    source: FindingSource = Field(..., description="Scanner that produced this finding")
    severity: SeverityLevel = Field(..., description="Normalized severity level")
    title: str = Field(..., description="Short finding title")
    description: Optional[str] = Field(
        default=None, description="Detailed description of the finding"
    )
    resource: Optional[str] = Field(
        default=None, description="Affected resource ARN or identifier"
    )
    resource_type: Optional[str] = Field(
        default=None, description="Type of resource (e.g., 'S3 Bucket', 'EC2 Instance')"
    )
    region: str = Field(default="global", description="Cloud region or 'global'")
    provider: Optional[CloudProvider] = Field(
        default=None, description="Cloud provider"
    )
    service: Optional[str] = Field(
        default=None, description="Service name (e.g., 's3', 'iam', 'ec2')"
    )
    check_id: Optional[str] = Field(
        default=None, description="Scanner-specific check ID"
    )
    compliance_tags: list[str] = Field(
        default_factory=list,
        description="Compliance framework tags (e.g., 'SOC2-CC6.1', 'HIPAA-164.312')",
    )
    remediation: Optional[str] = Field(
        default=None, description="Recommended remediation steps"
    )
    raw: Optional[dict] = Field(
        default=None, description="Original scanner output for reference"
    )
    timestamp: Optional[datetime] = Field(
        default=None, description="When the finding was detected"
    )

    model_config = {"extra": "ignore"}


class ScanSummary(BaseModel):
    """Summary statistics for a single scanner run."""

    source: FindingSource = Field(..., description="Scanner that produced the results")
    provider: CloudProvider = Field(..., description="Cloud provider scanned")
    total_findings: int = Field(default=0, description="Total number of findings")
    critical_count: int = Field(default=0, description="Count of CRITICAL findings")
    high_count: int = Field(default=0, description="Count of HIGH findings")
    medium_count: int = Field(default=0, description="Count of MEDIUM findings")
    low_count: int = Field(default=0, description="Count of LOW findings")
    info_count: int = Field(default=0, description="Count of INFO findings")
    pass_count: int = Field(default=0, description="Count of PASS findings")
    scan_timestamp: datetime = Field(..., description="When the scan was executed")
    scan_duration_seconds: Optional[float] = Field(
        default=None, description="How long the scan took"
    )
    regions_scanned: list[str] = Field(
        default_factory=list, description="List of regions that were scanned"
    )
    services_scanned: list[str] = Field(
        default_factory=list, description="List of services that were scanned"
    )
    errors: list[str] = Field(
        default_factory=list, description="Any errors encountered during scan"
    )

    model_config = {"extra": "ignore"}


class ScanResult(BaseModel):
    """Complete results from a single scanner execution."""

    findings: list[SecurityFinding] = Field(
        default_factory=list, description="List of security findings"
    )
    summary: ScanSummary = Field(..., description="Summary statistics for this scan")
    metadata: dict = Field(
        default_factory=dict,
        description="Additional scanner-specific metadata",
    )

    model_config = {"extra": "ignore"}


class ComparisonDelta(BaseModel):
    """Comparison between two scan results for trend analysis."""

    baseline_timestamp: datetime = Field(
        ..., description="Timestamp of the baseline scan"
    )
    current_timestamp: datetime = Field(
        ..., description="Timestamp of the current scan"
    )
    new_findings: list[SecurityFinding] = Field(
        default_factory=list, description="Findings present in current but not baseline"
    )
    resolved_findings: list[SecurityFinding] = Field(
        default_factory=list, description="Findings present in baseline but not current"
    )
    unchanged_findings: list[SecurityFinding] = Field(
        default_factory=list, description="Findings present in both scans"
    )
    severity_trend: dict[str, int] = Field(
        default_factory=dict,
        description="Change in count per severity (positive = more, negative = fewer)",
    )
    summary: str = Field(
        default="", description="Human-readable summary of the comparison"
    )

    model_config = {"extra": "ignore"}


class ConsolidatedReport(BaseModel):
    """Consolidated report aggregating results from multiple scanners."""

    scan_results: dict[str, ScanResult] = Field(
        default_factory=dict,
        description="Scan results keyed by scanner name (e.g., 'prowler', 'trivy')",
    )
    total_findings: int = Field(
        default=0, description="Total findings across all scanners"
    )
    findings_by_severity: dict[str, int] = Field(
        default_factory=dict,
        description="Count of findings per severity level",
    )
    findings_by_service: dict[str, int] = Field(
        default_factory=dict,
        description="Count of findings per service",
    )
    findings_by_provider: dict[str, int] = Field(
        default_factory=dict,
        description="Count of findings per cloud provider",
    )
    compliance_coverage: dict[str, dict] = Field(
        default_factory=dict,
        description="Compliance framework coverage statistics",
    )
    generated_at: datetime = Field(..., description="When this report was generated")
    report_id: Optional[str] = Field(
        default=None, description="Unique identifier for this report"
    )
    metadata: dict = Field(
        default_factory=dict,
        description="Additional report metadata",
    )

    model_config = {"extra": "ignore"}
