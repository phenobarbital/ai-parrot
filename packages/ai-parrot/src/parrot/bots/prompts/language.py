"""Bounded language resolution for the bot-level output-language directive (FEAT-638).

An operator-supplied language value ends up interpolated into the system prompt,
so it is normalized against an allowlist here and NEVER passed through raw.
Adding a language means adding an entry to SUPPORTED_LANGUAGES plus its rows in
GROUNDING_SENTINELS (domain_layers.py) and JIRA_MESSAGES (jira_messages.py) —
see docs/prompts/output-language.md.
"""
from __future__ import annotations

import logging
import re
from typing import Final, Optional

logger = logging.getLogger(__name__)

SUPPORTED_LANGUAGES: Final[dict[str, str]] = {"en": "English", "es": "Spanish"}
"""ISO 639-1 code -> English display name used in the prompt directive."""

FALLBACK_LANGUAGE: Final[str] = "en"
"""Language used for Python-authored text when none is configured."""

_SUBTAG: Final[re.Pattern[str]] = re.compile(r"[a-z]{2,3}")
_SEPARATORS: Final[re.Pattern[str]] = re.compile(r"[-_]")


def normalize_language(raw: Optional[str]) -> Optional[str]:
    """Normalize a raw language value to a supported ISO 639-1 base subtag.

    Strips whitespace, lowercases, and keeps the base subtag before the first
    ``-`` or ``_`` separator, so ``"es-MX"`` and ``"ES_mx"`` both yield ``"es"``.

    Args:
        raw: The operator-supplied value (constructor kwarg, DB column, UI field).

    Returns:
        A key of :data:`SUPPORTED_LANGUAGES`, or ``None`` when ``raw`` is ``None``,
        not a string, empty, malformed, or unsupported. Never returns
        caller-controlled text.
    """
    if raw is None:
        return None
    if not isinstance(raw, str):
        logger.warning("Unsupported language type %s; treating as unset", type(raw).__name__)
        return None

    language = _SEPARATORS.split(raw.strip().lower(), maxsplit=1)[0]
    if _SUBTAG.fullmatch(language) and language in SUPPORTED_LANGUAGES:
        return language

    logger.warning("Unsupported language %s; treating as unset", repr(raw)[:40])
    return None


def resolve_language_name(code: Optional[str]) -> Optional[str]:
    """Map a normalized code to its English display name for the prompt.

    Args:
        code: A value previously returned by :func:`normalize_language`.

    Returns:
        e.g. ``"Spanish"`` for ``"es"``; ``None`` when ``code`` is ``None`` or unknown.
    """
    if code is None:
        return None
    return SUPPORTED_LANGUAGES.get(code)
