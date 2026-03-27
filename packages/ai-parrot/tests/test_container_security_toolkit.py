"""Unit tests for the ContainerSecurityToolkit."""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from parrot.tools.security.container_security_toolkit import ContainerSecurityToolkit
from parrot.tools.security.models import (
    CloudProvider,
    ComparisonDelta,
    FindingSource,
    ScanResult,
    ScanSummary,
    SecurityFinding,
    SeverityLevel,
)
from parrot.tools.security.trivy.config import TrivyConfig


@pytest.fixture
def toolkit():
    """Create a toolkit instance for testing."""
    return ContainerSecurityToolkit()


@pytest.fixture
def mock_scan_result():
    """Create a mock scan result with mixed finding types."""
    findings = [
        SecurityFinding(
            id="trivy-CVE-2023-1234-pkg",
            source=FindingSource.TRIVY,
            severity=SeverityLevel.CRITICAL,
            title="Critical CVE",
            resource_type="vulnerability",
            check_id="CVE-2023-1234",
        ),
        SecurityFinding(
            id="trivy-secret-aws-key",
            source=FindingSource.TRIVY,
            severity=SeverityLevel.HIGH,
            title="Exposed AWS Key",
            resource_type="secret",
            check_id="aws-access-key-id",
        ),
        SecurityFinding(
            id="trivy-misconfig-DS002",
            source=FindingSource.TRIVY,
            severity=SeverityLevel.MEDIUM,
            title="Root user in Dockerfile",
            resource_type="Dockerfile",
            check_id="DS002",
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
        services_scanned=["vulnerability", "secret", "Dockerfile"],
    )
    return ScanResult(findings=findings, summary=summary)


@pytest.fixture
def baseline_scan_result():
    """Create a baseline scan result for comparison tests."""
    findings = [
        SecurityFinding(
            id="trivy-CVE-2023-1234-pkg",
            source=FindingSource.TRIVY,
            severity=SeverityLevel.CRITICAL,
            title="Critical CVE",
            resource_type="vulnerability",
        ),
        SecurityFinding(
            id="trivy-CVE-2023-OLD",
            source=FindingSource.TRIVY,
            severity=SeverityLevel.HIGH,
            title="Old resolved issue",
            resource_type="vulnerability",
        ),
    ]
    summary = ScanSummary(
        source=FindingSource.TRIVY,
        provider=CloudProvider.LOCAL,
        total_findings=2,
        critical_count=1,
        high_count=1,
        scan_timestamp=datetime.now(),
    )
    return ScanResult(findings=findings, summary=summary)


class TestToolkitInitialization:
    """Test toolkit initialization."""

    def test_default_config(self, toolkit):
        """Toolkit initializes with default config."""
        assert toolkit.config.docker_image == "aquasec/trivy:latest"
        assert toolkit.executor is not None
        assert toolkit.parser is not None
        assert toolkit._last_result is None

    def test_custom_config(self):
        """Toolkit accepts custom config."""
        config = TrivyConfig(severity_filter=["CRITICAL"])
        toolkit = ContainerSecurityToolkit(config=config)
        assert toolkit.config.severity_filter == ["CRITICAL"]

    def test_name_and_description(self, toolkit):
        """Toolkit has correct name and description."""
        assert toolkit.name == "container_security"
        assert "Trivy" in toolkit.description


class TestToolExposure:
    """Test tool exposure via AbstractToolkit."""

    def test_get_tools_returns_list(self, toolkit):
        """get_tools() returns a list of tools."""
        tools = toolkit.get_tools()
        assert isinstance(tools, list)
        assert len(tools) > 0

    def test_all_methods_exposed(self, toolkit):
        """All 10 public async methods are exposed as tools."""
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

    def test_tool_count(self, toolkit):
        """Exactly 10 tools are exposed."""
        tool_names = toolkit.list_tool_names()
        assert len(tool_names) == 10


class TestTrivyScanImage:
    """Test trivy_scan_image method."""

    @pytest.mark.asyncio
    async def test_scan_image_basic(self, toolkit, mock_scan_result):
        """Basic image scan execution."""
        with patch.object(toolkit.executor, "scan_image", new_callable=AsyncMock) as mock_exec:
            with patch.object(toolkit.parser, "parse") as mock_parse:
                mock_exec.return_value = ("{}", "", 0)
                mock_parse.return_value = mock_scan_result

                result = await toolkit.trivy_scan_image(image="nginx:latest")

                assert result.summary.total_findings == 3
                assert toolkit._last_result == result
                mock_exec.assert_called_once()

    @pytest.mark.asyncio
    async def test_scan_image_with_options(self, toolkit, mock_scan_result):
        """Image scan with severity and scanners options."""
        with patch.object(toolkit.executor, "scan_image", new_callable=AsyncMock) as mock_exec:
            with patch.object(toolkit.parser, "parse") as mock_parse:
                mock_exec.return_value = ("{}", "", 0)
                mock_parse.return_value = mock_scan_result

                await toolkit.trivy_scan_image(
                    image="nginx:latest",
                    severity=["CRITICAL", "HIGH"],
                    ignore_unfixed=True,
                    scanners=["vuln", "secret"],
                )

                mock_exec.assert_called_once_with(
                    image="nginx:latest",
                    severity=["CRITICAL", "HIGH"],
                    ignore_unfixed=True,
                    scanners=["vuln", "secret"],
                )

    @pytest.mark.asyncio
    async def test_scan_image_stores_result(self, toolkit, mock_scan_result):
        """Image scan stores result for later retrieval."""
        with patch.object(toolkit.executor, "scan_image", new_callable=AsyncMock) as mock_exec:
            with patch.object(toolkit.parser, "parse") as mock_parse:
                mock_exec.return_value = ("{}", "", 0)
                mock_parse.return_value = mock_scan_result

                await toolkit.trivy_scan_image(image="alpine:3.18")
                assert toolkit._last_result is not None
                assert toolkit._last_result.summary.total_findings == 3


class TestTrivyScanFilesystem:
    """Test trivy_scan_filesystem method."""

    @pytest.mark.asyncio
    async def test_scan_filesystem(self, toolkit, mock_scan_result):
        """Filesystem scan execution."""
        with patch.object(toolkit.executor, "scan_filesystem", new_callable=AsyncMock) as mock_exec:
            with patch.object(toolkit.parser, "parse") as mock_parse:
                mock_exec.return_value = ("{}", "", 0)
                mock_parse.return_value = mock_scan_result

                result = await toolkit.trivy_scan_filesystem(path="/app")

                assert result is not None
                mock_exec.assert_called_once()


class TestTrivyScanRepo:
    """Test trivy_scan_repo method."""

    @pytest.mark.asyncio
    async def test_scan_repo_with_branch(self, toolkit, mock_scan_result):
        """Repository scan with branch specification."""
        with patch.object(toolkit.executor, "scan_repository", new_callable=AsyncMock) as mock_exec:
            with patch.object(toolkit.parser, "parse") as mock_parse:
                mock_exec.return_value = ("{}", "", 0)
                mock_parse.return_value = mock_scan_result

                result = await toolkit.trivy_scan_repo(
                    repo_url="https://github.com/org/repo.git",
                    branch="main",
                )

                assert result is not None
                mock_exec.assert_called_once_with(
                    repo_url="https://github.com/org/repo.git",
                    branch="main",
                    severity=None,
                )


class TestTrivyScanK8s:
    """Test trivy_scan_k8s method."""

    @pytest.mark.asyncio
    async def test_scan_k8s_with_context(self, toolkit, mock_scan_result):
        """K8s scan with context and namespace."""
        with patch.object(toolkit.executor, "scan_k8s", new_callable=AsyncMock) as mock_exec:
            with patch.object(toolkit.parser, "parse") as mock_parse:
                mock_exec.return_value = ("{}", "", 0)
                mock_parse.return_value = mock_scan_result

                result = await toolkit.trivy_scan_k8s(
                    context="my-cluster",
                    namespace="default",
                )

                assert result is not None
                mock_exec.assert_called_once()

    @pytest.mark.asyncio
    async def test_scan_k8s_with_compliance(self, toolkit, mock_scan_result):
        """K8s scan with compliance specification."""
        with patch.object(toolkit.executor, "scan_k8s", new_callable=AsyncMock) as mock_exec:
            with patch.object(toolkit.parser, "parse") as mock_parse:
                mock_exec.return_value = ("{}", "", 0)
                mock_parse.return_value = mock_scan_result

                await toolkit.trivy_scan_k8s(
                    context="prod",
                    compliance="k8s-cis-1.23",
                )

                mock_exec.assert_called_once_with(
                    context="prod",
                    namespace=None,
                    compliance="k8s-cis-1.23",
                    components=None,
                )


class TestTrivyScanIac:
    """Test trivy_scan_iac method."""

    @pytest.mark.asyncio
    async def test_scan_iac_terraform(self, toolkit, mock_scan_result):
        """IaC scan for Terraform configs."""
        with patch.object(toolkit.executor, "scan_config", new_callable=AsyncMock) as mock_exec:
            with patch.object(toolkit.parser, "parse") as mock_parse:
                mock_exec.return_value = ("{}", "", 0)
                mock_parse.return_value = mock_scan_result

                result = await toolkit.trivy_scan_iac(
                    path="./terraform",
                    compliance="aws-cis-1.4.0",
                )

                assert result is not None
                mock_exec.assert_called_once()


class TestTrivyGenerateSbom:
    """Test trivy_generate_sbom method."""

    @pytest.mark.asyncio
    async def test_generate_sbom_with_output_path(self, toolkit, tmp_path):
        """SBOM generation with output path returns the path."""
        with patch.object(toolkit.executor, "generate_sbom", new_callable=AsyncMock) as mock_exec:
            sbom_content = '{"bomFormat": "CycloneDX"}'
            mock_exec.return_value = (sbom_content, "", 0)

            output_path = str(tmp_path / "sbom.json")
            result = await toolkit.trivy_generate_sbom(
                target="myapp:v1",
                format="cyclonedx",
                output_path=output_path,
            )

            assert result == output_path
            mock_exec.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_sbom_returns_content(self, toolkit):
        """SBOM generation without output path returns content."""
        with patch.object(toolkit.executor, "generate_sbom", new_callable=AsyncMock) as mock_exec:
            sbom_content = '{"bomFormat": "CycloneDX"}'
            mock_exec.return_value = (sbom_content, "", 0)

            result = await toolkit.trivy_generate_sbom(
                target="myapp:v1",
                format="spdx",
            )

            assert result == sbom_content


class TestTrivyGetSummary:
    """Test trivy_get_summary method."""

    @pytest.mark.asyncio
    async def test_get_summary_returns_dict(self, toolkit, mock_scan_result):
        """get_summary returns a dictionary with stats."""
        toolkit._last_result = mock_scan_result
        summary = await toolkit.trivy_get_summary()

        assert isinstance(summary, dict)
        assert summary["total_findings"] == 3
        assert summary["critical_count"] == 1
        assert summary["high_count"] == 1
        assert summary["medium_count"] == 1

    @pytest.mark.asyncio
    async def test_get_summary_no_scan(self, toolkit):
        """get_summary returns empty dict when no scan run."""
        summary = await toolkit.trivy_get_summary()
        assert summary == {}

    @pytest.mark.asyncio
    async def test_get_summary_includes_services(self, toolkit, mock_scan_result):
        """get_summary includes services_scanned list."""
        toolkit._last_result = mock_scan_result
        summary = await toolkit.trivy_get_summary()

        assert "services_scanned" in summary
        assert "vulnerability" in summary["services_scanned"]


class TestTrivyGetFindings:
    """Test trivy_get_findings method."""

    @pytest.mark.asyncio
    async def test_get_findings_all(self, toolkit, mock_scan_result):
        """get_findings returns all findings without filters."""
        toolkit._last_result = mock_scan_result
        findings = await toolkit.trivy_get_findings()

        assert len(findings) == 3

    @pytest.mark.asyncio
    async def test_get_findings_by_severity(self, toolkit, mock_scan_result):
        """get_findings filters by severity."""
        toolkit._last_result = mock_scan_result
        findings = await toolkit.trivy_get_findings(severity="CRITICAL")

        assert len(findings) == 1
        assert findings[0].severity == SeverityLevel.CRITICAL

    @pytest.mark.asyncio
    async def test_get_findings_by_scanner_type(self, toolkit, mock_scan_result):
        """get_findings filters by scanner_type (resource_type)."""
        toolkit._last_result = mock_scan_result
        findings = await toolkit.trivy_get_findings(scanner_type="vulnerability")

        assert len(findings) == 1
        assert findings[0].resource_type == "vulnerability"

    @pytest.mark.asyncio
    async def test_get_findings_with_limit(self, toolkit, mock_scan_result):
        """get_findings respects limit parameter."""
        toolkit._last_result = mock_scan_result
        findings = await toolkit.trivy_get_findings(limit=1)

        assert len(findings) == 1

    @pytest.mark.asyncio
    async def test_get_findings_combined_filters(self, toolkit, mock_scan_result):
        """get_findings applies multiple filters."""
        toolkit._last_result = mock_scan_result
        findings = await toolkit.trivy_get_findings(
            severity="HIGH",
            scanner_type="secret",
        )

        assert len(findings) == 1
        assert findings[0].resource_type == "secret"

    @pytest.mark.asyncio
    async def test_get_findings_no_scan(self, toolkit):
        """get_findings returns empty list when no scan run."""
        findings = await toolkit.trivy_get_findings()
        assert findings == []


class TestTrivyGenerateReport:
    """Test trivy_generate_report method."""

    @pytest.mark.asyncio
    async def test_generate_report_json(self, toolkit, mock_scan_result, tmp_path):
        """Generate report in JSON format."""
        toolkit._last_result = mock_scan_result
        output_path = str(tmp_path / "report.json")

        with patch.object(toolkit.parser, "save_result") as mock_save:
            result = await toolkit.trivy_generate_report(
                output_path=output_path,
                format="json",
            )

            assert result == output_path
            mock_save.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_report_no_scan(self, toolkit, tmp_path):
        """Generate report raises when no scan run."""
        with pytest.raises(ValueError, match="No scan results"):
            await toolkit.trivy_generate_report(
                output_path=str(tmp_path / "report.html"),
            )


class TestTrivyCompareScans:
    """Test trivy_compare_scans method."""

    @pytest.mark.asyncio
    async def test_compare_scans_identifies_new(
        self, toolkit, mock_scan_result, baseline_scan_result, tmp_path
    ):
        """compare_scans identifies new findings."""
        toolkit._last_result = mock_scan_result

        with patch.object(toolkit.parser, "load_result") as mock_load:
            mock_load.return_value = baseline_scan_result

            delta = await toolkit.trivy_compare_scans(
                baseline_path=str(tmp_path / "baseline.json"),
            )

            assert isinstance(delta, ComparisonDelta)
            # mock_scan_result has 2 findings not in baseline
            assert len(delta.new_findings) == 2

    @pytest.mark.asyncio
    async def test_compare_scans_identifies_resolved(
        self, toolkit, mock_scan_result, baseline_scan_result, tmp_path
    ):
        """compare_scans identifies resolved findings."""
        toolkit._last_result = mock_scan_result

        with patch.object(toolkit.parser, "load_result") as mock_load:
            mock_load.return_value = baseline_scan_result

            delta = await toolkit.trivy_compare_scans(
                baseline_path=str(tmp_path / "baseline.json"),
            )

            # baseline has CVE-2023-OLD not in current
            assert len(delta.resolved_findings) == 1
            assert delta.resolved_findings[0].id == "trivy-CVE-2023-OLD"

    @pytest.mark.asyncio
    async def test_compare_scans_identifies_unchanged(
        self, toolkit, mock_scan_result, baseline_scan_result, tmp_path
    ):
        """compare_scans identifies unchanged findings."""
        toolkit._last_result = mock_scan_result

        with patch.object(toolkit.parser, "load_result") as mock_load:
            mock_load.return_value = baseline_scan_result

            delta = await toolkit.trivy_compare_scans(
                baseline_path=str(tmp_path / "baseline.json"),
            )

            # CVE-2023-1234 is in both
            assert len(delta.unchanged_findings) == 1
            assert delta.unchanged_findings[0].id == "trivy-CVE-2023-1234-pkg"

    @pytest.mark.asyncio
    async def test_compare_scans_no_current(self, toolkit, tmp_path):
        """compare_scans raises when no current scan."""
        with pytest.raises(ValueError, match="No current scan"):
            await toolkit.trivy_compare_scans(
                baseline_path=str(tmp_path / "baseline.json"),
            )

    @pytest.mark.asyncio
    async def test_compare_scans_summary(
        self, toolkit, mock_scan_result, baseline_scan_result, tmp_path
    ):
        """compare_scans generates human-readable summary."""
        toolkit._last_result = mock_scan_result

        with patch.object(toolkit.parser, "load_result") as mock_load:
            mock_load.return_value = baseline_scan_result

            delta = await toolkit.trivy_compare_scans(
                baseline_path=str(tmp_path / "baseline.json"),
            )

            assert delta.summary is not None
            assert "new" in delta.summary.lower()


class TestErrorHandling:
    """Test error handling scenarios."""

    @pytest.mark.asyncio
    async def test_scan_handles_executor_error(self, toolkit):
        """Scan handles non-zero exit code gracefully."""
        with patch.object(toolkit.executor, "scan_image", new_callable=AsyncMock) as mock_exec:
            with patch.object(toolkit.parser, "parse") as mock_parse:
                mock_exec.return_value = ("", "Error message", 1)
                mock_parse.return_value = ScanResult(
                    findings=[],
                    summary=ScanSummary(
                        source=FindingSource.TRIVY,
                        provider=CloudProvider.LOCAL,
                        total_findings=0,
                        scan_timestamp=datetime.now(),
                    ),
                )

                # Should not raise, just log the error
                result = await toolkit.trivy_scan_image(image="nonexistent:latest")
                assert result.summary.total_findings == 0


class TestImports:
    """Test module imports."""

    def test_import_from_security_package(self):
        """Toolkit can be imported from security package."""
        from parrot.tools.security import ContainerSecurityToolkit

        assert ContainerSecurityToolkit is not None

    def test_instantiation_from_import(self):
        """Imported toolkit can be instantiated."""
        from parrot.tools.security import ContainerSecurityToolkit

        toolkit = ContainerSecurityToolkit()
        assert toolkit is not None
        assert toolkit.name == "container_security"
