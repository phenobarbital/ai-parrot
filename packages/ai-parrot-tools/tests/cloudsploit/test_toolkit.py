"""Integration tests for CloudSploitToolkit."""
import json
import logging
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


def _mock_executor(
    toolkit,
    output=MOCK_CLOUDSPLOIT_OUTPUT,
    collection="{}",
    code=0,
    stderr="",
):
    """Patch executor.run_scan / run_compliance_scan with canned output.

    The toolkit now consumes ``(results_json, collection_json, stdout,
    stderr, exit_code)`` from the executor's high-level methods (which
    internally materialise temp files). Patch those directly so tests
    don't need to worry about the file lifecycle.
    """
    return_value = (output, collection, "", stderr, code)
    patches = [
        patch.object(
            toolkit.executor,
            "run_scan",
            new_callable=AsyncMock,
            return_value=return_value,
        ),
        patch.object(
            toolkit.executor,
            "run_compliance_scan",
            new_callable=AsyncMock,
            return_value=return_value,
        ),
    ]

    class _Combined:
        def __enter__(self):
            self.mocks = [p.__enter__() for p in patches]
            # Return the run_scan mock so existing tests using
            # ``with _mock_executor(...) as mock_exec`` keep working.
            return self.mocks[0]

        def __exit__(self, *exc):
            for p in reversed(patches):
                p.__exit__(*exc)

    return _Combined()


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
        # ECR tools added by FEAT-165
        assert "collect_ecr_findings" in names
        assert "generate_ecr_report" in names

    def test_tool_count(self, toolkit):
        tools = toolkit.get_tools()
        assert len(tools) == 8  # 6 original + 2 ECR tools (FEAT-165)

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
            await toolkit.run_scan()
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


# ── run_scan config argument ─────────────────────────────────────────────


class TestRunScanConfig:
    @pytest.mark.asyncio
    async def test_call_arg_forwarded(self):
        """Per-call config is forwarded to executor.run_scan."""
        toolkit = CloudSploitToolkit(CloudSploitConfig())
        with patch.object(toolkit.executor, "run_scan",
                          new_callable=AsyncMock) as mock:
            mock.return_value = (MOCK_CLOUDSPLOIT_OUTPUT, "", "", "", 0)
            await toolkit.run_scan(config="/p/cfg.js")
            assert mock.await_args.kwargs["config"] == "/p/cfg.js"

    @pytest.mark.asyncio
    async def test_model_default_applies(self):
        """When no per-call config, CloudSploitConfig.config_file is used."""
        toolkit = CloudSploitToolkit(
            CloudSploitConfig(config_file="/d/cfg.js")
        )
        with patch.object(toolkit.executor, "run_scan",
                          new_callable=AsyncMock) as mock:
            mock.return_value = (MOCK_CLOUDSPLOIT_OUTPUT, "", "", "", 0)
            await toolkit.run_scan()
            assert mock.await_args.kwargs["config"] == "/d/cfg.js"

    @pytest.mark.asyncio
    async def test_call_arg_overrides_model_default_and_logs(self, caplog):
        """Per-call config overrides model default and emits a DEBUG log."""
        toolkit = CloudSploitToolkit(
            CloudSploitConfig(config_file="/orig.js")
        )
        with patch.object(toolkit.executor, "run_scan",
                          new_callable=AsyncMock) as mock:
            mock.return_value = (MOCK_CLOUDSPLOIT_OUTPUT, "", "", "", 0)
            with caplog.at_level(logging.DEBUG,
                                 logger=toolkit.logger.name):
                await toolkit.run_scan(config="/override.js")
            assert mock.await_args.kwargs["config"] == "/override.js"
            assert any("overrides" in r.message.lower()
                       for r in caplog.records)

    @pytest.mark.asyncio
    async def test_no_config_no_log(self, caplog):
        """With no config set at all, no DEBUG log is emitted."""
        toolkit = CloudSploitToolkit(CloudSploitConfig())
        with patch.object(toolkit.executor, "run_scan",
                          new_callable=AsyncMock) as mock:
            mock.return_value = (MOCK_CLOUDSPLOIT_OUTPUT, "", "", "", 0)
            with caplog.at_level(logging.DEBUG,
                                 logger=toolkit.logger.name):
                await toolkit.run_scan()
            assert mock.await_args.kwargs["config"] is None
            assert not any("overrides" in r.message.lower()
                           for r in caplog.records)

    @pytest.mark.asyncio
    async def test_effective_config_logged_when_active(self, caplog):
        """Effective config path is always logged at DEBUG when non-None."""
        toolkit = CloudSploitToolkit(
            CloudSploitConfig(config_file="/d/cfg.js")
        )
        with patch.object(toolkit.executor, "run_scan",
                          new_callable=AsyncMock) as mock:
            mock.return_value = (MOCK_CLOUDSPLOIT_OUTPUT, "", "", "", 0)
            with caplog.at_level(logging.DEBUG,
                                 logger=toolkit.logger.name):
                await toolkit.run_scan()
            assert any(
                "effective" in r.message.lower() and "/d/cfg.js" in r.message
                for r in caplog.records
            )


