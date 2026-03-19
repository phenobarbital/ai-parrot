# AI-Parrot Security Toolkits Suite — Spec & Brainstorming

> **Spec-Driven-Development document for Claude Code implementation**
> **Author:** Jesus (Lead Developer, AI-Parrot)
> **Date:** 2026-02-26
> **Status:** DRAFT — Brainstorming / Architecture Definition

---

## 1. Vision & Goals

### 1.1 Problem Statement

DevOps teams spend excessive time manually running cloud security scanners, cross-referencing results, and producing compliance reports (SOC2, HIPAA, PCI-DSS). Each tool has its own CLI, output format, and learning curve. There is no unified interface for an AI agent to orchestrate multiple security tools, correlate findings, and auto-generate compliance narratives.

### 1.2 Objective

Build a **Security Toolkits Suite** for AI-Parrot that exposes cloud security tools as agent-callable tools via `AbstractToolkit`. Each toolkit wraps a specific open-source scanner following the proven pattern established by `CloudSploitToolkit` (executor → parser → reports → models), enabling agents to:

- Run security scans across AWS, Azure, GCP, and Kubernetes
- Parse and normalize findings into a **unified data model**
- Compare scans over time (drift detection)
- Generate compliance reports (SOC2, HIPAA, PCI-DSS, CIS, ISO27001)
- Produce consolidated aggregate reports combining multiple tools

### 1.3 Design Principles

- **DRY/KISS**: Each scanner's integration code lives in its own module; toolkits compose these modules, never duplicate logic.
- **Unified Data Model**: All scanners normalize findings into a shared `SecurityFinding` model, enabling cross-tool aggregation.
- **Composition over inheritance**: Scanners are standalone executors; toolkits compose them.
- **Lazy loading**: Heavy imports (docker SDK, CLI wrappers) are deferred to execution time.
- **Provider-agnostic credentials**: Credential config follows the same env-var pattern as CloudSploit.

---

## 2. Architecture Overview

### 2.1 Module Structure

```
parrot/tools/security/
├── __init__.py                     # Re-exports all toolkits
├── models.py                       # ← SHARED unified data models
├── base_executor.py                # ← SHARED base executor (Docker/CLI)
├── base_parser.py                  # ← SHARED base parser interface
├── reports/                        # ← SHARED report generation
│   ├── __init__.py
│   ├── generator.py                # Multi-format report engine
│   ├── templates/                  # Jinja2/HTML templates
│   │   ├── soc2_report.html
│   │   ├── hipaa_report.html
│   │   ├── executive_summary.html
│   │   └── consolidated_report.html
│   └── compliance_mapper.py        # Maps findings → compliance controls
│
├── prowler/                        # Scanner: Prowler
│   ├── __init__.py
│   ├── executor.py                 # ProwlerExecutor(BaseExecutor)
│   ├── parser.py                   # ProwlerParser(BaseParser)
│   ├── models.py                   # Prowler-specific models (extends shared)
│   └── config.py                   # ProwlerConfig
│
├── trivy/                          # Scanner: Trivy
│   ├── __init__.py
│   ├── executor.py                 # TrivyExecutor(BaseExecutor)
│   ├── parser.py                   # TrivyParser(BaseParser)
│   ├── models.py                   # Trivy-specific models
│   └── config.py                   # TrivyConfig
│
├── checkov/                        # Scanner: Checkov
│   ├── __init__.py
│   ├── executor.py                 # CheckovExecutor(BaseExecutor)
│   ├── parser.py                   # CheckovParser(BaseParser)
│   ├── models.py                   # Checkov-specific models
│   └── config.py                   # CheckovConfig
│
├── cloud_posture_toolkit.py        # CloudPostureToolkit (Prowler wrapper)
├── container_security_toolkit.py   # ContainerSecurityToolkit (Trivy wrapper)
├── secrets_iac_toolkit.py          # SecretsIaCToolkit (Checkov wrapper)
└── compliance_report_toolkit.py    # ComplianceReportToolkit (aggregator)
```

### 2.2 Dependency Graph

```
ComplianceReportToolkit
    ├── calls → prowler.executor (under the hood)
    ├── calls → trivy.executor (under the hood)
    ├── calls → checkov.executor (under the hood)
    ├── uses  → reports.generator
    └── uses  → reports.compliance_mapper

CloudPostureToolkit
    └── composes → prowler.executor + prowler.parser

ContainerSecurityToolkit
    └── composes → trivy.executor + trivy.parser

SecretsIaCToolkit
    └── composes → checkov.executor + checkov.parser
```

Key insight: `ComplianceReportToolkit` does NOT depend on the other Toolkits — it directly uses the executors and parsers from each scanner module. This avoids circular dependencies and keeps each toolkit independent while the aggregator calls the underlying libraries directly.

---

## 3. Shared Components

### 3.1 Unified Data Models (`security/models.py`)

```python
"""Unified security data models shared across all scanner toolkits."""
from datetime import datetime
from enum import Enum
from typing import Optional, Union
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
    """Scanner that produced the finding."""
    PROWLER = "prowler"
    TRIVY = "trivy"
    CHECKOV = "checkov"
    CLOUDSPLOIT = "cloudsploit"


class ComplianceFramework(str, Enum):
    """Supported compliance frameworks."""
    SOC2 = "soc2"
    HIPAA = "hipaa"
    PCI_DSS = "pci_dss"
    CIS_AWS = "cis_aws"
    CIS_GCP = "cis_gcp"
    CIS_AZURE = "cis_azure"
    CIS_K8S = "cis_k8s"
    ISO27001 = "iso27001"
    NIST_800_53 = "nist_800_53"
    NIST_CSF = "nist_csf"
    GDPR = "gdpr"
    MITRE_ATTACK = "mitre_attack"


class CloudProvider(str, Enum):
    """Cloud providers supported by scanners."""
    AWS = "aws"
    GCP = "gcp"
    AZURE = "azure"
    KUBERNETES = "kubernetes"
    GITHUB = "github"
    LOCAL = "local"  # for IaC / container scans


class SecurityFinding(BaseModel):
    """Unified finding model — all scanners normalize to this."""
    id: str = Field(..., description="Unique finding ID (scanner-specific)")
    source: FindingSource = Field(..., description="Which scanner produced this")
    severity: SeverityLevel = Field(..., description="Normalized severity")
    title: str = Field(..., description="Short finding title")
    description: str = Field(default="", description="Detailed description")
    resource: Optional[str] = Field(default=None, description="Affected resource ARN/ID/path")
    resource_type: Optional[str] = Field(default=None, description="Resource type (e.g. S3 Bucket, EC2)")
    region: str = Field(default="global", description="Cloud region or 'global'")
    provider: CloudProvider = Field(default=CloudProvider.AWS)
    service: Optional[str] = Field(default=None, description="Cloud service (e.g. s3, iam, ec2)")
    check_id: Optional[str] = Field(default=None, description="Original check/plugin ID")
    compliance_tags: list[str] = Field(default_factory=list, description="Compliance controls mapped")
    remediation: Optional[str] = Field(default=None, description="Recommended remediation")
    raw: Optional[dict] = Field(default=None, description="Raw scanner output for this finding")


class ScanSummary(BaseModel):
    """Summary statistics for a scan run."""
    source: FindingSource
    provider: CloudProvider
    total_findings: int = 0
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    info_count: int = 0
    pass_count: int = 0
    scan_timestamp: datetime = Field(default_factory=datetime.now)
    duration_seconds: Optional[float] = None
    compliance_framework: Optional[str] = None
    services_scanned: list[str] = Field(default_factory=list)
    categories: dict[str, int] = Field(default_factory=dict)


class ScanResult(BaseModel):
    """Container for scan results — used by all scanners."""
    findings: list[SecurityFinding] = Field(default_factory=list)
    summary: ScanSummary
    raw_output: Optional[Union[dict, list, str]] = None


class ComparisonDelta(BaseModel):
    """Delta between two scans."""
    new_findings: list[SecurityFinding] = Field(default_factory=list)
    resolved_findings: list[SecurityFinding] = Field(default_factory=list)
    unchanged_findings: list[SecurityFinding] = Field(default_factory=list)
    severity_changes: list[dict] = Field(default_factory=list)
    baseline_summary: ScanSummary
    current_summary: ScanSummary


class ConsolidatedReport(BaseModel):
    """Aggregated report across multiple scanners."""
    scan_results: dict[str, ScanResult] = Field(
        default_factory=dict,
        description="Results keyed by scanner name"
    )
    total_findings: int = 0
    findings_by_severity: dict[str, int] = Field(default_factory=dict)
    findings_by_service: dict[str, int] = Field(default_factory=dict)
    findings_by_provider: dict[str, int] = Field(default_factory=dict)
    compliance_coverage: dict[str, dict] = Field(
        default_factory=dict,
        description="Per-framework: {controls_checked, controls_passed, coverage_pct}"
    )
    generated_at: datetime = Field(default_factory=datetime.now)
    report_paths: dict[str, str] = Field(
        default_factory=dict,
        description="Generated report file paths keyed by format"
    )
```

