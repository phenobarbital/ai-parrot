"""Integration tests for CloudSploitToolkit."""
import json
from unittest.mock import AsyncMock, patch

import pytest

from parrot.tools.cloudsploit import CloudSploitConfig, CloudSploitToolkit


MOCK_CLOUDSPLOIT_OUTPUT = json.dumps({
    "ec2OpenSSH": {
        "title": "Open SSH",
        "category": "EC2",
        "description": "Check for open SSH",
        "results": [
            {
                "status": "FAIL",
                "region": "us-east-1",
                "resource": "sg-abc",
                "message": "Unrestricted SSH",
            },
        ],
    },
    "s3Encryption": {
        "title": "S3 Encryption",
        "category": "S3",
        "description": "Check encryption",
        "results": [
            {
                "status": "OK",
                "region": "global",
                "resource": "my-bucket",
                "message": "Encrypted",
            },
        ],
    },
})


@pytest.fixture
def config():
    return CloudSploitConfig(
        aws_access_key_id="AKIATEST",
        aws_secret_access_key="secret",
    )


@pytest.fixture
def toolkit(config):
    return CloudSploitToolkit(config=config)


def _mock_executor(toolkit, output=MOCK_CLOUDSPLOIT_OUTPUT, code=0, stderr=""):
    """Patch executor.execute to return canned output."""
    return patch.object(
        toolkit.executor,
        "execute",
        new_callable=AsyncMock,
        return_value=(output, stderr, code),
    )


# ── Tool registration ───────────────────────────────────────────────────


class TestToolRegistration:
    def test_tools_registered(self, toolkit):
        tools = toolkit.get_tools()
        names = [t.name for t in tools]
        assert "run_scan" in names
        assert "run_compliance_scan" in names
        assert "get_summary" in names
        assert "generate_report" in names
        assert "compare_scans" in names
        assert "list_findings" in names

    def test_tool_count(self, toolkit):
        tools = toolkit.get_tools()
        assert len(tools) == 6

    def test_tool_descriptions(self, toolkit):
        tools = toolkit.get_tools()
        for tool in tools:
            assert tool.description and len(tool.description) > 10


# ── run_scan ─────────────────────────────────────────────────────────────


class TestRunScan:
    @pytest.mark.asyncio
    async def test_full_scan(self, toolkit):
        with _mock_executor(toolkit):
            result = await toolkit.run_scan()
            assert result.summary.total_findings == 2
            assert result.summary.fail_count == 1
            assert result.summary.ok_count == 1

    @pytest.mark.asyncio
    async def test_scan_stores_last_result(self, toolkit):
        with _mock_executor(toolkit):
            result = await toolkit.run_scan()
            assert toolkit._last_result is result

    @pytest.mark.asyncio
    async def test_scan_with_plugins(self, toolkit):
        with _mock_executor(toolkit) as mock_exec:
            await toolkit.run_scan(plugins=["ec2OpenSSH"])
            mock_exec.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_scan_saves_to_results_dir(self, toolkit, tmp_path):
        toolkit.config.results_dir = str(tmp_path)
        with _mock_executor(toolkit):
            result = await toolkit.run_scan()
            saved_files = list(tmp_path.glob("scan_*.json"))
            assert len(saved_files) == 1

    @pytest.mark.asyncio
    async def test_scan_with_nonzero_exit(self, toolkit):
        with _mock_executor(toolkit, code=1, stderr="Docker error"):
            result = await toolkit.run_scan()
            # Should still parse output and return result
            assert result.summary.total_findings == 2


# ── run_compliance_scan ──────────────────────────────────────────────────


class TestComplianceScan:
    @pytest.mark.asyncio
    async def test_compliance_scan(self, toolkit):
        with _mock_executor(toolkit):
            result = await toolkit.run_compliance_scan(framework="pci")
            assert result is not None
            assert result.summary.compliance_framework == "pci"

    @pytest.mark.asyncio
    async def test_invalid_framework(self, toolkit):
        with pytest.raises(ValueError, match="Unknown compliance framework"):
            await toolkit.run_compliance_scan(framework="invalid")

    @pytest.mark.asyncio
    async def test_compliance_case_insensitive(self, toolkit):
        with _mock_executor(toolkit):
            result = await toolkit.run_compliance_scan(framework="HIPAA")
            assert result.summary.compliance_framework == "hipaa"


# ── get_summary ──────────────────────────────────────────────────────────


class TestGetSummary:
    @pytest.mark.asyncio
    async def test_summary_after_scan(self, toolkit):
        with _mock_executor(toolkit):
            await toolkit.run_scan()
            summary = await toolkit.get_summary()
            assert summary["total_findings"] == 2
            assert summary["fail_count"] == 1

    @pytest.mark.asyncio
    async def test_summary_no_scan(self, toolkit):
        summary = await toolkit.get_summary()
        assert "error" in summary


