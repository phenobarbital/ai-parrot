"""Unit tests for ReportPersistenceMixin and pop_persistence_kwargs."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.storage.security_reports import (
    EmbeddedFinding,
    ReportKind,
    ReportRef,
    SeverityBreakdown,
)
from parrot_tools.security.persistence import (
    ReportPersistenceMixin,
    pop_persistence_kwargs,
)


class _Probe(ReportPersistenceMixin):
    """Minimal concrete class for testing the mixin in isolation."""
    pass


# ---------------------------------------------------------------------------
# No-op path (deps missing)
# ---------------------------------------------------------------------------

class TestNoOpWhenDepsMissing:
    async def test_returns_none_when_both_missing(self) -> None:
        """_persist_report returns None (silently) when deps are not configured."""
        probe = _Probe()
        result = await probe._persist_report(
            scanner="cloudsploit",
            framework="HIPAA",
            provider="aws",
            scope={},
            content=b"{}",
        )
        assert result is None

    async def test_returns_none_when_only_file_manager_missing(self) -> None:
        """_persist_report returns None when file_manager is absent."""
        probe = _Probe()
        probe.report_store = AsyncMock()
        result = await probe._persist_report(
            scanner="cloudsploit",
            framework="HIPAA",
            provider="aws",
            scope={},
            content=b"{}",
        )
        assert result is None
        probe.report_store.save_report.assert_not_called()

    async def test_returns_none_when_only_store_missing(self) -> None:
        """_persist_report returns None when report_store is absent."""
        probe = _Probe()
        probe.file_manager = MagicMock()
        result = await probe._persist_report(
            scanner="cloudsploit",
            framework="HIPAA",
            provider="aws",
            scope={},
            content=b"{}",
        )
        assert result is None


# ---------------------------------------------------------------------------
# Active path (both deps wired)
# ---------------------------------------------------------------------------

class TestActivated:
    async def test_parser_invoked_when_summary_omitted(self) -> None:
        """When severity_summary is not provided, the parser is called once."""
        probe = _Probe()
        probe.file_manager = MagicMock()
        probe.report_store = AsyncMock()
        probe.report_store.save_report = AsyncMock(side_effect=lambda ref, content: ref)

        with patch("parrot_tools.security.persistence.get_report_parser") as gp:
            mock_parser = MagicMock()
            mock_parser.parse.return_value.severity_summary = SeverityBreakdown(critical=1)
            mock_parser.parse.return_value.top_findings = []
            gp.return_value = mock_parser

            await probe._persist_report(
                scanner="cloudsploit",
                framework="HIPAA",
                provider="aws",
                scope={},
                content=b"{}",
            )
            gp.assert_called_once_with("cloudsploit")
            mock_parser.parse.assert_called_once()

    async def test_parser_not_invoked_when_summary_provided(self) -> None:
        """When severity_summary AND top_findings are provided, no parser is called."""
        probe = _Probe()
        probe.file_manager = MagicMock()
        probe.report_store = AsyncMock()
        probe.report_store.save_report = AsyncMock(side_effect=lambda ref, content: ref)

        with patch("parrot_tools.security.persistence.get_report_parser") as gp:
            await probe._persist_report(
                scanner="cloudsploit",
                framework="HIPAA",
                provider="aws",
                scope={},
                content=b"{}",
                severity_summary=SeverityBreakdown(critical=2),
                top_findings=[],
            )
            gp.assert_not_called()

    async def test_produced_by_defaults_to_class_name(self) -> None:
        """produced_by defaults to 'toolkit:<ClassName>'."""
        probe = _Probe()
        probe.file_manager = MagicMock()
        probe.report_store = AsyncMock()

        captured: dict = {}

        async def _save(ref: ReportRef, content: bytes) -> ReportRef:
            captured["ref"] = ref
            return ref

        probe.report_store.save_report = _save

        await probe._persist_report(
            scanner="cloudsploit",
            framework="HIPAA",
            provider="aws",
            scope={},
            content=b"{}",
            severity_summary=SeverityBreakdown(),
            top_findings=[],
        )
        assert captured["ref"].produced_by == "toolkit:_Probe"

    async def test_explicit_produced_by_is_used(self) -> None:
        """Explicit produced_by overrides the default."""
        probe = _Probe()
        probe.file_manager = MagicMock()
        probe.report_store = AsyncMock()
        captured: dict = {}

        async def _save(ref: ReportRef, content: bytes) -> ReportRef:
            captured["ref"] = ref
            return ref

        probe.report_store.save_report = _save

        await probe._persist_report(
            scanner="cloudsploit",
            framework="HIPAA",
            provider="aws",
            scope={},
            content=b"{}",
            severity_summary=SeverityBreakdown(),
            top_findings=[],
            produced_by="custom-agent",
        )
        assert captured["ref"].produced_by == "custom-agent"

    async def test_top_findings_capped_at_10(self) -> None:
        """top_findings must be capped at 10 entries."""
        probe = _Probe()
        probe.file_manager = MagicMock()
        probe.report_store = AsyncMock()
        captured: dict = {}

        async def _save(ref: ReportRef, content: bytes) -> ReportRef:
            captured["ref"] = ref
            return ref

        probe.report_store.save_report = _save

        many = [
            EmbeddedFinding(
                finding_id=f"f-{i}",
                severity="HIGH",
                title=f"Finding {i}",
                resource="",
                description="",
            )
            for i in range(20)
        ]

        await probe._persist_report(
            scanner="cloudsploit",
            framework="HIPAA",
            provider="aws",
            scope={},
            content=b"{}",
            severity_summary=SeverityBreakdown(high=20),
            top_findings=many,
        )
        assert len(captured["ref"].top_findings) <= 10


# ---------------------------------------------------------------------------
# pop_persistence_kwargs
# ---------------------------------------------------------------------------

class TestPopKwargs:
    def test_pops_known_keys(self) -> None:
        """pop_persistence_kwargs removes file_manager and report_store."""
        kwargs: dict = {"file_manager": "FM", "report_store": "RS", "other": 1}
        fm, store = pop_persistence_kwargs(kwargs)
        assert fm == "FM"
        assert store == "RS"
        assert kwargs == {"other": 1}

    def test_missing_keys_return_none(self) -> None:
        """Returns (None, None) when keys are absent."""
        kwargs: dict = {}
        fm, store = pop_persistence_kwargs(kwargs)
        assert fm is None
        assert store is None

    def test_partial_keys(self) -> None:
        """Only file_manager present → store is None."""
        kwargs: dict = {"file_manager": "FM"}
        fm, store = pop_persistence_kwargs(kwargs)
        assert fm == "FM"
        assert store is None
        assert kwargs == {}