### 3.2 Base Executor (`security/base_executor.py`)

Reusable executor abstraction for running any CLI-based scanner via Docker or direct process. Follows the same pattern as `CloudSploitExecutor`.

```python
"""Base executor for CLI-based security scanners."""
from abc import ABC, abstractmethod
from typing import Optional
import asyncio
import os
from pydantic import BaseModel, Field
from navconfig.logging import logging


class BaseExecutorConfig(BaseModel):
    """Base configuration shared by all scanner executors."""
    use_docker: bool = Field(default=True, description="Run via Docker or direct CLI")
    docker_image: str = Field(default="", description="Docker image to use")
    cli_path: Optional[str] = Field(default=None, description="Path to CLI binary (non-Docker)")
    timeout: int = Field(default=600, description="Execution timeout in seconds")
    results_dir: Optional[str] = Field(default=None, description="Directory to save results")

    # Cloud credentials (common across providers)
    aws_access_key_id: Optional[str] = Field(default=None)
    aws_secret_access_key: Optional[str] = Field(default=None)
    aws_session_token: Optional[str] = Field(default=None)
    aws_profile: Optional[str] = Field(default=None)
    aws_region: str = Field(default="us-east-1")

    gcp_credentials_file: Optional[str] = Field(default=None)
    gcp_project_id: Optional[str] = Field(default=None)

    azure_client_id: Optional[str] = Field(default=None)
    azure_client_secret: Optional[str] = Field(default=None)
    azure_tenant_id: Optional[str] = Field(default=None)
    azure_subscription_id: Optional[str] = Field(default=None)


class BaseExecutor(ABC):
    """Abstract base executor — Docker or CLI process management."""

    def __init__(self, config: BaseExecutorConfig):
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)

    def _build_env_vars(self) -> dict[str, str]:
        """Build cloud credential env vars from config."""
        env: dict[str, str] = {}
        if self.config.aws_access_key_id:
            env["AWS_ACCESS_KEY_ID"] = self.config.aws_access_key_id
            env["AWS_SECRET_ACCESS_KEY"] = self.config.aws_secret_access_key or ""
            if self.config.aws_session_token:
                env["AWS_SESSION_TOKEN"] = self.config.aws_session_token
        if self.config.aws_profile:
            env["AWS_PROFILE"] = self.config.aws_profile
        env["AWS_DEFAULT_REGION"] = self.config.aws_region
        # GCP
        if self.config.gcp_credentials_file:
            env["GOOGLE_APPLICATION_CREDENTIALS"] = self.config.gcp_credentials_file
        if self.config.gcp_project_id:
            env["GCP_PROJECT_ID"] = self.config.gcp_project_id
        # Azure
        if self.config.azure_client_id:
            env["AZURE_CLIENT_ID"] = self.config.azure_client_id
            env["AZURE_CLIENT_SECRET"] = self.config.azure_client_secret or ""
            env["AZURE_TENANT_ID"] = self.config.azure_tenant_id or ""
        return env

    @abstractmethod
    def _build_cli_args(self, **kwargs) -> list[str]:
        """Build CLI arguments specific to the scanner."""
        ...

    def _build_docker_command(self, args: list[str]) -> list[str]:
        """Build `docker run` command with env vars."""
        cmd = ["docker", "run", "--rm"]
        for key, val in self._build_env_vars().items():
            cmd.extend(["-e", f"{key}={val}"])
        cmd.append(self.config.docker_image)
        cmd.extend(args)
        return cmd

    def _build_direct_command(self, args: list[str]) -> list[str]:
        """Build direct CLI command (non-Docker)."""
        cli = self.config.cli_path or self._default_cli_name()
        return [cli, *args]

    @abstractmethod
    def _default_cli_name(self) -> str:
        """Return the default CLI binary name (e.g. 'prowler', 'trivy')."""
        ...

    async def execute(self, args: list[str]) -> tuple[str, str, int]:
        """Run the scanner and return (stdout, stderr, exit_code)."""
        if self.config.use_docker:
            cmd = self._build_docker_command(args)
        else:
            cmd = self._build_direct_command(args)

        self.logger.info("Executing: %s", self._mask_command(cmd))

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=None if self.config.use_docker else {**os.environ, **self._build_env_vars()},
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.config.timeout
            )
            return stdout.decode(), stderr.decode(), proc.returncode or 0
        except asyncio.TimeoutError:
            self.logger.error("Scanner execution timed out after %ds", self.config.timeout)
            proc.kill()
            return "", "Timeout exceeded", -1

    def _mask_command(self, cmd: list[str]) -> str:
        """Mask credentials in command for safe logging."""
        import re
        masked = []
        for part in cmd:
            m = part
            m = re.sub(r'(SECRET_ACCESS_KEY|CLIENT_SECRET|SESSION_TOKEN)=[^\s]+',
                        r'\1=***', m)
            m = re.sub(r'(ACCESS_KEY_ID|CLIENT_ID)=([A-Za-z0-9]{3})[^\s]*',
                        r'\1=\2***', m)
            masked.append(m)
        return " ".join(masked)
```

### 3.3 Base Parser (`security/base_parser.py`)

