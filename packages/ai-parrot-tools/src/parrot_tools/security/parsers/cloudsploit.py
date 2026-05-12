"""Catalog-level CloudSploit JSON parser.

Parses CloudSploit's scan JSON output (``findings`` + ``summary``) into the
catalog's ``ParsedReport``. Accepts both the raw CloudSploit JSON format and
the ``parrot_tools.cloudsploit.models.ScanResult`` serialized shape.
"""
from __future__ import annotations

import json
from pathlib import Path

from parrot.storage.security_reports import EmbeddedFinding, SeverityBreakdown

from ._types import ParsedReport, load_bytes, sort_findings, validate_section

# CloudSploit native severity strings (status field in raw JSON) → catalog severity
_CS_SEV_MAP: dict[str, str] = {
    "CRITICAL": "CRITICAL",
    "HIGH": "HIGH",
    "MEDIUM": "MEDIUM",
    "LOW": "LOW",
    "INFORMATIONAL": "INFORMATIONAL",
    "INFO": "INFORMATIONAL",
    "WARN": "MEDIUM",
    "FAIL": "HIGH",
    "OK": "INFORMATIONAL",
    "UNKNOWN": "INFORMATIONAL",
}


class CloudSploitParser:
    """Catalog-level parser for CloudSploit scan JSON reports.

    Accepts the CloudSploit native JSON format as emitted by its CLI as
    well as the ``parrot_tools.cloudsploit.models.ScanResult`` serialized
    shape.  Both have a ``findings`` list; the parser normalizes either.

    Attributes:
        parser_version: Fixed at ``"1.0.0"`` for v1 of this catalog.
    """

    parser_version: str = "1.0.0"

    def _load(self, content: bytes | Path) -> dict:
        return json.loads(load_bytes(content))

    def _extract_findings(self, data: dict) -> list[EmbeddedFinding]:
        """Build EmbeddedFinding list from CloudSploit JSON data."""
        findings_raw = data.get("findings", [])
        findings: list[EmbeddedFinding] = []
        for item in findings_raw:
            # Native CloudSploit format has ``status`` (OK/WARN/FAIL/UNKNOWN)
            # parrot_tools ScanResult format has ``severity`` (CRITICAL/HIGH/...)
            sev_raw = (
                item.get("severity") or item.get("status") or "UNKNOWN"
            ).upper()
            sev = _CS_SEV_MAP.get(sev_raw, "INFORMATIONAL")
            plugin = item.get("plugin", "")
            resource = item.get("resource") or item.get("arn", "")
            region = item.get("region", "global")
            finding_id = f"{plugin}/{region}/{resource}" if resource else f"{plugin}/{region}"
            findings.append(
                EmbeddedFinding(
                    finding_id=finding_id,
                    severity=sev,
                    title=item.get("title", plugin),
                    resource_id=resource or None,
                )
            )
        return findings

    def parse(self, content: bytes | Path) -> ParsedReport:
        """Parse CloudSploit JSON into a ``ParsedReport``.

        Args:
            content: Raw CloudSploit JSON bytes or path to the JSON file.

        Returns:
            Deterministic ``ParsedReport`` with severity summary and top 10
            findings sorted by severity desc, then finding_id asc.
        """
        data = self._load(content)
        findings = self._extract_findings(data)
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
        """Extract a named section from the CloudSploit JSON report.

        Args:
            content: Raw CloudSploit JSON bytes or path to the JSON file.
            section: One of ``"summary"``, ``"critical"``, ``"high"``,
                ``"medium"``, ``"low"``, ``"executive"``, ``"full"``.

        Returns:
            Dictionary with section-specific content.

        Raises:
            ValueError: If ``section`` is not in the supported set.
        """
        validate_section(section)
        parsed = self.parse(content)
        data = self._load(content)

        if section == "summary":
            return parsed.severity_summary.model_dump()
        if section == "full":
            return data
        if section == "executive":
            return {"paragraph": ""}
        filtered = [
            f.model_dump() for f in sort_findings(self._extract_findings(data))
            if f.severity.upper() == section.upper()
        ]
        return {"findings": filtered}
