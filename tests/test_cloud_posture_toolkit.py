"""Unit tests for the CloudPostureToolkit."""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from parrot.tools.security.cloud_posture_toolkit import CloudPostureToolkit
from parrot.tools.security.models import (
    CloudProvider,
    ComparisonDelta,
    FindingSource,
    ScanResult,
    ScanSummary,
    SecurityFinding,
    SeverityLevel,
)
from parrot.tools.security.prowler.config import ProwlerConfig


@pytest.fixture
def toolkit():
    """Create a toolkit instance for testing."""
    return CloudPostureToolkit()


@pytest.fixture
def mock_scan_result():
    """Create a mock scan result with various findings."""
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
    """Test toolkit initialization."""

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

    def test_initial_last_result_is_none(self, toolkit):
        """_last_result starts as None."""
        assert toolkit._last_result is None

    def test_has_name_and_description(self, toolkit):
        """Toolkit has required name and description."""
        assert toolkit.name == "cloud_posture"
        assert "Prowler" in toolkit.description


class TestToolExposure:
    """Test that methods are properly exposed as tools."""

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

    def test_tool_count(self, toolkit):
        """Toolkit exposes exactly 9 tools."""
        tools = toolkit.get_tools()
        assert len(tools) == 9


class TestProwlerRunScan:
    """Test prowler_run_scan method."""

    @pytest.mark.asyncio
    async def test_run_scan_basic(self, toolkit, mock_scan_result):
        """Basic scan execution."""
        with patch.object(
            toolkit.executor, "run_scan", new_callable=AsyncMock
        ) as mock_exec:
            with patch.object(toolkit.parser, "parse") as mock_parse:
                mock_exec.return_value = ('{"findings": []}', "", 0)
                mock_parse.return_value = mock_scan_result

                result = await toolkit.prowler_run_scan()

                assert result.summary.total_findings == 3
                assert toolkit._last_result == result
                mock_exec.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_scan_with_parameters(self, toolkit, mock_scan_result):
        """Scan with custom parameters."""
        with patch.object(
            toolkit.executor, "run_scan", new_callable=AsyncMock
        ) as mock_exec:
            with patch.object(toolkit.parser, "parse") as mock_parse:
                mock_exec.return_value = ("{}", "", 0)
                mock_parse.return_value = mock_scan_result

                await toolkit.prowler_run_scan(
                    provider="azure",
                    services=["storage", "keyvault"],
                    regions=["eastus"],
                    severity=["critical"],
                )

                mock_exec.assert_called_once_with(
                    provider="azure",
                    services=["storage", "keyvault"],
                    checks=None,
                    filter_regions=["eastus"],
                    severity=["critical"],
                )

    @pytest.mark.asyncio
    async def test_run_scan_exclude_passing(self, toolkit, mock_scan_result):
        """exclude_passing filters PASS findings."""
        with patch.object(
            toolkit.executor, "run_scan", new_callable=AsyncMock
        ) as mock_exec:
            with patch.object(toolkit.parser, "parse") as mock_parse:
                mock_exec.return_value = ("{}", "", 0)
                mock_parse.return_value = mock_scan_result

                result = await toolkit.prowler_run_scan(exclude_passing=True)

                assert all(f.severity != SeverityLevel.PASS for f in result.findings)
                assert len(result.findings) == 2

    @pytest.mark.asyncio
    async def test_run_scan_handles_failure(self, toolkit, mock_scan_result):
        """Scan handles executor failure gracefully."""
        with patch.object(
            toolkit.executor, "run_scan", new_callable=AsyncMock
        ) as mock_exec:
            with patch.object(toolkit.parser, "parse") as mock_parse:
                mock_exec.return_value = ("", "Error message", 1)
                mock_parse.return_value = mock_scan_result

                # Should not raise, but log error
                result = await toolkit.prowler_run_scan()
                assert result is not None


class TestProwlerComplianceScan:
    """Test prowler_compliance_scan method."""

    @pytest.mark.asyncio
    async def test_compliance_scan_sets_framework(self, toolkit, mock_scan_result):
        """Compliance scan sets framework in config."""
        with patch.object(
            toolkit.executor, "run_scan", new_callable=AsyncMock
        ) as mock_exec:
            with patch.object(toolkit.parser, "parse") as mock_parse:
                mock_exec.return_value = ("{}", "", 0)
                mock_parse.return_value = mock_scan_result

                original_framework = toolkit.config.compliance_framework
                await toolkit.prowler_compliance_scan(
                    framework="cis_1.5_aws", provider="aws"
                )

                # Framework should be restored after scan
                assert toolkit.config.compliance_framework == original_framework

    @pytest.mark.asyncio
    async def test_compliance_scan_excludes_passing_by_default(
        self, toolkit, mock_scan_result
    ):
        """Compliance scan excludes passing by default."""
        with patch.object(
            toolkit.executor, "run_scan", new_callable=AsyncMock
        ) as mock_exec:
            with patch.object(toolkit.parser, "parse") as mock_parse:
                mock_exec.return_value = ("{}", "", 0)
                mock_parse.return_value = mock_scan_result

                result = await toolkit.prowler_compliance_scan(framework="soc2")

                assert all(f.severity != SeverityLevel.PASS for f in result.findings)