```python
"""Base parser interface for normalizing scanner output."""
from abc import ABC, abstractmethod
from pathlib import Path
from .models import ScanResult, SecurityFinding
from datamodel.parsers.json import json_encoder, json_decoder


class BaseParser(ABC):
    """Abstract parser — each scanner implements its own normalization."""

    @abstractmethod
    def parse(self, raw_output: str) -> ScanResult:
        """Parse raw scanner stdout into a normalized ScanResult."""
        ...

    @abstractmethod
    def normalize_finding(self, raw_finding: dict) -> SecurityFinding:
        """Convert a single raw finding into the unified SecurityFinding model."""
        ...

    def save_result(self, result: ScanResult, path: str) -> str:
        """Persist scan result to JSON file."""
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            f.write(json_encoder(result.model_dump()))
        return path

    def load_result(self, path: str) -> ScanResult:
        """Load a previously saved scan result."""
        with open(path, "r") as f:
            data = json_decoder(f.read())
        return ScanResult(**data)
```

---

## 4. Toolkit #1: CloudPostureToolkit (Prowler)

### 4.1 Scanner Module: `security/prowler/`

#### 4.1.1 Config (`prowler/config.py`)

```python
from ..base_executor import BaseExecutorConfig
from pydantic import Field

class ProwlerConfig(BaseExecutorConfig):
    """Prowler-specific configuration."""
    docker_image: str = Field(default="toniblyx/prowler:latest")
    provider: str = Field(default="aws", description="Cloud provider: aws, azure, gcp, kubernetes")
    output_modes: list[str] = Field(default=["json-ocsf"], description="Output formats")
    # AWS-specific
    aws_profile: str | None = Field(default=None)
    filter_regions: list[str] = Field(default_factory=list, description="Specific regions to scan")
    # Azure-specific
    azure_auth_method: str | None = Field(default=None, description="sp-env-auth|az-cli-auth|browser-auth|managed-identity-auth")
    subscription_ids: list[str] = Field(default_factory=list)
    # GCP-specific
    gcp_project_ids: list[str] = Field(default_factory=list)
    # Scan filtering
    services: list[str] = Field(default_factory=list, description="Specific services to scan")
    checks: list[str] = Field(default_factory=list, description="Specific checks to run")
    excluded_checks: list[str] = Field(default_factory=list)
    excluded_services: list[str] = Field(default_factory=list)
    severity: list[str] = Field(default_factory=list, description="Filter by severity levels")
    compliance_framework: str | None = Field(default=None, description="E.g. cis_1.5_aws, soc2, hipaa")
```

#### 4.1.2 Executor (`prowler/executor.py`)

Key responsibilities: Build Prowler CLI args per provider, handle Docker/CLI execution, manage credential injection.

```python
class ProwlerExecutor(BaseExecutor):
    """Executes Prowler scans via Docker or CLI."""

    def __init__(self, config: ProwlerConfig):
        super().__init__(config)
        self.config: ProwlerConfig = config

    def _default_cli_name(self) -> str:
        return "prowler"

    def _build_cli_args(self, **kwargs) -> list[str]:
        """Build Prowler CLI arguments.

        Prowler CLI pattern:
            prowler <provider> [options]

        Key options:
            -M / --output-modes     : csv, json, json-ocsf, json-asff, html
            -c / --checks           : specific check IDs
            -s / --services         : specific services
            -e / --excluded-checks  : exclude checks
            --excluded-services     : exclude services
            -f / --filter-region    : specific regions (AWS)
            --compliance            : compliance framework filter
            --severity              : severity filter (critical, high, medium, low)
            -p / --profile          : AWS profile
            --sp-env-auth           : Azure service principal
            --az-cli-auth           : Azure CLI auth
            --project-ids           : GCP project IDs
        """
        config = self.config
        provider = kwargs.get("provider", config.provider)
        args = [provider]

        # Output format — always JSON for parsing
        output_modes = kwargs.get("output_modes", config.output_modes)
        if output_modes:
            args.extend(["-M", ",".join(output_modes)])

        # Region filtering (AWS)
        regions = kwargs.get("filter_regions", config.filter_regions)
        if regions:
            args.extend(["-f"] + regions)

        # AWS profile
        if config.aws_profile:
            args.extend(["-p", config.aws_profile])

        # Azure auth method
        if provider == "azure" and config.azure_auth_method:
            args.append(f"--{config.azure_auth_method}")
            if config.subscription_ids:
                args.extend(["--subscription-ids"] + config.subscription_ids)

        # GCP project IDs
        if provider == "gcp" and config.gcp_project_ids:
            args.extend(["--project-ids"] + config.gcp_project_ids)

        # Service/check filtering
        services = kwargs.get("services", config.services)
        if services:
            args.extend(["-s"] + services)

        checks = kwargs.get("checks", config.checks)
        if checks:
            args.extend(["-c"] + checks)

        if config.excluded_checks:
            args.extend(["-e"] + config.excluded_checks)
        if config.excluded_services:
            args.extend(["--excluded-services"] + config.excluded_services)

        # Severity filter
        severity = kwargs.get("severity", config.severity)
        if severity:
            args.extend(["--severity"] + severity)

        # Compliance framework
        compliance = kwargs.get("compliance", config.compliance_framework)
        if compliance:
            args.extend(["--compliance", compliance])

        return args

    async def run_scan(self, **kwargs) -> tuple[str, str, int]:
        """Run a Prowler scan with the configured options."""
        args = self._build_cli_args(**kwargs)
        return await self.execute(args)

    async def list_checks(self, provider: str = None) -> tuple[str, str, int]:
        """List available checks for a provider."""
        p = provider or self.config.provider
        return await self.execute([p, "--list-checks"])

    async def list_services(self, provider: str = None) -> tuple[str, str, int]:
        """List available services for a provider."""
        p = provider or self.config.provider
        return await self.execute([p, "--list-services"])
```

#### 4.1.3 Parser (`prowler/parser.py`)

Maps Prowler JSON-OCSF output to the unified `SecurityFinding` model.

```python
class ProwlerParser(BaseParser):
    """Parses Prowler JSON-OCSF output into unified SecurityFinding models."""

    # Prowler severity → unified severity mapping
    SEVERITY_MAP = {
        "critical": SeverityLevel.CRITICAL,
        "high": SeverityLevel.HIGH,
        "medium": SeverityLevel.MEDIUM,
        "low": SeverityLevel.LOW,
        "informational": SeverityLevel.INFO,
    }

    # Prowler status → unified severity for pass/fail
    STATUS_MAP = {
        "PASS": SeverityLevel.PASS,
        "FAIL": None,  # use severity
        "MANUAL": SeverityLevel.INFO,
    }

    def parse(self, raw_output: str) -> ScanResult:
        """Parse Prowler JSON-OCSF stdout."""
        # Implementation: parse JSON lines or JSON array,
        # normalize each finding, build summary
        ...

    def normalize_finding(self, raw: dict) -> SecurityFinding:
        """Map a single Prowler OCSF finding to SecurityFinding.

        Prowler JSON-OCSF structure (key fields):
            - finding_info.uid → check_id
            - finding_info.title → title
            - finding_info.desc → description
            - severity_id / severity → severity
            - status → PASS/FAIL
            - resources[0].uid → resource
            - resources[0].region → region
            - resources[0].type → resource_type
            - unmapped.check_type → compliance_tags
            - remediation.desc → remediation
        """
        ...
```

