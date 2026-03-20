# TASK-048: Integration Tests

**Feature**: Security Toolkits Suite
**Spec**: `sdd/specs/compliancereport-toolkit.spec.md`
**Status**: in-progress
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-037, TASK-040, TASK-043, TASK-046, TASK-047
**Assigned-to**: claude-session

---

## Context

This task creates comprehensive integration tests that verify the end-to-end workflows of the Security Toolkits Suite, including the full consolidated scan workflow with mocked executors.

Reference: Spec Section 4 (Test Specification) and Section 5 (Acceptance Criteria).

---

## Scope

- Create integration test suite: `tests/integration/test_security_toolkits.py`
- Test end-to-end workflows:
  - Prowler scan → parse → findings
  - Trivy image scan → parse → findings
  - Checkov scan → parse → findings
  - Full consolidated scan → report generation
  - Scan comparison (drift detection)
- Use mocked executors with realistic fixture data
- Test error handling and partial failures
- Verify compliance mapping and report generation

**NOT in scope**:
- Actual Docker/CLI execution (use mocks)
- Real cloud account scanning
- Performance benchmarks

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/integration/__init__.py` | CREATE | Package init |
| `tests/integration/test_security_toolkits.py` | CREATE | Integration tests |
| `tests/fixtures/prowler_ocsf_sample.json` | VERIFY | Fixture exists from TASK-036 |
| `tests/fixtures/trivy_image_sample.json` | VERIFY | Fixture exists from TASK-039 |
| `tests/fixtures/checkov_terraform_sample.json` | VERIFY | Fixture exists from TASK-042 |

---

## Implementation Notes

### Test Structure

```python
# tests/integration/test_security_toolkits.py
"""Integration tests for Security Toolkits Suite.

These tests verify end-to-end workflows with mocked executors.
They use realistic fixture data to ensure proper parsing and normalization.
"""
import pytest
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch
from datetime import datetime

from parrot.tools.security import (
    CloudPostureToolkit,
    ContainerSecurityToolkit,
    SecretsIaCToolkit,
    ComplianceReportToolkit,
    SecurityFinding,
    SeverityLevel,
    ComplianceFramework,
)


@pytest.fixture
def fixtures_dir():
    return Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def prowler_output(fixtures_dir):
    return (fixtures_dir / "prowler_ocsf_sample.json").read_text()


@pytest.fixture
def trivy_output(fixtures_dir):
    return (fixtures_dir / "trivy_image_sample.json").read_text()


@pytest.fixture
def checkov_output(fixtures_dir):
    return (fixtures_dir / "checkov_terraform_sample.json").read_text()
```

### Key Test Scenarios

1. **End-to-End Prowler Scan**
   - Mock executor returns fixture data
   - Parser normalizes to SecurityFinding
   - Toolkit stores result correctly
   - Findings can be filtered

2. **End-to-End Trivy Scan**
   - Multiple finding types (vuln, secret, misconfig)
   - All types normalized correctly
   - Secret values are masked

3. **End-to-End Checkov Scan**
   - Passed and failed checks handled
   - Severity derived correctly
   - File path/line info preserved

4. **Consolidated Scan Workflow**
   - All three scanners run in parallel
   - Results aggregated correctly
   - Compliance coverage calculated
   - Report generated

5. **Scan Comparison (Drift Detection)**
   - Baseline vs current comparison
   - New findings identified
   - Resolved findings identified
   - Unchanged findings counted

6. **Partial Failure Handling**
   - One scanner fails, others succeed
   - Available results returned
   - Warning logged

### Key Constraints

- Use `pytest.mark.asyncio` for all async tests
- Load fixture files at runtime (not hardcoded)
- Mock only the executor's `execute()` method
- Verify actual parsing logic, not just mocks

---

## Acceptance Criteria

- [ ] All integration tests pass with mocked executors
- [ ] End-to-end Prowler workflow tested
- [ ] End-to-end Trivy workflow tested
- [ ] End-to-end Checkov workflow tested
- [ ] Consolidated scan workflow tested
- [ ] Scan comparison (drift) tested
- [ ] Partial failure handling tested
- [ ] Report generation produces valid HTML
- [ ] All tests pass: `pytest tests/integration/test_security_toolkits.py -v`

---

## Test Specification

```python
# tests/integration/test_security_toolkits.py
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from datetime import datetime

