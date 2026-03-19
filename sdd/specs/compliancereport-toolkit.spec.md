# Feature Specification: Security Toolkits Suite

**Feature ID**: FEAT-011
**Date**: 2026-02-26
**Author**: Jesus Lara
**Status**: approved
**Target version**: next

---

## 1. Motivation & Business Requirements

### Problem Statement

DevOps teams spend excessive time manually running cloud security scanners, cross-referencing results, and producing compliance reports (SOC2, HIPAA, PCI-DSS). Each tool has its own CLI, output format, and learning curve. There is no unified interface for an AI agent to orchestrate multiple security tools, correlate findings, and auto-generate compliance narratives.

### Goals

- Build a **Security Toolkits Suite** for AI-Parrot that exposes cloud security tools as agent-callable tools via `AbstractToolkit`
- Wrap Prowler, Trivy, and Checkov following the proven `CloudSploitToolkit` pattern
- Run security scans across AWS, Azure, GCP, and Kubernetes
- Parse and normalize findings into a **unified data model** (`SecurityFinding`)
- Compare scans over time (drift detection)
- Generate compliance reports (SOC2, HIPAA, PCI-DSS, CIS, ISO27001)
- Produce consolidated aggregate reports combining multiple tools

### Non-Goals (explicitly out of scope)

- Commercial scanner integrations (e.g., Prisma Cloud, Wiz)
- Real-time continuous monitoring (this is scan-on-demand)
- Custom policy authoring UI
- Direct database storage of findings (filesystem/JSON initially)

---

## 2. Architectural Design

### Overview

The suite consists of 4 toolkits, each wrapping a specific scanner. A `ComplianceReportToolkit` aggregates results from all scanners and produces unified compliance reports. Each scanner has its own module with executor, parser, config, and models.

### Component Diagram

```
ComplianceReportToolkit (aggregator)
    ├── prowler.executor ──→ ProwlerParser ──→ SecurityFinding
    ├── trivy.executor   ──→ TrivyParser   ──→ SecurityFinding
    ├── checkov.executor ──→ CheckovParser ──→ SecurityFinding
    ├── reports.generator
    └── reports.compliance_mapper

CloudPostureToolkit ──→ prowler.executor + prowler.parser
ContainerSecurityToolkit ──→ trivy.executor + trivy.parser
SecretsIaCToolkit ──→ checkov.executor + checkov.parser
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractToolkit` | extends | All 4 toolkits inherit from AbstractToolkit |
| `CloudSploitToolkit` | pattern reference | Follow executor → parser → reports structure |
| `Agent` | uses | Agents register toolkit tools via `get_tools()` |
| `datamodel.parsers.json` | uses | JSON encoding/decoding for scan results |

### Data Models

```python
# parrot/tools/security/models.py — Unified models

class SeverityLevel(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"
    PASS = "PASS"
    UNKNOWN = "UNKNOWN"

class FindingSource(str, Enum):
    PROWLER = "prowler"
    TRIVY = "trivy"
    CHECKOV = "checkov"
    CLOUDSPLOIT = "cloudsploit"

class ComplianceFramework(str, Enum):
    SOC2 = "soc2"
    HIPAA = "hipaa"
    PCI_DSS = "pci_dss"
    CIS_AWS = "cis_aws"
    CIS_GCP = "cis_gcp"
    CIS_AZURE = "cis_azure"
    CIS_K8S = "cis_k8s"
    ISO27001 = "iso27001"
    NIST_800_53 = "nist_800_53"
    GDPR = "gdpr"

class CloudProvider(str, Enum):
    AWS = "aws"
    GCP = "gcp"
    AZURE = "azure"
    KUBERNETES = "kubernetes"
    LOCAL = "local"

class SecurityFinding(BaseModel):
    """Unified finding model — all scanners normalize to this."""
    id: str
    source: FindingSource
    severity: SeverityLevel
    title: str
    description: str = ""
    resource: Optional[str] = None
    resource_type: Optional[str] = None
    region: str = "global"
    provider: CloudProvider = CloudProvider.AWS
    service: Optional[str] = None
    check_id: Optional[str] = None
    compliance_tags: list[str] = []
    remediation: Optional[str] = None
    raw: Optional[dict] = None

class ScanSummary(BaseModel):
    source: FindingSource
    provider: CloudProvider
    total_findings: int = 0
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    pass_count: int = 0
    scan_timestamp: datetime
    duration_seconds: Optional[float] = None

class ScanResult(BaseModel):
    findings: list[SecurityFinding] = []
    summary: ScanSummary
    raw_output: Optional[Union[dict, list, str]] = None

class ConsolidatedReport(BaseModel):
    scan_results: dict[str, ScanResult] = {}
    total_findings: int = 0
    findings_by_severity: dict[str, int] = {}
    compliance_coverage: dict[str, dict] = {}
    generated_at: datetime
    report_paths: dict[str, str] = {}
```

