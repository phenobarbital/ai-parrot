"""Unit tests for the shared security models."""

import pytest
from datetime import datetime

from parrot.tools.security.models import (
    SeverityLevel,
    FindingSource,
    ComplianceFramework,
    CloudProvider,
    SecurityFinding,
    ScanSummary,
    ScanResult,
    ComparisonDelta,
    ConsolidatedReport,
)


class TestEnums:
    def test_severity_level_values(self):
        """All expected severity levels exist."""
        assert SeverityLevel.CRITICAL == "CRITICAL"
        assert SeverityLevel.HIGH == "HIGH"
        assert SeverityLevel.MEDIUM == "MEDIUM"
        assert SeverityLevel.LOW == "LOW"
        assert SeverityLevel.INFO == "INFO"
        assert SeverityLevel.PASS == "PASS"
        assert SeverityLevel.UNKNOWN == "UNKNOWN"

    def test_finding_source_values(self):
        """All scanner sources defined."""
        assert FindingSource.PROWLER == "prowler"
        assert FindingSource.TRIVY == "trivy"
        assert FindingSource.CHECKOV == "checkov"
        assert FindingSource.CLOUDSPLOIT == "cloudsploit"
        assert FindingSource.MANUAL == "manual"

    def test_compliance_framework_values(self):
        """Key compliance frameworks defined."""
        assert ComplianceFramework.SOC2 == "soc2"
        assert ComplianceFramework.HIPAA == "hipaa"
        assert ComplianceFramework.PCI_DSS == "pci_dss"
        assert ComplianceFramework.GDPR == "gdpr"
        assert ComplianceFramework.NIST_800_53 == "nist_800_53"
        assert ComplianceFramework.CIS == "cis"

    def test_cloud_provider_values(self):
        """Cloud provider values defined."""
        assert CloudProvider.AWS == "aws"
        assert CloudProvider.GCP == "gcp"
        assert CloudProvider.AZURE == "azure"
        assert CloudProvider.KUBERNETES == "kubernetes"
        assert CloudProvider.LOCAL == "local"


class TestSecurityFinding:
    def test_minimal_finding(self):
        """Finding with required fields only."""
        finding = SecurityFinding(
            id="test-001",
            source=FindingSource.PROWLER,
            severity=SeverityLevel.HIGH,
            title="Test Finding",
        )
        assert finding.id == "test-001"
        assert finding.source == FindingSource.PROWLER
        assert finding.severity == SeverityLevel.HIGH
        assert finding.title == "Test Finding"
        assert finding.region == "global"  # default
        assert finding.description is None
        assert finding.compliance_tags == []

    def test_full_finding(self):
        """Finding with all fields populated."""
        finding = SecurityFinding(
            id="test-002",
            source=FindingSource.TRIVY,
            severity=SeverityLevel.CRITICAL,
            title="Critical CVE Found",
            description="CVE-2024-1234 in package X",
            resource="arn:aws:s3:::my-bucket",
            resource_type="S3 Bucket",
            region="us-east-1",
            provider=CloudProvider.AWS,
            service="s3",
            check_id="s3_bucket_public_access",
            compliance_tags=["SOC2-CC6.1", "HIPAA-164.312"],
            remediation="Enable bucket encryption",
            raw={"original": "data"},
        )
        assert finding.compliance_tags == ["SOC2-CC6.1", "HIPAA-164.312"]
        assert finding.resource == "arn:aws:s3:::my-bucket"
        assert finding.raw == {"original": "data"}

    def test_finding_json_roundtrip(self):
        """Finding serializes and deserializes correctly."""
        finding = SecurityFinding(
            id="test-003",
            source=FindingSource.CHECKOV,
            severity=SeverityLevel.MEDIUM,
            title="IaC Misconfiguration",
        )
        json_data = finding.model_dump_json()
        restored = SecurityFinding.model_validate_json(json_data)
        assert restored.id == finding.id
        assert restored.source == finding.source
        assert restored.severity == finding.severity

    def test_finding_enum_serialization(self):
        """Enums serialize to string values in JSON."""
        finding = SecurityFinding(
            id="test-004",
            source=FindingSource.PROWLER,
            severity=SeverityLevel.HIGH,
            title="Test",
        )
        data = finding.model_dump()
        assert data["source"] == "prowler"
        assert data["severity"] == "HIGH"


