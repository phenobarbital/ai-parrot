"""Shared types for the catalog-level scanner parser registry.

These types are SEPARATE from parrot_tools.security.models (which serves
scanner-internal normalization). This layer normalizes into the catalog's
EmbeddedFinding / SeverityBreakdown shapes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from parrot.storage.security_reports import EmbeddedFinding, SeverityBreakdown

# ---------------------------------------------------------------------------
# Severity rank for deterministic sort (CRITICAL=4 ... INFORMATIONAL=0)
# ---------------------------------------------------------------------------

SEVERITY_RANK: dict[str, int] = {
    "CRITICAL": 4,
    "HIGH": 3,
    "MEDIUM": 2,
    "LOW": 1,
    "INFORMATIONAL": 0,
    "INFO": 0,
    "UNKNOWN": 0,
}


@dataclass(frozen=True)
class ParsedReport:
    """Result returned by every catalog-level parser's ``parse()`` method.

    Attributes:
        severity_summary: Aggregated severity counts for the report.
        top_findings: Up to 10 findings sorted by severity desc, then finding_id asc.
    """

    severity_summary: SeverityBreakdown
    top_findings: list[EmbeddedFinding] = field(default_factory=list)


class ReportParser(Protocol):
    """Protocol every catalog-level parser must satisfy.

    Attributes:
        parser_version: Semantic version string used to populate
            ``ReportRef.parser_version`` (e.g., ``"1.0.0"``).
    """

    parser_version: str

    def parse(self, content: bytes | Path) -> ParsedReport:
        """Parse scanner output into a canonical ``ParsedReport``.

        Args:
            content: Raw scanner JSON as bytes, or a ``Path`` to the file.

        Returns:
            Deterministic ``ParsedReport`` — same input always produces the
            same output.
        """
        ...

    def extract_section(self, content: bytes | Path, section: str) -> dict:
        """Extract a named section from the scanner output.

        Args:
            content: Raw scanner JSON as bytes or ``Path``.
            section: One of ``"summary"``, ``"critical"``, ``"high"``,
                ``"medium"``, ``"low"``, ``"executive"``, ``"full"``.

        Returns:
            Dictionary with section-specific content.

        Raises:
            ValueError: If ``section`` is not one of the supported values.
        """
        ...


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_SECTIONS = frozenset(
    {"summary", "critical", "high", "medium", "low", "executive", "full"}
)


def validate_section(section: str) -> None:
    """Raise ValueError if section is not in the supported set."""
    if section not in _VALID_SECTIONS:
        raise ValueError(
            f"Unknown section {section!r}. "
            f"Valid values: {sorted(_VALID_SECTIONS)}"
        )


def sort_findings(findings: list[EmbeddedFinding]) -> list[EmbeddedFinding]:
    """Sort findings by severity desc, then finding_id asc (deterministic).

    Args:
        findings: Unsorted list of EmbeddedFinding objects.

    Returns:
        Sorted list (mutates a copy, not in-place).
    """
    return sorted(
        findings,
        key=lambda f: (-SEVERITY_RANK.get(f.severity.upper(), 0), f.finding_id),
    )


def load_bytes(content: bytes | Path) -> bytes:
    """Normalise content to bytes regardless of input type.

    Args:
        content: Raw bytes or path to a file.

    Returns:
        File content as bytes.
    """
    if isinstance(content, Path):
        return content.read_bytes()
    return content
