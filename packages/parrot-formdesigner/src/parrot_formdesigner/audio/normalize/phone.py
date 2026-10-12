"""PHONE post-processor: spoken or written phone → '+'? digits, valid for the submit gate (FEAT-653)."""

from __future__ import annotations

import logging
import re

from ...services.validators import PHONE_PATTERN
from ..narration.lexicon import SpokenLexicon
from .base import NormalizeContext, NormalizeResult
from .numbers import parse_numbers, tokenize

logger = logging.getLogger(__name__)

_NON_DIGIT_RE = re.compile(r"\D")


def _is_number_word(token: str, spoken: SpokenLexicon) -> bool:
    return token in spoken.units or token in spoken.tens or token in spoken.scales


def _build(tokens: list[str], spoken: SpokenLexicon) -> tuple[str, str]:
    """Return ``(plus, digits)`` from the token stream (leading zeros preserved)."""
    plus = ""
    digits: list[str] = []
    repeat = 1
    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        if tok in spoken.plus_words or (tok.startswith("+") and i == 0):
            if i == 0 and not digits:
                plus = "+"
            if tok.startswith("+") and len(tok) > 1:
                tok = tok[1:]
            else:
                i += 1
                continue
        if tok in spoken.repeat_words:
            repeat = spoken.repeat_words[tok]
            i += 1
            continue
        if tok in spoken.digit_aliases:
            digits.append(spoken.digit_aliases[tok] * repeat)
            repeat = 1
            i += 1
            continue
        if _is_number_word(tok, spoken):
            j = i
            while j < n and _is_number_word(tokens[j], spoken) and tokens[j] not in spoken.digit_aliases:
                j += 1
            parts = [str(num) for num in parse_numbers(tokens[i:j], spoken)]
            if parts and repeat > 1:
                parts[0] = parts[0][0] * repeat + parts[0][1:] if len(parts[0]) > 1 else parts[0] * repeat
            repeat = 1
            digits.extend(parts)
            i = j
            continue
        if any(ch.isdigit() for ch in tok):
            chunk = _NON_DIGIT_RE.sub("", tok)
            if chunk:
                digits.append(chunk[0] * repeat + chunk[1:] if repeat > 1 else chunk)
            repeat = 1
        i += 1
    return plus, "".join(digits)


def normalize_phone(text: str, ctx: NormalizeContext) -> NormalizeResult:
    """Leading plus word/'+' kept; digit words, digit_aliases, repeat_words, compound tens ('fifty five'→'55');
    every separator (space , . - ( )) dropped; accepted iff PHONE_PATTERN matches, else rejected (too_short)."""
    try:
        plus, digits = _build(tokenize(text), ctx.lexicon.spoken)
    except Exception as exc:  # noqa: BLE001
        logger.debug("normalize_phone failed: %s", type(exc).__name__)
        return NormalizeResult.rejected("no_parse")
    if not digits:
        return NormalizeResult.rejected("no_parse")
    value = plus + digits
    if len(digits) >= 7 and PHONE_PATTERN.match(value):
        return NormalizeResult.accepted(value)
    return NormalizeResult.rejected("too_short", value=value)
