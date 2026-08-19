"""Suffix registry for pluggable per-language wiki repo scanners.

Scanners are registered explicitly below (no entry-point discovery — see
the spec's rejected "external plugin packages" option). Each new
language plugin task adds one instantiation to :data:`_SCANNERS` and its
suffixes become part of :func:`scanned_suffixes`.
"""

from __future__ import annotations

from pathlib import Path

from parrot.knowledge.wiki.languages.base import LanguageOutline, LanguageScanner
from parrot.knowledge.wiki.languages.javascript import JavaScriptScanner
from parrot.knowledge.wiki.languages.perl import PerlScanner
from parrot.knowledge.wiki.languages.php import PhpScanner
from parrot.knowledge.wiki.languages.python import PythonScanner
from parrot.knowledge.wiki.languages.rust import RustScanner

__all__ = [
    "LanguageOutline",
    "LanguageScanner",
    "all_scanners",
    "get_scan_root",
    "scanned_suffixes",
    "scanner_for",
    "set_scan_root",
]

#: Registered scanner instances, name -> scanner. Populated explicitly as
#: each language plugin task lands.
_SCANNERS: dict[str, LanguageScanner] = {
    "python": PythonScanner(),
    "php": PhpScanner(),
    "javascript": JavaScriptScanner(),
    "rust": RustScanner(),
    "perl": PerlScanner(),
}

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


#: The repository root of the scan currently in progress, if any. Some
#: scanners (e.g. PHP's PSR-4 resolution) need to read an auxiliary file
#: (``composer.json``) from disk, but ``LanguageScanner.build_reference_index``
#: only receives relative-path strings — no root — by design (the ABC is
#: frozen; see TASK-2010). ``scan_repository()`` sets this once per scan so
#: such lookups resolve against the actual repo root instead of falling
#: back to the ambient process CWD (which is not guaranteed to match root,
#: e.g. ``wikitoolkit build --path /other/repo``).
_scan_root: Path | None = None


def set_scan_root(root: Path) -> None:
    """Record the repository root of the scan currently in progress.

    Args:
        root: Absolute repository root, as resolved by ``scan_repository()``.
    """
    global _scan_root
    _scan_root = root


def get_scan_root() -> Path | None:
    """Return the repository root set by :func:`set_scan_root`, if any.

    Returns:
        The absolute repository root, or ``None`` if no scan has set one
        yet (e.g. a scanner method called directly in a unit test).
    """
    return _scan_root
