"""Unit tests for WeeklySecuritySummarizer and MonthlySecuritySummarizer."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from parrot.storage.security_reports import (
    EmbeddedFinding,
    ReportKind,
    ReportRef,
    SeverityBreakdown,
)
from parrot_tools.security.summarizer import (
    MonthlySecuritySummarizer,
    MonthlySummary,
    WeeklySecuritySummarizer,
    WeeklySummary,
    _Executive,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scan(
    severity_kwargs: dict | None = None,
    top_findings: list[EmbeddedFinding] | None = None,
) -> ReportRef:
    if severity_kwargs is None:
        severity_kwargs = {}
    if top_findings is None:
        top_findings = []
    return ReportRef(
        report_kind=ReportKind.SCAN,
        scanner="cloudsploit",
        framework="HIPAA",
        provider="aws",
        scope={},
        severity_summary=SeverityBreakdown(**severity_kwargs),
        top_findings=top_findings,
        uri="s3://b/k.json",
        produced_at=datetime.now(timezone.utc),
        produced_by="test",
        parser_version="1.0.0",
    )


def _f(fid: str, sev: str = "HIGH") -> EmbeddedFinding:
    return EmbeddedFinding(finding_id=fid, severity=sev, title=fid)


def _mock_llm() -> AsyncMock:
    """Build a mock LLM that returns a constant executive paragraph."""
    llm = AsyncMock()
    response = MagicMock()
    response.structured_output = _Executive(paragraph="Test executive paragraph.")
    llm.ask = AsyncMock(return_value=response)
    return llm


def _prev_summary(persistent: list[EmbeddedFinding] | None = None) -> WeeklySummary:
    return WeeklySummary(
        framework="HIPAA",
        provider="aws",
        period_start=datetime.now(timezone.utc) - timedelta(days=14),
        period_end=datetime.now(timezone.utc) - timedelta(days=7),
        severity_totals=SeverityBreakdown(),
        new_findings=[],
        resolved_findings=[],
        persistent_findings=persistent or [],
        executive_paragraph="prev",
        source_report_ids=[],
    )


# ---------------------------------------------------------------------------
# WeeklySecuritySummarizer tests
# ---------------------------------------------------------------------------


class TestWeeklySeverityTotals:
    async def test_sums_are_arithmetic(self) -> None:
        """severity_totals must be element-wise sums, never LLM-derived."""
        llm = _mock_llm()
        s = WeeklySecuritySummarizer(llm_client=llm)
        scans = [
            _scan(dict(critical=1, high=2)),
            _scan(dict(critical=3, high=4, medium=5)),
        ]
        summary = await s.build(scans=scans, framework="HIPAA", provider="aws")
        assert summary.severity_totals.critical == 4
        assert summary.severity_totals.high == 6
        assert summary.severity_totals.medium == 5
        assert summary.severity_totals.low == 0
        assert summary.severity_totals.informational == 0

    async def test_empty_scans_produce_zero_totals(self) -> None:
        """Empty scan list must produce zero severity totals."""
        llm = _mock_llm()
        s = WeeklySecuritySummarizer(llm_client=llm)
        summary = await s.build(scans=[], framework="HIPAA", provider="aws")
        assert summary.severity_totals.critical == 0
        assert summary.severity_totals.high == 0


class TestWeeklyLLMCallCount:
    async def test_llm_called_exactly_once(self) -> None:
        """LLM must be invoked exactly once per build() call."""
        llm = _mock_llm()
        s = WeeklySecuritySummarizer(llm_client=llm)
        await s.build(scans=[_scan(dict())], framework="HIPAA", provider="aws")
        assert llm.ask.call_count == 1

    async def test_executive_paragraph_from_llm(self) -> None:
        """executive_paragraph must equal the LLM's returned paragraph."""
        llm = _mock_llm()
        s = WeeklySecuritySummarizer(llm_client=llm)
        summary = await s.build(scans=[_scan(dict())], framework="HIPAA", provider="aws")
        assert summary.executive_paragraph == "Test executive paragraph."