### 4.2 Toolkit: `cloud_posture_toolkit.py`

```python
class CloudPostureToolkit(AbstractToolkit):
    """Cloud Security Posture Management toolkit powered by Prowler.

    Runs multi-cloud security assessments, compliance scans, and posture
    tracking against AWS, Azure, GCP and Kubernetes.

    All public async methods automatically become agent tools.
    """

    def __init__(self, config: ProwlerConfig | None = None, **kwargs):
        super().__init__(**kwargs)
        self.config = config or ProwlerConfig()
        self.executor = ProwlerExecutor(self.config)
        self.parser = ProwlerParser()
        self._last_result: ScanResult | None = None
```

#### 4.2.1 Tools (async methods → agent tools)

| Tool Method | Description | Key Args |
|---|---|---|
| `prowler_run_scan` | Full security scan | `provider`, `services`, `checks`, `regions`, `severity` |
| `prowler_compliance_scan` | Compliance-filtered scan | `provider`, `framework` (soc2, hipaa, pci_dss, cis) |
| `prowler_scan_service` | Scan a specific cloud service | `provider`, `service` (e.g. s3, iam, ec2) |
| `prowler_list_checks` | List available checks | `provider`, `service` (optional filter) |
| `prowler_list_services` | List scannable services | `provider` |
| `prowler_get_summary` | Summary of last scan | — |
| `prowler_get_findings` | Get findings with filters | `severity`, `service`, `status` |
| `prowler_generate_report` | Generate HTML/PDF report | `format`, `output_path` |
| `prowler_compare_scans` | Compare two scan results | `baseline_path`, `current_path` |
| `prowler_get_remediation` | Get remediation for finding | `finding_id` or `check_id` |

#### 4.2.2 Method Signatures (detailed)

```python
async def prowler_run_scan(
    self,
    provider: str = "aws",
    services: list[str] | None = None,
    checks: list[str] | None = None,
    regions: list[str] | None = None,
    severity: list[str] | None = None,
    exclude_passing: bool = False,
) -> ScanResult:
    """Run a Prowler security scan against cloud infrastructure.

    Args:
        provider: Cloud provider to scan — aws, azure, gcp, kubernetes.
        services: Specific services to scan (e.g. ['s3', 'iam', 'ec2']).
                  If None, scans all services.
        checks: Specific check IDs to run. If None, runs all checks.
        regions: AWS regions to scan. If None, scans all regions.
        severity: Filter by severity — ['critical', 'high', 'medium', 'low'].
        exclude_passing: If True, exclude PASS findings from results.

    Returns:
        ScanResult with normalized findings and summary.
    """

async def prowler_compliance_scan(
    self,
    provider: str = "aws",
    framework: str = "soc2",
    exclude_passing: bool = True,
) -> ScanResult:
    """Run a compliance-focused scan filtered by framework.

    Args:
        provider: Cloud provider to scan.
        framework: Compliance framework — soc2, hipaa, pci_dss, cis_1.5_aws,
                   cis_2.0_gcp, iso27001, nist_800_53, gdpr, mitre_attack.
        exclude_passing: Exclude passing checks (default True for compliance).

    Returns:
        ScanResult filtered to the specified compliance framework.
    """

async def prowler_scan_service(
    self,
    provider: str = "aws",
    service: str = "s3",
    severity: list[str] | None = None,
) -> ScanResult:
    """Scan a specific cloud service for security issues.

    Args:
        provider: Cloud provider.
        service: Service to scan (e.g. s3, iam, ec2, rds, lambda, ecs).
        severity: Optional severity filter.

    Returns:
        ScanResult for the specified service.
    """

async def prowler_list_checks(
    self,
    provider: str = "aws",
    service: str | None = None,
) -> list[dict]:
    """List available Prowler checks.

    Args:
        provider: Cloud provider.
        service: Filter checks by service (optional).

    Returns:
        List of check definitions with id, title, service, severity.
    """

async def prowler_list_services(
    self,
    provider: str = "aws",
) -> list[str]:
    """List all scannable services for a cloud provider.

    Args:
        provider: Cloud provider.

    Returns:
        List of service names.
    """

async def prowler_get_summary(self) -> dict:
    """Get summary of the most recent scan.

    Returns:
        Dict with severity counts, service breakdown, compliance coverage.
    """

async def prowler_get_findings(
    self,
    severity: str | None = None,
    service: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[SecurityFinding]:
    """Get findings from last scan with optional filters.

    Args:
        severity: Filter by severity level.
        service: Filter by cloud service.
        status: Filter by status (PASS, FAIL).
        limit: Max findings to return (for LLM context management).

    Returns:
        Filtered list of SecurityFinding objects.
    """

async def prowler_generate_report(
    self,
    format: str = "html",
    output_path: str | None = None,
) -> str:
    """Generate a security report from the most recent scan.

    Args:
        format: Report format — 'html' or 'pdf'.
        output_path: File path to save report. Auto-generated if not set.

    Returns:
        File path of the generated report.
    """

async def prowler_compare_scans(
    self,
    baseline_path: str,
    current_path: str | None = None,
) -> ComparisonDelta:
    """Compare current scan with a baseline to detect posture drift.

    Args:
        baseline_path: Path to a previously saved scan JSON.
        current_path: Path to another scan JSON. Uses last scan if None.

    Returns:
        ComparisonDelta with new, resolved, and unchanged findings.
    """

async def prowler_get_remediation(
    self,
    check_id: str | None = None,
    finding_id: str | None = None,
) -> dict:
    """Get remediation guidance for a specific check or finding.

    Args:
        check_id: Prowler check ID (e.g. 's3_bucket_public_access').
        finding_id: Finding ID from scan results.

    Returns:
        Dict with remediation description and links.
    """
```

---

## 5. Toolkit #2: ContainerSecurityToolkit (Trivy)

### 5.1 Scanner Module: `security/trivy/`

#### 5.1.1 Config (`trivy/config.py`)

```python
class TrivyConfig(BaseExecutorConfig):
    """Trivy-specific configuration."""
    docker_image: str = Field(default="aquasec/trivy:latest")
    cache_dir: str | None = Field(default=None, description="Trivy cache directory")
    db_skip_update: bool = Field(default=False, description="Skip vulnerability DB update")
    # Scan targets
    severity_filter: list[str] = Field(
        default=["CRITICAL", "HIGH"],
        description="Severity levels to include"
    )
    ignore_unfixed: bool = Field(default=False, description="Ignore unfixed vulnerabilities")
    # Output
    output_format: str = Field(default="json", description="Output format: json, table, sarif")
```

#### 5.1.2 Executor (`trivy/executor.py`)

