"""EMAIL post-processor: spoken or written email → lowercase address matching the submit gate (FEAT-653)."""

from __future__ import annotations

import logging

from ...services.validators import EMAIL_PATTERN
from ..narration.lexicon import SpokenLexicon
from .base import NormalizeContext, NormalizeResult
from .numbers import parse_numbers, tokenize

logger = logging.getLogger(__name__)

_MAX_PHRASE_WORDS = 3


def _is_number_word(token: str, spoken: SpokenLexicon) -> bool:
    return token in spoken.units or token in spoken.tens or token in spoken.scales


def _build_candidate(tokens: list[str], spoken: SpokenLexicon) -> str:
    """Replace symbol phrases, turn number words into digits, concatenate everything else."""
    out: list[str] = []
    i = 0
    n = len(tokens)
    while i < n:
        matched = False
        for size in range(min(_MAX_PHRASE_WORDS, n - i), 0, -1):
            phrase = " ".join(tokens[i : i + size])
            symbol = spoken.email_symbols.get(phrase)
            if symbol is not None:
                out.append(symbol)
                i += size
                matched = True
                break
        if matched:
            continue
        if _is_number_word(tokens[i], spoken):
            j = i
            while j < n and _is_number_word(tokens[j], spoken) and tokens[j] not in spoken.email_symbols:
                j += 1
            out.extend(str(num) for num in parse_numbers(tokens[i:j], spoken))
            i = j
            continue
        out.append(tokens[i])
        i += 1
    return "".join(out).strip(".")


def normalize_email(text: str, ctx: NormalizeContext) -> NormalizeResult:
    """Map email_symbols, join spelled letters, number words → digits, drop spaces, lowercase; accepted iff
    EMAIL_PATTERN matches, else rejected (invalid_email) with the candidate."""
    try:
        tokens = tokenize(text)
        candidate = _build_candidate(tokens, ctx.lexicon.spoken).replace(" ", "").lower()
    except Exception as exc:  # noqa: BLE001 — normalizers never raise
        logger.debug("normalize_email failed: %s", type(exc).__name__)
        return NormalizeResult.rejected("no_parse")
    if candidate.count("@") == 1 and EMAIL_PATTERN.match(candidate):
        return NormalizeResult.accepted(candidate)
    return NormalizeResult.rejected("invalid_email", value=candidate or None)