from parrot.tools.security import (
    CloudPostureToolkit,
    ContainerSecurityToolkit,
    SecretsIaCToolkit,
    ComplianceReportToolkit,
    SecurityFinding,
    SeverityLevel,
    FindingSource,
    ComplianceFramework,
)


@pytest.fixture
def fixtures_dir():
    return Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def prowler_output(fixtures_dir):
    fixture_path = fixtures_dir / "prowler_ocsf_sample.json"
    if fixture_path.exists():
        return fixture_path.read_text()
    # Fallback minimal fixture
    return '[{"finding_info": {"uid": "test", "title": "Test"}, "severity": "High", "status": "FAIL", "resources": []}]'


@pytest.fixture
def trivy_output(fixtures_dir):
    fixture_path = fixtures_dir / "trivy_image_sample.json"
    if fixture_path.exists():
        return fixture_path.read_text()
    return '{"SchemaVersion": 2, "Results": []}'


@pytest.fixture
def checkov_output(fixtures_dir):
    fixture_path = fixtures_dir / "checkov_terraform_sample.json"
    if fixture_path.exists():
        return fixture_path.read_text()
    return '{"check_type": "terraform", "results": {"passed_checks": [], "failed_checks": []}, "summary": {"passed": 0, "failed": 0}}'


class TestProwlerEndToEnd:
    @pytest.mark.asyncio
    async def test_prowler_scan_workflow(self, prowler_output):
        """End-to-end Prowler scan with fixture data."""
        toolkit = CloudPostureToolkit()

        with patch.object(toolkit.executor, 'execute', new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = (prowler_output, '', 0)

            result = await toolkit.prowler_run_scan(provider="aws")

            assert result.summary.total_findings > 0
            assert all(f.source == FindingSource.PROWLER for f in result.findings)
            assert toolkit._last_result == result

    @pytest.mark.asyncio
    async def test_prowler_findings_filter(self, prowler_output):
        """Findings can be filtered by severity and service."""
        toolkit = CloudPostureToolkit()

        with patch.object(toolkit.executor, 'execute', new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = (prowler_output, '', 0)

            await toolkit.prowler_run_scan()
            high_findings = await toolkit.prowler_get_findings(severity="HIGH")

            assert all(f.severity == SeverityLevel.HIGH for f in high_findings)


class TestTrivyEndToEnd:
    @pytest.mark.asyncio
    async def test_trivy_image_scan_workflow(self, trivy_output):
        """End-to-end Trivy image scan with fixture data."""
        toolkit = ContainerSecurityToolkit()

        with patch.object(toolkit.executor, 'scan_image', new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = (trivy_output, '', 0)

            result = await toolkit.trivy_scan_image(image="nginx:latest")

            assert result is not None
            assert all(f.source == FindingSource.TRIVY for f in result.findings)

    @pytest.mark.asyncio
    async def test_trivy_handles_multiple_finding_types(self, trivy_output):
        """Trivy parser handles vulns, secrets, and misconfigs."""
        toolkit = ContainerSecurityToolkit()

        with patch.object(toolkit.executor, 'scan_image', new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = (trivy_output, '', 0)

            result = await toolkit.trivy_scan_image(image="test:latest")

            # Should have various resource_types
            resource_types = {f.resource_type for f in result.findings}
            # At minimum we should have parsed something
            assert result.summary is not None


class TestCheckovEndToEnd:
    @pytest.mark.asyncio
    async def test_checkov_scan_workflow(self, checkov_output):
        """End-to-end Checkov scan with fixture data."""
        toolkit = SecretsIaCToolkit()

        with patch.object(toolkit.executor, 'scan_directory', new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = (checkov_output, '', 0)

            result = await toolkit.checkov_scan_directory(path="/app/terraform")

            assert result is not None
            assert all(f.source == FindingSource.CHECKOV for f in result.findings)

    @pytest.mark.asyncio
    async def test_checkov_preserves_file_info(self, checkov_output):
        """Checkov findings include file path and line info."""
        toolkit = SecretsIaCToolkit()

        with patch.object(toolkit.executor, 'scan_directory', new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = (checkov_output, '', 0)

            result = await toolkit.checkov_scan_directory(path="/app")

            # Check that file info is in description
            for finding in result.findings:
                if finding.severity != SeverityLevel.PASS:
                    # Failed checks should have file info
                    assert finding.description or finding.resource


class TestConsolidatedScanWorkflow:
    @pytest.mark.asyncio
    async def test_full_consolidated_scan(self, prowler_output, trivy_output, checkov_output):
        """Full consolidated scan across all scanners."""
        toolkit = ComplianceReportToolkit()

        with patch.object(toolkit.prowler_executor, 'execute', new_callable=AsyncMock) as mock_prowler:
            with patch.object(toolkit.trivy_executor, 'scan_image', new_callable=AsyncMock) as mock_trivy:
                with patch.object(toolkit.checkov_executor, 'scan_directory', new_callable=AsyncMock) as mock_checkov:
                    mock_prowler.return_value = (prowler_output, '', 0)
                    mock_trivy.return_value = (trivy_output, '', 0)
                    mock_checkov.return_value = (checkov_output, '', 0)

                    result = await toolkit.compliance_full_scan(
                        provider="aws",
                        target_image="nginx:latest",
                        iac_path="/app/terraform",
                    )

                    # Should have results from multiple scanners
                    assert result.total_findings > 0
                    assert len(result.scan_results) >= 1
                    assert result.compliance_coverage is not None

    @pytest.mark.asyncio
    async def test_consolidated_scan_parallel_execution(self, prowler_output, trivy_output):
        """Scanners execute in parallel."""
        toolkit = ComplianceReportToolkit()
        execution_order = []

        async def mock_prowler_exec(*args, **kwargs):
            execution_order.append(('prowler_start', datetime.now()))
            await asyncio.sleep(0.1)
            execution_order.append(('prowler_end', datetime.now()))
            return (prowler_output, '', 0)

        async def mock_trivy_exec(*args, **kwargs):
            execution_order.append(('trivy_start', datetime.now()))
            await asyncio.sleep(0.1)
            execution_order.append(('trivy_end', datetime.now()))
            return (trivy_output, '', 0)

        with patch.object(toolkit.prowler_executor, 'execute', side_effect=mock_prowler_exec):
            with patch.object(toolkit.trivy_executor, 'scan_image', side_effect=mock_trivy_exec):
                await toolkit.compliance_full_scan(
                    provider="aws",
                    target_image="nginx:latest",
                )

                # Both should have started before either finished
                starts = [e for e in execution_order if 'start' in e[0]]
                ends = [e for e in execution_order if 'end' in e[0]]
                if len(starts) == 2:
                    assert starts[1][1] < ends[0][1]  # Second start before first end


class TestPartialFailureHandling:
    @pytest.mark.asyncio
    async def test_partial_failure_continues(self, prowler_output):
        """Partial scanner failure doesn't abort entire scan."""
        toolkit = ComplianceReportToolkit()

        with patch.object(toolkit.prowler_executor, 'execute', new_callable=AsyncMock) as mock_prowler:
            with patch.object(toolkit.trivy_executor, 'scan_image', new_callable=AsyncMock) as mock_trivy:
                mock_prowler.return_value = (prowler_output, '', 0)
                mock_trivy.side_effect = Exception("Trivy connection failed")

                result = await toolkit.compliance_full_scan(
                    provider="aws",
                    target_image="nginx:latest",
                )

                # Should have Prowler results
                assert "prowler" in result.scan_results
                # Should not have Trivy results (but shouldn't crash)
                assert result.total_findings > 0


class TestScanComparison:
    @pytest.mark.asyncio
    async def test_scan_drift_detection(self, prowler_output, tmp_path):
        """Scan comparison detects new, resolved, and unchanged findings."""
        toolkit = CloudPostureToolkit()

        # Create baseline
        with patch.object(toolkit.executor, 'execute', new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = (prowler_output, '', 0)
            baseline = await toolkit.prowler_run_scan()

        # Save baseline
        baseline_path = tmp_path / "baseline.json"
        toolkit.parser.save_result(baseline, str(baseline_path))

        # Simulate different current scan (modify one finding)
        import json
        current_data = json.loads(prowler_output)
        if isinstance(current_data, list) and len(current_data) > 0:
            # Add a new finding
            new_finding = current_data[0].copy()
            new_finding['finding_info'] = {'uid': 'new-finding-123', 'title': 'New Issue'}
            current_data.append(new_finding)

        with patch.object(toolkit.executor, 'execute', new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = (json.dumps(current_data), '', 0)
            await toolkit.prowler_run_scan()

        delta = await toolkit.prowler_compare_scans(baseline_path=str(baseline_path))

        # Should detect the new finding
        assert delta is not None
        assert isinstance(delta.new_findings, list)
        assert isinstance(delta.resolved_findings, list)


class TestReportGeneration:
    @pytest.mark.asyncio
    async def test_soc2_report_generation(self, prowler_output, tmp_path):
        """SOC2 report generates valid HTML."""
        toolkit = ComplianceReportToolkit(report_output_dir=str(tmp_path))

        with patch.object(toolkit.prowler_executor, 'execute', new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = (prowler_output, '', 0)

            await toolkit.compliance_full_scan(provider="aws")
            report_path = await toolkit.compliance_soc2_report()

            assert Path(report_path).exists()
            content = Path(report_path).read_text()
            assert "<html" in content.lower()
            assert "soc2" in content.lower()

    @pytest.mark.asyncio
    async def test_executive_summary_structure(self, prowler_output):
        """Executive summary returns expected structure."""
        toolkit = ComplianceReportToolkit()

        with patch.object(toolkit.prowler_executor, 'execute', new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = (prowler_output, '', 0)

            await toolkit.compliance_full_scan(provider="aws")
            summary = await toolkit.compliance_executive_summary()

            assert isinstance(summary, dict)
            # Should have key metrics
            assert 'total_findings' in summary or 'critical_findings_count' in summary


class TestComplianceGaps:
    @pytest.mark.asyncio
    async def test_compliance_gaps_identified(self, prowler_output):
        """Compliance gaps are identified per framework."""
        toolkit = ComplianceReportToolkit()

        with patch.object(toolkit.prowler_executor, 'execute', new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = (prowler_output, '', 0)

            await toolkit.compliance_full_scan(provider="aws")
            gaps = await toolkit.compliance_get_gaps(framework="soc2")

            assert isinstance(gaps, list)
            # Each gap should have control info
            for gap in gaps:
                assert 'control_id' in gap or 'status' in gap


class TestRemediationPlan:
    @pytest.mark.asyncio
    async def test_remediation_plan_prioritized(self, prowler_output):
        """Remediation plan is prioritized by severity."""
        toolkit = ComplianceReportToolkit()

        with patch.object(toolkit.prowler_executor, 'execute', new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = (prowler_output, '', 0)

            await toolkit.compliance_full_scan(provider="aws")
            plan = await toolkit.compliance_get_remediation_plan(
                max_items=10,
                severity_filter=["CRITICAL", "HIGH"],
            )

            assert isinstance(plan, list)
            # Critical should come before high
            severities = [item.get('finding', {}).get('severity') or item.get('severity') for item in plan if item]
            # Plan should be sorted by priority
```

---

## Agent Instructions

When you pick up this task:

1. **Check dependencies** — All toolkit tasks must be complete
2. **Verify fixtures exist** from prior tasks
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Create tests/integration/ directory**
5. **Implement** all test scenarios
6. **Run tests** to verify they pass with mocked data
7. **Verify** all acceptance criteria are met
8. **Move this file** to `sdd/tasks/completed/TASK-048-integration-tests.md`
9. **Update index** → `"done"`

---

## Completion Note

**Completed by**: Claude (claude-session)
**Date**: 2026-02-26
**Notes**: Created comprehensive integration test suite with 35 tests covering:
- End-to-end Prowler workflows (5 tests)
- End-to-end Trivy workflows (4 tests)
- End-to-end Checkov workflows (4 tests)
- Consolidated scan workflows (3 tests)
- Partial failure handling (2 tests)
- Scan comparison / drift detection (2 tests)
- Report generation (4 tests)
- Compliance gap analysis (1 test)
- Remediation plan generation (2 tests)
- Toolkit instantiation with configs (4 tests)
- Toolkit tool exposure (4 tests)

All tests pass with mocked executors and realistic fixture data.

**Deviations from spec**: Minor test adjustments to match actual toolkit method signatures (e.g., `run_scan` vs `execute` for ProwlerExecutor)
