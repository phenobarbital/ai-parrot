"""Suffix registry for pluggable per-language wiki repo scanners.

Scanners are registered explicitly below (no entry-point discovery — see
the spec's rejected "external plugin packages" option). Each new
language plugin task adds one instantiation to :data:`_SCANNERS` and its
suffixes become part of :func:`scanned_suffixes`.
"""

from __future__ import annotations

from parrot.knowledge.wiki.languages.base import LanguageOutline, LanguageScanner

__all__ = [
    "LanguageOutline",
    "LanguageScanner",
    "all_scanners",
    "scanned_suffixes",
    "scanner_for",
]

#: Registered scanner instances, name -> scanner. Populated explicitly as
#: each language plugin task lands; empty until the first plugin (Python,
#: TASK-2011) is registered.
_SCANNERS: dict[str, LanguageScanner] = {}

#: suffix -> scanner name, derived from ``_SCANNERS`` for O(1) lookup.
_SUFFIX_INDEX: dict[str, str] = {
    suffix: scanner.name
    for scanner in _SCANNERS.values()
    for suffix in scanner.suffixes
}


def scanner_for(suffix: str) -> LanguageScanner | None:
    """Return the registered scanner claiming ``suffix``, if any.

    Args:
        suffix: A file suffix including the leading dot (e.g. ``".php"``).

    Returns:
        The matching :class:`LanguageScanner`, or ``None`` when no
        scanner is registered for it.
    """
    name = _SUFFIX_INDEX.get(suffix)
    return _SCANNERS.get(name) if name else None


def all_scanners() -> dict[str, LanguageScanner]:
    """Return the full registry, keyed by scanner name.

    Returns:
        A shallow copy of the name -> scanner mapping.
    """
    return dict(_SCANNERS)


def scanned_suffixes() -> frozenset[str]:
    """Return the union of every registered scanner's suffixes.

    Returns:
        A frozenset of all claimed file suffixes.
    """
    return frozenset(_SUFFIX_INDEX)