class TestProwlerScanService:
    """Test prowler_scan_service method."""

    @pytest.mark.asyncio
    async def test_scan_service(self, toolkit, mock_scan_result):
        """Service scan targets specific service."""
        with patch.object(
            toolkit.executor, "run_scan", new_callable=AsyncMock
        ) as mock_exec:
            with patch.object(toolkit.parser, "parse") as mock_parse:
                mock_exec.return_value = ("{}", "", 0)
                mock_parse.return_value = mock_scan_result

                await toolkit.prowler_scan_service(service="s3", provider="aws")

                mock_exec.assert_called_once()
                call_kwargs = mock_exec.call_args.kwargs
                assert call_kwargs["services"] == ["s3"]


class TestProwlerListChecks:
    """Test prowler_list_checks method."""

    @pytest.mark.asyncio
    async def test_list_checks(self, toolkit):
        """list_checks returns check list."""
        with patch.object(
            toolkit.executor, "list_checks", new_callable=AsyncMock
        ) as mock_exec:
            mock_exec.return_value = ("check1\ncheck2\ncheck3", "", 0)

            checks = await toolkit.prowler_list_checks(provider="aws")

            assert len(checks) == 3
            assert checks[0]["check_id"] == "check1"
            assert checks[0]["provider"] == "aws"

    @pytest.mark.asyncio
    async def test_list_checks_handles_failure(self, toolkit):
        """list_checks handles failure gracefully."""
        with patch.object(
            toolkit.executor, "list_checks", new_callable=AsyncMock
        ) as mock_exec:
            mock_exec.return_value = ("", "Error", 1)

            checks = await toolkit.prowler_list_checks()

            assert checks == []


class TestProwlerListServices:
    """Test prowler_list_services method."""

    @pytest.mark.asyncio
    async def test_list_services(self, toolkit):
        """list_services returns service list."""
        with patch.object(
            toolkit.executor, "list_services", new_callable=AsyncMock
        ) as mock_exec:
            mock_exec.return_value = ("s3\niam\nec2", "", 0)

            services = await toolkit.prowler_list_services(provider="aws")

            assert services == ["s3", "iam", "ec2"]

    @pytest.mark.asyncio
    async def test_list_services_handles_failure(self, toolkit):
        """list_services handles failure gracefully."""
        with patch.object(
            toolkit.executor, "list_services", new_callable=AsyncMock
        ) as mock_exec:
            mock_exec.return_value = ("", "Error", 1)

            services = await toolkit.prowler_list_services()

            assert services == []


class TestProwlerGetSummary:
    """Test prowler_get_summary method."""

    @pytest.mark.asyncio
    async def test_get_summary(self, toolkit, mock_scan_result):
        """get_summary returns last scan summary."""
        toolkit._last_result = mock_scan_result
        summary = await toolkit.prowler_get_summary()

        assert summary["total_findings"] == 3
        assert summary["critical_count"] == 1
        assert summary["high_count"] == 1
        assert summary["pass_count"] == 1

    @pytest.mark.asyncio
    async def test_get_summary_no_scan(self, toolkit):
        """get_summary returns empty when no scan run."""
        summary = await toolkit.prowler_get_summary()
        assert summary == {}

    @pytest.mark.asyncio
    async def test_get_summary_includes_provider(self, toolkit, mock_scan_result):
        """get_summary includes provider info."""
        toolkit._last_result = mock_scan_result
        summary = await toolkit.prowler_get_summary()

        assert summary["provider"] == "aws"


