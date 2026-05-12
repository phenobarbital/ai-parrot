"""Catalog-level Prowler JSON parser.

Parses Prowler's JSON-OCSF output (array of finding objects) into the
catalog's ``ParsedReport``.
"""
from __future__ import annotations

import json
from pathlib import Path

from parrot.storage.security_reports import EmbeddedFinding, SeverityBreakdown

from ._types import ParsedReport, load_bytes, sort_findings, validate_section

_PROWLER_SEV_MAP: dict[str, str] = {
    "critical": "CRITICAL",
    "high": "HIGH",
    "medium": "MEDIUM",
    "low": "LOW",
    "informational": "INFORMATIONAL",
    "info": "INFORMATIONAL",
    "unknown": "INFORMATIONAL",
}


class ProwlerParser:
    """Catalog-level parser for Prowler JSON-OCSF reports.

    Accepts either a JSON array ``[{...}, ...]`` or NDJSON format.

    Attributes:
        parser_version: Fixed at ``"1.0.0"`` for v1 of this catalog.
    """

    parser_version: str = "1.0.0"

    def _load(self, content: bytes | Path) -> list[dict]:
        raw = load_bytes(content).decode("utf-8", errors="replace").strip()
        if raw.startswith("["):
            return json.loads(raw)
        # NDJSON — one JSON object per line
        items = []
        for line in raw.splitlines():
            line = line.strip()
            if line:
                items.append(json.loads(line))
        return items

    def _extract_findings(self, items: list[dict]) -> list[EmbeddedFinding]:
        findings: list[EmbeddedFinding] = []
        for item in items:
            sev_raw = (item.get("severity") or "informational").lower()
            sev = _PROWLER_SEV_MAP.get(sev_raw, "INFORMATIONAL")
            # OCSF shape
            fi = item.get("finding_info") or {}
            check_id = fi.get("uid") or item.get("check_id", "")
            title = fi.get("title") or item.get("check_title", check_id)
            resource_uid = (item.get("resources") or [{}])[0].get("uid", "")
            region = (item.get("resources") or [{}])[0].get("region", "global")
            finding_id = f"{check_id}/{region}/{resource_uid}" if resource_uid else f"{check_id}/{region}"
            findings.append(
                EmbeddedFinding(
                    finding_id=finding_id,
                    severity=sev,
                    title=title,
                    resource=resource_uid,
                    description=item.get("message") or item.get("status_detail", ""),
                )
            )
        return findings

    def parse(self, content: bytes | Path) -> ParsedReport:
        """Parse Prowler JSON-OCSF output into a ``ParsedReport``.

        Args:
            content: Raw Prowler JSON bytes or path to the JSON file.

        Returns:
            Deterministic ``ParsedReport``.
        """
        items = self._load(content)
        findings = self._extract_findings(items)
        sorted_findings = sort_findings(findings)

        counts: dict[str, int] = {
            "critical": 0, "high": 0, "medium": 0, "low": 0, "informational": 0,
        }
        for f in findings:
            sev = f.severity.lower()
            if sev in counts:
                counts[sev] += 1
            else:
                counts["informational"] += 1

        return ParsedReport(
            severity_summary=SeverityBreakdown(
                critical=counts["critical"],
                high=counts["high"],
                medium=counts["medium"],
                low=counts["low"],
                informational=counts["informational"],
            ),
            top_findings=sorted_findings[:10],
        )

    def extract_section(self, content: bytes | Path, section: str) -> dict:
        """Extract a named section from the Prowler JSON report.

        Args:
            content: Raw Prowler JSON bytes or path to the JSON file.
            section: One of ``"summary"``, ``"critical"``, ``"high"``,
                ``"medium"``, ``"low"``, ``"executive"``, ``"full"``.

        Returns:
            Dictionary with section-specific content.

        Raises:
            ValueError: If ``section`` is not in the supported set.
        """
        validate_section(section)
        parsed = self.parse(content)
        items = self._load(content)

        if section == "summary":
            return parsed.severity_summary.model_dump()
        if section == "full":
            return {"findings": items}
        if section == "executive":
            return {"paragraph": ""}
        filtered = [
            f.model_dump() for f in sort_findings(self._extract_findings(items))
            if f.severity.upper() == section.upper()
        ]
        return {"findings": filtered}
