"""Deterministic narration (templates + lexicon) for audio forms (FEAT-649)."""

from .engine import NARRATION_KEYS, Narrator, render_author_prompt
from .lexicon import (
    TEMPLATES_DIR,
    Lexicon,
    load_lexicon,
    load_locale_document,
    locale_chain,
    locale_document_path,
    normalize,
)

__all__ = [
    "NARRATION_KEYS",
    "Narrator",
    "TEMPLATES_DIR",
    "Lexicon",
    "load_lexicon",
    "load_locale_document",
    "locale_chain",
    "locale_document_path",
    "normalize",
    "render_author_prompt",
]
