# TASK-043: SecretsIaCToolkit

**Feature**: Security Toolkits Suite
**Spec**: `sdd/specs/compliancereport-toolkit.spec.md`
**Status**: in-progress
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-041, TASK-042
**Assigned-to**: claude-session

---

## Context

SecretsIaCToolkit is the agent-facing toolkit that wraps Checkov. It exposes IaC scanning and secrets detection capabilities as tools that agents can call.

Reference: Spec Section 6.2 (Toolkit).

---

## Scope

- Implement `parrot/tools/security/secrets_iac_toolkit.py`
- Create `SecretsIaCToolkit` extending `AbstractToolkit`
- Implement all tool methods:
  - `checkov_scan_directory()` — Scan IaC directory
  - `checkov_scan_file()` — Scan specific file
  - `checkov_scan_terraform()` — Specialized Terraform scan
  - `checkov_scan_cloudformation()` — Specialized CFn scan
  - `checkov_scan_kubernetes()` — Scan K8s manifests
  - `checkov_scan_dockerfile()` — Scan Dockerfiles
  - `checkov_scan_helm()` — Scan Helm charts
  - `checkov_scan_secrets()` — Secrets scanning
  - `checkov_scan_github_actions()` — Scan GH Actions
  - `checkov_list_checks()` — List available checks
  - `checkov_get_summary()` — Summary of last scan
  - `checkov_get_findings()` — Get findings with filters
  - `checkov_generate_report()` — Generate HTML report
  - `checkov_compare_scans()` — Compare two scan results
- Write unit tests verifying tool exposure

**NOT in scope**:
- Report generation implementation (placeholder)
- Actual execution (mocked)
- ComplianceReportToolkit (separate task)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/security/secrets_iac_toolkit.py` | CREATE | SecretsIaCToolkit class |
| `parrot/tools/security/__init__.py` | MODIFY | Add toolkit export |
| `tests/test_secrets_iac_toolkit.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow

```python
# parrot/tools/security/secrets_iac_toolkit.py
from typing import Optional
from ..toolkit import AbstractToolkit
from .checkov.config import CheckovConfig
from .checkov.executor import CheckovExecutor
from .checkov.parser import CheckovParser
from .models import ScanResult, SecurityFinding


class SecretsIaCToolkit(AbstractToolkit):
    """Infrastructure as Code and Secrets scanning toolkit powered by Checkov.

    Scans Terraform, CloudFormation, Kubernetes, Helm, Dockerfiles, and code
    for security misconfigurations and exposed secrets.

    All public async methods automatically become agent tools.
    """

    def __init__(self, config: CheckovConfig | None = None, **kwargs):
        super().__init__(**kwargs)
        self.config = config or CheckovConfig()
        self.executor = CheckovExecutor(self.config)
        self.parser = CheckovParser()
        self._last_result: ScanResult | None = None
```

### Tool Method Summary

| Method | Description | Key Args |
|---|---|---|
| `checkov_scan_directory` | Scan IaC directory | `path`, `framework`, `checks`, `skip_checks` |
| `checkov_scan_file` | Scan specific file | `file_path`, `framework` |
| `checkov_scan_terraform` | Terraform scan | `path`, `var_files` |
| `checkov_scan_cloudformation` | CloudFormation scan | `path`, `template_file` |
| `checkov_scan_kubernetes` | K8s manifests | `path`, `namespace_filter` |
| `checkov_scan_dockerfile` | Dockerfiles | `path` |
| `checkov_scan_helm` | Helm charts | `path`, `values_file` |
| `checkov_scan_secrets` | Secrets in code | `path` |
| `checkov_scan_github_actions` | GH Actions | `path` |
| `checkov_list_checks` | List checks | `framework` |
| `checkov_get_summary` | Last scan summary | — |
| `checkov_get_findings` | Filtered findings | `severity`, `framework`, `limit` |
| `checkov_generate_report` | Generate report | `format`, `output_path` |
| `checkov_compare_scans` | Compare results | `baseline_path`, `current_path` |

### Key Constraints

- All tool methods must be `async`
- Store `_last_result` for summary/findings methods
- `framework` filter in `get_findings()` should filter by `resource_type`
- Specialized scan methods should set the `--framework` flag automatically

---

## Acceptance Criteria

- [ ] `SecretsIaCToolkit` extends `AbstractToolkit`
- [ ] All 14 tool methods implemented with proper docstrings
- [ ] `get_tools()` returns list of ToolkitTool instances
- [ ] Specialized scan methods set framework automatically
- [ ] Finding filters work correctly (severity, framework)
- [ ] All tests pass: `pytest tests/test_secrets_iac_toolkit.py -v`
- [ ] Import works: `from parrot.tools.security import SecretsIaCToolkit`

---

## Test Specification

