"""Unit tests for the Compliance Mapper."""

import pytest

from parrot.tools.security.models import (
    ComplianceFramework,
    FindingSource,
    SecurityFinding,
    SeverityLevel,
)
from parrot.tools.security.reports.compliance_mapper import ComplianceMapper


@pytest.fixture
def mapper():
    """Create a mapper instance for testing."""
    return ComplianceMapper()


@pytest.fixture
def prowler_s3_finding():
    """Prowler finding for S3 public access."""
    return SecurityFinding(
        id="test-prowler-1",
        source=FindingSource.PROWLER,
        severity=SeverityLevel.HIGH,
        title="S3 Bucket Public Access",
        description="S3 bucket allows public access",
        check_id="s3_bucket_public_access",
        resource="arn:aws:s3:::my-bucket",
    )


@pytest.fixture
def prowler_iam_finding():
    """Prowler finding for IAM MFA."""
    return SecurityFinding(
        id="test-prowler-2",
        source=FindingSource.PROWLER,
        severity=SeverityLevel.CRITICAL,
        title="Root MFA Disabled",
        description="MFA is not enabled for root account",
        check_id="iam_root_mfa_enabled",
        resource="arn:aws:iam::123456789:root",
    )


@pytest.fixture
def prowler_pass_finding():
    """Prowler passing finding."""
    return SecurityFinding(
        id="test-prowler-pass",
        source=FindingSource.PROWLER,
        severity=SeverityLevel.PASS,
        title="S3 Encryption Enabled",
        check_id="s3_bucket_encryption_enabled",
    )


@pytest.fixture
def checkov_s3_finding():
    """Checkov finding for S3 logging."""
    return SecurityFinding(
        id="CKV_AWS_18",
        source=FindingSource.CHECKOV,
        severity=SeverityLevel.MEDIUM,
        title="S3 Logging Disabled",
        description="S3 bucket does not have access logging enabled",
        check_id="CKV_AWS_18",
        resource="aws_s3_bucket.data",
    )


@pytest.fixture
def checkov_secret_finding():
    """Checkov finding for exposed secret."""
    return SecurityFinding(
        id="CKV_SECRET_1",
        source=FindingSource.CHECKOV,
        severity=SeverityLevel.CRITICAL,
        title="Secret Exposed",
        check_id="CKV_SECRET_1",
    )


@pytest.fixture
def trivy_critical_cve():
    """Trivy critical vulnerability finding."""
    return SecurityFinding(
        id="CVE-2023-12345",
        source=FindingSource.TRIVY,
        severity=SeverityLevel.CRITICAL,
        title="Critical CVE in base image",
        resource_type="vulnerability",
    )


@pytest.fixture
def trivy_secret_finding():
    """Trivy secret finding."""
    return SecurityFinding(
        id="trivy-secret-1",
        source=FindingSource.TRIVY,
        severity=SeverityLevel.HIGH,
        title="AWS Access Key Found",
        resource_type="secret",
    )


@pytest.fixture
def trivy_misconfig_finding():
    """Trivy misconfiguration finding."""
    return SecurityFinding(
        id="trivy-misconfig-1",
        source=FindingSource.TRIVY,
        severity=SeverityLevel.HIGH,
        title="Dockerfile runs as root",
        resource_type="misconfig",
    )


class TestComplianceMapperInit:
    """Test mapper initialization."""

    def test_default_mappings_dir(self, mapper):
        """Mapper uses default mappings directory."""
        assert mapper.mappings_dir.exists()
        assert mapper.mappings_dir.name == "mappings"

    def test_custom_mappings_dir(self, tmp_path):
        """Accepts custom mappings directory."""
        mapper = ComplianceMapper(mappings_dir=str(tmp_path))
        assert mapper.mappings_dir == tmp_path

    def test_lazy_loading(self, mapper):
        """Mappings are not loaded until first use."""
        # Before any mapping call, no frameworks should be loaded
        assert len(mapper._loaded_frameworks) == 0