# ── list_findings ────────────────────────────────────────────────────────


class TestListFindings:
    @pytest.mark.asyncio
    async def test_list_all(self, toolkit):
        with _mock_executor(toolkit):
            await toolkit.run_scan()
            findings = await toolkit.list_findings()
            assert len(findings) == 2

    @pytest.mark.asyncio
    async def test_filter_by_severity(self, toolkit):
        with _mock_executor(toolkit):
            await toolkit.run_scan()
            findings = await toolkit.list_findings(severity="FAIL")
            assert len(findings) == 1
            assert all(f["status"] == "FAIL" for f in findings)

    @pytest.mark.asyncio
    async def test_filter_by_category(self, toolkit):
        with _mock_executor(toolkit):
            await toolkit.run_scan()
            findings = await toolkit.list_findings(category="S3")
            assert len(findings) == 1
            assert findings[0]["category"] == "S3"

    @pytest.mark.asyncio
    async def test_filter_by_region(self, toolkit):
        with _mock_executor(toolkit):
            await toolkit.run_scan()
            findings = await toolkit.list_findings(region="us-east-1")
            assert len(findings) == 1
            assert findings[0]["region"] == "us-east-1"

    @pytest.mark.asyncio
    async def test_filter_no_match(self, toolkit):
        with _mock_executor(toolkit):
            await toolkit.run_scan()
            findings = await toolkit.list_findings(category="Lambda")
            assert findings == []

    @pytest.mark.asyncio
    async def test_list_no_scan(self, toolkit):
        findings = await toolkit.list_findings()
        assert findings == []

    @pytest.mark.asyncio
    async def test_invalid_severity(self, toolkit):
        with _mock_executor(toolkit):
            await toolkit.run_scan()
            findings = await toolkit.list_findings(severity="CRITICAL")
            assert findings == []


# ── generate_report ──────────────────────────────────────────────────────


class TestReportGeneration:
    @pytest.mark.asyncio
    async def test_html_report(self, toolkit, tmp_path):
        with _mock_executor(toolkit):
            await toolkit.run_scan()
            path = str(tmp_path / "report.html")
            result = await toolkit.generate_report(format="html", output_path=path)
            assert result == path

    @pytest.mark.asyncio
    async def test_report_no_scan(self, toolkit):
        result = await toolkit.generate_report()
        assert result.startswith("Error:")

    @pytest.mark.asyncio
    async def test_report_bad_format(self, toolkit):
        with _mock_executor(toolkit):
            await toolkit.run_scan()
            result = await toolkit.generate_report(format="csv")
            assert result.startswith("Error:")

    @pytest.mark.asyncio
    async def test_report_auto_path(self, toolkit, tmp_path):
        toolkit.config.results_dir = str(tmp_path)
        with _mock_executor(toolkit):
            await toolkit.run_scan()
            result = await toolkit.generate_report(format="html")
            assert result.endswith(".html")


# ── compare_scans ────────────────────────────────────────────────────────


class TestCompareScan:
    @pytest.mark.asyncio
    async def test_compare_with_files(self, toolkit, tmp_path):
        with _mock_executor(toolkit):
            await toolkit.run_scan()

        baseline_path = str(tmp_path / "baseline.json")
        current_path = str(tmp_path / "current.json")
        toolkit.parser.save_result(toolkit._last_result, baseline_path)
        toolkit.parser.save_result(toolkit._last_result, current_path)

        report = await toolkit.compare_scans(
            baseline_path=baseline_path,
            current_path=current_path,
        )
        assert report.new_findings == []
        assert report.resolved_findings == []

    @pytest.mark.asyncio
    async def test_compare_uses_last_result(self, toolkit, tmp_path):
        with _mock_executor(toolkit):
            await toolkit.run_scan()

        baseline_path = str(tmp_path / "baseline.json")
        toolkit.parser.save_result(toolkit._last_result, baseline_path)

        report = await toolkit.compare_scans(baseline_path=baseline_path)
        assert report is not None

    @pytest.mark.asyncio
    async def test_compare_no_current(self, toolkit, tmp_path):
        baseline_path = str(tmp_path / "baseline.json")
        # Create a minimal baseline
        with _mock_executor(toolkit):
            await toolkit.run_scan()
        toolkit.parser.save_result(toolkit._last_result, baseline_path)
        toolkit._last_result = None

        with pytest.raises(ValueError, match="No current scan available"):
            await toolkit.compare_scans(baseline_path=baseline_path)