class TestWeeklyDiffDeterminism:
    async def test_same_inputs_same_diffs(self) -> None:
        """Same scans + same previous summary must produce identical diffs across runs."""
        scans = [_scan(dict(), [_f("F1"), _f("F2"), _f("F3")])]
        prev = _prev_summary([_f("F2"), _f("F4")])

        llm = _mock_llm()
        s = WeeklySecuritySummarizer(llm_client=llm)

        a = await s.build(scans=scans, framework="HIPAA", provider="aws", previous_summary_data=prev)
        b = await s.build(scans=scans, framework="HIPAA", provider="aws", previous_summary_data=prev)

        assert {f.finding_id for f in a.new_findings} == {f.finding_id for f in b.new_findings}
        assert {f.finding_id for f in a.resolved_findings} == {f.finding_id for f in b.resolved_findings}
        assert {f.finding_id for f in a.persistent_findings} == {f.finding_id for f in b.persistent_findings}

    async def test_new_findings_are_current_minus_previous(self) -> None:
        """new_findings = current - previous (by finding_id)."""
        scans = [_scan(dict(), [_f("F1"), _f("F2"), _f("F3")])]
        prev = _prev_summary([_f("F2"), _f("F4")])  # F2 persists, F4 resolves

        llm = _mock_llm()
        s = WeeklySecuritySummarizer(llm_client=llm)
        summary = await s.build(scans=scans, framework="HIPAA", provider="aws", previous_summary_data=prev)

        assert {f.finding_id for f in summary.new_findings} == {"F1", "F3"}
        assert {f.finding_id for f in summary.resolved_findings} == {"F4"}
        assert {f.finding_id for f in summary.persistent_findings} == {"F2"}

    async def test_no_previous_all_findings_are_new(self) -> None:
        """Without previous summary, all current findings are new."""
        scans = [_scan(dict(), [_f("F1"), _f("F2")])]
        llm = _mock_llm()
        s = WeeklySecuritySummarizer(llm_client=llm)
        summary = await s.build(scans=scans, framework="HIPAA", provider="aws")

        assert {f.finding_id for f in summary.new_findings} == {"F1", "F2"}
        assert summary.resolved_findings == []
        assert summary.persistent_findings == []

    async def test_source_report_ids_match_scans(self) -> None:
        """source_report_ids must contain exactly the scan report_ids."""
        scans = [_scan(dict()), _scan(dict())]
        expected_ids = {s.report_id for s in scans}

        llm = _mock_llm()
        s = WeeklySecuritySummarizer(llm_client=llm)
        summary = await s.build(scans=scans, framework="HIPAA", provider="aws")

        assert set(summary.source_report_ids) == expected_ids

    async def test_provider_field_set(self) -> None:
        """WeeklySummary.provider must match the provider arg."""
        llm = _mock_llm()
        s = WeeklySecuritySummarizer(llm_client=llm)
        summary = await s.build(scans=[_scan()], framework="HIPAA", provider="gcp")
        assert summary.provider == "gcp"


# ---------------------------------------------------------------------------
# MonthlySecuritySummarizer tests
# ---------------------------------------------------------------------------


def _weekly(
    persistent: list[EmbeddedFinding],
    totals: SeverityBreakdown | None = None,
) -> WeeklySummary:
    return WeeklySummary(
        framework="HIPAA",
        provider="aws",
        period_start=datetime.now(timezone.utc) - timedelta(days=7),
        period_end=datetime.now(timezone.utc),
        severity_totals=totals or SeverityBreakdown(),
        new_findings=[],
        resolved_findings=[],
        persistent_findings=persistent,
        executive_paragraph="weekly exec",
        source_report_ids=[uuid4()],
    )


class TestMonthlySummarizer:
    async def test_severity_totals_sum_weeklies(self) -> None:
        """Monthly severity_totals must be the sum of weekly severity_totals."""
        w1 = _weekly([], totals=SeverityBreakdown(critical=2, high=3))
        w2 = _weekly([], totals=SeverityBreakdown(critical=1, high=2, medium=4))

        llm = _mock_llm()
        s = MonthlySecuritySummarizer(llm_client=llm)
        summary = await s.build(weekly_summaries=[w1, w2], framework="HIPAA", provider="aws")

        assert summary.severity_totals.critical == 3
        assert summary.severity_totals.high == 5
        assert summary.severity_totals.medium == 4

    async def test_persistent_findings_intersection(self) -> None:
        """Monthly persistent_findings = intersection of weekly persistent_finding_ids."""
        # F1 present in both, F2 only in w1, F3 only in w2
        w1 = _weekly([_f("F1"), _f("F2")])
        w2 = _weekly([_f("F1"), _f("F3")])

        llm = _mock_llm()
        s = MonthlySecuritySummarizer(llm_client=llm)
        summary = await s.build(weekly_summaries=[w1, w2], framework="HIPAA", provider="aws")

        assert {f.finding_id for f in summary.persistent_findings} == {"F1"}

    async def test_llm_called_exactly_once(self) -> None:
        """LLM must be invoked exactly once per monthly build()."""
        w1 = _weekly([_f("F1")])
        w2 = _weekly([_f("F1")])

        llm = _mock_llm()
        s = MonthlySecuritySummarizer(llm_client=llm)
        await s.build(weekly_summaries=[w1, w2], framework="HIPAA", provider="aws")

        assert llm.ask.call_count == 1

    async def test_empty_weeklies_empty_persistent(self) -> None:
        """Empty weekly list produces empty persistent_findings."""
        llm = _mock_llm()
        s = MonthlySecuritySummarizer(llm_client=llm)
        summary = await s.build(weekly_summaries=[], framework="HIPAA", provider="aws")
        assert summary.persistent_findings == []
        assert summary.severity_totals.critical == 0

    async def test_provider_field_set(self) -> None:
        """MonthlySummary.provider must match the provider arg."""
        llm = _mock_llm()
        s = MonthlySecuritySummarizer(llm_client=llm)
        summary = await s.build(weekly_summaries=[_weekly([])], framework="HIPAA", provider="container")
        assert summary.provider == "container"