### New Public Interfaces

```python
# Individual toolkits
class CloudPostureToolkit(AbstractToolkit):
    """Prowler wrapper for cloud security posture management."""
    async def prowler_run_scan(...) -> ScanResult
    async def prowler_compliance_scan(...) -> ScanResult
    async def prowler_scan_service(...) -> ScanResult
    async def prowler_get_findings(...) -> list[SecurityFinding]
    async def prowler_generate_report(...) -> str

class ContainerSecurityToolkit(AbstractToolkit):
    """Trivy wrapper for container and IaC scanning."""
    async def trivy_scan_image(...) -> ScanResult
    async def trivy_scan_k8s(...) -> ScanResult
    async def trivy_scan_iac(...) -> ScanResult
    async def trivy_generate_sbom(...) -> str

class SecretsIaCToolkit(AbstractToolkit):
    """Checkov wrapper for IaC and secrets scanning."""
    async def checkov_scan_directory(...) -> ScanResult
    async def checkov_scan_terraform(...) -> ScanResult
    async def checkov_scan_secrets(...) -> ScanResult

class ComplianceReportToolkit(AbstractToolkit):
    """Aggregator that orchestrates all scanners."""
    async def compliance_full_scan(...) -> ConsolidatedReport
    async def compliance_soc2_report(...) -> str
    async def compliance_hipaa_report(...) -> str
    async def compliance_executive_summary(...) -> dict
    async def compliance_get_gaps(...) -> list[dict]
    async def compliance_get_remediation_plan(...) -> list[dict]
```

---

## 3. Module Breakdown

### Module 1: Shared Models
- **Path**: `parrot/tools/security/models.py`
- **Responsibility**: Unified data models (SecurityFinding, ScanResult, etc.)
- **Depends on**: pydantic

### Module 2: Base Executor
- **Path**: `parrot/tools/security/base_executor.py`
- **Responsibility**: Abstract executor for Docker/CLI scanner execution
- **Depends on**: asyncio, Module 1

### Module 3: Base Parser
- **Path**: `parrot/tools/security/base_parser.py`
- **Responsibility**: Abstract parser interface for normalizing scanner output
- **Depends on**: Module 1

### Module 4: Prowler Scanner Module
- **Path**: `parrot/tools/security/prowler/`
- **Responsibility**: Prowler config, executor, parser
- **Depends on**: Modules 1-3

### Module 5: Trivy Scanner Module
- **Path**: `parrot/tools/security/trivy/`
- **Responsibility**: Trivy config, executor, parser
- **Depends on**: Modules 1-3

### Module 6: Checkov Scanner Module
- **Path**: `parrot/tools/security/checkov/`
- **Responsibility**: Checkov config, executor, parser
- **Depends on**: Modules 1-3

### Module 7: Compliance Mapper
- **Path**: `parrot/tools/security/reports/compliance_mapper.py`
- **Responsibility**: Map findings to compliance framework controls
- **Depends on**: Module 1

### Module 8: Report Generator
- **Path**: `parrot/tools/security/reports/generator.py`
- **Responsibility**: Generate HTML/PDF/JSON compliance reports
- **Depends on**: Modules 1, 7, Jinja2

### Module 9: CloudPostureToolkit
- **Path**: `parrot/tools/security/cloud_posture_toolkit.py`
- **Responsibility**: Prowler toolkit exposing tools to agents
- **Depends on**: Module 4, AbstractToolkit

### Module 10: ContainerSecurityToolkit
- **Path**: `parrot/tools/security/container_security_toolkit.py`
- **Responsibility**: Trivy toolkit exposing tools to agents
- **Depends on**: Module 5, AbstractToolkit

### Module 11: SecretsIaCToolkit
- **Path**: `parrot/tools/security/secrets_iac_toolkit.py`
- **Responsibility**: Checkov toolkit exposing tools to agents
- **Depends on**: Module 6, AbstractToolkit

### Module 12: ComplianceReportToolkit
- **Path**: `parrot/tools/security/compliance_report_toolkit.py`
- **Responsibility**: Aggregator toolkit orchestrating all scanners
- **Depends on**: Modules 4-8, AbstractToolkit

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_security_finding_model` | Module 1 | Validates SecurityFinding serialization |
| `test_severity_normalization` | Module 1 | Maps scanner-specific severities to unified |
| `test_base_executor_env_vars` | Module 2 | Builds cloud credential env vars correctly |
| `test_base_executor_docker_cmd` | Module 2 | Builds docker run command correctly |
| `test_base_executor_mask_creds` | Module 2 | Masks secrets in logged commands |
| `test_prowler_parser_ocsf` | Module 4 | Parses Prowler JSON-OCSF output |
| `test_trivy_parser_json` | Module 5 | Parses Trivy JSON output |
| `test_checkov_parser_json` | Module 6 | Parses Checkov JSON output |
| `test_compliance_mapper_soc2` | Module 7 | Maps findings to SOC2 controls |
| `test_report_generator_html` | Module 8 | Generates valid HTML report |
| `test_toolkit_get_tools` | Module 9-12 | Each toolkit exposes tools via get_tools() |

### Integration Tests

| Test | Description |
|---|---|
| `test_prowler_scan_mock` | End-to-end Prowler scan with mocked executor |
| `test_trivy_image_scan_mock` | End-to-end Trivy image scan with mocked executor |
| `test_checkov_terraform_scan_mock` | End-to-end Checkov scan with mocked executor |
| `test_consolidated_report_full` | Full workflow: run all scanners, aggregate, generate report |
| `test_comparison_delta` | Compare two scan results for drift detection |

### Test Data / Fixtures

```python
@pytest.fixture
def prowler_ocsf_sample():
    """Sample Prowler JSON-OCSF output."""
    return Path("tests/fixtures/prowler_ocsf_sample.json").read_text()

