"""Catalog-level Checkov JSON parser.

Parses Checkov's ``check_type`` / ``results`` JSON format into the catalog's
``ParsedReport``.
"""
from __future__ import annotations

import json
from pathlib import Path

from parrot.storage.security_reports import EmbeddedFinding, SeverityBreakdown

from ._types import ParsedReport, load_bytes, sort_findings, validate_section

_CHECKOV_SEV_MAP: dict[str, str] = {
    "CRITICAL": "CRITICAL",
    "HIGH": "HIGH",
    "MEDIUM": "MEDIUM",
    "LOW": "LOW",
    "NONE": "INFORMATIONAL",
    "UNKNOWN": "INFORMATIONAL",
}


class CheckovParser:
    """Catalog-level parser for Checkov JSON reports.

    Accepts both single-check-type ``{check_type, results, ...}`` and a
    list of per-check-type objects (Checkov can produce either).

    Attributes:
        parser_version: Fixed at ``"1.0.0"`` for v1 of this catalog.
    """

    parser_version: str = "1.0.0"

    def _load(self, content: bytes | Path) -> list[dict]:
        """Return a list of check-type result blocks regardless of input shape."""
        raw = json.loads(load_bytes(content))
        if isinstance(raw, list):
            return raw
        if isinstance(raw, dict):
            # Single check-type result or multi-type wrapper
            if "check_type" in raw:
                return [raw]
            # Could be {check_type: {results: ...}}; flatten
            return list(raw.values()) if raw else []
        return []

    def _extract_findings(self, blocks: list[dict]) -> list[EmbeddedFinding]:
        findings: list[EmbeddedFinding] = []
        for block in blocks:
            results = block.get("results", {})
            failed = results.get("failed_checks", [])
            for check in failed:
                check_id = check.get("check_id", "")
                check_type = block.get("check_type", "")
                sev_raw = (check.get("severity") or "NONE").upper()
                sev = _CHECKOV_SEV_MAP.get(sev_raw, "INFORMATIONAL")
                resource = check.get("resource", "")
                file_path = check.get("repo_file_path") or check.get("file_path", "")
                finding_id = f"{check_id}/{file_path}/{resource}" if resource else f"{check_id}/{file_path}"
                findings.append(
                    EmbeddedFinding(
                        finding_id=finding_id or f"checkov/{check_type}",
                        severity=sev,
                        title=check.get("check_name", check_id),
                        resource=resource or file_path,
                        description=check.get("description", ""),
                    )
                )
        return findings

    def parse(self, content: bytes | Path) -> ParsedReport:
        """Parse Checkov JSON into a ``ParsedReport``.

        Args:
            content: Raw Checkov JSON bytes or path to the JSON file.

        Returns:
            Deterministic ``ParsedReport``.
        """
        blocks = self._load(content)
        findings = self._extract_findings(blocks)
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
        """Extract a named section from the Checkov JSON report.

        Args:
            content: Raw Checkov JSON bytes or path to the JSON file.
            section: One of ``"summary"``, ``"critical"``, ``"high"``,
                ``"medium"``, ``"low"``, ``"executive"``, ``"full"``.

        Returns:
            Dictionary with section-specific content.

        Raises:
            ValueError: If ``section`` is not in the supported set.
        """
        validate_section(section)
        parsed = self.parse(content)
        blocks = self._load(content)

        if section == "summary":
            return parsed.severity_summary.model_dump()
        if section == "full":
            return {"blocks": blocks}
        if section == "executive":
            return {"paragraph": ""}
        filtered = [
            f.model_dump() for f in sort_findings(self._extract_findings(blocks))
            if f.severity.upper() == section.upper()
        ]
        return {"findings": filtered}
