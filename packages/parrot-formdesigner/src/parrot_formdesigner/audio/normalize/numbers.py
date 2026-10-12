"""Spoken/written number parsing shared by every typed post-processor (FEAT-653)."""

from __future__ import annotations

import logging
import re
import unicodedata

from ..narration.lexicon import SpokenLexicon
from .base import NormalizeContext, NormalizeResult

logger = logging.getLogger(__name__)

_KEEP_RE = re.compile(r"[^\w\s@+./:,\-]", flags=re.UNICODE)
_SPACE_RE = re.compile(r"\s+")
_HYPHEN_WORDS_RE = re.compile(r"^[^\W\d_]+(-[^\W\d_]+)+$", flags=re.UNICODE)
_INT_RE = re.compile(r"^\d+$")
_DIGITS_RE = re.compile(r"^\d+$")


def tokenize(text: str) -> list[str]:
    """Casefold + accent fold, keep digits and ``@ + . / : , -``, split on whitespace.

    Trailing sentence punctuation (``.,:;``) is stripped from every token, so ``com.`` becomes
    ``com`` and ``25,`` becomes ``25`` while ``3.5`` and ``0,4,12`` are kept intact.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    no_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    cleaned = _KEEP_RE.sub(" ", no_marks.casefold())
    tokens = (t.rstrip(".,:;").lstrip(":;") for t in _SPACE_RE.split(cleaned))
    return [t for t in tokens if t]


def _grouping_re(sep: str) -> tuple[re.Pattern[str], str]:
    grp = "," if sep == "." else "."
    pattern = re.compile(rf"^\d{{1,3}}(?:{re.escape(grp)}\d{{3}})+(?:{re.escape(sep)}\d+)?$")
    return pattern, grp


def _parse_written(token: str, sep: str) -> list[int | float] | None:
    """Parse one written numeric token into one or several numbers; None when not numeric."""
    negative = token.startswith("-")
    body = token.lstrip("+-")
    if not body or not body[0].isdigit():
        return None
    sign = -1 if negative else 1
    if _INT_RE.match(body):
        return [sign * int(body)]
    grouped, grp = _grouping_re(sep)
    if grouped.match(body):
        return [sign * _to_number(body.replace(grp, "").replace(sep, "."))]
    if re.match(rf"^\d+{re.escape(sep)}\d+$", body):
        return [sign * _to_number(body.replace(sep, "."))]
    if re.match(r"^\d+\.\d+$", body):  # tolerate the other separator for a single fraction
        return [sign * _to_number(body)]
    if re.match(r"^\d+(?:[.,]\d+)+$", body):  # "0,4,12,523,573": a list of separate numbers
        return [sign * int(p) if i == 0 else int(p) for i, p in enumerate(re.split(r"[.,]", body))]
    return None


def _to_number(text: str) -> int | float:
    value = float(text)
    return int(value) if value.is_integer() and "." not in text else value


def _expand(tokens: list[str]) -> list[str]:
    """Split hyphenated spoken words (``twenty-five``) into separate tokens."""
    out: list[str] = []
    for tok in tokens:
        if _HYPHEN_WORDS_RE.match(tok):
            out.extend(tok.split("-"))
        else:
            out.append(tok)
    return out


def _fraction(tokens: list[str], i: int, spoken: SpokenLexicon) -> tuple[str, int]:
    """Read the digits after a decimal word; returns (digit string, next index)."""
    digits = ""
    j = i
    if j < len(tokens) and _DIGITS_RE.match(tokens[j]):
        return tokens[j], j + 1
    while j < len(tokens) and tokens[j] in spoken.units and spoken.units[tokens[j]] < 10:
        digits += str(spoken.units[tokens[j]])
        j += 1
    return digits, j


def _read_words(tokens: list[str], i: int, spoken: SpokenLexicon) -> tuple[int | None, int]:
    """Read one spoken-word integer starting at ``i``; returns (value or None, next index)."""
    total = 0
    current = 0
    last: str | None = None
    end = i
    j = i
    while j < len(tokens):
        t = tokens[j]
        if t in spoken.number_joiners and last is not None:
            j += 1
            continue
        if t in spoken.units:
            v = spoken.units[t]
            ok = (
                last is None
                or (last == "t" and v < 10 and current % 10 == 0 and v > 0)
                or (last in ("h", "s") and v > 0 and current % 100 == 0)
            )
            if not ok:
                break
            current += v
            last = "u"
        elif t in spoken.tens:
            if not (last is None or (last in ("h", "s") and current % 100 == 0)):
                break
            current += spoken.tens[t]
            last = "t"
        elif t in spoken.scales:
            v = spoken.scales[t]
            if v >= 1000:
                total += (current or 1) * v
                current = 0
                last = "s"
            else:
                if v == 100 and 0 < current < 10:
                    current *= 100
                elif last in ("h",):
                    break
                else:
                    current += v
                last = "h"
        else:
            break
        j += 1
        end = j
    if end == i:
        return None, i
    return total + current, end


def parse_numbers(tokens: list[str], spoken: SpokenLexicon) -> list[int | float]:
    """Every number in the token stream, in order (words and written digits)."""
    toks = _expand(tokens)
    numbers: list[int | float] = []
    n = len(toks)
    i = 0
    while i < n:
        negative = False
        j = i
        if toks[j] in spoken.minus_words and j + 1 < n:
            negative = True
            j += 1
        values: list[int | float] | None = None
        nxt = j
        written = _parse_written(toks[j], spoken.decimal_separator)
        if written is not None:
            values, nxt = written, j + 1
        else:
            word, nxt = _read_words(toks, j, spoken)
            if word is not None:
                values = [word]
        if not values:
            i += 1
            continue
        if len(values) == 1:
            value = values[0]
            if nxt < n and toks[nxt] in spoken.decimal_words and isinstance(value, int):
                digits, after = _fraction(toks, nxt + 1, spoken)
                if digits:
                    value = float(f"{abs(value)}.{digits}") * (-1 if value < 0 else 1)
                    nxt = after
            if written is not None and nxt < n and toks[nxt] in spoken.scales and spoken.scales[toks[nxt]] >= 100:
                value = value * spoken.scales[toks[nxt]]
                nxt += 1
            values = [value]
        if negative:
            values[0] = -values[0]
        numbers.extend(values)
        i = nxt
    return numbers


def normalize_number(text: str, ctx: NormalizeContext, *, integer: bool) -> NormalizeResult:
    """Exactly one number → accepted int/float; 0 or >1 numbers → rejected (no_parse / multiple_values)."""
    try:
        numbers = parse_numbers(tokenize(text), ctx.lexicon.spoken)
    except Exception as exc:  # noqa: BLE001 — normalizers never raise
        logger.debug("normalize_number failed: %s", type(exc).__name__)
        return NormalizeResult.rejected("no_parse")
    if not numbers:
        return NormalizeResult.rejected("no_parse")
    if len(numbers) > 1:
        return NormalizeResult.rejected("multiple_values")
    value = numbers[0]
    is_integral = float(value).is_integer()
    if integer and not is_integral:
        return NormalizeResult.rejected("non_integral", value=value)
    return NormalizeResult.accepted(int(value) if is_integral else float(value))
