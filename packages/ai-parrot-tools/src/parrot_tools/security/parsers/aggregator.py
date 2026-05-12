"""Catalog-level Aggregator passthrough parser.

For ``WEEKLY_SUMMARY`` / ``MONTHLY_SUMMARY`` report kinds, the content IS
already a serialized summary JSON produced by the summarizer.  The aggregator
parser extracts the severity breakdown and executive paragraph directly from
that structure without re-parsing scanner output.
"""
from __future__ import annotations

import json
from pathlib import Path

from parrot.storage.security_reports import EmbeddedFinding, SeverityBreakdown

from ._types import ParsedReport, load_bytes, sort_findings, validate_section


class AggregatorParser:
    """Passthrough parser for weekly / monthly aggregated summary reports.

    The expected JSON shape mirrors the output of ``WeeklySummarizer`` /
    ``MonthlySummarizer``:

    .. code-block:: json

        {
          "severity_summary": {"critical": 2, "high": 5, ...},
          "top_findings": [
            {"finding_id": "...", "severity": "CRITICAL", "title": "...", ...}
          ],
          "executive_paragraph": "Overall posture improved this week..."
        }

    Attributes:
        parser_version: Fixed at ``"1.0.0"`` for v1 of this catalog.
    """

    parser_version: str = "1.0.0"

    def _load(self, content: bytes | Path) -> dict:
        return json.loads(load_bytes(content))

    def parse(self, content: bytes | Path) -> ParsedReport:
        """Parse an aggregated summary JSON into a ``ParsedReport``.

        Args:
            content: Raw summary JSON bytes or path to the JSON file.

        Returns:
            Deterministic ``ParsedReport`` reflecting the pre-computed
            severity summary and top findings.
        """
        data = self._load(content)
        sev_raw = data.get("severity_summary", {})
        sev = SeverityBreakdown(
            critical=sev_raw.get("critical", 0),
            high=sev_raw.get("high", 0),
            medium=sev_raw.get("medium", 0),
            low=sev_raw.get("low", 0),
            informational=sev_raw.get("informational", 0),
        )
        raw_findings = data.get("top_findings", [])
        findings = [
            EmbeddedFinding(
                finding_id=f.get("finding_id", f"agg/{i}"),
                severity=f.get("severity", "INFORMATIONAL"),
                title=f.get("title", ""),
                resource=f.get("resource", ""),
                description=f.get("description", ""),
            )
            for i, f in enumerate(raw_findings)
        ]
        sorted_findings = sort_findings(findings)
        return ParsedReport(
            severity_summary=sev,
            top_findings=sorted_findings[:10],
        )

    def extract_section(self, content: bytes | Path, section: str) -> dict:
        """Extract a named section from the aggregated summary JSON.

        For ``"executive"``, returns the ``executive_paragraph`` text if
        present (only meaningful for this parser — others return ``""``).

        Args:
            content: Raw summary JSON bytes or path to the JSON file.
            section: One of ``"summary"``, ``"critical"``, ``"high"``,
                ``"medium"``, ``"low"``, ``"executive"``, ``"full"``.

        Returns:
            Dictionary with section-specific content.

        Raises:
            ValueError: If ``section`` is not in the supported set.
        """
        validate_section(section)
        data = self._load(content)
        parsed = self.parse(content)

        if section == "summary":
            return parsed.severity_summary.model_dump()
        if section == "full":
            return data
        if section == "executive":
            return {"paragraph": data.get("executive_paragraph", "")}
        filtered = [
            f.model_dump() for f in sort_findings(parsed.top_findings)
            if f.severity.upper() == section.upper()
        ]
        return {"findings": filtered}
