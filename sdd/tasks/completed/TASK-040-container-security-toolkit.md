# TASK-040: ContainerSecurityToolkit

**Feature**: Security Toolkits Suite
**Spec**: `sdd/specs/compliancereport-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-038, TASK-039
**Assigned-to**: claude-session

---

## Context

ContainerSecurityToolkit is the agent-facing toolkit that wraps Trivy. It exposes container, filesystem, Kubernetes, and IaC scanning capabilities as tools that agents can call.

Reference: Spec Section 5.2 (Toolkit).

---

## Scope

- Implement `parrot/tools/security/container_security_toolkit.py`
- Create `ContainerSecurityToolkit` extending `AbstractToolkit`
- Implement all tool methods:
  - `trivy_scan_image()` — Scan container image for CVEs
  - `trivy_scan_filesystem()` — Scan local directory
  - `trivy_scan_repo()` — Scan git repository
  - `trivy_scan_k8s()` — Scan Kubernetes cluster
  - `trivy_scan_iac()` — Scan IaC configurations
  - `trivy_generate_sbom()` — Generate SBOM
  - `trivy_get_summary()` — Summary of last scan
  - `trivy_get_findings()` — Get findings with filters
  - `trivy_generate_report()` — Generate HTML report
  - `trivy_compare_scans()` — Compare two scan results
- Write unit tests verifying tool exposure

**NOT in scope**:
- Report generation implementation (placeholder)
- Actual Docker execution (mocked)
- ComplianceReportToolkit (separate task)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/security/container_security_toolkit.py` | CREATE | ContainerSecurityToolkit class |
| `parrot/tools/security/__init__.py` | MODIFY | Add toolkit export |
| `tests/test_container_security_toolkit.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow

```python
# parrot/tools/security/container_security_toolkit.py
from typing import Optional
from ..toolkit import AbstractToolkit
from .trivy.config import TrivyConfig
from .trivy.executor import TrivyExecutor
from .trivy.parser import TrivyParser
from .models import ScanResult, SecurityFinding


class ContainerSecurityToolkit(AbstractToolkit):
    """Container and infrastructure security toolkit powered by Trivy.

    Scans container images, filesystems, git repositories, Kubernetes clusters,
    and Infrastructure as Code for vulnerabilities, secrets, and misconfigurations.

    All public async methods automatically become agent tools.
    """

    def __init__(self, config: TrivyConfig | None = None, **kwargs):
        super().__init__(**kwargs)
        self.config = config or TrivyConfig()
        self.executor = TrivyExecutor(self.config)
        self.parser = TrivyParser()
        self._last_result: ScanResult | None = None

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
        ...
```

### Tool Method Summary

| Method | Description | Key Args |
|---|---|---|
| `trivy_scan_image` | Scan container image | `image`, `severity`, `ignore_unfixed`, `scanners` |
| `trivy_scan_filesystem` | Scan local directory | `path`, `scanners` |
| `trivy_scan_repo` | Scan git repository | `repo_url`, `branch` |
| `trivy_scan_k8s` | Scan Kubernetes cluster | `context`, `namespace`, `compliance` |
| `trivy_scan_iac` | Scan IaC configs | `path`, `config_type` |
| `trivy_generate_sbom` | Generate SBOM | `target`, `format` (cyclonedx/spdx) |
| `trivy_get_summary` | Last scan summary | — |
| `trivy_get_findings` | Filtered findings | `severity`, `scanner_type`, `limit` |
| `trivy_generate_report` | Generate HTML report | `format`, `output_path` |
| `trivy_compare_scans` | Compare two results | `baseline_path`, `current_path` |

### Key Constraints

- All tool methods must be `async`
- Store `_last_result` for `get_summary()` and `get_findings()`
- `scanner_type` filter in `get_findings()` should filter by `resource_type`
- SBOM generation should return file path

---

## Acceptance Criteria

- [ ] `ContainerSecurityToolkit` extends `AbstractToolkit`
- [ ] All 10 tool methods implemented with proper docstrings
- [ ] `get_tools()` returns list of ToolkitTool instances
- [ ] `_last_result` stored and used by summary/findings methods
- [ ] Finding filters work correctly (severity, scanner_type)
- [ ] SBOM generation returns file path
- [ ] All tests pass: `pytest tests/test_container_security_toolkit.py -v`
- [ ] Import works: `from parrot.tools.security import ContainerSecurityToolkit`

---

## Test Specification

```python
# tests/test_container_security_toolkit.py
import pytest
from unittest.mock import AsyncMock, patch
from parrot.tools.security.container_security_toolkit import ContainerSecurityToolkit
from parrot.tools.security.trivy.config import TrivyConfig
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
    return ContainerSecurityToolkit()


