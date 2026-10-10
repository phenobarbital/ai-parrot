"""Deterministic narration (templates + lexicon) for audio forms (FEAT-649)."""

from .lexicon import TEMPLATES_DIR, Lexicon, load_lexicon, load_locale_document, locale_chain, normalize

__all__ = ["TEMPLATES_DIR", "Lexicon", "load_lexicon", "load_locale_document", "locale_chain", "normalize"]