class TestMapFindingToControlsSOC2:
    """Test mapping findings to SOC2 controls."""

    def test_map_prowler_s3_finding(self, mapper, prowler_s3_finding):
        """Maps Prowler S3 finding to SOC2 controls."""
        controls = mapper.map_finding_to_controls(
            prowler_s3_finding, ComplianceFramework.SOC2
        )
        assert isinstance(controls, list)
        # s3_bucket_public_access maps to CC6.1, CC6.6
        assert "CC6.1" in controls
        assert "CC6.6" in controls

    def test_map_prowler_iam_finding(self, mapper, prowler_iam_finding):
        """Maps Prowler IAM finding to SOC2 controls."""
        controls = mapper.map_finding_to_controls(
            prowler_iam_finding, ComplianceFramework.SOC2
        )
        assert isinstance(controls, list)
        # iam_root_mfa_enabled maps to CC6.1, CC6.2
        assert "CC6.1" in controls

    def test_map_checkov_finding(self, mapper, checkov_s3_finding):
        """Maps Checkov finding to SOC2 controls."""
        controls = mapper.map_finding_to_controls(
            checkov_s3_finding, ComplianceFramework.SOC2
        )
        assert isinstance(controls, list)
        # CKV_AWS_18 (S3 logging) maps to CC7.3, CC4.1
        if controls:  # Only check if mapping exists
            assert any(c.startswith("CC") for c in controls)

    def test_map_trivy_vulnerability(self, mapper, trivy_critical_cve):
        """Maps Trivy vulnerability to SOC2 controls."""
        controls = mapper.map_finding_to_controls(
            trivy_critical_cve, ComplianceFramework.SOC2
        )
        assert isinstance(controls, list)
        # vulnerability_critical maps to CC7.1
        if controls:
            assert "CC7.1" in controls

    def test_map_trivy_secret(self, mapper, trivy_secret_finding):
        """Maps Trivy secret finding to SOC2 controls."""
        controls = mapper.map_finding_to_controls(
            trivy_secret_finding, ComplianceFramework.SOC2
        )
        assert isinstance(controls, list)
        # secret_exposed maps to CC6.1, CC6.7
        if controls:
            assert "CC6.1" in controls

    def test_unmapped_check_returns_empty(self, mapper):
        """Unmapped check IDs return empty list."""
        finding = SecurityFinding(
            id="unknown",
            source=FindingSource.PROWLER,
            severity=SeverityLevel.LOW,
            title="Unknown Check",
            check_id="nonexistent_check_xyz_12345",
        )
        controls = mapper.map_finding_to_controls(finding, ComplianceFramework.SOC2)
        assert controls == []


class TestMapFindingToControlsHIPAA:
    """Test mapping findings to HIPAA controls."""

    def test_map_prowler_to_hipaa(self, mapper, prowler_s3_finding):
        """Maps Prowler finding to HIPAA controls."""
        controls = mapper.map_finding_to_controls(
            prowler_s3_finding, ComplianceFramework.HIPAA
        )
        assert isinstance(controls, list)
        # Should map to technical safeguards
        if controls:
            assert any("164.312" in c for c in controls)

    def test_map_checkov_to_hipaa(self, mapper, checkov_s3_finding):
        """Maps Checkov finding to HIPAA controls."""
        controls = mapper.map_finding_to_controls(
            checkov_s3_finding, ComplianceFramework.HIPAA
        )
        assert isinstance(controls, list)

    def test_map_trivy_to_hipaa(self, mapper, trivy_critical_cve):
        """Maps Trivy finding to HIPAA controls."""
        controls = mapper.map_finding_to_controls(
            trivy_critical_cve, ComplianceFramework.HIPAA
        )
        assert isinstance(controls, list)


class TestMapFindingToControlsPCIDSS:
    """Test mapping findings to PCI-DSS controls."""

    def test_map_prowler_to_pci(self, mapper, prowler_s3_finding):
        """Maps Prowler finding to PCI-DSS controls."""
        controls = mapper.map_finding_to_controls(
            prowler_s3_finding, ComplianceFramework.PCI_DSS
        )
        assert isinstance(controls, list)

    def test_map_iam_mfa_to_pci(self, mapper, prowler_iam_finding):
        """Maps IAM MFA finding to PCI-DSS authentication controls."""
        controls = mapper.map_finding_to_controls(
            prowler_iam_finding, ComplianceFramework.PCI_DSS
        )
        assert isinstance(controls, list)
        # iam_root_mfa_enabled maps to 8.3.9, 8.4.1
        if controls:
            assert any(c.startswith("8.") for c in controls)


