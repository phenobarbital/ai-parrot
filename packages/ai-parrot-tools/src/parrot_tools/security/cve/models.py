"""CVE records, search results and download receipts (FEAT-778 M12)."""

from __future__ import annotations

import math
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


_CVSS3_AV: Final = {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.2}
_CVSS3_AC: Final = {"L": 0.77, "H": 0.44}
_CVSS3_PR_U: Final = {"N": 0.85, "L": 0.62, "H": 0.27}
_CVSS3_PR_C: Final = {"N": 0.85, "L": 0.68, "H": 0.5}
_CVSS3_UI: Final = {"N": 0.85, "R": 0.62}
_CVSS3_CIA: Final = {"H": 0.56, "L": 0.22, "N": 0.0}


def _roundup(value: float, version: str) -> float:
    """CVSS Roundup: integer-safe for 3.1, ``ceil(x*10)/10`` for 3.0."""
    if version == "3.0":
        return math.ceil(value * 10) / 10
    i = round(value * 100000)
    if i % 10000 == 0:
        return i / 100000.0
    return (math.floor(i / 10000) + 1) / 10.0


def cvss3_base_score(vector: str) -> float | None:
    """Compute the CVSS 3.0/3.1 base score of ``vector``.

    Returns ``None`` (never raises) for CVSS 4.0 vectors, other prefixes, or a
    missing/invalid base metric. CVSS 4.0 needs the macro-vector lookup table and is
    deliberately not scored here.
    """
    try:
        parts = vector.strip().split("/")
        prefix = parts[0]
        if prefix not in ("CVSS:3.0", "CVSS:3.1"):
            return None
        version = prefix.split(":", 1)[1]
        metrics: dict[str, str] = {}
        for part in parts[1:]:
            key, _, val = part.partition(":")
            metrics.setdefault(key, val)
        scope = metrics.get("S")
        if scope not in ("U", "C"):
            return None
        changed = scope == "C"
        av = _CVSS3_AV[metrics["AV"]]
        ac = _CVSS3_AC[metrics["AC"]]
        pr = (_CVSS3_PR_C if changed else _CVSS3_PR_U)[metrics["PR"]]
        ui = _CVSS3_UI[metrics["UI"]]
        c = _CVSS3_CIA[metrics["C"]]
        i = _CVSS3_CIA[metrics["I"]]
        a = _CVSS3_CIA[metrics["A"]]
    except (KeyError, AttributeError, IndexError):
        return None
    iss = 1 - (1 - c) * (1 - i) * (1 - a)
    if changed:
        impact = 7.52 * (iss - 0.029) - 3.25 * (iss - 0.02) ** 15
    else:
        impact = 6.42 * iss
    if impact <= 0:
        return 0.0
    exploitability = 8.22 * av * ac * pr * ui
    total = impact + exploitability
    if changed:
        total *= 1.08
    return _roundup(min(total, 10.0), version)


class CVSS(BaseModel):
    """A CVSS score with its vector and provenance."""

    version: Literal["3.0", "3.1", "4.0"]
    score: float | None = None  # None means "not computed" (e.g. a CVSS 4.0 vector from OSV)
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