@pytest.fixture
def mock_scan_result():
    findings = [
        SecurityFinding(
            id="CVE-2023-1234",
            source=FindingSource.TRIVY,
            severity=SeverityLevel.CRITICAL,
            title="Critical CVE",
            resource_type="vulnerability",
        ),
        SecurityFinding(
            id="secret-1",
            source=FindingSource.TRIVY,
            severity=SeverityLevel.HIGH,
            title="Exposed Secret",
            resource_type="secret",
        ),
        SecurityFinding(
            id="DS002",
            source=FindingSource.TRIVY,
            severity=SeverityLevel.MEDIUM,
            title="Dockerfile Issue",
            resource_type="Dockerfile",
        ),
    ]
    summary = ScanSummary(
        source=FindingSource.TRIVY,
        provider=CloudProvider.LOCAL,
        total_findings=3,
        critical_count=1,
        high_count=1,
        medium_count=1,
        scan_timestamp=datetime.now(),
    )
    return ScanResult(findings=findings, summary=summary)


class TestToolkitInitialization:
    def test_default_config(self, toolkit):
        """Toolkit initializes with default config."""
        assert toolkit.config.docker_image == "aquasec/trivy:latest"
        assert toolkit.executor is not None
        assert toolkit.parser is not None

    def test_custom_config(self):
        """Toolkit accepts custom config."""
        config = TrivyConfig(severity_filter=["CRITICAL"])
        toolkit = ContainerSecurityToolkit(config=config)
        assert toolkit.config.severity_filter == ["CRITICAL"]


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
            "trivy_scan_image",
            "trivy_scan_filesystem",
            "trivy_scan_repo",
            "trivy_scan_k8s",
            "trivy_scan_iac",
            "trivy_generate_sbom",
            "trivy_get_summary",
            "trivy_get_findings",
            "trivy_generate_report",
            "trivy_compare_scans",
        ]
        for name in expected:
            assert name in tool_names, f"Missing tool: {name}"


class TestTrivyScanImage:
    @pytest.mark.asyncio
    async def test_scan_image_basic(self, toolkit, mock_scan_result):
        """Basic image scan execution."""
        with patch.object(toolkit.executor, 'scan_image', new_callable=AsyncMock) as mock_exec:
            with patch.object(toolkit.parser, 'parse') as mock_parse:
                mock_exec.return_value = ('{}', '', 0)
                mock_parse.return_value = mock_scan_result

                result = await toolkit.trivy_scan_image(image="nginx:latest")

                assert result.summary.total_findings == 3
                assert toolkit._last_result == result
                mock_exec.assert_called_once()


class TestGetFindings:
    @pytest.mark.asyncio
    async def test_get_findings_by_scanner_type(self, toolkit, mock_scan_result):
        """get_findings filters by scanner_type (resource_type)."""
        toolkit._last_result = mock_scan_result
        findings = await toolkit.trivy_get_findings(scanner_type="vulnerability")
        assert len(findings) == 1
        assert findings[0].resource_type == "vulnerability"

    @pytest.mark.asyncio
    async def test_get_findings_by_severity(self, toolkit, mock_scan_result):
        """get_findings filters by severity."""
        toolkit._last_result = mock_scan_result
        findings = await toolkit.trivy_get_findings(severity="CRITICAL")
        assert len(findings) == 1
        assert findings[0].severity == SeverityLevel.CRITICAL


class TestTrivyScanK8s:
    @pytest.mark.asyncio
    async def test_scan_k8s_with_context(self, toolkit, mock_scan_result):
        """K8s scan with context and namespace."""
        with patch.object(toolkit.executor, 'scan_k8s', new_callable=AsyncMock) as mock_exec:
            with patch.object(toolkit.parser, 'parse') as mock_parse:
                mock_exec.return_value = ('{}', '', 0)
                mock_parse.return_value = mock_scan_result

                result = await toolkit.trivy_scan_k8s(
                    context="my-cluster",
                    namespace="default",
                )

                assert result is not None
                mock_exec.assert_called_once()


class TestTrivyGenerateSbom:
    @pytest.mark.asyncio
    async def test_generate_sbom_returns_path(self, toolkit, tmp_path):
        """SBOM generation returns file path."""
        with patch.object(toolkit.executor, 'generate_sbom', new_callable=AsyncMock) as mock_exec:
            sbom_content = '{"bomFormat": "CycloneDX"}'
            mock_exec.return_value = (sbom_content, '', 0)

            output_path = str(tmp_path / "sbom.json")
            result = await toolkit.trivy_generate_sbom(
                target="myapp:v1",
                format="cyclonedx",
                output_path=output_path,
            )

            assert result is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/compliancereport-toolkit.spec.md` Section 5.2
2. **Check dependencies** — TASK-038, TASK-039 must be complete
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-040-container-security-toolkit.md`
7. **Update index** → `"done"`

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-26
**Notes**: Implemented ContainerSecurityToolkit extending AbstractToolkit with all 10 tool methods wrapping TrivyExecutor. All 35 tests pass. Tools exposed: trivy_scan_image, trivy_scan_filesystem, trivy_scan_repo, trivy_scan_k8s, trivy_scan_iac, trivy_generate_sbom, trivy_get_summary, trivy_get_findings, trivy_generate_report, trivy_compare_scans.

**Deviations from spec**: none
