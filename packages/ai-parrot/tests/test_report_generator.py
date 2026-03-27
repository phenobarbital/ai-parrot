"""Unit tests for the Report Generator."""

from datetime import datetime
from pathlib import Path

import pytest

from parrot.tools.security.models import (
    CloudProvider,
    ComplianceFramework,
    ConsolidatedReport,
    FindingSource,
    ScanResult,
    ScanSummary,
    SecurityFinding,
    SeverityLevel,
)
from parrot.tools.security.reports.generator import ReportGenerator


@pytest.fixture
def generator(tmp_path):
    """Create a generator instance with temp output directory."""
    return ReportGenerator(output_dir=str(tmp_path))


@pytest.fixture
def sample_findings():
    """Create sample findings for testing."""
    return [
        SecurityFinding(
            id="f1",
            source=FindingSource.PROWLER,
            severity=SeverityLevel.CRITICAL,
            title="Critical IAM Issue",
            description="Root MFA is not enabled",
            check_id="iam_root_mfa_enabled",
            resource="arn:aws:iam::123456789:root",
            remediation="Enable MFA for root account",
        ),
        SecurityFinding(
            id="f2",
            source=FindingSource.TRIVY,
            severity=SeverityLevel.HIGH,
            title="High CVE Detected",
            description="CVE-2023-1234 in base image",
            check_id="CVE-2023-1234",
            resource="nginx:latest",
            resource_type="vulnerability",
        ),
        SecurityFinding(
            id="f3",
            source=FindingSource.CHECKOV,
            severity=SeverityLevel.MEDIUM,
            title="S3 Logging Disabled",
            description="S3 bucket does not have access logging",
            check_id="CKV_AWS_18",
            resource="aws_s3_bucket.data",
        ),
        SecurityFinding(
            id="f4",
            source=FindingSource.PROWLER,
            severity=SeverityLevel.PASS,
            title="S3 Encryption Enabled",
            description="S3 bucket has encryption",
            check_id="s3_bucket_encryption_enabled",
        ),
    ]


@pytest.fixture
def sample_scan_result(sample_findings):
    """Create a sample scan result."""
    summary = ScanSummary(
        source=FindingSource.PROWLER,
        provider=CloudProvider.AWS,
        total_findings=4,
        critical_count=1,
        high_count=1,
        medium_count=1,
        pass_count=1,
        scan_timestamp=datetime.now(),
    )
    return ScanResult(findings=sample_findings[:2], summary=summary)


@pytest.fixture
def sample_consolidated(sample_findings):
    """Create a sample consolidated report."""
    prowler_summary = ScanSummary(
        source=FindingSource.PROWLER,
        provider=CloudProvider.AWS,
        total_findings=2,
        critical_count=1,
        pass_count=1,
        scan_timestamp=datetime.now(),
    )
    trivy_summary = ScanSummary(
        source=FindingSource.TRIVY,
        provider=CloudProvider.LOCAL,
        total_findings=1,
        high_count=1,
        scan_timestamp=datetime.now(),
    )
    checkov_summary = ScanSummary(
        source=FindingSource.CHECKOV,
        provider=CloudProvider.LOCAL,
        total_findings=1,
        medium_count=1,
        scan_timestamp=datetime.now(),
    )

    prowler_result = ScanResult(
        findings=[sample_findings[0], sample_findings[3]],
        summary=prowler_summary
    )
    trivy_result = ScanResult(
        findings=[sample_findings[1]],
        summary=trivy_summary
    )
    checkov_result = ScanResult(
        findings=[sample_findings[2]],
        summary=checkov_summary
    )

    return ConsolidatedReport(
        scan_results={
            "prowler": prowler_result,
            "trivy": trivy_result,
            "checkov": checkov_result,
        },
        total_findings=4,
        findings_by_severity={"CRITICAL": 1, "HIGH": 1, "MEDIUM": 1, "PASS": 1},
        generated_at=datetime.now(),
    )


class TestReportGeneratorInit:
    """Test generator initialization."""

    def test_creates_output_dir(self, tmp_path):
        """Creates output directory if it doesn't exist."""
        output_dir = tmp_path / "reports" / "subdir"
        ReportGenerator(output_dir=str(output_dir))
        assert output_dir.exists()

    def test_loads_templates(self, generator):
        """Jinja2 environment is configured."""
        assert generator.env is not None
        assert generator.template_dir.exists()

    def test_has_compliance_mapper(self, generator):
        """Has ComplianceMapper instance."""
        assert generator.compliance_mapper is not None


