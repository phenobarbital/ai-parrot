"""Cached, never-raising optional tree-sitter grammar loader.

Every non-Python :class:`~parrot.knowledge.wiki.languages.base.LanguageScanner`
plugin uses tree-sitter for accurate outlines when the optional
``ai-parrot[wiki-languages]`` extra is installed, and degrades to a
stdlib-only regex heuristic otherwise. This module is the single seam
that hides the optional dependency: :func:`get_parser` returns ``None``
whenever the grammar or the ``tree-sitter`` package itself is missing —
callers never need to catch an import error themselves.
"""

from __future__ import annotations

import importlib
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from tree_sitter import Parser

logger = logging.getLogger(__name__)

#: Process-level cache: language name -> Parser instance, or ``None`` when
#: that language's grammar could not be loaded (cached so we never retry).
_PARSER_CACHE: dict[str, Parser | None] = {}

#: Maps a scanner-facing language name to the module that exposes its
#: compiled grammar via ``<module>.language()`` (the ``tree_sitter_python``
#: convention already used by graphindex).
_GRAMMAR_MODULES: dict[str, str] = {
    "php": "tree_sitter_php",
    "javascript": "tree_sitter_javascript",
    "typescript": "tree_sitter_typescript",
    "rust": "tree_sitter_rust",
}


def get_parser(language: str) -> Parser | None:
    """Return a cached tree-sitter ``Parser`` for ``language``, or ``None``.

    Never raises: missing ``tree-sitter``, a missing grammar wheel, or any
    other load failure all degrade to ``None`` so callers can fall back to
    a heuristic extractor unconditionally.

    Args:
        language: Scanner-facing language name (e.g. ``"php"``,
            ``"rust"``). Unknown names also return ``None``.

    Returns:
        A configured ``tree_sitter.Parser``, or ``None`` when unavailable.
    """
    if language in _PARSER_CACHE:
        return _PARSER_CACHE[language]

    parser = _build_parser(language)
    _PARSER_CACHE[language] = parser
    return parser


def _build_parser(language: str) -> Parser | None:
    """Construct a tree-sitter ``Parser`` for ``language``, or ``None``."""
    module_name = _GRAMMAR_MODULES.get(language)
    if module_name is None:
        return None
    try:
        from tree_sitter import Language, Parser

        grammar_module = importlib.import_module(module_name)
        ts_language = Language(grammar_module.language())
        return Parser(ts_language)
    except Exception as exc:  # noqa: BLE001 - optional dependency, never raise
        logger.debug(
            "tree-sitter grammar for %s unavailable, falling back to "
            "heuristic extraction: %s", language, exc,
        )
        return None
