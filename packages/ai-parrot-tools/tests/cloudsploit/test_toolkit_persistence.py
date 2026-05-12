"""Unit tests for CloudSploitToolkit persistence integration (FEAT-162)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.tools.cloudsploit import CloudSploitConfig, CloudSploitToolkit
from parrot_tools.cloudsploit.models import (
    ScanFinding,
    ScanResult,
    ScanSummary,
    SeverityLevel,
)


def _make_scan_result() -> ScanResult:
    """Build a minimal valid ScanResult for testing."""
    return ScanResult(
        findings=[
            ScanFinding(
                plugin="s3Encryption",
                category="S3",
                title="S3 Bucket Not Encrypted",
                region="us-east-1",
                status=SeverityLevel.FAIL,
            )
        ],
        summary=ScanSummary(
            total_findings=1,
            ok_count=0,
            warn_count=0,
            fail_count=1,
            unknown_count=0,
            scan_timestamp=datetime(2026, 5, 12, 6, 0, tzinfo=timezone.utc),
        ),
    )


# Minimal CloudSploit JSON output that the parser can handle
_MOCK_OUTPUT = json.dumps({
    "s3Encryption": {
        "title": "S3 Encryption",
        "category": "S3",
        "description": "Check S3 encryption",
        "results": [
            {"status": "FAIL", "region": "us-east-1", "resource": "my-bucket", "message": "Not encrypted"},
        ],
    }
})


def _stub_executor(toolkit: CloudSploitToolkit) -> None:
    """Replace the heavy executor with a mock that returns _MOCK_OUTPUT."""
    toolkit.executor = MagicMock()
    toolkit.executor.run_scan = AsyncMock(
        return_value=(_MOCK_OUTPUT, "{}", "", "", 0)
    )
    toolkit.executor.run_compliance_scan = AsyncMock(
        return_value=(_MOCK_OUTPUT, "{}", "", "", 0)
    )


class TestCloudSploitPersistence:
    async def test_inheritance(self) -> None:
        """CloudSploitToolkit must inherit ReportPersistenceMixin first."""
        from parrot_tools.security.persistence import ReportPersistenceMixin
        assert issubclass(CloudSploitToolkit, ReportPersistenceMixin)

    async def test_kwargs_pop_keeps_super_init_clean(self) -> None:
        """Constructing with persistence kwargs must NOT raise."""
        fm = MagicMock()
        store = AsyncMock()
        toolkit = CloudSploitToolkit(
            config=CloudSploitConfig(
                aws_access_key_id="K",
                aws_secret_access_key="S",
            ),
            file_manager=fm,
            report_store=store,
        )
        assert toolkit.file_manager is fm
        assert toolkit.report_store is store

    async def test_noop_when_persistence_kwargs_missing(self) -> None:
        """When no persistence kwargs, _persist_report returns None."""
        toolkit = CloudSploitToolkit(
            config=CloudSploitConfig(
                aws_access_key_id="K",
                aws_secret_access_key="S",
            )
        )
        assert toolkit.file_manager is None
        assert toolkit.report_store is None
        result = await toolkit._persist_report(
            scanner="cloudsploit",
            framework="HIPAA",
            provider="aws",
            scope={},
            content=b"{}",
        )
        assert result is None

    async def test_persists_after_compliance_scan(self) -> None:
        """run_compliance_scan with wired deps calls _persist_report once."""
        fm = MagicMock()
        store = AsyncMock()
        toolkit = CloudSploitToolkit(
            config=CloudSploitConfig(
                aws_access_key_id="K",
                aws_secret_access_key="S",
            ),
            file_manager=fm,
            report_store=store,
        )
        _stub_executor(toolkit)

        with patch.object(toolkit, "_persist_report", new=AsyncMock()) as p:
            await toolkit.run_compliance_scan("hipaa")
            p.assert_called_once()
            call_kwargs = p.call_args.kwargs
            assert call_kwargs["scanner"] == "cloudsploit"
            assert call_kwargs["framework"] == "hipaa"

    async def test_persists_after_run_scan(self) -> None:
        """run_scan with wired deps calls _persist_report once with framework=None."""
        fm = MagicMock()
        store = AsyncMock()
        toolkit = CloudSploitToolkit(
            config=CloudSploitConfig(
                aws_access_key_id="K",
                aws_secret_access_key="S",
            ),
            file_manager=fm,
            report_store=store,
        )
        _stub_executor(toolkit)

        with patch.object(toolkit, "_persist_report", new=AsyncMock()) as p:
            await toolkit.run_scan()
            p.assert_called_once()
            call_kwargs = p.call_args.kwargs
            assert call_kwargs["scanner"] == "cloudsploit"
            assert call_kwargs["framework"] is None

    async def test_run_scan_returns_scan_result(self) -> None:
        """Return shape is unchanged — still ScanResult."""
        toolkit = CloudSploitToolkit(
            config=CloudSploitConfig(
                aws_access_key_id="K",
                aws_secret_access_key="S",
            )
        )
        _stub_executor(toolkit)

        result = await toolkit.run_scan()
        assert isinstance(result, ScanResult)

    async def test_ecr_persistence_call_when_deps_present(self, tmp_path) -> None:
        """collect_ecr_findings with wired deps calls _persist_report with ecr-image-scan."""
        from unittest.mock import patch, AsyncMock
        from parrot_tools.cloudsploit.models import (
            EcrCollectionResult,
            EcrRepoFindings,
            EcrSeverity,
        )
        fm = MagicMock()
        store = AsyncMock()
        toolkit = CloudSploitToolkit(
            config=CloudSploitConfig(
                aws_access_key_id="K",
                aws_secret_access_key="S",
            ),
            file_manager=fm,
            report_store=store,
        )

        plan_path = tmp_path / "plan.yaml"
        plan_path.write_text(
            "region: us-east-2\nrepos:\n  - {name: alpha, tags: [staging]}\n"
        )
        fake_result = EcrCollectionResult(
            generated_at=datetime(2026, 5, 12, 6, 0, tzinfo=timezone.utc),
            region="us-east-2",
            repos=[
                EcrRepoFindings(
                    repo="alpha",
                    tag="staging",
                    counts={EcrSeverity.CRITICAL: 2},
                    findings=[],
                )
            ],
        )

        with patch.object(
            toolkit.ecr_collector, "collect", new=AsyncMock(return_value=fake_result),
        ), patch.object(toolkit, "_persist_report", new=AsyncMock()) as p:
            await toolkit.collect_ecr_findings(plan=str(plan_path))
            p.assert_awaited_once()
            call_kwargs = p.call_args.kwargs
            assert call_kwargs["scanner"] == "ecr-image-scan"
            assert call_kwargs["provider"] == "aws"
            assert call_kwargs["scope"]["region"] == "us-east-2"
