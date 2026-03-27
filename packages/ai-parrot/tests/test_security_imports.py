"""Import verification tests for Security Toolkits Suite.

Verifies that all security components are properly exported and importable
from expected paths without circular import errors.
"""


class TestSecurityPackageImports:
    """Test imports from parrot.tools.security package."""

    def test_import_toolkits_from_security(self):
        """Toolkits importable from parrot.tools.security."""
        from parrot.tools.security import (
            CloudPostureToolkit,
            ComplianceReportToolkit,
            ContainerSecurityToolkit,
            SecretsIaCToolkit,
        )

        assert CloudPostureToolkit is not None
        assert ContainerSecurityToolkit is not None
        assert SecretsIaCToolkit is not None
        assert ComplianceReportToolkit is not None

    def test_import_toolkits_from_tools(self):
        """Toolkits importable from parrot.tools."""
        from parrot.tools import (
            CloudPostureToolkit,
            ComplianceReportToolkit,
            ContainerSecurityToolkit,
            SecretsIaCToolkit,
        )

        assert CloudPostureToolkit is not None
        assert ContainerSecurityToolkit is not None
        assert SecretsIaCToolkit is not None
        assert ComplianceReportToolkit is not None

    def test_import_models(self):
        """Models importable from security.models."""
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

        assert SeverityLevel.CRITICAL == "CRITICAL"
        assert FindingSource.PROWLER == "prowler"
        assert ComplianceFramework.SOC2 == "soc2"
        assert CloudProvider.AWS == "aws"
        assert SecurityFinding is not None
        assert ScanSummary is not None
        assert ScanResult is not None
        assert ComparisonDelta is not None
        assert ConsolidatedReport is not None

    def test_import_models_from_security(self):
        """Models importable directly from parrot.tools.security."""
        from parrot.tools.security import (
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

        assert SeverityLevel is not None
        assert SecurityFinding is not None
        assert CloudProvider is not None
        assert ComparisonDelta is not None
        assert ComplianceFramework is not None
        assert ConsolidatedReport is not None
        assert FindingSource is not None
        assert ScanResult is not None
        assert ScanSummary is not None

    def test_import_base_classes(self):
        """Base classes importable."""
        from parrot.tools.security import (
            BaseExecutor,
            BaseExecutorConfig,
            BaseParser,
        )

        assert BaseExecutor is not None
        assert BaseExecutorConfig is not None
        assert BaseParser is not None

    def test_import_prowler_components(self):
        """Prowler components importable."""
        from parrot.tools.security.prowler import (
            ProwlerConfig,
            ProwlerExecutor,
            ProwlerParser,
        )

        assert ProwlerExecutor is not None
        assert ProwlerConfig is not None
        assert ProwlerParser is not None

    def test_import_prowler_from_security(self):
        """Prowler components importable from parrot.tools.security."""
        from parrot.tools.security import (
            ProwlerConfig,
            ProwlerExecutor,
            ProwlerParser,
        )

        assert ProwlerExecutor is not None
        assert ProwlerConfig is not None
        assert ProwlerParser is not None

    def test_import_trivy_components(self):
        """Trivy components importable."""
        from parrot.tools.security.trivy import (
            TrivyConfig,
            TrivyExecutor,
            TrivyParser,
        )

        assert TrivyExecutor is not None
        assert TrivyConfig is not None
        assert TrivyParser is not None

    def test_import_trivy_from_security(self):
        """Trivy components importable from parrot.tools.security."""
        from parrot.tools.security import (
            TrivyConfig,
            TrivyExecutor,
            TrivyParser,
        )

        assert TrivyExecutor is not None
        assert TrivyConfig is not None
        assert TrivyParser is not None

    def test_import_checkov_components(self):
        """Checkov components importable."""
        from parrot.tools.security.checkov import (
            CheckovConfig,
            CheckovExecutor,
            CheckovParser,
        )

        assert CheckovExecutor is not None
        assert CheckovConfig is not None
        assert CheckovParser is not None

    def test_import_checkov_from_security(self):
        """Checkov components importable from parrot.tools.security."""
        from parrot.tools.security import (
            CheckovConfig,
            CheckovExecutor,
            CheckovParser,
        )

        assert CheckovExecutor is not None
        assert CheckovConfig is not None
        assert CheckovParser is not None

    def test_import_reports(self):
        """Report components importable."""
        from parrot.tools.security.reports import (
            ComplianceMapper,
            ReportGenerator,
        )

        assert ComplianceMapper is not None
        assert ReportGenerator is not None

    def test_import_reports_from_security(self):
        """Report components importable from parrot.tools.security."""
        from parrot.tools.security import (
            ComplianceMapper,
            ReportGenerator,
        )

        assert ComplianceMapper is not None
        assert ReportGenerator is not None

    def test_all_defined(self):
        """__all__ is defined in security package."""
        from parrot.tools import security

        assert hasattr(security, "__all__")
        assert len(security.__all__) > 0

    def test_all_exports_valid(self):
        """All items in __all__ are actually importable."""
        from parrot.tools import security

        for name in security.__all__:
            assert hasattr(security, name), f"Missing export: {name}"

    def test_no_circular_imports(self):
        """No circular import errors."""
        # If we got here without ImportError, circular imports are avoided
        import parrot.tools.security  # noqa: F401
        import parrot.tools.security.checkov  # noqa: F401
        import parrot.tools.security.cloud_posture_toolkit  # noqa: F401
        import parrot.tools.security.compliance_report_toolkit  # noqa: F401
        import parrot.tools.security.container_security_toolkit  # noqa: F401
        import parrot.tools.security.models  # noqa: F401
        import parrot.tools.security.prowler  # noqa: F401
        import parrot.tools.security.reports  # noqa: F401
        import parrot.tools.security.secrets_iac_toolkit  # noqa: F401
        import parrot.tools.security.trivy  # noqa: F401

        assert True


class TestToolkitInstantiation:
    """Test that toolkits can be instantiated."""

    def test_instantiate_cloud_posture(self):
        """CloudPostureToolkit can be instantiated."""
        from parrot.tools.security import CloudPostureToolkit

        toolkit = CloudPostureToolkit()
        assert toolkit is not None
        assert len(toolkit.get_tools()) > 0

    def test_instantiate_container_security(self):
        """ContainerSecurityToolkit can be instantiated."""
        from parrot.tools.security import ContainerSecurityToolkit

        toolkit = ContainerSecurityToolkit()
        assert toolkit is not None
        assert len(toolkit.get_tools()) > 0

    def test_instantiate_secrets_iac(self):
        """SecretsIaCToolkit can be instantiated."""
        from parrot.tools.security import SecretsIaCToolkit

        toolkit = SecretsIaCToolkit()
        assert toolkit is not None
        assert len(toolkit.get_tools()) > 0

    def test_instantiate_compliance_report(self):
        """ComplianceReportToolkit can be instantiated."""
        from parrot.tools.security import ComplianceReportToolkit

        toolkit = ComplianceReportToolkit()
        assert toolkit is not None
        assert len(toolkit.get_tools()) > 0

    def test_toolkits_from_tools_package(self):
        """Toolkits instantiable via parrot.tools import."""
        from parrot.tools import (
            CloudPostureToolkit,
            ComplianceReportToolkit,
            ContainerSecurityToolkit,
            SecretsIaCToolkit,
        )

        assert CloudPostureToolkit() is not None
        assert ContainerSecurityToolkit() is not None
        assert SecretsIaCToolkit() is not None
        assert ComplianceReportToolkit() is not None


class TestModelUsage:
    """Test that models can be used correctly."""

    def test_create_security_finding(self):
        """SecurityFinding model can be instantiated."""
        from parrot.tools.security import FindingSource, SecurityFinding, SeverityLevel

        finding = SecurityFinding(
            id="test-001",
            source=FindingSource.PROWLER,
            severity=SeverityLevel.CRITICAL,
            title="Test Finding",
            description="This is a test finding",
        )
        assert finding.id == "test-001"
        assert finding.severity == SeverityLevel.CRITICAL

    def test_create_scan_result(self):
        """ScanResult model can be instantiated."""
        from datetime import datetime

        from parrot.tools.security import (
            CloudProvider,
            FindingSource,
            ScanResult,
            ScanSummary,
        )

        summary = ScanSummary(
            source=FindingSource.PROWLER,
            provider=CloudProvider.AWS,
            total_findings=5,
            critical_count=1,
            high_count=2,
            medium_count=2,
            scan_timestamp=datetime.now(),
        )
        result = ScanResult(findings=[], summary=summary)
        assert result.summary.total_findings == 5

    def test_compliance_framework_enum(self):
        """ComplianceFramework enum has expected values."""
        from parrot.tools.security import ComplianceFramework

        assert ComplianceFramework.SOC2.value == "soc2"
        assert ComplianceFramework.HIPAA.value == "hipaa"
        assert ComplianceFramework.PCI_DSS.value == "pci_dss"


class TestReportComponents:
    """Test report components."""

    def test_instantiate_compliance_mapper(self):
        """ComplianceMapper can be instantiated."""
        from parrot.tools.security import ComplianceMapper

        mapper = ComplianceMapper()
        assert mapper is not None

    def test_instantiate_report_generator(self, tmp_path):
        """ReportGenerator can be instantiated."""
        from parrot.tools.security import ReportGenerator

        generator = ReportGenerator(output_dir=str(tmp_path))
        assert generator is not None
        assert generator.output_dir.exists()