# ── run_compliance_scan config argument ──────────────────────────────────


class TestRunComplianceScanConfig:
    @pytest.mark.asyncio
    async def test_call_arg_forwarded(self):
        """Per-call config is forwarded to executor.run_compliance_scan."""
        toolkit = CloudSploitToolkit(CloudSploitConfig())
        with patch.object(toolkit.executor, "run_compliance_scan",
                          new_callable=AsyncMock) as mock:
            mock.return_value = (MOCK_CLOUDSPLOIT_OUTPUT, "", "", "", 0)
            await toolkit.run_compliance_scan(framework="hipaa",
                                              config="/p/cfg.js")
            assert mock.await_args.kwargs["config"] == "/p/cfg.js"

    @pytest.mark.asyncio
    async def test_model_default_applies(self):
        """When no per-call config, CloudSploitConfig.config_file is used."""
        toolkit = CloudSploitToolkit(
            CloudSploitConfig(config_file="/d/cfg.js")
        )
        with patch.object(toolkit.executor, "run_compliance_scan",
                          new_callable=AsyncMock) as mock:
            mock.return_value = (MOCK_CLOUDSPLOIT_OUTPUT, "", "", "", 0)
            await toolkit.run_compliance_scan(framework="hipaa")
            assert mock.await_args.kwargs["config"] == "/d/cfg.js"

    @pytest.mark.asyncio
    async def test_call_arg_overrides_model_default_and_logs(self, caplog):
        """Per-call config overrides model default and emits a DEBUG log."""
        toolkit = CloudSploitToolkit(
            CloudSploitConfig(config_file="/orig.js")
        )
        with patch.object(toolkit.executor, "run_compliance_scan",
                          new_callable=AsyncMock) as mock:
            mock.return_value = (MOCK_CLOUDSPLOIT_OUTPUT, "", "", "", 0)
            with caplog.at_level(logging.DEBUG,
                                 logger=toolkit.logger.name):
                await toolkit.run_compliance_scan(framework="hipaa",
                                                  config="/override.js")
            assert mock.await_args.kwargs["config"] == "/override.js"
            assert any("overrides" in r.message.lower()
                       for r in caplog.records)

    @pytest.mark.asyncio
    async def test_no_config_no_log(self, caplog):
        """With no config set at all, no DEBUG log is emitted."""
        toolkit = CloudSploitToolkit(CloudSploitConfig())
        with patch.object(toolkit.executor, "run_compliance_scan",
                          new_callable=AsyncMock) as mock:
            mock.return_value = (MOCK_CLOUDSPLOIT_OUTPUT, "", "", "", 0)
            with caplog.at_level(logging.DEBUG,
                                 logger=toolkit.logger.name):
                await toolkit.run_compliance_scan(framework="pci")
            assert mock.await_args.kwargs["config"] is None
            assert not any("overrides" in r.message.lower()
                           for r in caplog.records)


# ---------------------------------------------------------------------------
# ECR agent-tool tests (TASK-1123)
# ---------------------------------------------------------------------------
from datetime import datetime, timezone  # noqa: E402
from unittest.mock import MagicMock  # noqa: E402

