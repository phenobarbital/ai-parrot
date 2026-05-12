"""Catalog-level Trivy JSON parser.

Parses Trivy's schema-version-2 JSON output into the catalog's
``ParsedReport`` (``SeverityBreakdown`` + ``EmbeddedFinding``).
"""
from __future__ import annotations

import json
from pathlib import Path

from parrot.storage.security_reports import EmbeddedFinding, SeverityBreakdown

from ._types import ParsedReport, load_bytes, sort_findings, validate_section

# Trivy severity → catalog severity (uppercase)
_TRIVY_SEV_MAP: dict[str, str] = {
    "CRITICAL": "CRITICAL",
    "HIGH": "HIGH",
    "MEDIUM": "MEDIUM",
    "LOW": "LOW",
    "UNKNOWN": "INFORMATIONAL",
}


class TrivyParser:
    """Catalog-level parser for Trivy filesystem/image JSON reports.

    Accepts Trivy's schema-version-2 JSON (``ArtifactName``, ``Results``
    list with ``Vulnerabilities`` entries).

    Attributes:
        parser_version: Fixed at ``"1.0.0"`` for v1 of this catalog.
    """

    parser_version: str = "1.0.0"

    def _load(self, content: bytes | Path) -> dict:
        return json.loads(load_bytes(content))

    def _extract_findings(self, data: dict) -> list[EmbeddedFinding]:
        """Build EmbeddedFinding list from Trivy JSON data."""
        findings: list[EmbeddedFinding] = []
        results = data.get("Results", [])
        for result in results:
            target = result.get("Target", "")
            for vuln in result.get("Vulnerabilities") or []:
                sev_raw = vuln.get("Severity", "UNKNOWN").upper()
                sev = _TRIVY_SEV_MAP.get(sev_raw, "INFORMATIONAL")
                vuln_id = vuln.get("VulnerabilityID", "")
                pkg = vuln.get("PkgName", "")
                finding_id = f"{vuln_id}/{pkg}" if pkg else vuln_id
                findings.append(
                    EmbeddedFinding(
                        finding_id=finding_id or f"trivy/{target}",
                        severity=sev,
                        title=vuln.get("Title", vuln_id),
                        resource_id=f"{target}:{vuln.get('InstalledVersion', '')}",
                    )
                )
            for misc in result.get("Misconfigurations") or []:
                sev_raw = misc.get("Severity", "UNKNOWN").upper()
                sev = _TRIVY_SEV_MAP.get(sev_raw, "INFORMATIONAL")
                check_id = misc.get("ID", "")
                findings.append(
                    EmbeddedFinding(
                        finding_id=check_id or f"trivy-misc/{target}",
                        severity=sev,
                        title=misc.get("Title", check_id),
                        resource_id=target,
                    )
                )
        return findings

    def parse(self, content: bytes | Path) -> ParsedReport:
        """Parse Trivy JSON into a ``ParsedReport``.

        Args:
            content: Raw Trivy JSON bytes or path to the JSON file.

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
        """Extract a named section from the Trivy JSON report.

        Args:
            content: Raw Trivy JSON bytes or path to the JSON file.
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
        # Severity filter sections
        filtered = [
            f.model_dump() for f in sort_findings(self._extract_findings(data))
            if f.severity.upper() == section.upper()
        ]
        return {"findings": filtered}
