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
_EXTENSION_WORDS = frozenset({"extension", "extensions", "ext", "extn", "x"})
_SEPARATOR_RE = re.compile(r"[,;]|\b(?:or|o|and|y|u)\b", flags=re.IGNORECASE)
_MIN_PHONE_DIGITS = 7
_MAX_PHONE_DIGITS = 15  # E.164: no real number is longer, so more digits means several numbers or a misread
_EXTENSION_GLUED_RE = re.compile(r"^(?:ext|extn|x)(\d+)$")


def _split_extension(tokens: list[str]) -> tuple[list[str], bool]:
    """Cut the utterance at an extension marker; returns ``(main number tokens, had an extension)``."""
    for i, tok in enumerate(tokens):
        if tok in _EXTENSION_WORDS or _EXTENSION_GLUED_RE.match(tok):
            return tokens[:i], True
    return tokens, False


def _digit_word(token: str, spoken: SpokenLexicon) -> bool:
    return 0 <= spoken.units.get(token, -1) <= 9 or token in spoken.digit_aliases


def _hundred_closes_chunk(run: list[str], k: int, spoken: SpokenLexicon) -> bool:
    """True when the hundred at ``k`` is a chunk of its own ('eight hundred | five five five').

    It composes with what follows ('two hundred twelve' = 212, 'seiscientos doce' = 612) unless the run ends there
    or digits are dictated one by one after it (two single digits in a row).
    """
    rest = run[k + 1 :]
    if not rest or rest[0] in spoken.scales:
        return True
    return len(rest) >= 2 and _digit_word(rest[0], spoken) and _digit_word(rest[1], spoken)


def _hundred_digits(run: list[str], spoken: SpokenLexicon) -> list[str]:
    """Digits of a number-word run; 'eight hundred five five five' is 8-0-0 5 5 5, not 805 5 5."""
    parts: list[str] = []
    start = 0
    for k, tok in enumerate(run):
        value = spoken.scales.get(tok, 0)
        if not 100 <= value <= 900 or value % 100 != 0 or not _hundred_closes_chunk(run, k, spoken):
            continue
        if value >= 200:  # 'ochocientos' is the chunk 8-0-0 on its own
            parts.extend(str(num) for num in parse_numbers(run[start:k], spoken))
            parts.append(str(value))
            start = k + 1
        elif k > start and spoken.units.get(run[k - 1], 0) in range(1, 10):
            parts.extend(str(num) for num in parse_numbers(run[start : k - 1], spoken))
            parts.append(str(spoken.units[run[k - 1]]) + "00")
            start = k + 1
    parts.extend(str(num) for num in parse_numbers(run[start:], spoken))
    return parts


def _is_number_word(token: str, spoken: SpokenLexicon) -> bool:
    return token in spoken.units or token in spoken.tens or token in spoken.scales


def _joins_tens_and_unit(tokens: list[str], j: int, spoken: SpokenLexicon) -> bool:
    """A joiner between a tens word and a unit word ('treinta y cuatro'), so the run must not break there."""
    return (
        tokens[j] in spoken.number_joiners
        and j > 0
        and j + 1 < len(tokens)
        and tokens[j - 1] in spoken.tens
        and 1 <= spoken.units.get(tokens[j + 1], 0) <= 9
    )


def _build(tokens: list[str], spoken: SpokenLexicon) -> tuple[str, str]:
    """Return ``(plus, digits)`` from the token stream (leading zeros preserved)."""
    plus = ""
    digits: list[str] = []
    repeat = 1
    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        if tok in spoken.plus_words or (tok.startswith("+") and not digits):
            if not digits:
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
            while j < n and tokens[j] not in spoken.digit_aliases:
                if _is_number_word(tokens[j], spoken):
                    j += 1
                elif _joins_tens_and_unit(tokens, j, spoken):  # es 'treinta y cuatro' is one chunk, 34
                    j += 2
                else:
                    break
            parts = _hundred_digits(tokens[i:j], spoken)
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


def _holds_several_numbers(text: str, spoken: SpokenLexicon) -> bool:
    """True when ``or`` / ``o`` / ``and`` / ``y`` / a comma separates two parts that are each a whole phone number.

    A pause inside one number ("555, 123, 4567") leaves parts too short to stand alone, so it is not flagged.
    """
    complete = 0
    for part in _SEPARATOR_RE.split(text):
        main, _ = _split_extension(tokenize(part))
        if len(_build(main, spoken)[1]) >= _MIN_PHONE_DIGITS:
            complete += 1
    return complete > 1


def normalize_phone(text: str, ctx: NormalizeContext) -> NormalizeResult:
    """Leading plus word/'+' kept; digit words, digit_aliases, repeat_words, compound tens ('fifty five'→'55');
    every separator (space , . - ( )) dropped; accepted iff PHONE_PATTERN matches, else rejected (too_short)."""
    try:
        tokens, has_extension = _split_extension(tokenize(text))
        plus, digits = _build(tokens, ctx.lexicon.spoken)
        if _holds_several_numbers(text, ctx.lexicon.spoken):  # two numbers are never one number
            return NormalizeResult.rejected("multiple_values")
    except Exception as exc:  # noqa: BLE001
        logger.debug("normalize_phone failed: %s", type(exc).__name__)
        return NormalizeResult.rejected("no_parse")
    if not digits:
        return NormalizeResult.rejected("no_parse")
    value = plus + digits
    if len(digits) > _MAX_PHONE_DIGITS:
        return NormalizeResult.rejected("too_long", value=value)
    if len(digits) >= _MIN_PHONE_DIGITS and PHONE_PATTERN.match(value):
        if has_extension:  # the extension is not part of the stored number: the user must see what is kept
            return NormalizeResult.confirm(value, "has_extension")
        return NormalizeResult.accepted(value)
    return NormalizeResult.rejected("too_short", value=value)
