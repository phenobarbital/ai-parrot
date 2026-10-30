"""CVE records, search results and download receipts (FEAT-778 M12)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Final, Literal

from pydantic import BaseModel, Field

from parrot_tools.security.models import SeverityLevel

CVE_ID_RE: Final[re.Pattern[str]] = re.compile(r"^CVE-\d{4}-\d{4,}$")
OSV_ECOSYSTEMS: Final[tuple[str, ...]] = (
    "PyPI",
    "npm",
    "crates.io",
    "Go",
    "Maven",
    "NuGet",
    "RubyGems",
    "Packagist",
    "Pub",
    "Hex",
)


class CVEToolkitError(Exception):
    """A CVE operation failed (bad namespace, write failure, provider error surfaced to the caller)."""


class CVENotFoundError(CVEToolkitError):
    """OSV has no record for the id (HTTP 404)."""


class CVSS(BaseModel):
    """A CVSS score with its vector and provenance."""

    version: Literal["3.0", "3.1", "4.0"]
    score: float
    vector: str
    source: Literal["osv", "nvd"]


class AffectedPackage(BaseModel):
    """A package affected by a vulnerability."""

    ecosystem: str
    name: str
    introduced: str | None = None
    fixed: str | None = None
    versions: list[str] = Field(default_factory=list)


class CVERecord(BaseModel):
    """A normalised CVE record merged from OSV, NVD and EPSS."""

    id: str
    aliases: list[str] = Field(default_factory=list)
    summary: str = ""
    details: str = ""
    severity: SeverityLevel = SeverityLevel.UNKNOWN
    cvss: list[CVSS] = Field(default_factory=list)
    epss: float | None = None
    cwe_ids: list[str] = Field(default_factory=list)
    affected: list[AffectedPackage] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    published: datetime | None = None
    modified: datetime | None = None
    sources: list[Literal["osv", "nvd", "epss"]] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class CVESearchResult(BaseModel):
    """CVE records found for a package (optionally at a given version)."""

    package: str
    ecosystem: str
    version: str | None = None
    records: list[CVERecord] = Field(default_factory=list)


class DownloadReceipt(BaseModel):
    """Receipt of a CVE record persisted to a wiki."""

    cve_id: str
    wiki_name: str
    concept_id: str
    json_path: str
    content_hash: str


def validate_cve_id(cve_id: str) -> str:
    """Return the stripped CVE id; raise ValueError when it does not match CVE_ID_RE.

    Args:
        cve_id: Candidate id such as ``CVE-2026-98432``.

    Returns:
        The stripped id.

    Raises:
        ValueError: When the id is not a well-formed upper-case CVE id.
    """
    candidate = cve_id.strip() if isinstance(cve_id, str) else ""
    if not CVE_ID_RE.match(candidate):
        raise ValueError(f"Invalid CVE id: {cve_id!r}")
    return candidate


def severity_from_score(score: float | None) -> SeverityLevel:
    """CRITICAL >=9, HIGH >=7, MEDIUM >=4, LOW >0, INFO ==0, UNKNOWN when None (see Context).

    Args:
        score: CVSS base score, or None when unavailable.

    Returns:
        The normalised severity level.
    """
    if score is None:
        return SeverityLevel.UNKNOWN
    if score >= 9.0:
        return SeverityLevel.CRITICAL
    if score >= 7.0:
        return SeverityLevel.HIGH
    if score >= 4.0:
        return SeverityLevel.MEDIUM
    if score > 0:
        return SeverityLevel.LOW
    return SeverityLevel.INFO
