"""Unit tests for SecurityReportToolkit (LLM-facing read side)."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from parrot.storage.security_reports import (
    ReportKind,
    ReportRef,
    SeverityBreakdown,
)
from parrot_tools.security.report_toolkit import SecurityReportToolkit


def _ref(scanner: str = "cloudsploit", framework: str | None = "HIPAA") -> ReportRef:
    return ReportRef(
        report_kind=ReportKind.SCAN,
        scanner=scanner,
        framework=framework,
        provider="aws",
        scope={"account_id": "123456789012"},
        severity_summary=SeverityBreakdown(critical=2, high=3),
        uri="s3://bucket/key.json",
        produced_at=datetime.now(timezone.utc),
        produced_by="test",
        parser_version="1.0.0",
    )


@pytest.fixture
def store() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def toolkit(store: AsyncMock) -> SecurityReportToolkit:
    fm = MagicMock()
    return SecurityReportToolkit(report_store=store, file_manager=fm)


# ---------------------------------------------------------------------------
# find_security_report
# ---------------------------------------------------------------------------

class TestFind:
    async def test_builds_filter_with_since(self, toolkit: SecurityReportToolkit, store: AsyncMock) -> None:
        """find_security_report builds ReportFilter with a since date."""
        store.query = AsyncMock(return_value=[_ref()])
        await toolkit.find_security_report(framework="HIPAA", max_age_days=14)
        flt = store.query.call_args.args[0]
        assert flt.framework == "HIPAA"
        assert flt.since is not None
        assert flt.report_kind == ReportKind.SCAN

    async def test_no_fetch_content(self, toolkit: SecurityReportToolkit, store: AsyncMock) -> None:
        """find_security_report must NOT call fetch_content."""
        store.query = AsyncMock(return_value=[_ref()])
        await toolkit.find_security_report()
        store.fetch_content.assert_not_called()

    async def test_returns_list_of_dicts(self, toolkit: SecurityReportToolkit, store: AsyncMock) -> None:
        """Result is a list of dicts, not ReportRef objects."""
        ref = _ref()
        store.query = AsyncMock(return_value=[ref])
        result = await toolkit.find_security_report()
        assert isinstance(result, list)
        assert isinstance(result[0], dict)
        assert result[0]["scanner"] == "cloudsploit"

    async def test_empty_when_no_results(self, toolkit: SecurityReportToolkit, store: AsyncMock) -> None:
        store.query = AsyncMock(return_value=[])
        result = await toolkit.find_security_report()
        assert result == []


# ---------------------------------------------------------------------------
# read_security_report
# ---------------------------------------------------------------------------

class TestRead:
    async def test_summary_skips_fetch(self, toolkit: SecurityReportToolkit, store: AsyncMock) -> None:
        """read_security_report with section='summary' must NOT call fetch_content."""
        ref = _ref()
        store.get = AsyncMock(return_value=ref)
        result = await toolkit.read_security_report(str(ref.report_id), "summary")
        assert "ref" in result
        store.fetch_content.assert_not_called()

    async def test_critical_uses_fetch_and_parser(self, toolkit: SecurityReportToolkit, store: AsyncMock) -> None:
        """read_security_report with section='critical' calls fetch_content and extract_section."""
        ref = _ref()
        store.get = AsyncMock(return_value=ref)
        store.fetch_content = AsyncMock(return_value=b'{"findings": []}')

        with patch("parrot_tools.security.report_toolkit.get_report_parser") as gp:
            mock_parser = MagicMock()
            mock_parser.extract_section.return_value = {"findings": []}
            gp.return_value = mock_parser

            result = await toolkit.read_security_report(str(ref.report_id), "critical")

        store.fetch_content.assert_called_once()
        gp.assert_called_once_with("cloudsploit")
        mock_parser.extract_section.assert_called_once()
        assert result == {"findings": []}

    async def test_missing_report_returns_error(self, toolkit: SecurityReportToolkit, store: AsyncMock) -> None:
        """Missing report returns {'error': ...} rather than raising."""
        store.get = AsyncMock(return_value=None)
        result = await toolkit.read_security_report(str(uuid4()), "summary")
        assert "error" in result

    async def test_invalid_uuid_returns_error(self, toolkit: SecurityReportToolkit, store: AsyncMock) -> None:
        """Invalid UUID returns {'error': ...} rather than raising ValueError."""
        result = await toolkit.read_security_report("not-a-uuid", "summary")
        assert "error" in result


# ---------------------------------------------------------------------------
# list_available_frameworks
# ---------------------------------------------------------------------------

class TestListFrameworks:
    async def test_sorted_unique(self, toolkit: SecurityReportToolkit, store: AsyncMock) -> None:
        """list_available_frameworks returns a sorted deduplicated list."""
        refs = [
            _ref(framework="SOC2"),
            _ref(framework="HIPAA"),
            _ref(framework="HIPAA"),  # duplicate
            _ref(framework=None),     # excluded
        ]
        store.query = AsyncMock(return_value=refs)
        result = await toolkit.list_available_frameworks()
        assert result == ["HIPAA", "SOC2"]  # sorted, unique, None excluded

    async def test_empty_when_no_reports(self, toolkit: SecurityReportToolkit, store: AsyncMock) -> None:
        store.query = AsyncMock(return_value=[])
        result = await toolkit.list_available_frameworks()
        assert result == []


# ---------------------------------------------------------------------------
# search_findings
# ---------------------------------------------------------------------------

class TestSearchFindings:
    def test_docstring_mentions_v1_limit(self) -> None:
        """search_findings docstring must mention the top-10 / top_findings limitation."""
        doc = SecurityReportToolkit.search_findings.__doc__ or ""
        assert "top-10" in doc or "top_findings" in doc, (
            "search_findings docstring must document the v1 top-10 limitation"
        )

    async def test_text_match(self, toolkit: SecurityReportToolkit, store: AsyncMock) -> None:
        """search_findings returns findings whose title contains the query."""
        from parrot.storage.security_reports import EmbeddedFinding
        ref = _ref()
        # Inject a top finding
        ref = ref.model_copy(update={
            "top_findings": [
                EmbeddedFinding(
                    finding_id="f-1",
                    severity="CRITICAL",
                    title="S3 Bucket Not Encrypted",
                    resource_id="arn:aws:s3:::my-bucket",
                )
            ]
        })
        store.query = AsyncMock(return_value=[ref])
        results = await toolkit.search_findings("not encrypted")
        assert len(results) == 1
        assert results[0]["title"] == "S3 Bucket Not Encrypted"

    async def test_no_match_returns_empty(self, toolkit: SecurityReportToolkit, store: AsyncMock) -> None:
        store.query = AsyncMock(return_value=[_ref()])
        results = await toolkit.search_findings("xyzzy-no-match")
        assert results == []
