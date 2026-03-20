# TASK-046: ComplianceReportToolkit

**Feature**: Security Toolkits Suite
**Spec**: `sdd/specs/compliancereport-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-035, TASK-036, TASK-038, TASK-039, TASK-041, TASK-042, TASK-044, TASK-045
**Assigned-to**: claude-session

---

## Context

ComplianceReportToolkit is the aggregation layer that orchestrates all three scanners (Prowler, Trivy, Checkov) and produces unified compliance reports. It uses the underlying executors and parsers directly (not the individual toolkits) to avoid circular dependencies.

Reference: Spec Section 7 (Toolkit #4: ComplianceReportToolkit).

---

## Scope

- Implement `parrot/tools/security/compliance_report_toolkit.py`
- Create `ComplianceReportToolkit` extending `AbstractToolkit`
- Implement all tool methods:
  - `compliance_full_scan()` — Run all scanners and consolidate
  - `compliance_soc2_report()` — SOC2 compliance report
  - `compliance_hipaa_report()` — HIPAA compliance report
  - `compliance_pci_report()` — PCI-DSS compliance report
  - `compliance_custom_report()` — Report for any framework
  - `compliance_executive_summary()` — High-level summary
  - `compliance_get_gaps()` — Compliance gaps per framework
  - `compliance_get_remediation_plan()` — Prioritized remediation
  - `compliance_compare_reports()` — Compare two reports
  - `compliance_export_findings()` — Export to CSV/JSON
- Run scans in parallel with `asyncio.gather()`
- Handle partial failures gracefully
- Write comprehensive unit tests

**NOT in scope**:
- Actual Docker execution (mocked in tests)
- Full compliance mapping coverage (use existing mappings)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/security/compliance_report_toolkit.py` | CREATE | ComplianceReportToolkit class |
| `parrot/tools/security/__init__.py` | MODIFY | Add toolkit export |
| `tests/test_compliance_report_toolkit.py` | CREATE | Unit tests |

---

## Implementation Notes

### Key Design: Direct Executor Composition

```python
# CORRECT: ComplianceReportToolkit composes executors directly
class ComplianceReportToolkit(AbstractToolkit):
    def __init__(
        self,
        prowler_config: ProwlerConfig | None = None,
        trivy_config: TrivyConfig | None = None,
        checkov_config: CheckovConfig | None = None,
        report_output_dir: str = "/tmp/security-reports",
        **kwargs,
    ):
        super().__init__(**kwargs)
        # Direct executor/parser composition
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

# WRONG: Do not depend on other toolkits
# self.prowler_toolkit = CloudPostureToolkit(...)  # Creates circular deps
```

### Parallel Scan Execution

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
    """Run comprehensive security scan across all configured scanners."""

    # Build scan tasks
    tasks = []
    task_names = []

    # Always run Prowler for cloud posture
    tasks.append(self._run_prowler_scan(provider, regions, framework))
    task_names.append("prowler")

    # Optionally run Trivy for container/k8s
    if target_image:
        tasks.append(self._run_trivy_image_scan(target_image))
        task_names.append("trivy_image")
    if k8s_context:
        tasks.append(self._run_trivy_k8s_scan(k8s_context))
        task_names.append("trivy_k8s")

    # Optionally run Checkov for IaC
    if iac_path:
        tasks.append(self._run_checkov_scan(iac_path))
        task_names.append("checkov")

    # Run all scans in parallel
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Process results, handling partial failures
    scan_results = {}
    for name, result in zip(task_names, results):
        if isinstance(result, Exception):
            self.logger.warning("Scanner %s failed: %s", name, result)
        else:
            scan_results[name] = result

    return self._consolidate_results(scan_results)
```

### Consolidation Logic

```python
def _consolidate_results(self, scan_results: dict[str, ScanResult]) -> ConsolidatedReport:
    """Consolidate multiple scan results into unified report."""
    all_findings = []
    severity_counts = defaultdict(int)
    service_counts = defaultdict(int)

    for scanner_name, result in scan_results.items():
        all_findings.extend(result.findings)
        for finding in result.findings:
            severity_counts[finding.severity.value] += 1
            if finding.service:
                service_counts[finding.service] += 1

    # Calculate compliance coverage for each framework
    compliance_coverage = {}
    for framework in ComplianceFramework:
        coverage = self.compliance_mapper.get_framework_coverage(all_findings, framework)
        compliance_coverage[framework.value] = coverage

    return ConsolidatedReport(
        scan_results=scan_results,
        total_findings=len(all_findings),
        findings_by_severity=dict(severity_counts),
        findings_by_service=dict(service_counts),
        compliance_coverage=compliance_coverage,
        generated_at=datetime.now(),
    )
