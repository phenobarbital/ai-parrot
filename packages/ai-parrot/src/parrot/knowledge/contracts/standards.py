"""Compliance standards seeded for the contracts pilot.

Eight hand-written :class:`ComplianceStandard` entries with deterministic
aliases. The framework ids (``soc2``, ``hipaa``, ``pci_dss``) match the
existing security report mappings under
``parrot_tools/security/reports/mappings/`` so a contract clause and a
scanner finding name the same standard.

Alias resolution is deterministic and LLM-free: it is used both at carding
time (mapping a clause's ``standard_name`` onto a stable id) and at
retrieval time (finding "SOC 2" inside a full question without erasing the
rest of the entity).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional

from pydantic import BaseModel, Field

__all__ = (
    "ComplianceStandard",
    "STANDARDS",
    "STANDARD_IDS",
    "normalize_standard_text",
    "get_standard",
    "resolve_standard",
    "find_standards",
)

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


class ComplianceStandard(BaseModel):
    """One compliance standard a contract can require.

    Args:
        standard_id: Stable snake_case id (also the ontology vertex key).
        name: Human-readable standard name.
        aliases: Normalized alias forms that resolve to this standard.
        category: Coarse grouping used by reports and digests.
    """

    standard_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    aliases: tuple[str, ...] = ()
    category: str = "compliance"


def normalize_standard_text(text: str) -> str:
    """Normalize free text for alias matching.

    NFKD-normalizes, strips diacritics, lowercases and collapses every
    non-alphanumeric run into a single space.

    Args:
        text: Free-form text (a clause excerpt, a question, an alias).

    Returns:
        The normalized, space-separated form.
    """
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii").lower()
    return _NON_ALNUM.sub(" ", ascii_text).strip()


def _standard(
    standard_id: str,
    name: str,
    aliases: tuple[str, ...],
    category: str = "compliance",
) -> ComplianceStandard:
    """Build a standard with normalized, de-duplicated aliases."""
    seen: list[str] = []
    for alias in (standard_id, *aliases):
        normalized = normalize_standard_text(alias)
        if normalized and normalized not in seen:
            seen.append(normalized)
    return ComplianceStandard(
        standard_id=standard_id,
        name=name,
        aliases=tuple(seen),
        category=category,
    )


#: The standards seeded before any ``requires`` edge is discovered.
STANDARDS: dict[str, ComplianceStandard] = {
    standard.standard_id: standard
    for standard in (
        _standard(
            "soc2",
            "SOC 2",
            (
                "soc 2",
                "soc ii",
                "soc-2",
                "soc 2 type i",
                "soc 2 type ii",
                "soc 2 type 2",
                "soc2 type 2",
                "service organization control 2",
                "ssae 18",
                "ssae 16",
                "aicpa trust services criteria",
            ),
        ),
        _standard(
            "soc1",
            "SOC 1",
            (
                "soc 1",
                "soc i",
                "soc-1",
                "soc 1 type i",
                "soc 1 type ii",
                "soc 1 type 2",
                "soc1 type 2",
                "service organization control 1",
            ),
        ),
        _standard(
            "iso27001",
            "ISO/IEC 27001",
            (
                "iso 27001",
                "iso/iec 27001",
                "iso iec 27001",
                "iso 27001:2013",
                "iso 27001:2022",
                "isms certification",
                "information security management system certification",
            ),
        ),
        _standard(
            "gdpr",
            "General Data Protection Regulation",
            (
                "general data protection regulation",
                "eu gdpr",
                "regulation (eu) 2016/679",
                "regulation eu 2016 679",
                "2016/679",
            ),
            category="data_protection",
        ),
        _standard(
            "uk_gdpr",
            "UK GDPR",
            (
                "uk gdpr",
                "uk general data protection regulation",
                "data protection act 2018",
                "dpa 2018",
            ),
            category="data_protection",
        ),
        _standard(
            "ccpa",
            "California Consumer Privacy Act",
            (
                "california consumer privacy act",
                "cpra",
                "california privacy rights act",
                "ccpa/cpra",
            ),
            category="data_protection",
        ),
        _standard(
            "hipaa",
            "Health Insurance Portability and Accountability Act",
            (
                "health insurance portability and accountability act",
                "hipaa security rule",
                "hipaa privacy rule",
                "business associate agreement",
                "protected health information safeguards",
            ),
            category="data_protection",
        ),
        _standard(
            "pci_dss",
            "PCI DSS",
            (
                "pci dss",
                "pci-dss",
                "pci dss v4.0",
                "pci dss 4.0",
                "pci dss v3.2.1",
                "payment card industry data security standard",
            ),
        ),
        _standard(
            "nist_800_53",
            "NIST SP 800-53",
            (
                "nist 800-53",
                "nist sp 800-53",
                "nist special publication 800-53",
                "800-53",
                "nist 800 53 rev 5",
            ),
        ),
        _standard(
            "cyber_insurance",
            "Cyber insurance",
            (
                "cyber insurance",
                "cyber liability insurance",
                "cyber liability coverage",
                "cybersecurity insurance",
                "network security and privacy liability insurance",
            ),
            category="insurance",
        ),
    )
}

#: Deterministic seeding order for the ontology projection.
STANDARD_IDS: tuple[str, ...] = tuple(STANDARDS)

#: Alias -> standard id, longest alias first so "soc 2 type ii" wins over
#: "soc 2" when scanning free text.
_ALIAS_INDEX: tuple[tuple[str, str], ...] = tuple(
    sorted(
        ((alias, standard.standard_id) for standard in STANDARDS.values() for alias in standard.aliases),
        key=lambda item: (-len(item[0]), item[0]),
    )
)


def get_standard(standard_id: str) -> Optional[ComplianceStandard]:
    """Return the seeded standard for ``standard_id``, if any.

    Args:
        standard_id: A stable standard id.

    Returns:
        The :class:`ComplianceStandard`, or ``None`` when unknown.
    """
    return STANDARDS.get(standard_id)


def resolve_standard(value: Optional[str]) -> Optional[str]:
    """Resolve a whole value (a name or alias) to a standard id.

    Args:
        value: A standard name as written on a clause, e.g. ``"SOC 2"``.

    Returns:
        The stable standard id, or ``None`` when nothing matches exactly.
    """
    if not value:
        return None
    normalized = normalize_standard_text(value)
    if not normalized:
        return None
    for alias, standard_id in _ALIAS_INDEX:
        if alias == normalized:
            return standard_id
    return None


def find_standards(text: Optional[str]) -> list[str]:
    """Find every standard mentioned anywhere in ``text``.

    Scans normalized text for whole-token alias occurrences, longest alias
    first, so a trigger phrase containing "SOC 2" resolves the entity
    without consuming the rest of the question.

    Args:
        text: Free-form text (a question, a clause, a filename).

    Returns:
        Standard ids in seeded order, without duplicates.
    """
    if not text:
        return []
    normalized = f" {normalize_standard_text(text)} "
    if not normalized.strip():
        return []
    found: set[str] = set()
    for alias, standard_id in _ALIAS_INDEX:
        if standard_id in found:
            continue
        if f" {alias} " in normalized:
            found.add(standard_id)
    return [standard_id for standard_id in STANDARD_IDS if standard_id in found]
