"""Unit tests for the SecretsIaCToolkit."""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from parrot.tools.security.checkov.config import CheckovConfig
from parrot.tools.security.models import (
    CloudProvider,
    FindingSource,
    ScanResult,
    ScanSummary,
    SecurityFinding,
    SeverityLevel,
)
from parrot.tools.security.secrets_iac_toolkit import SecretsIaCToolkit


@pytest.fixture
def toolkit():
    """Create a toolkit instance for testing."""
    return SecretsIaCToolkit()


@pytest.fixture
def mock_scan_result():
    """Create a mock ScanResult for testing."""
    findings = [
        SecurityFinding(
            id="CKV_AWS_21",
            source=FindingSource.CHECKOV,
            severity=SeverityLevel.MEDIUM,
            title="S3 versioning disabled",
            description="S3 bucket does not have versioning enabled",
            resource="aws_s3_bucket.data",
            resource_type="terraform",
        ),
        SecurityFinding(
            id="CKV_AWS_19",
            source=FindingSource.CHECKOV,
            severity=SeverityLevel.HIGH,
            title="S3 encryption disabled",
            description="S3 bucket does not have encryption enabled",
            resource="aws_s3_bucket.data",
            resource_type="terraform",
        ),
        SecurityFinding(
            id="CKV_DOCKER_3",
            source=FindingSource.CHECKOV,
            severity=SeverityLevel.MEDIUM,
            title="Dockerfile USER not set",
            description="No USER instruction in Dockerfile",
            resource="Dockerfile",
            resource_type="dockerfile",
        ),
        SecurityFinding(
            id="CKV_SECRET_1",
            source=FindingSource.CHECKOV,
            severity=SeverityLevel.CRITICAL,
            title="Hardcoded secret found",
            description="Secret detected in code",
            resource="config.py",
            resource_type="secrets",
        ),
    ]
    summary = ScanSummary(
        source=FindingSource.CHECKOV,
        provider=CloudProvider.LOCAL,
        total_findings=4,
        critical_count=1,
        high_count=1,
        medium_count=2,
        scan_timestamp=datetime.now(),
        services_scanned=["terraform", "dockerfile", "secrets"],
    )
    return ScanResult(findings=findings, summary=summary)


@pytest.fixture
def baseline_scan_result():
    """Create a baseline ScanResult for comparison tests."""
    findings = [
        SecurityFinding(
            id="CKV_AWS_21",
            source=FindingSource.CHECKOV,
            severity=SeverityLevel.MEDIUM,
            title="S3 versioning disabled",
            resource_type="terraform",
        ),
        SecurityFinding(
            id="CKV_AWS_OLD",
            source=FindingSource.CHECKOV,
            severity=SeverityLevel.HIGH,
            title="Old finding now resolved",
            resource_type="terraform",
        ),
    ]
    summary = ScanSummary(
        source=FindingSource.CHECKOV,
        provider=CloudProvider.LOCAL,
        total_findings=2,
        high_count=1,
        medium_count=1,
        scan_timestamp=datetime(2024, 1, 1),
    )
    return ScanResult(findings=findings, summary=summary)


class TestToolkitInitialization:
    """Test toolkit initialization."""

    def test_default_config(self, toolkit):
        """Toolkit initializes with default config."""
        assert toolkit.config.docker_image == "bridgecrew/checkov:latest"
        assert toolkit.executor is not None
        assert toolkit.parser is not None
        assert toolkit._last_result is None

    def test_custom_config(self):
        """Toolkit accepts custom config."""
        config = CheckovConfig(frameworks=["terraform"], soft_fail=True)
        toolkit = SecretsIaCToolkit(config=config)
        assert toolkit.config.frameworks == ["terraform"]
        assert toolkit.config.soft_fail is True

    def test_toolkit_name(self, toolkit):
        """Toolkit has correct name and description."""
        assert toolkit.name == "secrets_iac"
        assert "Checkov" in toolkit.description