@pytest.fixture
def trivy_image_sample():
    """Sample Trivy image scan output."""
    return Path("tests/fixtures/trivy_image_sample.json").read_text()

@pytest.fixture
def checkov_terraform_sample():
    """Sample Checkov Terraform scan output."""
    return Path("tests/fixtures/checkov_terraform_sample.json").read_text()

@pytest.fixture
def security_findings_mixed():
    """Mixed findings from multiple scanners for aggregation tests."""
    return [...]
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All unit tests pass (`pytest tests/test_security_*.py -v`)
- [ ] All integration tests pass with mocked executors
- [ ] Each toolkit exposes tools via `get_tools()` that agents can register
- [ ] Unified `SecurityFinding` model normalizes output from all 3 scanners
- [ ] `ComplianceReportToolkit.compliance_full_scan()` runs all scanners and aggregates results
- [ ] SOC2, HIPAA, and PCI-DSS report templates generate valid HTML
- [ ] Scan comparison produces accurate delta (new/resolved/unchanged findings)
- [ ] Credentials are masked in all log output
- [ ] No breaking changes to existing `CloudSploitToolkit` API
- [ ] Documentation: usage examples in docstrings

---

## 6. Implementation Notes & Constraints

### Patterns to Follow

- Follow `CloudSploitToolkit` pattern: `config.py`, `executor.py`, `parser.py`, `models.py`
- Inherit from `AbstractToolkit` — all public async methods become agent tools
- Use `BaseExecutor` for Docker/CLI execution with credential injection
- Use `BaseParser` for normalizing scanner-specific output to `SecurityFinding`
- Async-first: all executor methods are async (subprocess with asyncio)
- Pydantic models for all data structures
- Comprehensive logging with `self.logger`

### Key Design Decision: Aggregator Independence

`ComplianceReportToolkit` uses the underlying executors and parsers **directly**, not the other toolkits. This prevents circular dependencies:

```python
# CORRECT: ComplianceReportToolkit composes executors directly
self.prowler_executor = ProwlerExecutor(config)
self.prowler_parser = ProwlerParser()

# WRONG: Would create circular imports
self.prowler_toolkit = CloudPostureToolkit(...)
```

### Known Risks / Gotchas

- **Docker availability**: Scanners run via Docker by default. Ensure Docker daemon is running or provide CLI fallback.
- **Credential scope**: Each scanner needs appropriate cloud credentials. Document required IAM permissions.
- **Output format changes**: Scanner CLI output formats may change across versions. Pin Docker image tags.
- **Large scan output**: Full cloud scans can produce 1000s of findings. Implement pagination/limits in `get_findings()`.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `pydantic` | `>=2.0` | Data models |
| `jinja2` | `>=3.0` | HTML report templates |
| `weasyprint` | `>=60.0` | PDF generation (optional) |
| Docker images | | |
| `toniblyx/prowler:latest` | | Prowler scanner |
| `aquasec/trivy:latest` | | Trivy scanner |
| `bridgecrew/checkov:latest` | | Checkov scanner |

---

## 7. Open Questions

> Questions resolved in the proposal document:

- [x] Parallel vs sequential scans — **Parallel with `asyncio.gather()`** (scans are independent): parallel
- [x] Partial scan failures — **Return partial results with warnings** (DevOps needs available data): available data.
- [x] Compliance mapping storage — **Static YAML files bundled**, overridable via config
- [x] Report format — **Jinja2 HTML primary**, PDF via WeasyPrint secondary: JSON or Jinja2 html are primary outputs, we can print to PDF using a secondary tool
- [x] CloudSploit integration — **Adapter pattern** to wrap existing toolkit: adding into ComplianceReportToolkit call to CloudSploit and integrate into the flow.

> Remaining open questions:

- [ ] Should we support custom compliance framework definitions? — *Owner: Jesus*
- [ ] Multi-account scanning (AWS Organizations)? — *Owner: Jesus*: No, one account for instance.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-02-26 | Jesus Lara | Initial draft from proposal document |