```

### Key Constraints

- All scanner executions must be parallel (`asyncio.gather`)
- Partial failures must not abort entire scan — return available data
- Log warnings for failed scanners
- Store `_last_consolidated` for subsequent queries
- Remediation plan should prioritize by severity and compliance impact

---

## Acceptance Criteria

- [ ] `ComplianceReportToolkit` uses executors/parsers directly (not other toolkits)
- [ ] `compliance_full_scan()` runs available scanners in parallel
- [ ] Partial failures are handled gracefully (continue with available results)
- [ ] All 10 tool methods implemented with proper docstrings
- [ ] `compliance_executive_summary()` returns structured summary dict
- [ ] `compliance_get_remediation_plan()` returns prioritized list
- [ ] All tests pass: `pytest tests/test_compliance_report_toolkit.py -v`
- [ ] Import works: `from parrot.tools.security import ComplianceReportToolkit`

---

## Test Specification

```python
# tests/test_compliance_report_toolkit.py
import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime
from parrot.tools.security.compliance_report_toolkit import ComplianceReportToolkit
from parrot.tools.security.models import (
    ConsolidatedReport,
    ScanResult,
    ScanSummary,
    SecurityFinding,
    FindingSource,
    SeverityLevel,
    CloudProvider,
    ComplianceFramework,
)


@pytest.fixture
def toolkit():
    return ComplianceReportToolkit()


@pytest.fixture
def mock_prowler_result():
    findings = [
        SecurityFinding(
            id="p1",
            source=FindingSource.PROWLER,
            severity=SeverityLevel.CRITICAL,
            title="IAM Root MFA Disabled",
            service="iam",
        ),
    ]
    return ScanResult(
        findings=findings,
        summary=ScanSummary(
            source=FindingSource.PROWLER,
            provider=CloudProvider.AWS,
            total_findings=1,
            critical_count=1,
            scan_timestamp=datetime.now(),
        ),
    )


@pytest.fixture
def mock_trivy_result():
    findings = [
        SecurityFinding(
            id="CVE-2023-1234",
            source=FindingSource.TRIVY,
            severity=SeverityLevel.HIGH,
            title="Critical CVE in nginx",
            service="container",
        ),
    ]
    return ScanResult(
        findings=findings,
        summary=ScanSummary(
            source=FindingSource.TRIVY,
            provider=CloudProvider.LOCAL,
            total_findings=1,
            high_count=1,
            scan_timestamp=datetime.now(),
        ),
    )


@pytest.fixture
def mock_checkov_result():
    findings = [
        SecurityFinding(
            id="CKV_AWS_21",
            source=FindingSource.CHECKOV,
            severity=SeverityLevel.MEDIUM,
            title="S3 Versioning Disabled",
            service="s3",
        ),
    ]
    return ScanResult(
        findings=findings,
        summary=ScanSummary(
            source=FindingSource.CHECKOV,
            provider=CloudProvider.LOCAL,
            total_findings=1,
            medium_count=1,
            scan_timestamp=datetime.now(),
        ),
    )


class TestToolkitInitialization:
    def test_uses_executors_directly(self, toolkit):
        """Toolkit composes executors directly, not other toolkits."""
        assert hasattr(toolkit, 'prowler_executor')
        assert hasattr(toolkit, 'trivy_executor')
        assert hasattr(toolkit, 'checkov_executor')
        assert hasattr(toolkit, 'prowler_parser')
        assert hasattr(toolkit, 'report_generator')
        assert hasattr(toolkit, 'compliance_mapper')


class TestToolExposure:
    def test_all_methods_exposed(self, toolkit):
        """All public async methods are exposed as tools."""
        tool_names = toolkit.list_tool_names()
        expected = [
            "compliance_full_scan",
            "compliance_soc2_report",
            "compliance_hipaa_report",
            "compliance_pci_report",
            "compliance_custom_report",
            "compliance_executive_summary",
            "compliance_get_gaps",
            "compliance_get_remediation_plan",
            "compliance_compare_reports",
            "compliance_export_findings",
        ]
        for name in expected:
            assert name in tool_names, f"Missing tool: {name}"


