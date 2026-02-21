"""Integration tests for the full CloudSploit toolkit pipeline.

Validates end-to-end workflows: scan → parse → report → compare.
All Docker/CLI calls are mocked; the real parsing, reporting, and
comparison pipelines are exercised.
"""
import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from parrot.tools.cloudsploit import CloudSploitConfig, CloudSploitToolkit

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def full_scan_json():
    """Realistic 11-plugin, 20-finding fixture."""
    return (FIXTURES_DIR / "full_scan_output.json").read_text(encoding="utf-8")


@pytest.fixture
def compliance_pci_json():
    """PCI compliance scan fixture."""
    return (FIXTURES_DIR / "compliance_pci_output.json").read_text(encoding="utf-8")


@pytest.fixture
def config():
    return CloudSploitConfig(
        aws_access_key_id="AKIATEST",
        aws_secret_access_key="secret",
    )


@pytest.fixture
def toolkit(config):
    return CloudSploitToolkit(config=config)


def _mock_exec(toolkit, output, stderr="", code=0):
    """Patch executor.execute to return canned output."""
    return patch.object(
        toolkit.executor,
        "execute",
        new_callable=AsyncMock,
        return_value=(output, stderr, code),
    )


# ── Full scan → parse → report pipeline ─────────────────────────────────


class TestFullScanPipeline:
    @pytest.mark.asyncio
    async def test_scan_to_html_report(self, toolkit, full_scan_json, tmp_path):
        """Full pipeline: scan → parse → HTML report → verify content."""
        with _mock_exec(toolkit, full_scan_json):
            result = await toolkit.run_scan()

            # Verify parsing
            assert result.summary.total_findings == 20
            assert result.summary.fail_count == 9
            assert result.summary.ok_count == 6
            assert result.summary.warn_count == 4
            assert result.summary.unknown_count == 1

            # Categories populated
            assert len(result.summary.categories) == 7
            assert result.summary.categories["EC2"] == 5
            assert result.summary.categories["S3"] == 4
            assert result.summary.categories["IAM"] == 4

            # Generate report
            path = str(tmp_path / "report.html")
            report_path = await toolkit.generate_report(format="html", output_path=path)
            assert Path(report_path).exists()

            html = Path(report_path).read_text(encoding="utf-8")
            assert "Open SSH" in html
            assert "Root Account Access" in html
            assert "KMS Key Rotation" in html

    @pytest.mark.asyncio
    async def test_scan_to_pdf_report(self, toolkit, full_scan_json, tmp_path):
        """Full pipeline: scan → parse → PDF report → verify PDF header."""
        with _mock_exec(toolkit, full_scan_json):
            await toolkit.run_scan()
            path = str(tmp_path / "report.pdf")
            report_path = await toolkit.generate_report(format="pdf", output_path=path)
            assert Path(report_path).exists()
            with open(report_path, "rb") as f:
                header = f.read(4)
                assert header == b"%PDF"

    @pytest.mark.asyncio
    async def test_scan_summary_pipeline(self, toolkit, full_scan_json):
        """Scan → get_summary → verify dict structure."""
        with _mock_exec(toolkit, full_scan_json):
            await toolkit.run_scan()
            summary = await toolkit.get_summary()

            assert isinstance(summary, dict)
            assert summary["total_findings"] == 20
            assert summary["fail_count"] == 9
            assert "categories" in summary
            assert "scan_timestamp" in summary

    @pytest.mark.asyncio
    async def test_scan_list_findings_pipeline(self, toolkit, full_scan_json):
        """Scan → list_findings with various filters."""
        with _mock_exec(toolkit, full_scan_json):
            await toolkit.run_scan()

            # All findings
            all_findings = await toolkit.list_findings()
            assert len(all_findings) == 20

            # Filter by severity
            fails = await toolkit.list_findings(severity="FAIL")
            assert len(fails) == 9
            assert all(f["status"] == "FAIL" for f in fails)

            # Filter by category
            s3 = await toolkit.list_findings(category="S3")
            assert len(s3) == 4
            assert all(f["category"] == "S3" for f in s3)

            # Filter by region
            us_east = await toolkit.list_findings(region="us-east-1")
            assert len(us_east) > 0
            assert all(f["region"] == "us-east-1" for f in us_east)

            # Combined filters
            ec2_fails = await toolkit.list_findings(severity="FAIL", category="EC2")
            assert len(ec2_fails) == 2
            assert all(
                f["status"] == "FAIL" and f["category"] == "EC2"
                for f in ec2_fails
            )


# ── Compliance scan pipeline ─────────────────────────────────────────────