```python
# tests/test_secrets_iac_toolkit.py
import pytest
from unittest.mock import AsyncMock, patch
from parrot.tools.security.secrets_iac_toolkit import SecretsIaCToolkit
from parrot.tools.security.checkov.config import CheckovConfig
from parrot.tools.security.models import (
    ScanResult,
    ScanSummary,
    SecurityFinding,
    FindingSource,
    SeverityLevel,
    CloudProvider,
)
from datetime import datetime


@pytest.fixture
def toolkit():
    return SecretsIaCToolkit()


@pytest.fixture
def mock_scan_result():
    findings = [
        SecurityFinding(
            id="CKV_AWS_21",
            source=FindingSource.CHECKOV,
            severity=SeverityLevel.MEDIUM,
            title="S3 versioning disabled",
            resource_type="terraform",
        ),
        SecurityFinding(
            id="CKV_AWS_19",
            source=FindingSource.CHECKOV,
            severity=SeverityLevel.HIGH,
            title="S3 encryption disabled",
            resource_type="terraform",
        ),
        SecurityFinding(
            id="CKV_DOCKER_3",
            source=FindingSource.CHECKOV,
            severity=SeverityLevel.MEDIUM,
            title="Dockerfile USER not set",
            resource_type="dockerfile",
        ),
    ]
    summary = ScanSummary(
        source=FindingSource.CHECKOV,
        provider=CloudProvider.LOCAL,
        total_findings=3,
        high_count=1,
        medium_count=2,
        scan_timestamp=datetime.now(),
    )
    return ScanResult(findings=findings, summary=summary)


class TestToolkitInitialization:
    def test_default_config(self, toolkit):
        """Toolkit initializes with default config."""
        assert toolkit.config.docker_image == "bridgecrew/checkov:latest"
        assert toolkit.executor is not None
        assert toolkit.parser is not None

    def test_custom_config(self):
        """Toolkit accepts custom config."""
        config = CheckovConfig(frameworks=["terraform"])
        toolkit = SecretsIaCToolkit(config=config)
        assert toolkit.config.frameworks == ["terraform"]


class TestToolExposure:
    def test_get_tools_returns_list(self, toolkit):
        """get_tools() returns tool list."""
        tools = toolkit.get_tools()
        assert isinstance(tools, list)
        assert len(tools) > 0

    def test_all_methods_exposed(self, toolkit):
        """All public async methods are exposed as tools."""
        tool_names = toolkit.list_tool_names()
        expected = [
            "checkov_scan_directory",
            "checkov_scan_file",
            "checkov_scan_terraform",
            "checkov_scan_cloudformation",
            "checkov_scan_kubernetes",
            "checkov_scan_dockerfile",
            "checkov_scan_helm",
            "checkov_scan_secrets",
            "checkov_scan_github_actions",
            "checkov_list_checks",
            "checkov_get_summary",
            "checkov_get_findings",
            "checkov_generate_report",
            "checkov_compare_scans",
        ]
        for name in expected:
            assert name in tool_names, f"Missing tool: {name}"

    def test_tools_have_descriptions(self, toolkit):
        """All tools have non-empty descriptions."""
        tools = toolkit.get_tools()
        for tool in tools:
            assert tool.description, f"Tool {tool.name} has no description"


class TestCheckovScanDirectory:
    @pytest.mark.asyncio
    async def test_scan_directory_basic(self, toolkit, mock_scan_result):
        """Basic directory scan execution."""
        with patch.object(toolkit.executor, 'scan_directory', new_callable=AsyncMock) as mock_exec:
            with patch.object(toolkit.parser, 'parse') as mock_parse:
                mock_exec.return_value = ('{}', '', 0)
                mock_parse.return_value = mock_scan_result

                result = await toolkit.checkov_scan_directory(path="/app/terraform")

                assert result.summary.total_findings == 3
                assert toolkit._last_result == result


class TestSpecializedScans:
    @pytest.mark.asyncio
    async def test_scan_terraform_sets_framework(self, toolkit, mock_scan_result):
        """Terraform scan sets framework automatically."""
        with patch.object(toolkit.executor, 'scan_directory', new_callable=AsyncMock) as mock_exec:
            with patch.object(toolkit.parser, 'parse') as mock_parse:
                mock_exec.return_value = ('{}', '', 0)
                mock_parse.return_value = mock_scan_result

                await toolkit.checkov_scan_terraform(path="/app/terraform")

                # Verify framework was set in the call
                call_kwargs = mock_exec.call_args
                assert call_kwargs is not None

    @pytest.mark.asyncio
    async def test_scan_dockerfile(self, toolkit, mock_scan_result):
        """Dockerfile scan works."""
        with patch.object(toolkit.executor, 'scan_directory', new_callable=AsyncMock) as mock_exec:
            with patch.object(toolkit.parser, 'parse') as mock_parse:
                mock_exec.return_value = ('{}', '', 0)
                mock_parse.return_value = mock_scan_result

                result = await toolkit.checkov_scan_dockerfile(path="/app")
                assert result is not None


class TestGetFindings:
    @pytest.mark.asyncio
    async def test_get_findings_by_framework(self, toolkit, mock_scan_result):
        """get_findings filters by framework (resource_type)."""
        toolkit._last_result = mock_scan_result
        findings = await toolkit.checkov_get_findings(framework="terraform")
        assert len(findings) == 2
        assert all(f.resource_type == "terraform" for f in findings)

    @pytest.mark.asyncio
    async def test_get_findings_by_severity(self, toolkit, mock_scan_result):
        """get_findings filters by severity."""
        toolkit._last_result = mock_scan_result
        findings = await toolkit.checkov_get_findings(severity="HIGH")
        assert len(findings) == 1
        assert findings[0].severity == SeverityLevel.HIGH


class TestListChecks:
    @pytest.mark.asyncio
    async def test_list_checks(self, toolkit):
        """list_checks returns available checks."""
        with patch.object(toolkit.executor, 'list_checks', new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = ('[]', '', 0)
            result = await toolkit.checkov_list_checks(framework="terraform")
            assert isinstance(result, list)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/compliancereport-toolkit.spec.md` Section 6.2
2. **Check dependencies** — TASK-041, TASK-042 must be complete
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-043-secrets-iac-toolkit.md`
7. **Update index** → `"done"`

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-26
**Notes**:
- Created `SecretsIaCToolkit` with all 14 tool methods
- All methods properly wrap `CheckovExecutor` and `CheckovParser`
- Specialized scans (terraform, cloudformation, k8s, dockerfile, helm, secrets, github_actions) auto-set framework
- Finding filters support severity, framework, and limit
- 36 tests passing covering all functionality

**Deviations from spec**: none
