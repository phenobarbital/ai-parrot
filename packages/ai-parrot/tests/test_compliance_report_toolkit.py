"""Unit tests for the ComplianceReportToolkit."""

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from parrot.tools.security.compliance_report_toolkit import ComplianceReportToolkit
from parrot.tools.security.models import (
    CloudProvider,
    ComparisonDelta,
    ComplianceFramework,
    ConsolidatedReport,
    FindingSource,
    ScanResult,
    ScanSummary,
    SecurityFinding,
    SeverityLevel,
)


@pytest.fixture
def toolkit():
    """Create a toolkit instance for testing."""
    return ComplianceReportToolkit()


@pytest.fixture
def mock_prowler_result():
    """Create sample Prowler scan result."""
    findings = [
        SecurityFinding(
            id="prowler-001",
            source=FindingSource.PROWLER,
            severity=SeverityLevel.CRITICAL,
            title="IAM Root MFA Disabled",
            description="Root account does not have MFA enabled",
            service="iam",
            resource="arn:aws:iam::123456789:root",
            remediation="Enable MFA for the root account",
        ),
        SecurityFinding(
            id="prowler-002",
            source=FindingSource.PROWLER,
            severity=SeverityLevel.HIGH,
            title="S3 Bucket Public Access",
            description="S3 bucket allows public access",
            service="s3",
            resource="arn:aws:s3:::my-bucket",
        ),
        SecurityFinding(
            id="prowler-003",
            source=FindingSource.PROWLER,
            severity=SeverityLevel.PASS,
            title="S3 Encryption Enabled",
            description="S3 bucket has encryption",
            service="s3",
        ),
    ]
    return ScanResult(
        findings=findings,
        summary=ScanSummary(
            source=FindingSource.PROWLER,
            provider=CloudProvider.AWS,
            total_findings=3,
            critical_count=1,
            high_count=1,
            pass_count=1,
            scan_timestamp=datetime.now(),
        ),
    )


@pytest.fixture
def mock_trivy_result():
    """Create sample Trivy scan result."""
    findings = [
        SecurityFinding(
            id="CVE-2023-1234",
            source=FindingSource.TRIVY,
            severity=SeverityLevel.HIGH,
            title="Critical CVE in nginx",
            description="Buffer overflow vulnerability",
            service="container",
            resource="nginx:latest",
            resource_type="vulnerability",
        ),
        SecurityFinding(
            id="CVE-2023-5678",
            source=FindingSource.TRIVY,
            severity=SeverityLevel.MEDIUM,
            title="Medium CVE in openssl",
            description="Information disclosure",
            service="container",
            resource="nginx:latest",
        ),
    ]
    return ScanResult(
        findings=findings,
        summary=ScanSummary(
            source=FindingSource.TRIVY,
            provider=CloudProvider.LOCAL,
            total_findings=2,
            high_count=1,
            medium_count=1,
            scan_timestamp=datetime.now(),
        ),
    )