class TestToolExposure:
    """Test that tools are properly exposed."""

    def test_get_tools_returns_list(self, toolkit):
        """get_tools() returns a list of tools."""
        tools = toolkit.get_tools()
        assert isinstance(tools, list)
        assert len(tools) > 0

    def test_all_methods_exposed(self, toolkit):
        """All public async methods are exposed as tools."""
        tool_names = toolkit.list_tool_names()
        expected = [
            "checkov_scan_directory",
            "checkov_scan_file",
            "checkov_scan_terraform",
            "checkov_scan_cloudformation",
            "checkov_scan_kubernetes",
            "checkov_scan_dockerfile",
            "checkov_scan_helm",
            "checkov_scan_secrets",
            "checkov_scan_github_actions",
            "checkov_list_checks",
            "checkov_get_summary",
            "checkov_get_findings",
            "checkov_generate_report",
            "checkov_compare_scans",
        ]
        for name in expected:
            assert name in tool_names, f"Missing tool: {name}"

    def test_tools_have_descriptions(self, toolkit):
        """All tools have non-empty descriptions."""
        tools = toolkit.get_tools()
        for tool in tools:
            assert tool.description, f"Tool {tool.name} has no description"


class TestCheckovScanDirectory:
    """Test directory scanning."""

    @pytest.mark.asyncio
    async def test_scan_directory_basic(self, toolkit, mock_scan_result):
        """Basic directory scan execution."""
        with patch.object(
            toolkit.executor, "scan_directory", new_callable=AsyncMock
        ) as mock_exec:
            with patch.object(toolkit.parser, "parse") as mock_parse:
                mock_exec.return_value = ("{}", "", 0)
                mock_parse.return_value = mock_scan_result

                result = await toolkit.checkov_scan_directory(path="/app/terraform")

                assert result.summary.total_findings == 4
                assert toolkit._last_result == result
                mock_exec.assert_called_once()

    @pytest.mark.asyncio
    async def test_scan_directory_with_frameworks(self, toolkit, mock_scan_result):
        """Directory scan with framework filter."""
        with patch.object(
            toolkit.executor, "scan_directory", new_callable=AsyncMock
        ) as mock_exec:
            with patch.object(toolkit.parser, "parse") as mock_parse:
                mock_exec.return_value = ("{}", "", 0)
                mock_parse.return_value = mock_scan_result

                await toolkit.checkov_scan_directory(
                    path="/app", frameworks=["terraform", "cloudformation"]
                )

                call_kwargs = mock_exec.call_args.kwargs
                assert call_kwargs["frameworks"] == ["terraform", "cloudformation"]

    @pytest.mark.asyncio
    async def test_scan_directory_with_skip_checks(self, toolkit, mock_scan_result):
        """Directory scan with skip_checks."""
        with patch.object(
            toolkit.executor, "scan_directory", new_callable=AsyncMock
        ) as mock_exec:
            with patch.object(toolkit.parser, "parse") as mock_parse:
                mock_exec.return_value = ("{}", "", 0)
                mock_parse.return_value = mock_scan_result

                await toolkit.checkov_scan_directory(
                    path="/app", skip_checks=["CKV_AWS_1"]
                )

                call_kwargs = mock_exec.call_args.kwargs
                assert call_kwargs["skip_checks"] == ["CKV_AWS_1"]