from parrot_tools.cloudsploit.models import (  # noqa: E402
    EcrCollectionResult,
    EcrRepoFindings,
    EcrSeverity,
)


@pytest.fixture
def fake_ecr_result():
    """Minimal EcrCollectionResult for toolkit ECR tests."""
    return EcrCollectionResult(
        generated_at=datetime.now(tz=timezone.utc),
        region="us-east-2",
        repos=[
            EcrRepoFindings(
                repo="alpha",
                tag="staging",
                counts={EcrSeverity.CRITICAL: 1},
                findings=[],
            ),
        ],
    )


@pytest.mark.asyncio
async def test_collect_ecr_findings_no_plan_raises():
    """ValueError raised when neither plan arg nor ecr_plan_file is set."""
    tk = CloudSploitToolkit()
    with pytest.raises(ValueError, match="No ECR collection plan"):
        await tk.collect_ecr_findings()


@pytest.mark.asyncio
async def test_collect_ecr_findings_uses_plan_arg(tmp_path, fake_ecr_result):
    """collect_ecr_findings delegates to ecr_collector.collect with loaded plan."""
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text(
        "region: us-east-2\n"
        "repos:\n  - {name: alpha, tags: [staging]}\n"
    )
    tk = CloudSploitToolkit()
    with patch.object(
        tk.ecr_collector, "collect", new=AsyncMock(return_value=fake_ecr_result),
    ) as collect_mock:
        out = await tk.collect_ecr_findings(plan=str(plan_path))
    collect_mock.assert_awaited_once()
    assert out is fake_ecr_result
    assert tk._last_ecr_result is fake_ecr_result


@pytest.mark.asyncio
async def test_per_call_plan_overrides_config_field(tmp_path, fake_ecr_result, caplog):
    """Per-call plan arg overrides ecr_plan_file and a DEBUG log is emitted."""
    plan_a = tmp_path / "a.yaml"
    plan_a.write_text("region: x\nrepos:\n  - {name: a, tags: [t]}\n")
    plan_b = tmp_path / "b.yaml"
    plan_b.write_text("region: y\nrepos:\n  - {name: b, tags: [t]}\n")

    cfg = CloudSploitConfig(ecr_plan_file=str(plan_a))
    tk = CloudSploitToolkit(config=cfg)
    with patch.object(
        tk.ecr_collector, "collect", new=AsyncMock(return_value=fake_ecr_result),
    ), caplog.at_level(logging.DEBUG, logger="CloudSploitToolkit"):
        await tk.collect_ecr_findings(plan=str(plan_b))
    assert "overrides" in caplog.text


@pytest.mark.asyncio
async def test_generate_ecr_report_uses_last_result(fake_ecr_result, tmp_path):
    """generate_ecr_report uses _last_ecr_result when no result arg given."""
    tk = CloudSploitToolkit(config=CloudSploitConfig(results_dir=str(tmp_path)))
    tk._last_ecr_result = fake_ecr_result
    with patch.object(
        tk.report_generator, "generate_ecr_html",
        new=AsyncMock(return_value=str(tmp_path / "out.html")),
    ) as render_mock:
        out = await tk.generate_ecr_report()
    render_mock.assert_awaited_once()
    assert out.endswith(".html")


@pytest.mark.asyncio
async def test_generate_ecr_report_no_result_raises():
    """ValueError raised when neither result arg nor _last_ecr_result is set."""
    tk = CloudSploitToolkit()
    with pytest.raises(ValueError, match="No ECR collection"):
        await tk.generate_ecr_report()


@pytest.mark.asyncio
async def test_no_op_when_persistence_deps_absent(tmp_path, fake_ecr_result):
    """collect_ecr_findings runs without error when no persistence kwargs."""
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text("region: r\nrepos:\n  - {name: a, tags: [t]}\n")
    tk = CloudSploitToolkit()
    with patch.object(
        tk.ecr_collector, "collect", new=AsyncMock(return_value=fake_ecr_result),
    ):
        out = await tk.collect_ecr_findings(plan=str(plan_path))
    assert out is fake_ecr_result
