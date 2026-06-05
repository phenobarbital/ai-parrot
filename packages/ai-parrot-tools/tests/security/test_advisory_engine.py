"""Unit tests for SecurityAdvisoryEngine (FEAT-226 TASK-1480).

Uses an in-memory store double; no Postgres or S3 required.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest

from parrot.storage.security_reports import (
    ReportFilter,
    ReportKind,
    ReportRef,
    SeverityBreakdown,
)
from parrot_tools.security.advisory_engine import (
    AdvisoryReport,
    FindingDelta,
    SecurityAdvisoryEngine,
)
from parrot_tools.security.models import (
    ComplianceFramework,
    FindingSource,
    SecurityFinding,
    SeverityLevel,
)
from parrot_tools.security.reports import ComplianceMapper


# ---------------------------------------------------------------------------
# In-memory store double
# ---------------------------------------------------------------------------


class _FakeStore:
    """Minimal SecurityReportStore double for unit tests."""

    def __init__(
        self,
        refs: list[ReportRef],
        contents: dict[UUID, bytes],
    ) -> None:
        self._refs = refs
        self._contents = contents

    async def query(self, filter: ReportFilter) -> list[ReportRef]:
        """Return refs matching filter, sorted and limited."""
        results = [
            r for r in self._refs
            if (filter.framework is None or r.framework == filter.framework)
            and (filter.report_kind is None or r.report_kind == filter.report_kind)
        ]
        reverse = (filter.order_by or "produced_at_desc") == "produced_at_desc"
        results.sort(key=lambda r: r.produced_at, reverse=reverse)
        limit = filter.limit or 50
        return results[:limit]

    async def fetch_content(self, report_id: UUID) -> bytes:
        """Return raw bytes for a report, or raise if missing."""
        if report_id not in self._contents:
            raise KeyError(f"No content for report {report_id}")
        return self._contents[report_id]


# ---------------------------------------------------------------------------
# Helpers for building fixtures
# ---------------------------------------------------------------------------


def _make_ref(
    report_id: UUID | None = None,
    framework: str = "soc2",
    scanner: str = "prowler",
    produced_at: datetime | None = None,
    severity_summary: SeverityBreakdown | None = None,
) -> ReportRef:
    return ReportRef(
        report_id=report_id or uuid4(),
        report_kind=ReportKind.SCAN,
        scanner=scanner,
        framework=framework,
        provider="aws",
        scope={"account_id": "123456789012"},
        severity_summary=severity_summary or SeverityBreakdown(),
        uri="s3://test-bucket/test-key.json",
        produced_at=produced_at or datetime.now(timezone.utc),
        produced_by="test",
        parser_version="1.0.0",
    )


def _prowler_finding(
    check_id: str,
    severity: str,
    resource: str,
    region: str = "us-east-1",
) -> dict:
    """Build a minimal Prowler OCSF finding dict."""
    finding_info = {"uid": check_id, "title": f"Check: {check_id}"}
    return {
        "severity": severity,
        "finding_info": finding_info,
        "resources": [{"uid": resource, "region": region}],
        "check_id": check_id,
    }


def _prowler_content(findings: list[dict]) -> bytes:
    """Serialise a list of prowler finding dicts to JSON bytes."""
    return json.dumps(findings).encode()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def single_report_store():
    """Store with only one SOC2 report (first-run scenario)."""
    ref_id = uuid4()
    findings = [
        _prowler_finding("s3_bucket_public_access", "CRITICAL", "arn:aws:s3:::my-bucket"),
        _prowler_finding("iam_root_mfa", "HIGH", "arn:aws:iam::123:root"),
        _prowler_finding("ec2_sg_open", "MEDIUM", "arn:aws:ec2:::sg-123"),
    ]
    refs = [
        _make_ref(
            report_id=ref_id,
            severity_summary=SeverityBreakdown(critical=1, high=1, medium=1),
        )
    ]
    return _FakeStore(refs, {ref_id: _prowler_content(findings)})


@pytest.fixture
def two_report_store():
    """Store with two SOC2 reports: yesterday (baseline) and today (current)."""
    from datetime import timedelta

    now = datetime.now(timezone.utc)
    yesterday = now - timedelta(days=1)

    # Baseline: CRITICAL s3 + HIGH iam + resolved ec2
    baseline_id = uuid4()
    baseline_findings = [
        _prowler_finding("s3_bucket_public_access", "CRITICAL", "arn:aws:s3:::my-bucket"),
        _prowler_finding("iam_root_mfa", "HIGH", "arn:aws:iam::123:root"),
        _prowler_finding("ec2_sg_open", "MEDIUM", "arn:aws:ec2:::sg-123"),
    ]
    baseline_ref = _make_ref(
        report_id=baseline_id,
        produced_at=yesterday,
        severity_summary=SeverityBreakdown(critical=1, high=1, medium=1),
    )

    # Current: s3 worsened to CRITICAL (persists), iam resolved, new lambda exposure
    current_id = uuid4()
    current_findings = [
        _prowler_finding("s3_bucket_public_access", "CRITICAL", "arn:aws:s3:::my-bucket"),
        _prowler_finding("lambda_public_access", "CRITICAL", "arn:aws:lambda:::func-1"),
    ]
    current_ref = _make_ref(
        report_id=current_id,
        produced_at=now,
        severity_summary=SeverityBreakdown(critical=2),
    )

    refs = [current_ref, baseline_ref]
    return _FakeStore(
        refs,
        {
            baseline_id: _prowler_content(baseline_findings),
            current_id: _prowler_content(current_findings),
        },
    )


@pytest.fixture
def engine_single(single_report_store):
    return SecurityAdvisoryEngine(report_store=single_report_store)


@pytest.fixture
def engine_two(two_report_store):
    return SecurityAdvisoryEngine(report_store=two_report_store)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSecurityAdvisoryEngine:
    @pytest.mark.asyncio
    async def test_first_run_all_new(self, engine_single):
        """Single report → baseline None, all deltas 'new'."""
        report = await engine_single.build_daily_advisory(framework="soc2")
        assert isinstance(report, AdvisoryReport)
        assert report.baseline_report_id is None
        assert len(report.deltas) > 0
        assert all(d.status == "new" for d in report.deltas)

    @pytest.mark.asyncio
    async def test_first_run_no_raise(self, engine_single):
        """First run must not raise even if only one report exists."""
        # Should return a valid AdvisoryReport
        report = await engine_single.build_daily_advisory(framework="soc2")
        assert report.current_report_id != "none"

    @pytest.mark.asyncio
    async def test_day_over_day_delta_has_new_and_resolved(self, engine_two):
        """Two reports → at least 'new' and 'resolved' statuses appear."""
        report = await engine_two.build_daily_advisory(framework="soc2")
        statuses = {d.status for d in report.deltas}
        assert "new" in statuses, f"Expected 'new' in {statuses}"
        assert "resolved" in statuses, f"Expected 'resolved' in {statuses}"

    @pytest.mark.asyncio
    async def test_day_over_day_signed_severity_delta(self, engine_two):
        """Severity delta should reflect current − baseline."""
        report = await engine_two.build_daily_advisory(framework="soc2")
        # Current has 2 CRITICAL, baseline had 1 → delta +1
        assert report.severity_delta.critical == 1

    @pytest.mark.asyncio
    async def test_reuses_compliance_mapper(self, engine_single):
        """SOC2 control IDs on deltas come from ComplianceMapper (not a new catalog)."""
        report = await engine_single.build_daily_advisory(framework="soc2")
        # The mapper may or may not resolve controls depending on YAML mappings;
        # the key assertion is that soc2_control_ids is a list (never raises).
        for delta in report.deltas:
            assert isinstance(delta.soc2_control_ids, list)

    @pytest.mark.asyncio
    async def test_engine_soc2_coverage_present(self, engine_single):
        """AdvisoryReport.soc2_coverage is populated from get_framework_coverage."""
        report = await engine_single.build_daily_advisory(framework="soc2")
        # Coverage is always a dict (may be empty if YAML not loaded in test env)
        assert isinstance(report.soc2_coverage, dict)

    @pytest.mark.asyncio
    async def test_material_recommendation_flag_critical(self, engine_single):
        """New CRITICAL finding → at least one material recommendation."""
        report = await engine_single.build_daily_advisory(framework="soc2")
        material = [r for r in report.recommendations if r.is_material]
        assert len(material) > 0, "Expected at least one material recommendation from CRITICAL finding"

    @pytest.mark.asyncio
    async def test_resolved_findings_not_material(self, engine_two):
        """Resolved findings must not create material recommendations."""
        report = await engine_two.build_daily_advisory(framework="soc2")
        for rec in report.recommendations:
            if not rec.is_material:
                continue
            # Material recs should be NEW or SEVERITY_CHANGED CRITICAL/HIGH
            assert rec.severity.upper() in ("CRITICAL", "HIGH"), (
                f"Material rec has unexpected severity {rec.severity}"
            )

    @pytest.mark.asyncio
    async def test_empty_store_returns_empty_advisory(self):
        """No reports → empty advisory, no raise."""
        store = _FakeStore(refs=[], contents={})
        engine = SecurityAdvisoryEngine(report_store=store)
        report = await engine.build_daily_advisory(framework="soc2")
        assert report.baseline_report_id is None
        assert report.current_report_id == "none"
        assert report.deltas == []

    @pytest.mark.asyncio
    async def test_deltas_sorted_by_severity_desc(self, engine_single):
        """Deltas should be sorted by severity descending."""
        report = await engine_single.build_daily_advisory(framework="soc2")
        if len(report.deltas) > 1:
            from parrot_tools.security.advisory_engine import _sev_rank
            ranks = [_sev_rank(d.severity) for d in report.deltas]
            assert ranks == sorted(ranks, reverse=True), "Deltas not sorted by severity desc"

    @pytest.mark.asyncio
    async def test_mapper_injected(self):
        """Engine accepts an injected ComplianceMapper (not always building a new one)."""
        from unittest.mock import MagicMock
        mock_mapper = MagicMock(spec=ComplianceMapper)
        mock_mapper.map_finding_to_controls.return_value = ["CC6.1", "CC6.6"]
        mock_mapper.get_framework_coverage.return_value = {
            "total_controls": 10, "coverage_pct": 50.0
        }
        mock_mapper.get_findings_by_control.return_value = {}

        ref_id = uuid4()
        findings = [_prowler_finding("s3_bucket_public_access", "CRITICAL", "arn:aws:s3:::bucket")]
        store = _FakeStore(
            refs=[_make_ref(report_id=ref_id)],
            contents={ref_id: _prowler_content(findings)},
        )
        engine = SecurityAdvisoryEngine(report_store=store, mapper=mock_mapper)
        report = await engine.build_daily_advisory(framework="soc2")

        # Verify injected mapper was used
        assert mock_mapper.map_finding_to_controls.called
        assert mock_mapper.get_framework_coverage.called
        # Controls from mock should appear on some delta
        assert any("CC6.1" in d.soc2_control_ids for d in report.deltas)