class TestSpecializedScans:
    """Test specialized scan methods."""

    @pytest.mark.asyncio
    async def test_scan_terraform(self, toolkit, mock_scan_result):
        """Terraform scan sets framework automatically."""
        with patch.object(
            toolkit.executor, "scan_terraform", new_callable=AsyncMock
        ) as mock_exec:
            with patch.object(toolkit.parser, "parse") as mock_parse:
                mock_exec.return_value = ("{}", "", 0)
                mock_parse.return_value = mock_scan_result

                result = await toolkit.checkov_scan_terraform(
                    path="/app/terraform", download_modules=True
                )

                assert result is not None
                call_kwargs = mock_exec.call_args.kwargs
                assert call_kwargs["download_modules"] is True

    @pytest.mark.asyncio
    async def test_scan_cloudformation(self, toolkit, mock_scan_result):
        """CloudFormation scan works."""
        with patch.object(
            toolkit.executor, "scan_cloudformation", new_callable=AsyncMock
        ) as mock_exec:
            with patch.object(toolkit.parser, "parse") as mock_parse:
                mock_exec.return_value = ("{}", "", 0)
                mock_parse.return_value = mock_scan_result

                result = await toolkit.checkov_scan_cloudformation(path="/app/cfn")

                assert result is not None
                mock_exec.assert_called_once()

    @pytest.mark.asyncio
    async def test_scan_kubernetes(self, toolkit, mock_scan_result):
        """Kubernetes scan works."""
        with patch.object(
            toolkit.executor, "scan_kubernetes", new_callable=AsyncMock
        ) as mock_exec:
            with patch.object(toolkit.parser, "parse") as mock_parse:
                mock_exec.return_value = ("{}", "", 0)
                mock_parse.return_value = mock_scan_result

                result = await toolkit.checkov_scan_kubernetes(path="/app/k8s")

                assert result is not None

    @pytest.mark.asyncio
    async def test_scan_dockerfile(self, toolkit, mock_scan_result):
        """Dockerfile scan works."""
        with patch.object(
            toolkit.executor, "scan_dockerfile", new_callable=AsyncMock
        ) as mock_exec:
            with patch.object(toolkit.parser, "parse") as mock_parse:
                mock_exec.return_value = ("{}", "", 0)
                mock_parse.return_value = mock_scan_result

                result = await toolkit.checkov_scan_dockerfile(path="/app/Dockerfile")

                assert result is not None

    @pytest.mark.asyncio
    async def test_scan_helm(self, toolkit, mock_scan_result):
        """Helm scan works."""
        with patch.object(
            toolkit.executor, "scan_directory", new_callable=AsyncMock
        ) as mock_exec:
            with patch.object(toolkit.parser, "parse") as mock_parse:
                mock_exec.return_value = ("{}", "", 0)
                mock_parse.return_value = mock_scan_result

                result = await toolkit.checkov_scan_helm(path="/app/charts/myapp")

                assert result is not None
                call_kwargs = mock_exec.call_args.kwargs
                assert call_kwargs["frameworks"] == ["helm"]

    @pytest.mark.asyncio
    async def test_scan_secrets(self, toolkit, mock_scan_result):
        """Secrets scan works."""
        with patch.object(
            toolkit.executor, "scan_secrets", new_callable=AsyncMock
        ) as mock_exec:
            with patch.object(toolkit.parser, "parse") as mock_parse:
                mock_exec.return_value = ("{}", "", 0)
                mock_parse.return_value = mock_scan_result

                result = await toolkit.checkov_scan_secrets(
                    path="/app/src", skip_paths=["node_modules"]
                )

                assert result is not None
                call_kwargs = mock_exec.call_args.kwargs
                assert call_kwargs["skip_paths"] == ["node_modules"]

    @pytest.mark.asyncio
    async def test_scan_github_actions(self, toolkit, mock_scan_result):
        """GitHub Actions scan works."""
        with patch.object(
            toolkit.executor, "scan_github_actions", new_callable=AsyncMock
        ) as mock_exec:
            with patch.object(toolkit.parser, "parse") as mock_parse:
                mock_exec.return_value = ("{}", "", 0)
                mock_parse.return_value = mock_scan_result

                result = await toolkit.checkov_scan_github_actions(
                    path="./.github/workflows"
                )

                assert result is not None


