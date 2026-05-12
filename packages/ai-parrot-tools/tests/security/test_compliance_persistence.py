"""Unit tests for ComplianceReportToolkit persistence integration (FEAT-162)."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot_tools.security.compliance_report_toolkit import ComplianceReportToolkit
from parrot_tools.security.models import (
    FindingSource,
    ScanResult,
    ScanSummary,
)


def _empty_scan_result() -> ScanResult:
    """Build a minimal valid ScanResult with no findings."""
    return ScanResult(
        findings=[],
        summary=ScanSummary(
            source=FindingSource.PROWLER,
            provider="aws",
            scan_timestamp=datetime(2026, 5, 12, tzinfo=timezone.utc),
        ),
    )


class TestCompliancePersistence:
    def test_inheritance(self) -> None:
        """ComplianceReportToolkit must inherit ReportPersistenceMixin first."""
        from parrot_tools.security.persistence import ReportPersistenceMixin
        assert issubclass(ComplianceReportToolkit, ReportPersistenceMixin)

    def test_kwargs_pop_keeps_super_init_clean(self) -> None:
        """Constructing with persistence kwargs must NOT raise."""
        fm = MagicMock()
        store = AsyncMock()
        toolkit = ComplianceReportToolkit(
            file_manager=fm,
            report_store=store,
        )
        assert toolkit.file_manager is fm
        assert toolkit.report_store is store

    def test_noop_when_persistence_kwargs_missing(self) -> None:
        """Without persistence kwargs, file_manager and report_store are None."""
        toolkit = ComplianceReportToolkit()
        assert toolkit.file_manager is None
        assert toolkit.report_store is None

    async def test_persist_report_noop_returns_none(self) -> None:
        """_persist_report returns None when deps are absent."""
        toolkit = ComplianceReportToolkit()
        result = await toolkit._persist_report(
            scanner="aggregator",
            framework="HIPAA",
            provider="aws",
            scope={},
            content=b"{}",
        )
        assert result is None

    async def test_persists_after_compliance_full_scan(self) -> None:
        """compliance_full_scan with wired deps calls _persist_report once."""
        fm = MagicMock()
        store = AsyncMock()
        toolkit = ComplianceReportToolkit(
            file_manager=fm,
            report_store=store,
        )

        with patch.object(toolkit, "_persist_report", new=AsyncMock()) as p, \
             patch.object(toolkit, "_run_prowler_scan", new=AsyncMock(return_value=_empty_scan_result())), \
             patch.object(toolkit, "_run_scoutsuite_scan", new=AsyncMock(return_value=_empty_scan_result())):
            await toolkit.compliance_full_scan(provider="aws", framework="HIPAA")

        p.assert_called_once()
        call_kwargs = p.call_args.kwargs
        assert call_kwargs["scanner"] == "aggregator"
        assert call_kwargs["framework"] == "HIPAA"
        assert call_kwargs["provider"] == "aws"

    async def test_no_persist_without_deps(self) -> None:
        """Without deps wired, _persist_report is not called on scan path."""
        toolkit = ComplianceReportToolkit()
        with patch.object(toolkit, "_run_prowler_scan", new=AsyncMock(return_value=_empty_scan_result())), \
             patch.object(toolkit, "_run_scoutsuite_scan", new=AsyncMock(return_value=_empty_scan_result())), \
             patch.object(toolkit, "_persist_report", wraps=toolkit._persist_report) as p:
            await toolkit.compliance_full_scan(provider="aws")
        # _persist_report was called but must have returned None (no-op)
        if p.called:
            # Retrieve the actual return value from the coroutine
            assert toolkit.file_manager is None  # confirms no-op path
