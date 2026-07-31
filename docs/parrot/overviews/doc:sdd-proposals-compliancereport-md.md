---
type: Wiki Overview
title: AI-Parrot Security Toolkits Suite — Spec & Brainstorming
id: doc:sdd-proposals-compliancereport-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: DevOps teams spend excessive time manually running cloud security scanners,
  cross-referencing results, and producing compliance reports (SOC2, HIPAA, PCI-DSS).
  Each tool has its own CLI, output format, and learning curve. There is no unified
  interface for an AI agent to orchestra
relates_to:
- concept: mod:parrot.agents
  rel: mentions
- concept: mod:parrot.tools
  rel: mentions
---

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

…(truncated)…