class TestCheckovScanFile:
    """Test single file scanning."""

    @pytest.mark.asyncio
    async def test_scan_file(self, toolkit, mock_scan_result):
        """Single file scan works."""
        with patch.object(
            toolkit.executor, "scan_file", new_callable=AsyncMock
        ) as mock_exec:
            with patch.object(toolkit.parser, "parse") as mock_parse:
                mock_exec.return_value = ("{}", "", 0)
                mock_parse.return_value = mock_scan_result

                result = await toolkit.checkov_scan_file(
                    file_path="./main.tf", framework="terraform"
                )

                assert result is not None
                call_kwargs = mock_exec.call_args.kwargs
                assert call_kwargs["frameworks"] == ["terraform"]


class TestGetSummary:
    """Test summary retrieval."""

    @pytest.mark.asyncio
    async def test_get_summary_with_results(self, toolkit, mock_scan_result):
        """get_summary returns data when scan exists."""
        toolkit._last_result = mock_scan_result
        summary = await toolkit.checkov_get_summary()

        assert summary["total_findings"] == 4
        assert summary["critical_count"] == 1
        assert summary["high_count"] == 1
        assert summary["medium_count"] == 2
        assert "terraform" in summary["services_scanned"]

    @pytest.mark.asyncio
    async def test_get_summary_no_results(self, toolkit):
        """get_summary returns empty dict when no scan."""
        summary = await toolkit.checkov_get_summary()
        assert summary == {}


class TestGetFindings:
    """Test findings retrieval with filters."""

    @pytest.mark.asyncio
    async def test_get_findings_all(self, toolkit, mock_scan_result):
        """get_findings returns all findings without filters."""
        toolkit._last_result = mock_scan_result
        findings = await toolkit.checkov_get_findings()
        assert len(findings) == 4

    @pytest.mark.asyncio
    async def test_get_findings_by_severity(self, toolkit, mock_scan_result):
        """get_findings filters by severity."""
        toolkit._last_result = mock_scan_result
        findings = await toolkit.checkov_get_findings(severity="HIGH")
        assert len(findings) == 1
        assert findings[0].severity == SeverityLevel.HIGH

    @pytest.mark.asyncio
    async def test_get_findings_by_critical(self, toolkit, mock_scan_result):
        """get_findings filters CRITICAL severity."""
        toolkit._last_result = mock_scan_result
        findings = await toolkit.checkov_get_findings(severity="CRITICAL")
        assert len(findings) == 1
        assert findings[0].severity == SeverityLevel.CRITICAL

    @pytest.mark.asyncio
    async def test_get_findings_by_framework(self, toolkit, mock_scan_result):
        """get_findings filters by framework (resource_type)."""
        toolkit._last_result = mock_scan_result
        findings = await toolkit.checkov_get_findings(framework="terraform")
        assert len(findings) == 2
        assert all(f.resource_type == "terraform" for f in findings)

    @pytest.mark.asyncio
    async def test_get_findings_by_dockerfile(self, toolkit, mock_scan_result):
        """get_findings filters dockerfile framework."""
        toolkit._last_result = mock_scan_result
        findings = await toolkit.checkov_get_findings(framework="dockerfile")
        assert len(findings) == 1
        assert findings[0].resource_type == "dockerfile"

    @pytest.mark.asyncio
    async def test_get_findings_with_limit(self, toolkit, mock_scan_result):
        """get_findings respects limit."""
        toolkit._last_result = mock_scan_result
        findings = await toolkit.checkov_get_findings(limit=2)
        assert len(findings) == 2

    @pytest.mark.asyncio
    async def test_get_findings_combined_filters(self, toolkit, mock_scan_result):
        """get_findings with multiple filters."""
        toolkit._last_result = mock_scan_result
        findings = await toolkit.checkov_get_findings(
            severity="MEDIUM", framework="terraform"
        )
        assert len(findings) == 1
        assert findings[0].id == "CKV_AWS_21"

    @pytest.mark.asyncio
    async def test_get_findings_no_results(self, toolkit):
        """get_findings returns empty list when no scan."""
        findings = await toolkit.checkov_get_findings()
        assert findings == []