class TestProwlerGetFindings:
    """Test prowler_get_findings method."""

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

    @pytest.mark.asyncio
    async def test_get_findings_by_status_pass(self, toolkit, mock_scan_result):
        """get_findings filters by PASS status."""
        toolkit._last_result = mock_scan_result
        findings = await toolkit.prowler_get_findings(status="PASS")

        assert len(findings) == 1
        assert findings[0].severity == SeverityLevel.PASS

    @pytest.mark.asyncio
    async def test_get_findings_by_status_fail(self, toolkit, mock_scan_result):
        """get_findings filters by FAIL status."""
        toolkit._last_result = mock_scan_result
        findings = await toolkit.prowler_get_findings(status="FAIL")

        assert len(findings) == 2
        assert all(f.severity != SeverityLevel.PASS for f in findings)

    @pytest.mark.asyncio
    async def test_get_findings_combined_filters(self, toolkit, mock_scan_result):
        """get_findings combines multiple filters."""
        toolkit._last_result = mock_scan_result
        findings = await toolkit.prowler_get_findings(service="s3", status="FAIL")

        assert len(findings) == 1
        assert findings[0].service == "s3"
        assert findings[0].severity == SeverityLevel.CRITICAL


class TestProwlerGenerateReport:
    """Test prowler_generate_report method."""

    @pytest.mark.asyncio
    async def test_generate_report_json(self, toolkit, mock_scan_result, tmp_path):
        """generate_report creates JSON file."""
        toolkit._last_result = mock_scan_result
        output_path = str(tmp_path / "report.json")

        result_path = await toolkit.prowler_generate_report(
            output_path=output_path, format="json"
        )

        assert result_path == output_path
        assert (tmp_path / "report.json").exists()

    @pytest.mark.asyncio
    async def test_generate_report_no_scan(self, toolkit, tmp_path):
        """generate_report raises when no scan run."""
        with pytest.raises(ValueError, match="No scan results"):
            await toolkit.prowler_generate_report(
                output_path=str(tmp_path / "report.html")
            )


class TestProwlerCompareScans:
    """Test prowler_compare_scans method."""

    @pytest.mark.asyncio
    async def test_compare_scans(self, toolkit, tmp_path):
        """compare_scans identifies new and resolved findings."""
        # Create baseline
        baseline = ScanResult(
            findings=[
                SecurityFinding(
                    id="old-1",
                    source=FindingSource.PROWLER,
                    severity=SeverityLevel.HIGH,
                    title="Old",
                ),
                SecurityFinding(
                    id="same-1",
                    source=FindingSource.PROWLER,
                    severity=SeverityLevel.MEDIUM,
                    title="Same",
                ),
            ],
            summary=ScanSummary(
                source=FindingSource.PROWLER,
                provider=CloudProvider.AWS,
                total_findings=2,
                scan_timestamp=datetime.now(),
            ),
        )

        # Create current
        current = ScanResult(
            findings=[
                SecurityFinding(
                    id="same-1",
                    source=FindingSource.PROWLER,
                    severity=SeverityLevel.MEDIUM,
                    title="Same",
                ),
                SecurityFinding(
                    id="new-1",
                    source=FindingSource.PROWLER,
                    severity=SeverityLevel.CRITICAL,
                    title="New",
                ),
            ],
            summary=ScanSummary(
                source=FindingSource.PROWLER,
                provider=CloudProvider.AWS,
                total_findings=2,
                scan_timestamp=datetime.now(),
            ),
        )

        # Save baseline
        baseline_path = tmp_path / "baseline.json"
        toolkit.parser.save_result(baseline, str(baseline_path))

        # Set current as last result
        toolkit._last_result = current

        # Compare
        delta = await toolkit.prowler_compare_scans(baseline_path=str(baseline_path))

        assert isinstance(delta, ComparisonDelta)
        assert len(delta.new_findings) == 1
        assert delta.new_findings[0].id == "new-1"
        assert len(delta.resolved_findings) == 1
        assert delta.resolved_findings[0].id == "old-1"
        assert len(delta.unchanged_findings) == 1
        assert delta.unchanged_findings[0].id == "same-1"

    @pytest.mark.asyncio
    async def test_compare_scans_no_current(self, toolkit, tmp_path):
        """compare_scans raises when no current scan."""
        baseline_path = tmp_path / "baseline.json"
        baseline_path.write_text("{}")

        with pytest.raises(ValueError, match="No current scan"):
            await toolkit.prowler_compare_scans(baseline_path=str(baseline_path))


class TestImports:
    """Test module imports."""

    def test_import_from_security_package(self):
        """CloudPostureToolkit can be imported from security package."""
        from parrot.tools.security import CloudPostureToolkit

        toolkit = CloudPostureToolkit()
        assert toolkit is not None

    def test_import_direct(self):
        """CloudPostureToolkit can be imported directly."""
        from parrot.tools.security.cloud_posture_toolkit import CloudPostureToolkit

        assert CloudPostureToolkit is not None