```python
class TrivyExecutor(BaseExecutor):
    """Executes Trivy scans via Docker or CLI.

    Trivy scan types:
        - image:   Container image vulnerabilities
        - fs:      Filesystem scanning (local project)
        - repo:    Git repository scanning
        - config:  IaC misconfiguration scanning
        - k8s:     Kubernetes cluster scanning
        - sbom:    SBOM generation
    """

    def _default_cli_name(self) -> str:
        return "trivy"

    def _build_cli_args(self, **kwargs) -> list[str]:
        """Build Trivy CLI arguments.

        Trivy CLI pattern:
            trivy <scan_type> [options] <target>

        Key options:
            --format         : json, table, sarif, cyclonedx, spdx
            --severity       : CRITICAL,HIGH,MEDIUM,LOW,UNKNOWN
            --ignore-unfixed : skip unfixed vulns
            --scanners       : vuln, misconfig, secret, license
            --output         : output file path
            --compliance     : compliance spec (e.g. docker-cis-1.6.0)
            --exit-code      : exit code on findings (for CI/CD)
        """
        ...
```

### 5.2 Toolkit: `container_security_toolkit.py`

#### 5.2.1 Tools (async methods)

| Tool Method | Description | Key Args |
|---|---|---|
| `trivy_scan_image` | Scan a container image for CVEs | `image`, `severity`, `ignore_unfixed` |
| `trivy_scan_filesystem` | Scan local directory/project | `path`, `scanners` |
| `trivy_scan_repo` | Scan a git repository | `repo_url`, `branch` |
| `trivy_scan_k8s` | Scan Kubernetes cluster | `context`, `namespace`, `compliance` |
| `trivy_scan_iac` | Scan IaC configurations | `path`, `config_type` |
| `trivy_generate_sbom` | Generate SBOM for image/project | `target`, `format` (cyclonedx/spdx) |
| `trivy_get_summary` | Summary of last scan | — |
| `trivy_get_findings` | Filtered findings list | `severity`, `scanner_type`, `limit` |
| `trivy_generate_report` | Generate HTML/PDF report | `format`, `output_path` |
| `trivy_compare_scans` | Compare two scan results | `baseline_path`, `current_path` |

#### 5.2.2 Key Method Signatures

```python
async def trivy_scan_image(
    self,
    image: str,
    severity: list[str] | None = None,
    ignore_unfixed: bool = False,
    scanners: list[str] | None = None,
) -> ScanResult:
    """Scan a container image for vulnerabilities, secrets, and misconfigurations.

    Args:
        image: Container image to scan (e.g. 'nginx:latest', 'myrepo/myapp:v1.2').
        severity: Filter by severity — ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'].
                  Default: CRITICAL, HIGH.
        ignore_unfixed: If True, skip vulnerabilities without available fixes.
        scanners: Types of scanning — ['vuln', 'misconfig', 'secret', 'license'].
                  Default: ['vuln', 'secret'].

    Returns:
        ScanResult with CVEs, secrets, and misconfigs found in the image.
    """

async def trivy_scan_k8s(
    self,
    context: str | None = None,
    namespace: str | None = None,
    compliance: str | None = None,
    scanners: list[str] | None = None,
) -> ScanResult:
    """Scan a Kubernetes cluster for security issues.

    Args:
        context: Kubernetes context to use. Uses current context if None.
        namespace: Specific namespace to scan. Scans all if None.
        compliance: K8s compliance spec (e.g. 'k8s-cis-1.23', 'k8s-nsa-1.0').
        scanners: Types — ['vuln', 'misconfig', 'secret', 'rbac'].

    Returns:
        ScanResult with cluster-wide security findings.
    """

async def trivy_scan_iac(
    self,
    path: str,
    config_type: str | None = None,
    severity: list[str] | None = None,
) -> ScanResult:
    """Scan Infrastructure as Code files for misconfigurations.

    Args:
        path: Path to IaC files (Terraform, CloudFormation, Helm, Dockerfile).
        config_type: Force specific scanner — 'terraform', 'cloudformation',
                     'kubernetes', 'dockerfile', 'helm'. Auto-detected if None.
        severity: Filter by severity.

    Returns:
        ScanResult with IaC misconfiguration findings.
    """

async def trivy_generate_sbom(
    self,
    target: str,
    format: str = "cyclonedx",
    output_path: str | None = None,
) -> str:
    """Generate a Software Bill of Materials for an image or project.

    Args:
        target: Container image or filesystem path.
        format: SBOM format — 'cyclonedx' or 'spdx-json'.
        output_path: Output file path. Auto-generated if None.

    Returns:
        Path to the generated SBOM file.
    """
```

---

## 6. Toolkit #3: SecretsIaCToolkit (Checkov)

### 6.1 Scanner Module: `security/checkov/`

#### 6.1.1 Config (`checkov/config.py`)

```python
class CheckovConfig(BaseExecutorConfig):
    """Checkov-specific configuration."""
    docker_image: str = Field(default="bridgecrew/checkov:latest")
    # Scan options
    frameworks: list[str] = Field(
        default_factory=list,
        description="IaC frameworks: terraform, cloudformation, kubernetes, helm, "
                    "dockerfile, arm, bicep, serverless, github_actions"
    )
    skip_checks: list[str] = Field(default_factory=list, description="Check IDs to skip")
    run_checks: list[str] = Field(default_factory=list, description="Only run these check IDs")
    # Output
    output_format: str = Field(default="json", description="Output: json, cli, sarif, junitxml")
    compact: bool = Field(default=True, description="Compact output (no passed checks)")
    # External checks
    external_checks_dir: str | None = Field(default=None, description="Custom policies directory")
    external_checks_git: str | None = Field(default=None, description="Git URL for custom policies")
```

#### 6.1.2 Executor (`checkov/executor.py`)

```python
class CheckovExecutor(BaseExecutor):
    """Executes Checkov scans via Docker or CLI.

    Checkov scan types:
        - directory:     Scan IaC directory
        - file:          Scan specific IaC file
        - repo:          Scan git repo (requires BC API key for some features)
        - dockerfile:    Scan Dockerfiles
        - secrets:       Secrets scanning in code
    """

    def _default_cli_name(self) -> str:
        return "checkov"

    def _build_cli_args(self, **kwargs) -> list[str]:
        """Build Checkov CLI arguments.

        Checkov CLI pattern:
            checkov -d <dir> | -f <file> | --repo-id <repo> [options]

        Key options:
            -d / --directory       : Directory to scan
            -f / --file            : Specific file to scan
            --framework            : terraform, cloudformation, kubernetes, etc.
            --check                : Specific check IDs to run (CKV_AWS_*)
            --skip-check           : Check IDs to skip
            -o / --output          : json, cli, sarif, junitxml
            --compact              : Only show failed checks
            --external-checks-dir  : Custom policy directory
            --soft-fail            : Always exit 0
        """
        ...
```

### 6.2 Toolkit: `secrets_iac_toolkit.py`

#### 6.2.1 Tools (async methods)

