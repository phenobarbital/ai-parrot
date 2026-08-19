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
#: compiled grammar. The callable that module exposes is **not** uniform —
#: see :data:`_GRAMMAR_CALLABLES`.
_GRAMMAR_MODULES: dict[str, str] = {
    "php": "tree_sitter_php",
    "javascript": "tree_sitter_javascript",
    "typescript": "tree_sitter_typescript",
    "rust": "tree_sitter_rust",
    "perl": "tree_sitter_perl",
}

#: Grammar-callable names to try, in order, for each language.
#:
#: The wheels do not share one loading convention. **Single-grammar**
#: wheels expose a plain ``language()`` — ``tree_sitter_javascript``,
#: ``tree_sitter_rust``, and the ``tree_sitter_python`` precedent already
#: used by graphindex. **Multi-grammar** wheels expose one named variant
#: per grammar and have no ``language()`` at all: ``tree_sitter_typescript``
#: ships ``language_typescript()``/``language_tsx()`` and
#: ``tree_sitter_php`` ships ``language_php()``/``language_php_only()``
#: (verified against typescript 0.23.0/0.23.2 and php 0.24.1 — every
#: version satisfying the ``wiki-languages`` extra's ``>=0.23`` pin).
#:
#: ``language`` is always tried FIRST so the single-grammar wheels keep
#: their existing behaviour untouched.
_GRAMMAR_CALLABLES: dict[str, tuple[str, ...]] = {
    "php": ("language", "language_php"),
    "javascript": ("language",),
    "typescript": ("language", "language_typescript"),
    "rust": ("language",),
    "perl": ("language",),
}

#: Candidates tried for any language absent from :data:`_GRAMMAR_CALLABLES`.
_DEFAULT_GRAMMAR_CALLABLES: tuple[str, ...] = ("language",)


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
    """Construct a tree-sitter ``Parser`` for ``language``, or ``None``.

    Resolves the grammar callable across both wheel conventions by trying
    each name in :data:`_GRAMMAR_CALLABLES` in order — ``language()``
    first, then the wheel's named variant. A candidate that is absent or
    that fails to build is skipped rather than aborting the search, so one
    unusable callable never masks a working one.

    Args:
        language: Scanner-facing language name (e.g. ``"typescript"``).

    Returns:
        A configured ``tree_sitter.Parser``, or ``None`` when the
        ``tree-sitter`` package, the grammar wheel, or every candidate
        callable is unavailable.
    """
    module_name = _GRAMMAR_MODULES.get(language)
    if module_name is None:
        return None
    try:
        from tree_sitter import Language, Parser

        grammar_module = importlib.import_module(module_name)
        candidates = _GRAMMAR_CALLABLES.get(language, _DEFAULT_GRAMMAR_CALLABLES)
        for attr in candidates:
            factory = getattr(grammar_module, attr, None)
            if factory is None:
                continue
            try:
                ts_language = Language(factory())
            except Exception as exc:  # noqa: BLE001 - try the next candidate
                logger.debug(
                    "tree-sitter grammar callable %s.%s() for %s failed: %s",
                    module_name, attr, language, exc,
                )
                continue
            logger.debug(
                "tree-sitter grammar for %s loaded via %s.%s()",
                language, module_name, attr,
            )
            return Parser(ts_language)
        raise AttributeError(
            f"module {module_name!r} exposes no usable grammar callable "
            f"among {candidates!r}"
        )
    except Exception as exc:  # noqa: BLE001 - optional dependency, never raise
        logger.debug(
            "tree-sitter grammar for %s unavailable, falling back to "
            "heuristic extraction: %s", language, exc,
        )
        return None