@pytest.fixture
def mock_checkov_result():
    """Create sample Checkov scan result."""
    findings = [
        SecurityFinding(
            id="CKV_AWS_21",
            source=FindingSource.CHECKOV,
            severity=SeverityLevel.MEDIUM,
            title="S3 Versioning Disabled",
            description="S3 bucket does not have versioning enabled",
            service="s3",
            resource="aws_s3_bucket.data",
            check_id="CKV_AWS_21",
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


@pytest.fixture
def mock_consolidated(mock_prowler_result, mock_trivy_result, mock_checkov_result):
    """Create a sample consolidated report."""
    return ConsolidatedReport(
        scan_results={
            "prowler": mock_prowler_result,
            "trivy_image": mock_trivy_result,
            "checkov": mock_checkov_result,
        },
        total_findings=6,
        findings_by_severity={
            "CRITICAL": 1,
            "HIGH": 2,
            "MEDIUM": 2,
            "PASS": 1,
        },
        findings_by_service={
            "iam": 1,
            "s3": 3,
            "container": 2,
        },
        compliance_coverage={
            "soc2": {"coverage_pct": 75, "checked_controls": 15, "passed_controls": 10},
            "hipaa": {"coverage_pct": 60, "checked_controls": 10, "passed_controls": 6},
            "pci_dss": {"coverage_pct": 80, "checked_controls": 20, "passed_controls": 16},
        },
        generated_at=datetime.now(),
    )


class TestToolkitInitialization:
    """Test toolkit initialization."""

    def test_uses_executors_directly(self, toolkit):
        """Toolkit composes executors directly, not other toolkits."""
        assert hasattr(toolkit, "prowler_executor")
        assert hasattr(toolkit, "prowler_parser")
        assert hasattr(toolkit, "trivy_executor")
        assert hasattr(toolkit, "trivy_parser")
        assert hasattr(toolkit, "checkov_executor")
        assert hasattr(toolkit, "checkov_parser")
        assert hasattr(toolkit, "report_generator")
        assert hasattr(toolkit, "compliance_mapper")

    def test_has_name_and_description(self, toolkit):
        """Toolkit has proper name and description."""
        assert toolkit.name == "compliance_report"
        assert "compliance" in toolkit.description.lower()

    def test_no_initial_state(self, toolkit):
        """Toolkit starts with no consolidated report."""
        assert toolkit._last_consolidated is None
        assert toolkit._report_history == []


class TestToolExposure:
    """Test that all methods are exposed as tools."""

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
    """Test the compliance_full_scan method."""

    @pytest.mark.asyncio
    async def test_full_scan_parallel_execution(
        self, toolkit, mock_prowler_result, mock_trivy_result, mock_checkov_result
    ):
        """Full scan runs scanners in parallel."""
        with patch.object(
            toolkit, "_run_prowler_scan", new_callable=AsyncMock
        ) as mock_prowler:
            with patch.object(
                toolkit, "_run_trivy_image_scan", new_callable=AsyncMock
            ) as mock_trivy:
                with patch.object(
                    toolkit, "_run_checkov_scan", new_callable=AsyncMock
                ) as mock_checkov:
                    mock_prowler.return_value = mock_prowler_result
                    mock_trivy.return_value = mock_trivy_result
                    mock_checkov.return_value = mock_checkov_result

                    result = await toolkit.compliance_full_scan(
                        provider="aws",
                        target_image="nginx:latest",
                        iac_path="/app/terraform",
                    )

                    assert result.total_findings == 6
                    assert "prowler" in result.scan_results
                    assert "trivy_image" in result.scan_results
                    assert "checkov" in result.scan_results
                    assert toolkit._last_consolidated == result

    @pytest.mark.asyncio
    async def test_full_scan_handles_partial_failure(
        self, toolkit, mock_prowler_result
    ):
        """Full scan continues with available results on partial failure."""
        with patch.object(
            toolkit, "_run_prowler_scan", new_callable=AsyncMock
        ) as mock_prowler:
            with patch.object(
                toolkit, "_run_trivy_image_scan", new_callable=AsyncMock
            ) as mock_trivy:
                mock_prowler.return_value = mock_prowler_result
                mock_trivy.side_effect = Exception("Trivy failed")

                result = await toolkit.compliance_full_scan(
                    provider="aws",
                    target_image="nginx:latest",
                )

                # Should have Prowler results, not Trivy
                assert "prowler" in result.scan_results
                assert "trivy_image" not in result.scan_results
                assert result.total_findings == 3

    @pytest.mark.asyncio
    async def test_full_scan_prowler_only(self, toolkit, mock_prowler_result):
        """Full scan runs only Prowler when no optional targets specified."""
        with patch.object(
            toolkit, "_run_prowler_scan", new_callable=AsyncMock
        ) as mock_prowler:
            mock_prowler.return_value = mock_prowler_result

            result = await toolkit.compliance_full_scan(provider="aws")

            assert "prowler" in result.scan_results
            assert len(result.scan_results) == 1

    @pytest.mark.asyncio
    async def test_full_scan_stores_history(self, toolkit, mock_prowler_result):
        """Full scan stores results in history."""
        with patch.object(
            toolkit, "_run_prowler_scan", new_callable=AsyncMock
        ) as mock_prowler:
            mock_prowler.return_value = mock_prowler_result

            await toolkit.compliance_full_scan(provider="aws")
            await toolkit.compliance_full_scan(provider="aws")

            assert len(toolkit._report_history) == 2


class TestConsolidation:
    """Test result consolidation logic."""

    def test_consolidate_results(
        self, toolkit, mock_prowler_result, mock_trivy_result
    ):
        """Consolidation aggregates findings correctly."""
        scan_results = {
            "prowler": mock_prowler_result,
            "trivy": mock_trivy_result,
        }
        report = toolkit._consolidate_results(scan_results)

        assert report.total_findings == 5
        assert report.findings_by_severity["CRITICAL"] == 1
        assert report.findings_by_severity["HIGH"] == 2
        assert report.findings_by_severity["MEDIUM"] == 1
        assert report.findings_by_severity["PASS"] == 1

    def test_consolidate_empty_results(self, toolkit):
        """Consolidation handles empty results."""
        report = toolkit._consolidate_results({})
        assert report.total_findings == 0


class TestComplianceReports:
    """Test compliance report generation."""

    @pytest.mark.asyncio
    async def test_soc2_report(self, toolkit, mock_consolidated, tmp_path):
        """Generates SOC2 compliance report."""
        toolkit._last_consolidated = mock_consolidated

        with patch.object(
            toolkit.report_generator,
            "generate_compliance_report",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_gen.return_value = str(tmp_path / "soc2_report.html")

            path = await toolkit.compliance_soc2_report(provider="aws")

            assert path.endswith(".html")
            mock_gen.assert_called_once()
            args = mock_gen.call_args
            assert args[0][1] == ComplianceFramework.SOC2

    @pytest.mark.asyncio
    async def test_hipaa_report(self, toolkit, mock_consolidated, tmp_path):
        """Generates HIPAA compliance report."""
        toolkit._last_consolidated = mock_consolidated

        with patch.object(
            toolkit.report_generator,
            "generate_compliance_report",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_gen.return_value = str(tmp_path / "hipaa_report.html")

            path = await toolkit.compliance_hipaa_report(provider="aws")

            assert path.endswith(".html")
            args = mock_gen.call_args
            assert args[0][1] == ComplianceFramework.HIPAA

    @pytest.mark.asyncio
    async def test_pci_report(self, toolkit, mock_consolidated, tmp_path):
        """Generates PCI-DSS compliance report."""
        toolkit._last_consolidated = mock_consolidated

        with patch.object(
            toolkit.report_generator,
            "generate_compliance_report",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_gen.return_value = str(tmp_path / "pci_report.html")

            path = await toolkit.compliance_pci_report(provider="aws")

            assert path.endswith(".html")
            args = mock_gen.call_args
            assert args[0][1] == ComplianceFramework.PCI_DSS

    @pytest.mark.asyncio
    async def test_custom_report_valid_framework(
        self, toolkit, mock_consolidated, tmp_path
    ):
        """Custom report accepts valid framework string."""
        toolkit._last_consolidated = mock_consolidated

        with patch.object(
            toolkit.report_generator,
            "generate_compliance_report",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_gen.return_value = str(tmp_path / "custom_report.html")

            await toolkit.compliance_custom_report(framework="hipaa")

            args = mock_gen.call_args
            assert args[0][1] == ComplianceFramework.HIPAA

    @pytest.mark.asyncio
    async def test_custom_report_invalid_framework(
        self, toolkit, mock_consolidated, tmp_path
    ):
        """Custom report defaults to SOC2 for invalid framework."""
        toolkit._last_consolidated = mock_consolidated

        with patch.object(
            toolkit.report_generator,
            "generate_compliance_report",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_gen.return_value = str(tmp_path / "report.html")

            await toolkit.compliance_custom_report(framework="invalid")

            args = mock_gen.call_args
            assert args[0][1] == ComplianceFramework.SOC2

    @pytest.mark.asyncio
    async def test_report_runs_scan_if_none(self, toolkit, mock_prowler_result, tmp_path):
        """Report generation triggers scan if no existing data."""
        with patch.object(
            toolkit, "_run_prowler_scan", new_callable=AsyncMock
        ) as mock_prowler:
            with patch.object(
                toolkit.report_generator,
                "generate_compliance_report",
                new_callable=AsyncMock,
            ) as mock_gen:
                mock_prowler.return_value = mock_prowler_result
                mock_gen.return_value = str(tmp_path / "report.html")

                await toolkit.compliance_soc2_report(provider="aws")

                mock_prowler.assert_called_once()


class TestExecutiveSummary:
    """Test executive summary generation."""

    @pytest.mark.asyncio
    async def test_executive_summary_structure(self, toolkit, mock_consolidated):
        """Executive summary returns expected structure."""
        toolkit._last_consolidated = mock_consolidated

        summary = await toolkit.compliance_executive_summary()

        assert "total_findings" in summary
        assert "findings_by_severity" in summary
        assert "compliance_coverage" in summary
        assert "overall_risk_score" in summary
        assert "scanners_used" in summary
        assert "scan_timestamp" in summary

    @pytest.mark.asyncio
    async def test_executive_summary_risk_score(self, toolkit, mock_consolidated):
        """Executive summary calculates risk score."""
        toolkit._last_consolidated = mock_consolidated

        summary = await toolkit.compliance_executive_summary()

        # Risk score should be between 0 and 100
        assert 0 <= summary["overall_risk_score"] <= 100

    @pytest.mark.asyncio
    async def test_executive_summary_top_critical(
        self, toolkit, mock_prowler_result
    ):
        """Executive summary includes top critical findings."""
        toolkit._last_consolidated = ConsolidatedReport(
            scan_results={"prowler": mock_prowler_result},
            total_findings=3,
            findings_by_severity={"CRITICAL": 1, "HIGH": 1, "PASS": 1},
            compliance_coverage={},
            generated_at=datetime.now(),
        )

        summary = await toolkit.compliance_executive_summary()

        assert "top_critical_findings" in summary
        assert len(summary["top_critical_findings"]) >= 1


class TestComplianceGaps:
    """Test compliance gap analysis."""

    @pytest.mark.asyncio
    async def test_get_gaps_returns_list(self, toolkit, mock_consolidated):
        """Gaps method returns a list."""
        toolkit._last_consolidated = mock_consolidated

        gaps = await toolkit.compliance_get_gaps(framework="soc2")

        assert isinstance(gaps, list)

    @pytest.mark.asyncio
    async def test_get_gaps_structure(self, toolkit, mock_consolidated):
        """Gap items have expected structure."""
        toolkit._last_consolidated = mock_consolidated

        with patch.object(
            toolkit.compliance_mapper, "get_all_controls"
        ) as mock_controls:
            with patch.object(
                toolkit.compliance_mapper, "get_findings_by_control"
            ) as mock_findings:
                mock_controls.return_value = {
                    "CC6.1": {"name": "Logical Access", "category": "access_control"}
                }
                mock_findings.return_value = {
                    "CC6.1": [
                        SecurityFinding(
                            id="f1",
                            source=FindingSource.PROWLER,
                            severity=SeverityLevel.HIGH,
                            title="Test",
                        )
                    ]
                }

                gaps = await toolkit.compliance_get_gaps(framework="soc2")

                if gaps:
                    gap = gaps[0]
                    assert "control_id" in gap
                    assert "status" in gap
                    assert "finding_count" in gap


class TestRemediationPlan:
    """Test remediation plan generation."""

    @pytest.mark.asyncio
    async def test_remediation_plan_prioritized(self, toolkit):
        """Remediation plan is prioritized by severity."""
        findings = [
            SecurityFinding(
                id="low",
                source=FindingSource.PROWLER,
                severity=SeverityLevel.LOW,
                title="Low Issue",
            ),
            SecurityFinding(
                id="crit",
                source=FindingSource.PROWLER,
                severity=SeverityLevel.CRITICAL,
                title="Critical Issue",
            ),
            SecurityFinding(
                id="high",
                source=FindingSource.PROWLER,
                severity=SeverityLevel.HIGH,
                title="High Issue",
            ),
        ]
        toolkit._last_consolidated = ConsolidatedReport(
            scan_results={
                "prowler": ScanResult(
                    findings=findings,
                    summary=ScanSummary(
                        source=FindingSource.PROWLER,
                        provider=CloudProvider.AWS,
                        total_findings=3,
                        scan_timestamp=datetime.now(),
                    ),
                )
            },
            total_findings=3,
            findings_by_severity={},
            compliance_coverage={},
            generated_at=datetime.now(),
        )

        plan = await toolkit.compliance_get_remediation_plan(max_items=3)

        assert len(plan) == 3
        # Critical should be first
        assert plan[0]["severity"] == "CRITICAL"
        assert plan[1]["severity"] == "HIGH"
        assert plan[2]["severity"] == "LOW"

    @pytest.mark.asyncio
    async def test_remediation_plan_max_items(self, toolkit, mock_consolidated):
        """Remediation plan respects max_items."""
        toolkit._last_consolidated = mock_consolidated

        plan = await toolkit.compliance_get_remediation_plan(max_items=2)

        assert len(plan) <= 2

    @pytest.mark.asyncio
    async def test_remediation_plan_excludes_passing(self, toolkit, mock_prowler_result):
        """Remediation plan excludes passing findings."""
        toolkit._last_consolidated = ConsolidatedReport(
            scan_results={"prowler": mock_prowler_result},
            total_findings=3,
            findings_by_severity={},
            compliance_coverage={},
            generated_at=datetime.now(),
        )

        plan = await toolkit.compliance_get_remediation_plan(max_items=10)

        # Should not include the PASS finding
        severities = [item["severity"] for item in plan]
        assert "PASS" not in severities


class TestCompareReports:
    """Test report comparison."""

    @pytest.mark.asyncio
    async def test_compare_insufficient_history(self, toolkit):
        """Compare returns empty delta with insufficient history."""
        delta = await toolkit.compliance_compare_reports()

        assert isinstance(delta, ComparisonDelta)
        assert delta.new_findings == []
        assert delta.resolved_findings == []

    @pytest.mark.asyncio
    async def test_compare_detects_new_findings(
        self, toolkit, mock_prowler_result, mock_trivy_result
    ):
        """Compare detects new findings between reports."""
        # First report: only prowler findings
        report1 = ConsolidatedReport(
            scan_results={"prowler": mock_prowler_result},
            total_findings=3,
            findings_by_severity={},
            compliance_coverage={},
            generated_at=datetime.now(),
        )

        # Second report: prowler + trivy findings
        report2 = ConsolidatedReport(
            scan_results={
                "prowler": mock_prowler_result,
                "trivy": mock_trivy_result,
            },
            total_findings=5,
            findings_by_severity={},
            compliance_coverage={},
            generated_at=datetime.now(),
        )

        toolkit._report_history = [report1, report2]

        delta = await toolkit.compliance_compare_reports()

        # Should detect Trivy findings as new
        assert len(delta.new_findings) == 2

    @pytest.mark.asyncio
    async def test_compare_detects_resolved_findings(self, toolkit):
        """Compare detects resolved findings."""
        # First report has finding "old-finding"
        finding1 = SecurityFinding(
            id="old-finding",
            source=FindingSource.PROWLER,
            severity=SeverityLevel.HIGH,
            title="Old Issue",
        )
        report1 = ConsolidatedReport(
            scan_results={
                "prowler": ScanResult(
                    findings=[finding1],
                    summary=ScanSummary(
                        source=FindingSource.PROWLER,
                        provider=CloudProvider.AWS,
                        total_findings=1,
                        scan_timestamp=datetime.now(),
                    ),
                )
            },
            total_findings=1,
            findings_by_severity={},
            compliance_coverage={},
            generated_at=datetime.now(),
        )

        # Second report has different finding
        finding2 = SecurityFinding(
            id="new-finding",
            source=FindingSource.PROWLER,
            severity=SeverityLevel.HIGH,
            title="New Issue",
        )
        report2 = ConsolidatedReport(
            scan_results={
                "prowler": ScanResult(
                    findings=[finding2],
                    summary=ScanSummary(
                        source=FindingSource.PROWLER,
                        provider=CloudProvider.AWS,
                        total_findings=1,
                        scan_timestamp=datetime.now(),
                    ),
                )
            },
            total_findings=1,
            findings_by_severity={},
            compliance_coverage={},
            generated_at=datetime.now(),
        )

        toolkit._report_history = [report1, report2]

        delta = await toolkit.compliance_compare_reports()

        assert len(delta.resolved_findings) == 1
        assert delta.resolved_findings[0].id == "old-finding"


class TestExportFindings:
    """Test findings export functionality."""

    @pytest.mark.asyncio
    async def test_export_csv(self, toolkit, mock_consolidated, tmp_path):
        """Export findings to CSV."""
        toolkit._last_consolidated = mock_consolidated
        output_path = str(tmp_path / "findings.csv")

        with patch.object(
            toolkit.report_generator,
            "export_findings_csv",
            new_callable=AsyncMock,
        ) as mock_export:
            mock_export.return_value = output_path

            path = await toolkit.compliance_export_findings(
                output_path=output_path,
                format="csv",
            )

            assert path == output_path
            mock_export.assert_called_once()

    @pytest.mark.asyncio
    async def test_export_json(self, toolkit, mock_consolidated, tmp_path):
        """Export findings to JSON."""
        toolkit._last_consolidated = mock_consolidated
        output_path = str(tmp_path / "findings.json")

        path = await toolkit.compliance_export_findings(
            output_path=output_path,
            format="json",
        )

        assert Path(path).exists()
        content = Path(path).read_text()
        assert "prowler-001" in content
        assert "IAM Root MFA" in content


class TestImports:
    """Test module imports."""

    def test_import_from_security_package(self):
        """ComplianceReportToolkit can be imported from security package."""
        from parrot.tools.security import ComplianceReportToolkit

        toolkit = ComplianceReportToolkit()
        assert toolkit is not None

    def test_import_directly(self):
        """ComplianceReportToolkit can be imported directly."""
        from parrot.tools.security.compliance_report_toolkit import (
            ComplianceReportToolkit,
        )

        assert ComplianceReportToolkit is not None