class TestComplianceScanPipeline:
    @pytest.mark.asyncio
    async def test_pci_compliance_scan(self, toolkit, compliance_pci_json):
        """Compliance scan → verify framework tagging and result structure."""
        with _mock_exec(toolkit, compliance_pci_json):
            result = await toolkit.run_compliance_scan(framework="pci")

            assert result.summary.compliance_framework == "pci"
            assert result.summary.total_findings == 5
            assert result.summary.fail_count == 4

    @pytest.mark.asyncio
    async def test_compliance_followed_by_report(self, toolkit, compliance_pci_json, tmp_path):
        """Compliance scan → HTML report → verify report content."""
        with _mock_exec(toolkit, compliance_pci_json):
            await toolkit.run_compliance_scan(framework="pci")
            path = str(tmp_path / "pci_report.html")
            report_path = await toolkit.generate_report(format="html", output_path=path)
            html = Path(report_path).read_text(encoding="utf-8")
            assert "Password Policy" in html
            assert "KMS Key Rotation" in html

    @pytest.mark.asyncio
    async def test_all_compliance_frameworks(self, toolkit, compliance_pci_json):
        """Verify all framework strings are accepted."""
        for fw in ("hipaa", "cis1", "cis2", "pci"):
            with _mock_exec(toolkit, compliance_pci_json):
                result = await toolkit.run_compliance_scan(framework=fw)
                assert result.summary.compliance_framework == fw


# ── Scan comparison pipeline ─────────────────────────────────────────────


class TestScanComparisonPipeline:
    @pytest.mark.asyncio
    async def test_compare_two_scans(self, toolkit, full_scan_json, tmp_path):
        """Baseline scan → modified scan → comparison → verify diff."""
        # First scan (baseline)
        with _mock_exec(toolkit, full_scan_json):
            baseline = await toolkit.run_scan()
            baseline_path = str(tmp_path / "baseline.json")
            toolkit.parser.save_result(baseline, baseline_path)

        # Modify: remove iamRootAccess (resolved), add new rdsPublicAccess (new finding)
        modified = json.loads(full_scan_json)
        del modified["iamRootAccess"]
        modified["rdsPublicAccess"] = {
            "title": "RDS Public Access",
            "category": "RDS",
            "description": "Checks for publicly accessible RDS instances",
            "recommended_action": "Disable public access",
            "results": [
                {
                    "status": "FAIL",
                    "region": "us-east-1",
                    "resource": "arn:aws:rds:us-east-1:123456:db/public-db",
                    "message": "RDS instance is publicly accessible",
                }
            ],
        }

        with _mock_exec(toolkit, json.dumps(modified)):
            await toolkit.run_scan()
            comparison = await toolkit.compare_scans(baseline_path=baseline_path)

            # iamRootAccess finding was resolved
            assert len(comparison.resolved_findings) >= 1
            resolved_plugins = [f.plugin for f in comparison.resolved_findings]
            assert "iamRootAccess" in resolved_plugins

            # rdsPublicAccess is new
            assert len(comparison.new_findings) >= 1
            new_plugins = [f.plugin for f in comparison.new_findings]
            assert "rdsPublicAccess" in new_plugins

            # Timestamps present
            assert comparison.baseline_timestamp is not None
            assert comparison.current_timestamp is not None

    @pytest.mark.asyncio
    async def test_identical_scans_no_diff(self, toolkit, full_scan_json, tmp_path):
        """Two identical scans should produce no new/resolved findings."""
        with _mock_exec(toolkit, full_scan_json):
            result = await toolkit.run_scan()
            path = str(tmp_path / "baseline.json")
            toolkit.parser.save_result(result, path)

        with _mock_exec(toolkit, full_scan_json):
            await toolkit.run_scan()
            comparison = await toolkit.compare_scans(baseline_path=path)
            assert len(comparison.new_findings) == 0
            assert len(comparison.resolved_findings) == 0
            assert len(comparison.unchanged_findings) == 20


# ── Persistence round-trip pipeline ──────────────────────────────────────