class TestListChecks:
    """Test listing available checks."""

    @pytest.mark.asyncio
    async def test_list_checks(self, toolkit):
        """list_checks returns available checks."""
        with patch.object(
            toolkit.executor, "list_checks", new_callable=AsyncMock
        ) as mock_exec:
            mock_exec.return_value = (
                '[{"id": "CKV_AWS_1", "name": "S3 versioning"}]',
                "",
                0,
            )
            result = await toolkit.checkov_list_checks(framework="terraform")
            assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_list_checks_non_json(self, toolkit):
        """list_checks handles non-JSON output."""
        with patch.object(
            toolkit.executor, "list_checks", new_callable=AsyncMock
        ) as mock_exec:
            mock_exec.return_value = ("CKV_AWS_1\nCKV_AWS_2", "", 0)
            result = await toolkit.checkov_list_checks()
            assert isinstance(result, list)


class TestGenerateReport:
    """Test report generation."""

    @pytest.mark.asyncio
    async def test_generate_report_json(self, toolkit, mock_scan_result, tmp_path):
        """generate_report creates JSON report."""
        toolkit._last_result = mock_scan_result
        output_path = str(tmp_path / "report.json")

        with patch.object(toolkit.parser, "save_result") as mock_save:
            result = await toolkit.checkov_generate_report(
                output_path=output_path, format="json"
            )

            assert result == output_path
            mock_save.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_report_no_scan(self, toolkit):
        """generate_report raises error without scan."""
        with pytest.raises(ValueError, match="No scan results"):
            await toolkit.checkov_generate_report(output_path="/tmp/report.json")


class TestCompareScans:
    """Test scan comparison functionality."""

    @pytest.mark.asyncio
    async def test_compare_scans_basic(
        self, toolkit, mock_scan_result, baseline_scan_result
    ):
        """compare_scans identifies differences."""
        toolkit._last_result = mock_scan_result

        with patch.object(toolkit.parser, "load_result") as mock_load:
            mock_load.return_value = baseline_scan_result

            delta = await toolkit.checkov_compare_scans(baseline_path="/baseline.json")

            # CKV_AWS_21 is in both (unchanged)
            # CKV_AWS_19, CKV_DOCKER_3, CKV_SECRET_1 are new
            # CKV_AWS_OLD is resolved
            assert len(delta.new_findings) == 3
            assert len(delta.resolved_findings) == 1
            assert len(delta.unchanged_findings) == 1
            assert delta.summary is not None

    @pytest.mark.asyncio
    async def test_compare_scans_no_current(self, toolkit):
        """compare_scans raises error without current scan."""
        with pytest.raises(ValueError, match="No current scan"):
            await toolkit.checkov_compare_scans(baseline_path="/baseline.json")

    @pytest.mark.asyncio
    async def test_compare_scans_severity_trend(
        self, toolkit, mock_scan_result, baseline_scan_result
    ):
        """compare_scans calculates severity trend."""
        toolkit._last_result = mock_scan_result

        with patch.object(toolkit.parser, "load_result") as mock_load:
            mock_load.return_value = baseline_scan_result

            delta = await toolkit.checkov_compare_scans(baseline_path="/baseline.json")

            # Check severity trend is populated
            assert isinstance(delta.severity_trend, dict)


class TestImports:
    """Test module imports."""

    def test_import_from_security_package(self):
        """SecretsIaCToolkit can be imported from security package."""
        from parrot.tools.security import SecretsIaCToolkit

        toolkit = SecretsIaCToolkit()
        assert toolkit is not None

    def test_import_directly(self):
        """SecretsIaCToolkit can be imported directly."""
        from parrot.tools.security.secrets_iac_toolkit import SecretsIaCToolkit

        assert SecretsIaCToolkit is not None