| Tool Method | Description | Key Args |
|---|---|---|
| `checkov_scan_directory` | Scan IaC directory | `path`, `framework`, `checks`, `skip_checks` |
| `checkov_scan_file` | Scan a specific IaC file | `file_path`, `framework` |
| `checkov_scan_terraform` | Specialized Terraform scan | `path`, `var_files` |
| `checkov_scan_cloudformation` | Specialized CFn scan | `path`, `template_file` |
| `checkov_scan_kubernetes` | Scan K8s manifests | `path`, `namespace_filter` |
| `checkov_scan_dockerfile` | Scan Dockerfiles | `path` |
| `checkov_scan_helm` | Scan Helm charts | `path`, `values_file` |
| `checkov_scan_secrets` | Secrets scanning in code | `path` |
| `checkov_scan_github_actions` | Scan GH Actions workflows | `path` |
| `checkov_list_checks` | List available checks | `framework` |
| `checkov_get_summary` | Summary of last scan | — |
| `checkov_get_findings` | Filtered findings | `severity`, `framework`, `limit` |
| `checkov_generate_report` | Generate HTML/PDF report | `format`, `output_path` |
| `checkov_compare_scans` | Compare two results | `baseline_path`, `current_path` |

#### 6.2.2 Key Method Signatures

```python
async def checkov_scan_directory(
    self,
    path: str,
    framework: str | None = None,
    checks: list[str] | None = None,
    skip_checks: list[str] | None = None,
    compact: bool = True,
) -> ScanResult:
    """Scan an IaC directory for misconfigurations and policy violations.

    Args:
        path: Path to the IaC directory.
        framework: Force specific framework — 'terraform', 'cloudformation',
                   'kubernetes', 'helm', 'dockerfile', 'arm', 'bicep',
                   'github_actions', 'serverless'. Auto-detected if None.
        checks: Specific check IDs to run (e.g. ['CKV_AWS_18', 'CKV_AWS_21']).
        skip_checks: Check IDs to skip.
        compact: If True, only return failed checks (default True).

    Returns:
        ScanResult with IaC findings.
    """

async def checkov_scan_terraform(
    self,
    path: str,
    var_files: list[str] | None = None,
    checks: list[str] | None = None,
    compact: bool = True,
) -> ScanResult:
    """Scan Terraform configurations for security issues.

    Args:
        path: Path to Terraform root module.
        var_files: Paths to .tfvars files for variable resolution.
        checks: Specific Terraform checks to run.
        compact: Only return failures.

    Returns:
        ScanResult with Terraform-specific findings.
    """

async def checkov_scan_secrets(
    self,
    path: str,
    entropy_threshold: float | None = None,
) -> ScanResult:
    """Scan code and configuration files for exposed secrets.

    Args:
        path: Directory or file to scan for secrets.
        entropy_threshold: Custom entropy threshold for secret detection.

    Returns:
        ScanResult with found secrets and their locations.
    """

async def checkov_list_checks(
    self,
    framework: str | None = None,
) -> list[dict]:
    """List available Checkov checks.

    Args:
        framework: Filter by IaC framework. All checks if None.

    Returns:
        List of check definitions with id, name, framework, guideline_url.
    """
```

---

## 7. Toolkit #4: ComplianceReportToolkit (Aggregator)

### 7.1 Design Philosophy

`ComplianceReportToolkit` is the **aggregation layer** that calls each scanner's executor/parser **directly** (not through the other toolkits). This keeps dependencies clean:

```python
# ComplianceReportToolkit does NOT do this:
# self.prowler_toolkit = CloudPostureToolkit(...)  ← circular/unnecessary

# It DOES this:
# self.prowler_executor = ProwlerExecutor(prowler_config)
# self.prowler_parser = ProwlerParser()
# self.trivy_executor = TrivyExecutor(trivy_config)
# ...etc
```

### 7.2 Toolkit: `compliance_report_toolkit.py`

```python
class ComplianceReportToolkit(AbstractToolkit):
    """Unified compliance reporting toolkit that orchestrates multiple scanners.

    Aggregates results from Prowler, Trivy, and Checkov to produce
    consolidated compliance reports for SOC2, HIPAA, PCI-DSS, etc.

    Uses the underlying executors directly — does NOT depend on the
    individual toolkit classes.
    """

    def __init__(
        self,
        prowler_config: ProwlerConfig | None = None,
        trivy_config: TrivyConfig | None = None,
        checkov_config: CheckovConfig | None = None,
        report_output_dir: str = "/tmp/security-reports",
        **kwargs,
    ):
        super().__init__(**kwargs)
        # Compose executors and parsers directly
        self.prowler_executor = ProwlerExecutor(prowler_config or ProwlerConfig())
        self.prowler_parser = ProwlerParser()
        self.trivy_executor = TrivyExecutor(trivy_config or TrivyConfig())
        self.trivy_parser = TrivyParser()
        self.checkov_executor = CheckovExecutor(checkov_config or CheckovConfig())
        self.checkov_parser = CheckovParser()
        # Report infrastructure
        self.report_generator = ReportGenerator(output_dir=report_output_dir)
        self.compliance_mapper = ComplianceMapper()
        # State
        self._last_consolidated: ConsolidatedReport | None = None
```

#### 7.2.1 Tools (async methods)

| Tool Method | Description | Key Args |
|---|---|---|
| `compliance_full_scan` | Run all 3 scanners and consolidate | `provider`, `target_image`, `iac_path`, `framework` |
| `compliance_soc2_report` | Generate SOC2 compliance report | `provider`, `output_format` |
| `compliance_hipaa_report` | Generate HIPAA compliance report | `provider`, `output_format` |
| `compliance_pci_report` | Generate PCI-DSS compliance report | `provider`, `output_format` |
| `compliance_custom_report` | Report for any framework | `framework`, `provider`, `output_format` |
| `compliance_executive_summary` | High-level executive summary | — (uses last consolidated) |
| `compliance_get_gaps` | Get compliance gaps per framework | `framework` |
| `compliance_get_remediation_plan` | Prioritized remediation plan | `max_items`, `severity_filter` |
| `compliance_compare_reports` | Compare two consolidated reports | `baseline_path`, `current_path` |
| `compliance_export_findings` | Export to CSV/JSON for audit | `format`, `output_path` |

#### 7.2.2 Key Method Signatures