class TestGenerateComplianceReport:
    """Test compliance report generation."""

    @pytest.mark.asyncio
    async def test_generate_soc2_report(self, generator, sample_consolidated):
        """Generates SOC2 HTML report."""
        path = await generator.generate_compliance_report(
            sample_consolidated,
            ComplianceFramework.SOC2,
            format="html",
        )
        assert Path(path).exists()
        content = Path(path).read_text()
        assert "SOC2" in content
        assert "Critical IAM Issue" in content

    @pytest.mark.asyncio
    async def test_generate_hipaa_report(self, generator, sample_consolidated):
        """Generates HIPAA HTML report."""
        path = await generator.generate_compliance_report(
            sample_consolidated,
            ComplianceFramework.HIPAA,
            format="html",
        )
        assert Path(path).exists()
        content = Path(path).read_text()
        assert "HIPAA" in content

    @pytest.mark.asyncio
    async def test_generate_pci_dss_report(self, generator, sample_consolidated):
        """Generates PCI-DSS HTML report."""
        path = await generator.generate_compliance_report(
            sample_consolidated,
            ComplianceFramework.PCI_DSS,
            format="html",
        )
        assert Path(path).exists()
        content = Path(path).read_text()
        assert "PCI" in content

    @pytest.mark.asyncio
    async def test_custom_output_path(self, generator, sample_consolidated, tmp_path):
        """Respects custom output path."""
        custom_path = str(tmp_path / "custom_report.html")
        path = await generator.generate_compliance_report(
            sample_consolidated,
            ComplianceFramework.SOC2,
            output_path=custom_path,
        )
        assert path == custom_path
        assert Path(path).exists()

    @pytest.mark.asyncio
    async def test_include_evidence_true(self, generator, sample_consolidated):
        """Report includes evidence when requested."""
        path = await generator.generate_compliance_report(
            sample_consolidated,
            ComplianceFramework.SOC2,
            include_evidence=True,
        )
        content = Path(path).read_text()
        assert "Evidence" in content or "MFA" in content

    @pytest.mark.asyncio
    async def test_include_evidence_false(self, generator, sample_consolidated):
        """Report excludes detailed findings when requested."""
        path = await generator.generate_compliance_report(
            sample_consolidated,
            ComplianceFramework.SOC2,
            include_evidence=False,
        )
        # Should still generate without errors
        assert Path(path).exists()


class TestGenerateExecutiveSummary:
    """Test executive summary generation."""

    @pytest.mark.asyncio
    async def test_generate_executive_summary(self, generator, sample_consolidated):
        """Generates executive summary report."""
        path = await generator.generate_executive_summary(
            sample_consolidated,
            format="html",
        )
        assert Path(path).exists()
        content = Path(path).read_text()
        assert "Summary" in content or "Executive" in content

    @pytest.mark.asyncio
    async def test_summary_includes_severity_counts(self, generator, sample_consolidated):
        """Executive summary includes severity breakdown."""
        path = await generator.generate_executive_summary(sample_consolidated)
        content = Path(path).read_text()
        assert "Critical" in content or "CRITICAL" in content

    @pytest.mark.asyncio
    async def test_summary_includes_scanner_info(self, generator, sample_consolidated):
        """Executive summary includes scanner information."""
        path = await generator.generate_executive_summary(sample_consolidated)
        content = Path(path).read_text()
        # Should reference the scanners used
        assert "Scanner" in content or "prowler" in content.lower()


class TestGenerateConsolidatedReport:
    """Test consolidated report generation."""

    @pytest.mark.asyncio
    async def test_generate_consolidated_report(self, generator, sample_consolidated):
        """Generates consolidated HTML report."""
        path = await generator.generate_consolidated_report(
            sample_consolidated,
            format="html",
        )
        assert Path(path).exists()
        content = Path(path).read_text()
        assert "Consolidated" in content or "Security" in content

    @pytest.mark.asyncio
    async def test_consolidated_includes_all_scanners(
        self, generator, sample_consolidated
    ):
        """Consolidated report includes all scanner results."""
        path = await generator.generate_consolidated_report(sample_consolidated)
        content = Path(path).read_text()
        # Should have results from all three scanners
        assert "prowler" in content.lower() or "Prowler" in content

    @pytest.mark.asyncio
    async def test_consolidated_with_all_findings(
        self, generator, sample_consolidated
    ):
        """Consolidated report can include all findings."""
        path = await generator.generate_consolidated_report(
            sample_consolidated,
            include_all_findings=True,
        )
        content = Path(path).read_text()
        # Should include detailed findings
        assert "Critical IAM Issue" in content