class TestComplianceFullScan:
    @pytest.mark.asyncio
    async def test_full_scan_parallel_execution(
        self, toolkit, mock_prowler_result, mock_trivy_result, mock_checkov_result
    ):
        """Full scan runs scanners in parallel."""
        with patch.object(toolkit, '_run_prowler_scan', new_callable=AsyncMock) as mock_prowler:
            with patch.object(toolkit, '_run_trivy_image_scan', new_callable=AsyncMock) as mock_trivy:
                with patch.object(toolkit, '_run_checkov_scan', new_callable=AsyncMock) as mock_checkov:
                    mock_prowler.return_value = mock_prowler_result
                    mock_trivy.return_value = mock_trivy_result
                    mock_checkov.return_value = mock_checkov_result

                    result = await toolkit.compliance_full_scan(
                        provider="aws",
                        target_image="nginx:latest",
                        iac_path="/app/terraform",
                    )

                    assert result.total_findings == 3
                    assert "prowler" in result.scan_results
                    assert toolkit._last_consolidated == result

    @pytest.mark.asyncio
    async def test_full_scan_handles_partial_failure(
        self, toolkit, mock_prowler_result
    ):
        """Full scan continues with available results on partial failure."""
        with patch.object(toolkit, '_run_prowler_scan', new_callable=AsyncMock) as mock_prowler:
            with patch.object(toolkit, '_run_trivy_image_scan', new_callable=AsyncMock) as mock_trivy:
                mock_prowler.return_value = mock_prowler_result
                mock_trivy.side_effect = Exception("Trivy failed")

                result = await toolkit.compliance_full_scan(
                    provider="aws",
                    target_image="nginx:latest",
                )

                # Should have Prowler results, not Trivy
                assert "prowler" in result.scan_results
                assert "trivy_image" not in result.scan_results
                assert result.total_findings == 1


class TestConsolidation:
    def test_consolidate_results(self, toolkit, mock_prowler_result, mock_trivy_result):
        """Consolidation aggregates findings correctly."""
        scan_results = {
            "prowler": mock_prowler_result,
            "trivy": mock_trivy_result,
        }
        report = toolkit._consolidate_results(scan_results)

        assert report.total_findings == 2
        assert report.findings_by_severity["CRITICAL"] == 1
        assert report.findings_by_severity["HIGH"] == 1


class TestComplianceReports:
    @pytest.mark.asyncio
    async def test_soc2_report(self, toolkit, mock_prowler_result):
        """Generates SOC2 compliance report."""
        toolkit._last_consolidated = ConsolidatedReport(
            scan_results={"prowler": mock_prowler_result},
            total_findings=1,
            generated_at=datetime.now(),
        )

        with patch.object(toolkit.report_generator, 'generate_compliance_report', new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = "/tmp/soc2_report.html"

            path = await toolkit.compliance_soc2_report(provider="aws")

            assert path == "/tmp/soc2_report.html"
            mock_gen.assert_called_once()


class TestExecutiveSummary:
    @pytest.mark.asyncio
    async def test_executive_summary_structure(self, toolkit, mock_prowler_result):
        """Executive summary returns expected structure."""
        toolkit._last_consolidated = ConsolidatedReport(
            scan_results={"prowler": mock_prowler_result},
            total_findings=1,
            findings_by_severity={"CRITICAL": 1},
            compliance_coverage={"soc2": {"coverage_pct": 75}},
            generated_at=datetime.now(),
        )

        summary = await toolkit.compliance_executive_summary()

        assert "overall_risk_score" in summary or "total_findings" in summary
        assert "critical_findings_count" in summary or "findings_by_severity" in summary


class TestRemediationPlan:
    @pytest.mark.asyncio
    async def test_remediation_plan_prioritized(self, toolkit):
        """Remediation plan is prioritized by severity."""
        findings = [
            SecurityFinding(id="low", source=FindingSource.PROWLER, severity=SeverityLevel.LOW, title="Low"),
            SecurityFinding(id="crit", source=FindingSource.PROWLER, severity=SeverityLevel.CRITICAL, title="Critical"),
            SecurityFinding(id="high", source=FindingSource.PROWLER, severity=SeverityLevel.HIGH, title="High"),
        ]
        toolkit._last_consolidated = ConsolidatedReport(
            scan_results={"prowler": ScanResult(
                findings=findings,
                summary=ScanSummary(
                    source=FindingSource.PROWLER,
                    provider=CloudProvider.AWS,
                    total_findings=3,
                    scan_timestamp=datetime.now(),
                ),
            )},
            total_findings=3,
            generated_at=datetime.now(),
        )

        plan = await toolkit.compliance_get_remediation_plan(max_items=3)

        assert len(plan) <= 3
        # Critical should be first
        assert plan[0]["finding"].severity == SeverityLevel.CRITICAL
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/compliancereport-toolkit.spec.md` Section 7
2. **Check ALL dependencies** — This task has many dependencies
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Key design**: Use executors directly, not other toolkits
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-046-compliance-report-toolkit.md`
8. **Update index** → `"done"`

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-26
**Notes**: Implemented ComplianceReportToolkit with all 10 tool methods. Uses executors/parsers directly (not other toolkits). Runs scans in parallel with asyncio.gather(). Handles partial failures gracefully. All 31 tests passing.

**Deviations from spec**: none - implementation matches spec exactly.