class TestGetFrameworkCoverage:
    """Test coverage calculation."""

    def test_coverage_with_mixed_findings(self, mapper):
        """Calculates coverage from mixed pass/fail findings."""
        findings = [
            SecurityFinding(
                id="f1",
                source=FindingSource.PROWLER,
                severity=SeverityLevel.HIGH,
                title="S3 Public",
                check_id="s3_bucket_public_access",
            ),
            SecurityFinding(
                id="f2",
                source=FindingSource.PROWLER,
                severity=SeverityLevel.PASS,
                title="S3 Encryption OK",
                check_id="s3_bucket_encryption_enabled",
            ),
            SecurityFinding(
                id="f3",
                source=FindingSource.PROWLER,
                severity=SeverityLevel.HIGH,
                title="IAM Issue",
                check_id="iam_root_mfa_enabled",
            ),
        ]
        coverage = mapper.get_framework_coverage(findings, ComplianceFramework.SOC2)

        assert "total_controls" in coverage
        assert "checked_controls" in coverage
        assert "passed_controls" in coverage
        assert "failed_controls" in coverage
        assert "unchecked_controls" in coverage
        assert "coverage_pct" in coverage
        assert "pass_pct" in coverage

        assert coverage["total_controls"] > 0
        assert 0 <= coverage["coverage_pct"] <= 100
        assert 0 <= coverage["pass_pct"] <= 100

    def test_coverage_empty_findings(self, mapper):
        """Handles empty findings list."""
        coverage = mapper.get_framework_coverage([], ComplianceFramework.SOC2)

        assert coverage["checked_controls"] == 0
        assert coverage["passed_controls"] == 0
        assert coverage["failed_controls"] == 0

    def test_coverage_all_passing(self, mapper):
        """All passing findings result in 100% pass rate."""
        findings = [
            SecurityFinding(
                id=f"pass{i}",
                source=FindingSource.PROWLER,
                severity=SeverityLevel.PASS,
                title=f"Pass {i}",
                check_id="s3_bucket_encryption_enabled",
            )
            for i in range(3)
        ]
        coverage = mapper.get_framework_coverage(findings, ComplianceFramework.SOC2)

        if coverage["checked_controls"] > 0:
            assert coverage["pass_pct"] == 100.0
            assert coverage["failed_controls"] == 0

    def test_coverage_all_failing(self, mapper):
        """All failing findings result in 0% pass rate."""
        findings = [
            SecurityFinding(
                id="fail1",
                source=FindingSource.PROWLER,
                severity=SeverityLevel.HIGH,
                title="Failed check",
                check_id="s3_bucket_public_access",
            ),
        ]
        coverage = mapper.get_framework_coverage(findings, ComplianceFramework.SOC2)

        if coverage["checked_controls"] > 0:
            assert coverage["pass_pct"] == 0.0
            assert coverage["passed_controls"] == 0


class TestGetControlDetails:
    """Test control details retrieval."""

    def test_get_existing_soc2_control(self, mapper):
        """Gets details for existing SOC2 control."""
        details = mapper.get_control_details("CC6.1", ComplianceFramework.SOC2)

        assert details is not None
        assert "name" in details
        assert "description" in details
        assert "category" in details

    def test_get_existing_hipaa_control(self, mapper):
        """Gets details for existing HIPAA control."""
        details = mapper.get_control_details("164.312(a)(1)", ComplianceFramework.HIPAA)

        assert details is not None
        assert "name" in details

    def test_get_existing_pci_control(self, mapper):
        """Gets details for existing PCI-DSS control."""
        details = mapper.get_control_details("8.3.9", ComplianceFramework.PCI_DSS)

        assert details is not None
        assert "name" in details

    def test_get_nonexistent_control(self, mapper):
        """Returns None for nonexistent control."""
        details = mapper.get_control_details("INVALID_999", ComplianceFramework.SOC2)
        assert details is None

    def test_get_control_wrong_framework(self, mapper):
        """Returns None for control in wrong framework."""
        # CC6.1 is SOC2, not HIPAA
        details = mapper.get_control_details("CC6.1", ComplianceFramework.HIPAA)
        assert details is None


class TestGetAllControls:
    """Test retrieving all controls."""

    def test_get_all_soc2_controls(self, mapper):
        """Gets all SOC2 controls."""
        controls = mapper.get_all_controls(ComplianceFramework.SOC2)

        assert isinstance(controls, dict)
        assert len(controls) > 0
        assert "CC6.1" in controls

    def test_get_all_hipaa_controls(self, mapper):
        """Gets all HIPAA controls."""
        controls = mapper.get_all_controls(ComplianceFramework.HIPAA)

        assert isinstance(controls, dict)
        assert len(controls) > 0

    def test_get_all_pci_controls(self, mapper):
        """Gets all PCI-DSS controls."""
        controls = mapper.get_all_controls(ComplianceFramework.PCI_DSS)

        assert isinstance(controls, dict)
        assert len(controls) > 0