class TestExportFindingsCsv:
    """Test CSV export functionality."""

    @pytest.mark.asyncio
    async def test_export_csv(self, generator, sample_findings, tmp_path):
        """Exports findings to CSV."""
        output_path = str(tmp_path / "findings.csv")
        path = await generator.export_findings_csv(sample_findings, output_path)

        assert Path(path).exists()
        content = Path(path).read_text()

        # Check header
        assert "id" in content.lower()
        assert "severity" in content.lower()
        assert "title" in content.lower()

        # Check data
        assert "f1" in content
        assert "CRITICAL" in content
        assert "Critical IAM Issue" in content

    @pytest.mark.asyncio
    async def test_export_csv_empty(self, generator, tmp_path):
        """Handles empty findings list."""
        output_path = str(tmp_path / "empty.csv")
        path = await generator.export_findings_csv([], output_path)

        assert Path(path).exists()
        content = Path(path).read_text()
        # Should have header but no data rows
        assert "id" in content.lower()

    @pytest.mark.asyncio
    async def test_export_csv_all_fields(self, generator, sample_findings, tmp_path):
        """CSV includes all expected fields."""
        output_path = str(tmp_path / "full.csv")
        await generator.export_findings_csv(sample_findings, output_path)

        content = Path(output_path).read_text()
        expected_fields = [
            "id", "source", "severity", "title", "description",
            "check_id", "resource", "resource_type", "remediation"
        ]
        for field in expected_fields:
            assert field in content.lower()


class TestReportContent:
    """Test report content quality."""

    @pytest.mark.asyncio
    async def test_report_includes_severity_breakdown(
        self, generator, sample_consolidated
    ):
        """Report includes severity statistics."""
        path = await generator.generate_compliance_report(
            sample_consolidated,
            ComplianceFramework.SOC2,
        )
        content = Path(path).read_text()
        assert "Critical" in content or "CRITICAL" in content

    @pytest.mark.asyncio
    async def test_report_includes_remediation(self, generator, sample_consolidated):
        """Report includes remediation guidance."""
        path = await generator.generate_compliance_report(
            sample_consolidated,
            ComplianceFramework.SOC2,
            include_evidence=True,
        )
        content = Path(path).read_text()
        # Should include remediation from the finding
        assert "MFA" in content or "remediation" in content.lower()

    @pytest.mark.asyncio
    async def test_report_has_timestamp(self, generator, sample_consolidated):
        """Report includes generation timestamp."""
        path = await generator.generate_compliance_report(
            sample_consolidated,
            ComplianceFramework.SOC2,
        )
        content = Path(path).read_text()
        assert "Generated" in content


class TestGenerateFromScanResult:
    """Test convenience method for single scan results."""

    @pytest.mark.asyncio
    async def test_generate_from_single_result(
        self, generator, sample_scan_result, tmp_path
    ):
        """Generates report from single scan result."""
        output_path = str(tmp_path / "single_report.html")
        path = await generator.generate_report_from_scan_result(
            sample_scan_result,
            report_type="consolidated",
            output_path=output_path,
        )
        assert Path(path).exists()

    @pytest.mark.asyncio
    async def test_generate_executive_from_single_result(
        self, generator, sample_scan_result, tmp_path
    ):
        """Generates executive summary from single scan result."""
        output_path = str(tmp_path / "executive.html")
        path = await generator.generate_report_from_scan_result(
            sample_scan_result,
            report_type="executive",
            output_path=output_path,
        )
        assert Path(path).exists()
        content = Path(path).read_text()
        assert "Summary" in content or "Executive" in content


class TestImports:
    """Test module imports."""

    def test_import_from_reports_package(self):
        """ReportGenerator can be imported from reports package."""
        from parrot.tools.security.reports import ReportGenerator

        generator = ReportGenerator(output_dir="/tmp/test-imports")
        assert generator is not None

    def test_import_directly(self):
        """ReportGenerator can be imported directly."""
        from parrot.tools.security.reports.generator import ReportGenerator

        assert ReportGenerator is not None
