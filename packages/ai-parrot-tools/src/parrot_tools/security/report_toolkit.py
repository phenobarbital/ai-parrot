"""SecurityReportToolkit — LLM-facing read side of the security report catalog.

This toolkit exposes the catalog to the LLM as agent tools.  The agent
calls these tools BEFORE running expensive scanners, guided by the freshness
policy in the SecurityAgent BACKSTORY.

Module implements Spec §3 Module 7.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from ..toolkit import AbstractToolkit
from parrot.interfaces.file import FileManagerInterface
from parrot.storage.security_reports import (
    ReportFilter,
    ReportKind,
    ReportRef,
    SecurityReportStore,
)
from parrot_tools.security.parsers import get_report_parser


class SecurityReportToolkit(AbstractToolkit):
    """LLM-facing tools for querying the cross-session security report catalog.

    These tools cover the **read side** of the catalog.  The write side is
    handled by ``ReportPersistenceMixin`` (TASK-1109) composited into each
    scanner toolkit.

    Usage pattern (agent BACKSTORY instructs this flow)::

        1. find_security_report(...)  → check if a fresh report exists
        2. read_security_report(id, "summary")  → assess severity
        3. read_security_report(id, "critical")  → get critical details
        4. (only if stale / absent) → run scanner toolkit
    """

    DEFAULT_VISIBILITY_DAYS: int = 30

    def __init__(
        self,
        report_store: SecurityReportStore,
        file_manager: FileManagerInterface,
        **kwargs,
    ) -> None:
        """Initialize SecurityReportToolkit.

        Args:
            report_store: Catalog persistence backend.
            file_manager: File manager for content downloads.
            **kwargs: Additional arguments forwarded to AbstractToolkit.
        """
        super().__init__(**kwargs)
        self._store = report_store
        self._fm = file_manager
        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Public async methods — auto-discovered as agent tools
    # ------------------------------------------------------------------

    async def find_security_report(
        self,
        scanner: str | None = None,
        framework: str | None = None,
        provider: str | None = None,
        scope_match: dict | None = None,
        max_age_days: int = 30,
        report_kind: str = "scan",
        limit: int = 5,
    ) -> list[dict]:
        """Find recent security reports matching the filter criteria.

        Returns metadata only (severity summary + top-10 embedded findings).
        Does NOT fetch or download full report content.

        **Freshness policy**: Always call this BEFORE running expensive scan
        tools.  If a report exists that is fresh enough (within
        ``max_age_days``), use ``read_security_report`` to read its details
        instead of re-scanning.

        Args:
            scanner: Filter by scanner name (e.g., ``"cloudsploit"``,
                ``"trivy"``, ``"prowler"``). None matches all.
            framework: Compliance framework filter (e.g., ``"HIPAA"``).
                None matches all.
            provider: Cloud provider filter (e.g., ``"aws"``). None matches all.
            scope_match: JSONB containment filter for the scope dict
                (e.g., ``{"account_id": "123"}`` matches any report whose
                scope contains that key-value pair).
            max_age_days: Only return reports produced within the last
                ``max_age_days`` days (default 30).  Set higher to look
                further back.
            report_kind: Report kind to filter on. One of ``"scan"``,
                ``"weekly_summary"``, ``"monthly_summary"``,
                ``"drift_comparison"`` (default ``"scan"``).
            limit: Maximum number of reports to return (default 5).

        Returns:
            List of report metadata dicts (JSON-serializable), sorted by
            ``produced_at`` descending.  Empty list if no match found.
        """
        since = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        try:
            kind = ReportKind(report_kind)
        except ValueError:
            kind = ReportKind.SCAN

        refs = await self._store.query(
            ReportFilter(
                scanner=scanner,
                framework=framework,
                provider=provider,
                scope_match=scope_match,
                report_kind=kind,
                since=since,
                limit=limit,
            )
        )
        return [r.model_dump(mode="json") for r in refs]

    async def read_security_report(
        self,
        report_id: str,
        section: Literal[
            "summary", "critical", "high", "medium", "low", "executive", "full"
        ] = "summary",
    ) -> dict:
        """Read a specific section of a security report.

        Section semantics:
        - ``"summary"``   — Returns metadata (severity counts, scanner, scope)
          WITHOUT downloading full content.  Start here.
        - ``"critical"``  — Returns only CRITICAL findings (fetches content).
        - ``"high"``      — Returns only HIGH findings (fetches content).
        - ``"medium"``    — Returns only MEDIUM findings (fetches content).
        - ``"low"``       — Returns only LOW findings (fetches content).
        - ``"executive"`` — Returns narrative paragraph (only meaningful for
          ``WEEKLY_SUMMARY`` / ``MONTHLY_SUMMARY`` report kinds; other
          parsers return an empty paragraph string).
        - ``"full"``      — Returns the entire parsed structure (fetches content).
          Use sparingly; full reports can be large.

        Args:
            report_id: UUID of the report to read.
            section: Named section to extract. Defaults to ``"summary"``.

        Returns:
            Section-specific dict.  Returns ``{"error": "..."}`` if the
            report is not found.  Raises ``ValueError`` if ``section`` is
            not one of the supported values.
        """
        try:
            rid = UUID(report_id)
        except ValueError:
            return {"error": f"Invalid report_id: {report_id!r}"}

        ref = await self._store.get(rid)
        if ref is None:
            return {"error": f"Report {report_id} not found"}

        if section == "summary":
            return {"ref": ref.model_dump(mode="json")}

        # For all non-summary sections, fetch the full content and dispatch
        # to the appropriate parser.
        content = await self._store.fetch_content(rid)
        parser = get_report_parser(ref.scanner)
        return parser.extract_section(content, section)

    async def search_findings(
        self,
        query: str,
        scanner: str | None = None,
        severity: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"] | None = None,
        since_days: int = 30,
        limit: int = 20,
    ) -> list[dict]:
        """Search security findings across catalog reports.

        **v1 LIMITATION**: This method only matches against the embedded
        ``top_findings`` JSONB column (the top-10 findings stored at write
        time per report).  Findings ranked 11th or lower within a report are
        NOT included in search results.  Communicate this limitation to users
        when they ask broad questions — a finding may exist in the catalog
        without appearing here.

        Args:
            query: Free-text search string matched against finding titles and
                descriptions (case-insensitive substring match on
                ``top_findings::text``).
            scanner: Narrow to a specific scanner. None searches all.
            severity: Filter by severity level. None searches all severity levels.
            since_days: Look back at most ``since_days`` days (default 30).
            limit: Maximum number of reports to search (default 20).

        Returns:
            List of finding dicts ``{report_id, scanner, framework, severity,
            title, resource, description}`` that match the query.
        """
        since = datetime.now(timezone.utc) - timedelta(days=since_days)
        refs = await self._store.query(
            ReportFilter(
                scanner=scanner,
                since=since,
                limit=limit,
            )
        )
        # v1: in-Python filter on top_findings
        query_lower = query.lower()
        matches: list[dict] = []
        for ref in refs:
            for finding in ref.top_findings:
                if severity and finding.severity.upper() != severity.upper():
                    continue
                text = f"{finding.title} {finding.rule_id or ''} {finding.remediation_hint or ''}".lower()
                if query_lower in text:
                    matches.append(
                        {
                            "report_id": str(ref.report_id),
                            "scanner": ref.scanner,
                            "framework": ref.framework,
                            "severity": finding.severity,
                            "title": finding.title,
                            "resource_id": finding.resource_id,
                            "rule_id": finding.rule_id,
                        }
                    )
        return matches

    async def list_available_frameworks(self) -> list[str]:
        """List compliance frameworks for which reports exist in the catalog.

        Useful for diagnosing what data is available before calling
        ``find_security_report``.

        Returns:
            Sorted, deduplicated list of framework strings (e.g.,
            ``["HIPAA", "PCI", "SOC2"]``).  Empty list if no reports exist.
        """
        # Push DISTINCT computation to the database to avoid unbounded Python
        # aggregation over potentially thousands of rows.
        rows = await self._store.query_distinct_frameworks()
        return sorted(rows)