```python
async def compliance_full_scan(
    self,
    provider: str = "aws",
    target_image: str | None = None,
    iac_path: str | None = None,
    k8s_context: str | None = None,
    framework: str | None = None,
    regions: list[str] | None = None,
) -> ConsolidatedReport:
    """Run a comprehensive security scan across all configured scanners.

    Orchestrates:
    1. Prowler scan against cloud infrastructure
    2. Trivy scan against container images (if target_image provided)
    3. Trivy scan against K8s cluster (if k8s_context provided)
    4. Checkov scan against IaC configs (if iac_path provided)
    5. Normalizes all findings into unified data model
    6. Maps findings to compliance controls
    7. Produces consolidated report

    Args:
        provider: Cloud provider for Prowler scan.
        target_image: Container image to scan with Trivy (optional).
        iac_path: Path to IaC directory for Checkov scan (optional).
        k8s_context: Kubernetes context for Trivy K8s scan (optional).
        framework: Compliance framework to focus on (optional).
        regions: Specific AWS regions to scan (optional).

    Returns:
        ConsolidatedReport with aggregated findings from all scanners.
    """

async def compliance_soc2_report(
    self,
    provider: str = "aws",
    output_format: str = "html",
    include_evidence: bool = True,
) -> str:
    """Generate a SOC2 Type II compliance report.

    Produces a report organized by SOC2 Trust Service Criteria:
    - CC1: Control Environment
    - CC2: Communication and Information
    - CC3: Risk Assessment
    - CC4: Monitoring Activities
    - CC5: Control Activities
    - CC6: Logical and Physical Access Controls
    - CC7: System Operations
    - CC8: Change Management
    - CC9: Risk Mitigation

    Args:
        provider: Cloud provider to assess.
        output_format: 'html' or 'pdf'.
        include_evidence: Include detailed evidence for each control.

    Returns:
        File path to the generated SOC2 report.
    """

async def compliance_hipaa_report(
    self,
    provider: str = "aws",
    output_format: str = "html",
    include_evidence: bool = True,
) -> str:
    """Generate a HIPAA compliance report.

    Produces a report organized by HIPAA Security Rule safeguards:
    - Administrative Safeguards (§164.308)
    - Physical Safeguards (§164.310)
    - Technical Safeguards (§164.312)
    - Organizational Requirements (§164.314)
    - Policies/Procedures/Documentation (§164.316)

    Args:
        provider: Cloud provider to assess.
        output_format: 'html' or 'pdf'.
        include_evidence: Include evidence for each safeguard.

    Returns:
        File path to the generated HIPAA report.
    """

async def compliance_executive_summary(self) -> dict:
    """Generate a high-level executive summary from the last consolidated scan.

    Returns:
        Dict with:
        - overall_risk_score: 0-100 weighted score
        - critical_findings_count: immediate action items
        - compliance_coverage: per-framework coverage percentages
        - top_risks: top 5 prioritized risks with remediation
        - trend: improved/degraded/stable vs last scan
        - narrative: LLM-ready text summary for report generation
    """

async def compliance_get_gaps(
    self,
    framework: str = "soc2",
) -> list[dict]:
    """Identify compliance gaps for a specific framework.

    Args:
        framework: Compliance framework to analyze.

    Returns:
        List of dicts with:
        - control_id: Framework control identifier
        - control_name: Human-readable name
        - status: pass/fail/partial
        - findings: Related findings from all scanners
        - remediation_priority: critical/high/medium/low
        - estimated_effort: estimated remediation effort
    """

async def compliance_get_remediation_plan(
    self,
    max_items: int = 20,
    severity_filter: list[str] | None = None,
) -> list[dict]:
    """Generate a prioritized remediation plan from consolidated findings.

    Args:
        max_items: Max remediation items to return.
        severity_filter: Filter by severity levels.

    Returns:
        Prioritized list of dicts with:
        - priority: 1-N
        - finding: SecurityFinding
        - source: Which scanner found it
        - remediation_steps: Actionable steps
        - compliance_impact: Which frameworks affected
        - estimated_effort: hours estimate
    """
```

---

## 8. Shared Report Infrastructure

### 8.1 Compliance Mapper (`reports/compliance_mapper.py`)

Responsible for mapping normalized `SecurityFinding` objects to compliance framework controls. This is the critical piece that enables cross-tool compliance reporting.

```python
class ComplianceMapper:
    """Maps security findings to compliance framework controls.

    Maintains a mapping database from:
    - Prowler check IDs → compliance controls
    - Trivy vulnerability types → compliance controls
    - Checkov policy IDs → compliance controls

    This enables unified compliance views regardless of which
    scanner produced the finding.
    """

    def map_finding_to_controls(
        self, finding: SecurityFinding, framework: ComplianceFramework
    ) -> list[str]:
        """Map a finding to relevant compliance controls."""
        ...

    def get_framework_coverage(
        self, findings: list[SecurityFinding], framework: ComplianceFramework
    ) -> dict:
        """Calculate compliance coverage for a framework.

        Returns:
            {
                "total_controls": int,
                "checked_controls": int,
                "passed_controls": int,
                "failed_controls": int,
                "coverage_pct": float,
                "gaps": list[dict]
            }
        """
        ...
```

### 8.2 Report Generator (`reports/generator.py`)

```python
class ReportGenerator:
    """Multi-format report generator with Jinja2 templates.

    Supports:
    - HTML reports (styled, interactive)
    - PDF reports (via weasyprint or headless chrome)
    - JSON exports (for programmatic consumption)
    - CSV exports (for audit spreadsheets)
    - Markdown (for LLM consumption and further processing)
    """

    def __init__(self, output_dir: str = "/tmp/security-reports"):
        self.output_dir = output_dir
        self.template_dir = Path(__file__).parent / "templates"

    async def generate_compliance_report(
        self,
        consolidated: ConsolidatedReport,
        framework: ComplianceFramework,
        format: str = "html",
        output_path: str | None = None,
        include_evidence: bool = True,
    ) -> str:
        """Generate a compliance report for a specific framework."""
        ...

    async def generate_executive_summary(
        self,
        consolidated: ConsolidatedReport,
        format: str = "html",
    ) -> str:
        """Generate an executive summary report."""
        ...

    async def generate_consolidated_report(
        self,
        consolidated: ConsolidatedReport,
        format: str = "html",
    ) -> str:
        """Generate a full consolidated security report."""
        ...

    async def export_findings_csv(
        self,
        findings: list[SecurityFinding],
        output_path: str,
    ) -> str:
        """Export findings to CSV for audit purposes."""
        ...
```

---

## 9. Implementation Tasks (Claude Code)

### Phase 1: Foundation (shared components)

| Task | Description | Priority | Estimated Complexity |
|---|---|---|---|
| **T1.1** | Create `security/models.py` with all shared data models | P0 | Low |
| **T1.2** | Create `security/base_executor.py` with BaseExecutor | P0 | Medium |
| **T1.3** | Create `security/base_parser.py` with BaseParser | P0 | Low |
| **T1.4** | Create `security/reports/compliance_mapper.py` skeleton | P0 | Medium |
| **T1.5** | Create `security/reports/generator.py` with Jinja2 templates | P1 | High |
| **T1.6** | Create `security/__init__.py` with re-exports | P0 | Low |

### Phase 2: Prowler Integration

| Task | Description | Priority | Estimated Complexity |
|---|---|---|---|
| **T2.1** | Create `security/prowler/config.py` (ProwlerConfig) | P0 | Low |
| **T2.2** | Create `security/prowler/executor.py` (ProwlerExecutor) | P0 | Medium |
| **T2.3** | Create `security/prowler/parser.py` — map JSON-OCSF → SecurityFinding | P0 | High |
| **T2.4** | Create `security/prowler/models.py` (Prowler-specific extensions) | P1 | Low |
| **T2.5** | Create `cloud_posture_toolkit.py` with all async tool methods | P0 | Medium |
| **T2.6** | Tests: ProwlerParser with sample JSON-OCSF fixtures | P0 | Medium |
| **T2.7** | Tests: CloudPostureToolkit tool exposure via get_tools() | P0 | Low |

### Phase 3: Trivy Integration

| Task | Description | Priority | Estimated Complexity |
|---|---|---|---|
| **T3.1** | Create `security/trivy/config.py` (TrivyConfig) | P0 | Low |
| **T3.2** | Create `security/trivy/executor.py` (TrivyExecutor) | P0 | Medium |
| **T3.3** | Create `security/trivy/parser.py` — map Trivy JSON → SecurityFinding | P0 | High |
| **T3.4** | Create `container_security_toolkit.py` with all async tool methods | P0 | Medium |
| **T3.5** | Tests: TrivyParser with sample output fixtures | P0 | Medium |
| **T3.6** | Tests: ContainerSecurityToolkit tool exposure | P0 | Low |