class TestScanSummary:
    def test_minimal_summary(self):
        """Summary with required fields only."""
        summary = ScanSummary(
            source=FindingSource.PROWLER,
            provider=CloudProvider.AWS,
            scan_timestamp=datetime.now(),
        )
        assert summary.total_findings == 0
        assert summary.critical_count == 0
        assert summary.regions_scanned == []

    def test_full_summary(self):
        """Summary with all fields populated."""
        timestamp = datetime.now()
        summary = ScanSummary(
            source=FindingSource.TRIVY,
            provider=CloudProvider.AWS,
            total_findings=10,
            critical_count=2,
            high_count=3,
            medium_count=4,
            low_count=1,
            scan_timestamp=timestamp,
            scan_duration_seconds=45.5,
            regions_scanned=["us-east-1", "us-west-2"],
            services_scanned=["s3", "ec2", "iam"],
            errors=["Warning: rate limited on region ap-south-1"],
        )
        assert summary.total_findings == 10
        assert summary.critical_count == 2
        assert summary.scan_duration_seconds == 45.5
        assert "us-east-1" in summary.regions_scanned


class TestScanResult:
    def test_empty_scan_result(self):
        """Scan result with no findings."""
        summary = ScanSummary(
            source=FindingSource.PROWLER,
            provider=CloudProvider.AWS,
            total_findings=0,
            scan_timestamp=datetime.now(),
        )
        result = ScanResult(findings=[], summary=summary)
        assert len(result.findings) == 0
        assert result.summary.total_findings == 0

    def test_scan_result_with_findings(self):
        """Scan result with multiple findings."""
        findings = [
            SecurityFinding(
                id=f"f-{i}",
                source=FindingSource.PROWLER,
                severity=SeverityLevel.HIGH,
                title=f"Finding {i}",
            )
            for i in range(3)
        ]
        summary = ScanSummary(
            source=FindingSource.PROWLER,
            provider=CloudProvider.AWS,
            total_findings=3,
            high_count=3,
            scan_timestamp=datetime.now(),
        )
        result = ScanResult(findings=findings, summary=summary)
        assert result.summary.total_findings == 3
        assert len(result.findings) == 3

    def test_scan_result_json_roundtrip(self):
        """Scan result serializes and deserializes correctly."""
        findings = [
            SecurityFinding(
                id="test-1",
                source=FindingSource.CHECKOV,
                severity=SeverityLevel.LOW,
                title="Test Finding",
            )
        ]
        summary = ScanSummary(
            source=FindingSource.CHECKOV,
            provider=CloudProvider.LOCAL,
            total_findings=1,
            low_count=1,
            scan_timestamp=datetime.now(),
        )
        result = ScanResult(findings=findings, summary=summary)
        json_data = result.model_dump_json()
        restored = ScanResult.model_validate_json(json_data)
        assert len(restored.findings) == 1
        assert restored.findings[0].id == "test-1"


class TestComparisonDelta:
    def test_empty_delta(self):
        """Comparison with no changes."""
        baseline = datetime(2024, 1, 1)
        current = datetime(2024, 1, 2)
        delta = ComparisonDelta(
            baseline_timestamp=baseline,
            current_timestamp=current,
        )
        assert len(delta.new_findings) == 0
        assert len(delta.resolved_findings) == 0
        assert len(delta.unchanged_findings) == 0

    def test_delta_with_changes(self):
        """Comparison with findings added and removed."""
        baseline = datetime(2024, 1, 1)
        current = datetime(2024, 1, 2)

        new_finding = SecurityFinding(
            id="new-1",
            source=FindingSource.PROWLER,
            severity=SeverityLevel.HIGH,
            title="New Finding",
        )
        resolved_finding = SecurityFinding(
            id="resolved-1",
            source=FindingSource.PROWLER,
            severity=SeverityLevel.MEDIUM,
            title="Resolved Finding",
        )

        delta = ComparisonDelta(
            baseline_timestamp=baseline,
            current_timestamp=current,
            new_findings=[new_finding],
            resolved_findings=[resolved_finding],
            severity_trend={"HIGH": 1, "MEDIUM": -1},
            summary="1 new finding, 1 resolved",
        )
        assert len(delta.new_findings) == 1
        assert len(delta.resolved_findings) == 1
        assert delta.severity_trend["HIGH"] == 1