class TestPersistencePipeline:
    @pytest.mark.asyncio
    async def test_save_and_load_round_trip(self, toolkit, full_scan_json, tmp_path):
        """Save scan result → load → verify full fidelity."""
        with _mock_exec(toolkit, full_scan_json):
            result = await toolkit.run_scan()

        path = str(tmp_path / "scan.json")
        toolkit.parser.save_result(result, path)
        loaded = toolkit.parser.load_result(path)

        assert loaded.summary.total_findings == result.summary.total_findings
        assert loaded.summary.fail_count == result.summary.fail_count
        assert loaded.summary.ok_count == result.summary.ok_count
        assert loaded.summary.warn_count == result.summary.warn_count
        assert loaded.summary.unknown_count == result.summary.unknown_count
        assert loaded.summary.categories == result.summary.categories
        assert len(loaded.findings) == len(result.findings)

        for orig, restored in zip(result.findings, loaded.findings):
            assert orig.plugin == restored.plugin
            assert orig.status == restored.status
            assert orig.region == restored.region

    @pytest.mark.asyncio
    async def test_auto_save_to_results_dir(self, toolkit, full_scan_json, tmp_path):
        """Scan with results_dir configured → auto-saves to that directory."""
        toolkit.config.results_dir = str(tmp_path)
        with _mock_exec(toolkit, full_scan_json):
            await toolkit.run_scan()

        saved_files = list(tmp_path.glob("scan_*.json"))
        assert len(saved_files) == 1

        # Verify the saved file can be loaded
        loaded = toolkit.parser.load_result(str(saved_files[0]))
        assert loaded.summary.total_findings == 20

    @pytest.mark.asyncio
    async def test_compare_with_persisted_files(self, toolkit, full_scan_json, tmp_path):
        """Save two scans to disk → compare_scans using both file paths."""
        with _mock_exec(toolkit, full_scan_json):
            result1 = await toolkit.run_scan()
        path1 = str(tmp_path / "scan1.json")
        toolkit.parser.save_result(result1, path1)

        modified = json.loads(full_scan_json)
        del modified["kmsKeyRotation"]
        with _mock_exec(toolkit, json.dumps(modified)):
            result2 = await toolkit.run_scan()
        path2 = str(tmp_path / "scan2.json")
        toolkit.parser.save_result(result2, path2)

        comparison = await toolkit.compare_scans(baseline_path=path1, current_path=path2)
        assert len(comparison.resolved_findings) >= 1


# ── Error handling pipeline ──────────────────────────────────────────────


class TestErrorHandlingPipeline:
    @pytest.mark.asyncio
    async def test_docker_failure_graceful(self, toolkit):
        """Docker failure (exit code 127) → toolkit returns empty result."""
        with _mock_exec(toolkit, "", stderr="Docker not found", code=127):
            result = await toolkit.run_scan()
            assert result.summary.total_findings == 0
            assert result.findings == []

    @pytest.mark.asyncio
    async def test_invalid_json_from_docker(self, toolkit):
        """Docker returns non-JSON output → toolkit handles gracefully."""
        with _mock_exec(toolkit, "ERROR: not json output", code=0):
            result = await toolkit.run_scan()
            assert result.summary.total_findings == 0

    @pytest.mark.asyncio
    async def test_partial_failure_still_parses(self, toolkit, full_scan_json):
        """Docker exits non-zero but still produces valid JSON → results parsed."""
        with _mock_exec(toolkit, full_scan_json, stderr="Warning: some plugins failed", code=1):
            result = await toolkit.run_scan()
            assert result.summary.total_findings == 20

    @pytest.mark.asyncio
    async def test_report_before_scan(self, toolkit):
        """Generate report with no scan → returns error string."""
        result = await toolkit.generate_report()
        assert result.startswith("Error:")

    @pytest.mark.asyncio
    async def test_summary_before_scan(self, toolkit):
        """Get summary with no scan → returns error dict."""
        summary = await toolkit.get_summary()
        assert "error" in summary

    @pytest.mark.asyncio
    async def test_compare_without_current(self, toolkit, full_scan_json, tmp_path):
        """Compare with no current scan and no current_path → raises ValueError."""
        with _mock_exec(toolkit, full_scan_json):
            result = await toolkit.run_scan()
        path = str(tmp_path / "baseline.json")
        toolkit.parser.save_result(result, path)
        toolkit._last_result = None

        with pytest.raises(ValueError, match="No current scan available"):
            await toolkit.compare_scans(baseline_path=path)

    @pytest.mark.asyncio
    async def test_invalid_compliance_framework(self, toolkit):
        """Invalid compliance framework string → raises ValueError."""
        with pytest.raises(ValueError, match="Unknown compliance framework"):
            await toolkit.run_compliance_scan(framework="sox")

    @pytest.mark.asyncio
    async def test_timeout_propagates(self, toolkit):
        """Executor timeout raises asyncio.TimeoutError through toolkit."""
        with patch.object(
            toolkit.executor,
            "execute",
            new_callable=AsyncMock,
            side_effect=asyncio.TimeoutError("Scan timed out"),
        ):
            with pytest.raises(asyncio.TimeoutError):
                await toolkit.run_scan()