### Phase 4: Checkov Integration

| Task | Description | Priority | Estimated Complexity |
|---|---|---|---|
| **T4.1** | Create `security/checkov/config.py` (CheckovConfig) | P0 | Low |
| **T4.2** | Create `security/checkov/executor.py` (CheckovExecutor) | P0 | Medium |
| **T4.3** | Create `security/checkov/parser.py` — map Checkov JSON → SecurityFinding | P0 | High |
| **T4.4** | Create `secrets_iac_toolkit.py` with all async tool methods | P0 | Medium |
| **T4.5** | Tests: CheckovParser with sample output fixtures | P0 | Medium |
| **T4.6** | Tests: SecretsIaCToolkit tool exposure | P0 | Low |

### Phase 5: Compliance Aggregator

| Task | Description | Priority | Estimated Complexity |
|---|---|---|---|
| **T5.1** | Implement compliance_mapper.py — control mapping DB | P0 | High |
| **T5.2** | Implement SOC2 report template (Jinja2) | P0 | High |
| **T5.3** | Implement HIPAA report template | P0 | High |
| **T5.4** | Implement PCI-DSS report template | P1 | Medium |
| **T5.5** | Create `compliance_report_toolkit.py` with all methods | P0 | High |
| **T5.6** | Implement executive_summary generation | P0 | Medium |
| **T5.7** | Implement remediation_plan prioritization | P1 | Medium |
| **T5.8** | Tests: Full consolidated scan workflow (mocked executors) | P0 | High |
| **T5.9** | Tests: Report generation with fixture data | P0 | Medium |

### Phase 6: Integration & Polish

| Task | Description | Priority | Estimated Complexity |
|---|---|---|---|
| **T6.1** | Integration tests: end-to-end with real Docker scans | P1 | High |
| **T6.2** | Add toolkits to `parrot/tools/__init__.py` exports | P0 | Low |
| **T6.3** | MCP Server exposure: expose toolkits via SimpleMCPServer | P2 | Medium |
| **T6.4** | Documentation: README with usage examples | P1 | Medium |
| **T6.5** | Performance: lazy loading of scanner dependencies | P1 | Low |
| **T6.6** | Security: credential isolation per scan execution | P0 | Medium |

---

## 10. Usage Examples

### 10.1 Individual Toolkit Usage

```python
from parrot.tools.security import CloudPostureToolkit, ProwlerConfig

# Create toolkit with AWS config
toolkit = CloudPostureToolkit(
    config=ProwlerConfig(
        provider="aws",
        aws_profile="production",
        filter_regions=["us-east-1", "eu-west-1"],
    )
)

# Get tools for agent registration
tools = toolkit.get_tools()
# → [prowler_run_scan, prowler_compliance_scan, prowler_scan_service, ...]

# Direct usage
result = await toolkit.prowler_compliance_scan(
    provider="aws",
    framework="soc2",
    exclude_passing=True,
)
print(f"SOC2 findings: {result.summary.total_findings}")
```

### 10.2 Agent Integration

```python
from parrot.agents import Agent
from parrot.tools.security import (
    CloudPostureToolkit,
    ContainerSecurityToolkit,
    SecretsIaCToolkit,
    ComplianceReportToolkit,
)

# Create security agent with all toolkits
security_agent = Agent(
    name="SecurityAuditor",
    instructions="""You are a cloud security auditor. Use the available
    tools to scan infrastructure, identify vulnerabilities, and generate
    compliance reports. Always prioritize critical findings.""",
    tools=[
        *CloudPostureToolkit().get_tools(),
        *ContainerSecurityToolkit().get_tools(),
        *SecretsIaCToolkit().get_tools(),
        *ComplianceReportToolkit().get_tools(),
    ],
)

# Agent can now be asked:
# "Run a SOC2 compliance scan on our AWS production account"
# "Scan the nginx:latest image for critical vulnerabilities"
# "Check our Terraform configs for security misconfigurations"
# "Generate a consolidated HIPAA report"
```

### 10.3 ComplianceReportToolkit Orchestration

```python
from parrot.tools.security import ComplianceReportToolkit

compliance = ComplianceReportToolkit(
    prowler_config=ProwlerConfig(provider="aws"),
    trivy_config=TrivyConfig(),
    checkov_config=CheckovConfig(),
    report_output_dir="/reports/security",
)

# Full scan across all tools
report = await compliance.compliance_full_scan(
    provider="aws",
    target_image="myapp:v2.1.0",
    iac_path="/code/terraform/",
    framework="hipaa",
)

# Generate the compliance report
report_path = await compliance.compliance_hipaa_report(
    provider="aws",
    output_format="html",
    include_evidence=True,
)

# Get actionable remediation plan
plan = await compliance.compliance_get_remediation_plan(
    max_items=10,
    severity_filter=["CRITICAL", "HIGH"],
)
```

---

## 11. Open Questions & Decisions

| # | Question | Options | Recommendation |
|---|---|---|---|
| 1 | Should ComplianceReportToolkit run scans in parallel or sequentially? | `asyncio.gather()` vs sequential | Parallel with `asyncio.gather()` — scans are independent |
| 2 | How to handle partial scan failures (e.g., Prowler succeeds but Trivy fails)? | Fail all / return partial / configurable | Return partial with warnings — DevOps needs whatever data is available |
| 3 | Where to persist scan results for comparison? | Filesystem / Redis / PostgreSQL | Filesystem (JSON) initially, PostgreSQL later for history queries |
| 4 | Should compliance mappings be static (bundled) or dynamic (loaded from DB)? | Static YAML / PostgreSQL / both | Static YAML files bundled with the module, overridable via config |
| 5 | Report templates: Jinja2 HTML or python-docx/WeasyPrint? | Jinja2→HTML→PDF vs python-docx | Jinja2 HTML as primary, PDF via WeasyPrint as secondary |
| 6 | Should individual toolkits re-export from `parrot/tools/` or only from `security/`? | Both / only security/ | Both — individual toolkits in `parrot/tools/` for discoverability |
| 7 | Integration with existing CloudSploitToolkit? | Migrate to new models / adapter / keep separate | Adapter pattern — wrap CloudSploitToolkit to emit SecurityFinding |
| 8 | Docker image management (pull/build/cache)? | Pre-built / build on start / configurable | Configurable — assume pre-built, document build instructions |

---

## 12. References

- **CloudSploitToolkit (existing)**: `parrot/tools/cloudsploit/` — reference implementation
- **AbstractToolkit**: `parrot/tools/toolkit.py` — base class for all toolkits
- **JiraToolkit**: `parrot/tools/jiratoolkit.py` — pattern reference for complex toolkits
- **WorkdayToolkit**: `parrot/tools/workday/tool.py` — multi-service toolkit pattern
- **Prowler docs**: https://docs.prowler.com/
- **Trivy docs**: https://aquasecurity.github.io/trivy/
- **Checkov docs**: https://www.checkov.io/1.Welcome/Quick%20Start.html