class TestConsolidatedReport:
    def test_empty_consolidated_report(self):
        """Consolidated report with no scan results."""
        report = ConsolidatedReport(generated_at=datetime.now())
        assert report.total_findings == 0
        assert report.scan_results == {}
        assert report.findings_by_severity == {}

    def test_consolidated_report_with_results(self):
        """Consolidated report with multiple scanner results."""
        prowler_findings = [
            SecurityFinding(
                id="p1",
                source=FindingSource.PROWLER,
                severity=SeverityLevel.CRITICAL,
                title="IAM Root MFA Disabled",
                service="iam",
            )
        ]
        prowler_summary = ScanSummary(
            source=FindingSource.PROWLER,
            provider=CloudProvider.AWS,
            total_findings=1,
            critical_count=1,
            scan_timestamp=datetime.now(),
        )
        prowler_result = ScanResult(findings=prowler_findings, summary=prowler_summary)

        trivy_findings = [
            SecurityFinding(
                id="t1",
                source=FindingSource.TRIVY,
                severity=SeverityLevel.HIGH,
                title="CVE-2024-1234",
                service="container",
            )
        ]
        trivy_summary = ScanSummary(
            source=FindingSource.TRIVY,
            provider=CloudProvider.LOCAL,
            total_findings=1,
            high_count=1,
            scan_timestamp=datetime.now(),
        )
        trivy_result = ScanResult(findings=trivy_findings, summary=trivy_summary)

        report = ConsolidatedReport(
            scan_results={"prowler": prowler_result, "trivy": trivy_result},
            total_findings=2,
            findings_by_severity={"CRITICAL": 1, "HIGH": 1},
            findings_by_service={"iam": 1, "container": 1},
            generated_at=datetime.now(),
        )

        assert report.total_findings == 2
        assert "prowler" in report.scan_results
        assert "trivy" in report.scan_results
        assert report.findings_by_severity["CRITICAL"] == 1

    def test_consolidated_report_json_roundtrip(self):
        """Consolidated report serializes and deserializes correctly."""
        report = ConsolidatedReport(
            total_findings=5,
            findings_by_severity={"HIGH": 3, "MEDIUM": 2},
            generated_at=datetime.now(),
            report_id="report-001",
        )
        json_data = report.model_dump_json()
        restored = ConsolidatedReport.model_validate_json(json_data)
        assert restored.total_findings == 5
        assert restored.report_id == "report-001"


class TestImports:
    def test_import_from_security_package(self):
        """Models can be imported from parrot.tools.security."""
        from parrot.tools.security import (
            SeverityLevel,
            FindingSource,
            ComplianceFramework,
            CloudProvider,
            SecurityFinding,
            ScanSummary,
            ScanResult,
            ComparisonDelta,
            ConsolidatedReport,
        )

        assert SeverityLevel.CRITICAL == "CRITICAL"
        assert FindingSource.PROWLER == "prowler"

    def test_import_from_models_module(self):
        """Models can be imported from parrot.tools.security.models."""
        from parrot.tools.security.models import SecurityFinding, ScanResult

        finding = SecurityFinding(
            id="import-test",
            source=FindingSource.PROWLER,
            severity=SeverityLevel.LOW,
            title="Import Test",
        )
        assert finding.id == "import-test"