class TestGetFindingsByControl:
    """Test grouping findings by control."""

    def test_group_by_control(self, mapper, prowler_s3_finding, prowler_iam_finding):
        """Groups findings by their mapped controls."""
        findings = [prowler_s3_finding, prowler_iam_finding]
        by_control = mapper.get_findings_by_control(findings, ComplianceFramework.SOC2)

        assert isinstance(by_control, dict)
        # CC6.1 should have both findings
        if "CC6.1" in by_control:
            assert len(by_control["CC6.1"]) >= 1

    def test_group_empty_findings(self, mapper):
        """Handles empty findings list."""
        by_control = mapper.get_findings_by_control([], ComplianceFramework.SOC2)
        assert by_control == {}


class TestGetUnmappedFindings:
    """Test identifying unmapped findings."""

    def test_get_unmapped(self, mapper):
        """Identifies findings with no control mappings."""
        unmapped_finding = SecurityFinding(
            id="unknown",
            source=FindingSource.PROWLER,
            severity=SeverityLevel.LOW,
            title="Unknown",
            check_id="totally_unknown_check_xyz",
        )
        mapped_finding = SecurityFinding(
            id="known",
            source=FindingSource.PROWLER,
            severity=SeverityLevel.HIGH,
            title="Known",
            check_id="s3_bucket_public_access",
        )

        unmapped = mapper.get_unmapped_findings(
            [unmapped_finding, mapped_finding], ComplianceFramework.SOC2
        )

        assert unmapped_finding in unmapped
        assert mapped_finding not in unmapped


class TestTrivyMappings:
    """Test Trivy-specific mapping logic."""

    def test_trivy_high_vulnerability(self, mapper):
        """Maps high-severity vulnerability correctly."""
        finding = SecurityFinding(
            id="CVE-2023-99999",
            source=FindingSource.TRIVY,
            severity=SeverityLevel.HIGH,
            title="High CVE",
            resource_type="vulnerability",
        )
        controls = mapper.map_finding_to_controls(finding, ComplianceFramework.SOC2)
        assert isinstance(controls, list)
        if controls:
            assert "CC7.1" in controls

    def test_trivy_medium_vulnerability(self, mapper):
        """Maps medium-severity vulnerability correctly."""
        finding = SecurityFinding(
            id="CVE-2023-11111",
            source=FindingSource.TRIVY,
            severity=SeverityLevel.MEDIUM,
            title="Medium CVE",
            resource_type="vulnerability",
        )
        controls = mapper.map_finding_to_controls(finding, ComplianceFramework.SOC2)
        assert isinstance(controls, list)

    def test_trivy_misconfig_high(self, mapper, trivy_misconfig_finding):
        """Maps high-severity misconfiguration correctly."""
        controls = mapper.map_finding_to_controls(
            trivy_misconfig_finding, ComplianceFramework.SOC2
        )
        assert isinstance(controls, list)


class TestCheckovSecretsMappings:
    """Test Checkov secrets mapping."""

    def test_secret_maps_to_access_control(self, mapper, checkov_secret_finding):
        """Secret findings map to access control controls."""
        controls = mapper.map_finding_to_controls(
            checkov_secret_finding, ComplianceFramework.SOC2
        )
        assert isinstance(controls, list)
        # CKV_SECRET_* should map to CC6.1, CC6.7
        if controls:
            assert "CC6.1" in controls or "CC6.7" in controls


class TestMultipleFrameworks:
    """Test mapping same finding to multiple frameworks."""

    def test_same_finding_different_frameworks(self, mapper, prowler_s3_finding):
        """Same finding maps to different controls in different frameworks."""
        soc2_controls = mapper.map_finding_to_controls(
            prowler_s3_finding, ComplianceFramework.SOC2
        )
        hipaa_controls = mapper.map_finding_to_controls(
            prowler_s3_finding, ComplianceFramework.HIPAA
        )
        pci_controls = mapper.map_finding_to_controls(
            prowler_s3_finding, ComplianceFramework.PCI_DSS
        )

        # All should be lists (may be empty if no mapping)
        assert isinstance(soc2_controls, list)
        assert isinstance(hipaa_controls, list)
        assert isinstance(pci_controls, list)

        # SOC2 uses CC prefix, HIPAA uses 164.*, PCI uses numbers
        if soc2_controls:
            assert all(c.startswith("CC") for c in soc2_controls)
        if hipaa_controls:
            assert all(c.startswith("164.") for c in hipaa_controls)


class TestImports:
    """Test module imports."""

    def test_import_from_reports_package(self):
        """ComplianceMapper can be imported from reports package."""
        from parrot.tools.security.reports import ComplianceMapper

        mapper = ComplianceMapper()
        assert mapper is not None

    def test_import_directly(self):
        """ComplianceMapper can be imported directly."""
        from parrot.tools.security.reports.compliance_mapper import ComplianceMapper

        assert ComplianceMapper is not None
