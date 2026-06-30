"""Shared test fixtures for security advisory tests (FEAT-226).

Provides:
- FakeStore: in-memory SecurityReportStore double with all methods used
  across test_advisory_engine.py, test_soc2_advisory.py, and
  tests/test_security_advisor.py.
- Helper functions: _make_ref, _prowler_finding, _prowler_content.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID, uuid4


from parrot.storage.security_reports import (
    ReportFilter,
    ReportKind,
    ReportRef,
    SeverityBreakdown,
)


# ---------------------------------------------------------------------------
# Unified in-memory store double
# ---------------------------------------------------------------------------


class FakeStore:
    """Minimal SecurityReportStore double for unit tests.

    Supports all methods used across the security advisory test suite:
    query, get, fetch_content, save_report, saved_refs, and
    query_distinct_frameworks.

    Args:
        refs: Optional list of ReportRef objects to pre-populate.
        contents: Optional mapping of report_id UUID → raw bytes.
    """

    def __init__(
        self,
        refs: list[ReportRef] | None = None,
        contents: dict[UUID, bytes] | None = None,
    ) -> None:
        self._refs: list[ReportRef] = refs or []
        self._contents: dict[UUID, bytes] = contents or {}
        self._saved: list[ReportRef] = []

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

    async def get(self, report_id: UUID) -> ReportRef | None:
        """Return a single ref by UUID, or None if not found."""
        for r in self._refs:
            if r.report_id == report_id:
                return r
        return None

    async def fetch_content(self, report_id: UUID) -> bytes:
        """Return raw bytes for a report, or raise KeyError if missing."""
        if report_id not in self._contents:
            raise KeyError(f"No content for report {report_id}")
        return self._contents[report_id]

    async def save_report(self, ref: ReportRef, content: bytes) -> ReportRef:
        """Simulate saving a report (assigns a fake URI, appends to saved list)."""
        saved = ref.model_copy(update={"uri": f"file:///tmp/{ref.report_id}.md"})
        self._saved.append(saved)
        return saved

    def saved_refs(self) -> list[ReportRef]:
        """Return all refs that were passed to save_report."""
        return self._saved

    async def query_distinct_frameworks(self) -> list[str]:
        """Return the set of distinct framework strings in stored refs."""
        return list({r.framework for r in self._refs if r.framework})


# ---------------------------------------------------------------------------
# Shared helper functions
# ---------------------------------------------------------------------------


def _make_ref(
    report_id: UUID | None = None,
    framework: str = "soc2",
    scanner: str = "prowler",
    produced_at: datetime | None = None,
    severity_summary: SeverityBreakdown | None = None,
) -> ReportRef:
    """Build a minimal SCAN ReportRef for test use."""
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
