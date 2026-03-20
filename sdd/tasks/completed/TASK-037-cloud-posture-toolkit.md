# TASK-037: CloudPostureToolkit

**Feature**: Security Toolkits Suite
**Spec**: `sdd/specs/compliancereport-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-035, TASK-036
**Assigned-to**: claude-session

---

## Context

CloudPostureToolkit is the agent-facing toolkit that wraps Prowler. It exposes security scanning capabilities as tools that agents can call. This follows the `AbstractToolkit` pattern where all public async methods become agent tools.

Reference: Spec Section 4.2 (Toolkit) and Section 2 (New Public Interfaces).

---

## Scope

- Implement `parrot/tools/security/cloud_posture_toolkit.py`
- Create `CloudPostureToolkit` extending `AbstractToolkit`
- Implement all tool methods:
  - `prowler_run_scan()` — Full security scan
  - `prowler_compliance_scan()` — Compliance-filtered scan
  - `prowler_scan_service()` — Scan specific service
  - `prowler_list_checks()` — List available checks
  - `prowler_list_services()` — List scannable services
  - `prowler_get_summary()` — Summary of last scan
  - `prowler_get_findings()` — Get findings with filters
  - `prowler_generate_report()` — Generate HTML report
  - `prowler_compare_scans()` — Compare two scan results
- Write unit tests verifying tool exposure

**NOT in scope**:
- Report generation implementation (uses placeholder for now)
- Actual Docker execution (mocked in tests)
- ComplianceReportToolkit (separate task)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/security/cloud_posture_toolkit.py` | CREATE | CloudPostureToolkit class |
| `parrot/tools/security/__init__.py` | MODIFY | Add toolkit export |
| `tests/test_cloud_posture_toolkit.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow

```python
# parrot/tools/security/cloud_posture_toolkit.py
from typing import Optional
from ..toolkit import AbstractToolkit
from .prowler.config import ProwlerConfig
from .prowler.executor import ProwlerExecutor
from .prowler.parser import ProwlerParser
from .models import ScanResult, SecurityFinding, ComparisonDelta


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
            checks: Specific check IDs to run.
            regions: AWS regions to scan.
            severity: Filter by severity — ['critical', 'high', 'medium', 'low'].
            exclude_passing: If True, exclude PASS findings from results.

        Returns:
            ScanResult with normalized findings and summary.
        """
        stdout, stderr, code = await self.executor.run_scan(
            provider=provider,
            services=services,
            checks=checks,
            filter_regions=regions,
            severity=severity,
        )

        if code != 0:
            self.logger.error("Prowler scan failed: %s", stderr)

        result = self.parser.parse(stdout)

        if exclude_passing:
            result.findings = [f for f in result.findings if f.severity != SeverityLevel.PASS]

        self._last_result = result
        return result
```

### Tool Method Signatures

All methods must have comprehensive docstrings (they become tool descriptions for the LLM).

### Key Constraints

- All tool methods must be `async`
- Store `_last_result` for `get_summary()` and `get_findings()` methods
- Use `self.logger` for logging
- Handle executor failures gracefully
- Implement finding filters in `get_findings()` (by severity, service, status)

### References in Codebase

- `parrot/tools/toolkit.py` — AbstractToolkit base class
- `parrot/tools/jiratoolkit.py` — example complex toolkit

---

## Acceptance Criteria

- [ ] `CloudPostureToolkit` extends `AbstractToolkit`
- [ ] All 9 tool methods implemented with proper docstrings
- [ ] `get_tools()` returns list of ToolkitTool instances
- [ ] `_last_result` is stored and used by `get_summary()` and `get_findings()`
- [ ] Finding filters work correctly (severity, service, status)
- [ ] `compare_scans()` produces `ComparisonDelta` with new/resolved/unchanged
- [ ] All tests pass: `pytest tests/test_cloud_posture_toolkit.py -v`
- [ ] Import works: `from parrot.tools.security import CloudPostureToolkit`

---

## Test Specification

```python
# tests/test_cloud_posture_toolkit.py
import pytest
from unittest.mock import AsyncMock, patch
from parrot.tools.security.cloud_posture_toolkit import CloudPostureToolkit
from parrot.tools.security.prowler.config import ProwlerConfig
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
    return CloudPostureToolkit()


@pytest.fixture
def mock_scan_result():
    findings = [
        SecurityFinding(
            id="f1",
            source=FindingSource.PROWLER,
            severity=SeverityLevel.CRITICAL,
            title="Critical Finding",
            service="s3",
        ),
        SecurityFinding(
            id="f2",
            source=FindingSource.PROWLER,
            severity=SeverityLevel.HIGH,
            title="High Finding",
            service="iam",
        ),
        SecurityFinding(
            id="f3",
            source=FindingSource.PROWLER,
            severity=SeverityLevel.PASS,
            title="Passing Check",
            service="s3",
        ),
    ]
    summary = ScanSummary(
        source=FindingSource.PROWLER,
        provider=CloudProvider.AWS,
        total_findings=3,
        critical_count=1,
        high_count=1,
        pass_count=1,
        scan_timestamp=datetime.now(),
    )
    return ScanResult(findings=findings, summary=summary)


class TestToolkitInitialization:
    def test_default_config(self, toolkit):
        """Toolkit initializes with default config."""
        assert toolkit.config.provider == "aws"
        assert toolkit.executor is not None
        assert toolkit.parser is not None

    def test_custom_config(self):
        """Toolkit accepts custom config."""
        config = ProwlerConfig(provider="azure")
        toolkit = CloudPostureToolkit(config=config)
        assert toolkit.config.provider == "azure"


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
            "prowler_run_scan",
            "prowler_compliance_scan",
            "prowler_scan_service",
            "prowler_list_checks",
            "prowler_list_services",
            "prowler_get_summary",
            "prowler_get_findings",
            "prowler_generate_report",
            "prowler_compare_scans",
        ]
        for name in expected:
            assert name in tool_names, f"Missing tool: {name}"

    def test_tools_have_descriptions(self, toolkit):
        """All tools have non-empty descriptions."""
        tools = toolkit.get_tools()
        for tool in tools:
            assert tool.description, f"Tool {tool.name} has no description"


class TestProwlerRunScan:
    @pytest.mark.asyncio
    async def test_run_scan_basic(self, toolkit, mock_scan_result):
        """Basic scan execution."""
        with patch.object(toolkit.executor, 'run_scan', new_callable=AsyncMock) as mock_exec:
            with patch.object(toolkit.parser, 'parse') as mock_parse:
                mock_exec.return_value = ('{"findings": []}', '', 0)
                mock_parse.return_value = mock_scan_result

                result = await toolkit.prowler_run_scan()

                assert result.summary.total_findings == 3
                assert toolkit._last_result == result

    @pytest.mark.asyncio
    async def test_run_scan_exclude_passing(self, toolkit, mock_scan_result):
        """exclude_passing filters PASS findings."""
        with patch.object(toolkit.executor, 'run_scan', new_callable=AsyncMock) as mock_exec:
            with patch.object(toolkit.parser, 'parse') as mock_parse:
                mock_exec.return_value = ('{}', '', 0)
                mock_parse.return_value = mock_scan_result

                result = await toolkit.prowler_run_scan(exclude_passing=True)

                assert all(f.severity != SeverityLevel.PASS for f in result.findings)


class TestGetFindings:
    @pytest.mark.asyncio
    async def test_get_findings_no_filter(self, toolkit, mock_scan_result):
        """get_findings returns all findings when no filter."""
        toolkit._last_result = mock_scan_result
        findings = await toolkit.prowler_get_findings()
        assert len(findings) == 3

    @pytest.mark.asyncio
    async def test_get_findings_by_severity(self, toolkit, mock_scan_result):
        """get_findings filters by severity."""
        toolkit._last_result = mock_scan_result
        findings = await toolkit.prowler_get_findings(severity="CRITICAL")
        assert len(findings) == 1
        assert findings[0].severity == SeverityLevel.CRITICAL

    @pytest.mark.asyncio
    async def test_get_findings_by_service(self, toolkit, mock_scan_result):
        """get_findings filters by service."""
        toolkit._last_result = mock_scan_result
        findings = await toolkit.prowler_get_findings(service="s3")
        assert len(findings) == 2
        assert all(f.service == "s3" for f in findings)

    @pytest.mark.asyncio
    async def test_get_findings_with_limit(self, toolkit, mock_scan_result):
        """get_findings respects limit parameter."""
        toolkit._last_result = mock_scan_result
        findings = await toolkit.prowler_get_findings(limit=1)
        assert len(findings) == 1

    @pytest.mark.asyncio
    async def test_get_findings_no_scan(self, toolkit):
        """get_findings returns empty when no scan run."""
        findings = await toolkit.prowler_get_findings()
        assert findings == []


class TestGetSummary:
    @pytest.mark.asyncio
    async def test_get_summary(self, toolkit, mock_scan_result):
        """get_summary returns last scan summary."""
        toolkit._last_result = mock_scan_result
        summary = await toolkit.prowler_get_summary()
        assert summary["total_findings"] == 3
        assert summary["critical_count"] == 1

    @pytest.mark.asyncio
    async def test_get_summary_no_scan(self, toolkit):
        """get_summary returns empty when no scan run."""
        summary = await toolkit.prowler_get_summary()
        assert summary == {}


class TestCompareScans:
    @pytest.mark.asyncio
    async def test_compare_scans(self, toolkit, tmp_path):
        """compare_scans identifies new and resolved findings."""
        baseline = ScanResult(
            findings=[
                SecurityFinding(id="old-1", source=FindingSource.PROWLER, severity=SeverityLevel.HIGH, title="Old"),
                SecurityFinding(id="same-1", source=FindingSource.PROWLER, severity=SeverityLevel.MEDIUM, title="Same"),
            ],
            summary=ScanSummary(
                source=FindingSource.PROWLER,
                provider=CloudProvider.AWS,
                total_findings=2,
                scan_timestamp=datetime.now(),
            ),
        )
        current = ScanResult(
            findings=[
                SecurityFinding(id="same-1", source=FindingSource.PROWLER, severity=SeverityLevel.MEDIUM, title="Same"),
                SecurityFinding(id="new-1", source=FindingSource.PROWLER, severity=SeverityLevel.CRITICAL, title="New"),
            ],
            summary=ScanSummary(
                source=FindingSource.PROWLER,
                provider=CloudProvider.AWS,
                total_findings=2,
                scan_timestamp=datetime.now(),
            ),
        )

        baseline_path = tmp_path / "baseline.json"
        toolkit.parser.save_result(baseline, str(baseline_path))
        toolkit._last_result = current

        delta = await toolkit.prowler_compare_scans(baseline_path=str(baseline_path))

        assert len(delta.new_findings) == 1
        assert delta.new_findings[0].id == "new-1"
        assert len(delta.resolved_findings) == 1
        assert delta.resolved_findings[0].id == "old-1"
        assert len(delta.unchanged_findings) == 1
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/compliancereport-toolkit.spec.md` Section 4.2
2. **Check dependencies** — TASK-035, TASK-036 must be complete
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-037-cloud-posture-toolkit.md`
7. **Update index** → `"done"`

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-26
**Notes**:
- Implemented CloudPostureToolkit extending AbstractToolkit
- All 9 async tool methods implemented with comprehensive docstrings
- Methods: prowler_run_scan, prowler_compliance_scan, prowler_scan_service, prowler_list_checks, prowler_list_services, prowler_get_summary, prowler_get_findings, prowler_generate_report, prowler_compare_scans
- Finding filters (severity, service, status, limit) working correctly
- compare_scans correctly computes new/resolved/unchanged findings with severity_trend
- 36 tests passing

**Deviations from spec**: Fixed ComparisonDelta usage to match actual model (uses baseline_timestamp/current_timestamp instead of baseline_summary/current_summary)
