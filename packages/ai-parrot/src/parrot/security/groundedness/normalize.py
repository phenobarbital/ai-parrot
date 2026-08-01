"""Normalization helpers for groundedness atom extraction (FEAT-398).

All functions are pure, synchronous, and stdlib-only (``re``,
``datetime``, ``unicodedata``). They fold surface-form variation
(magnitude suffixes, thousand/decimal separators, multi-format dates,
identifier casing, fullwidth Unicode forms) into canonical comparison
keys so the same real-world fact compares equal regardless of how it was
written in the answer vs. the evidence.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date

#: Magnitude suffixes recognized on numeric/money literals (case-insensitive).
_MAGNITUDE_SUFFIXES = {
    "k": 1_000.0,
    "m": 1_000_000.0,
    "b": 1_000_000_000.0,
}

#: Currency symbols and the percent sign stripped before numeric parsing.
_CURRENCY_AND_PERCENT_RE = re.compile(r"[%$€£¥₹]")

_DIGIT_RE = re.compile(r"\d")

_MONTH_NAMES = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5,
    "june": 6, "july": 7, "august": 8, "september": 9, "october": 10,
    "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_SLASH_DATE_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_MONTH_NAME_DATE_RE = re.compile(r"^([A-Za-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})$")


def nfkc_normalize(text: str) -> str:
    """Apply an NFKC Unicode normalization pre-pass to *text*.

    Folds fullwidth/compatibility forms (e.g. fullwidth digits, fullwidth
    currency signs) into their canonical ASCII-compatible equivalents so
    downstream regex extractors see a consistent character set.

    Args:
        text: Raw input text.

    Returns:
        The NFKC-normalized text.
    """
    return unicodedata.normalize("NFKC", text)


def normalize_number(raw: str) -> float:
    """Normalize a numeric/money/percent literal to a canonical float.

    Strips currency symbols, percent signs, and thousand separators, then
    resolves a trailing magnitude suffix (``k``/``M``/``B``,
    case-insensitive).

    Args:
        raw: The raw numeric literal as it appeared in text, e.g.
            ``"$1.24M"``, ``"1,234,500"``, or ``"15.3%"``.

    Returns:
        The canonical float value, e.g. ``"$1.24M"`` -> ``1_240_000.0``.

    Raises:
        ValueError: If *raw* does not contain a parseable number.
    """
    text = nfkc_normalize(raw).strip()
    text = text.replace(",", "")
    text = _CURRENCY_AND_PERCENT_RE.sub("", text)
    text = text.strip()

    multiplier = 1.0
    if text and text[-1].lower() in _MAGNITUDE_SUFFIXES:
        multiplier = _MAGNITUDE_SUFFIXES[text[-1].lower()]
        text = text[:-1].strip()

    if not text:
        raise ValueError(f"Cannot normalize empty numeric literal: {raw!r}")

    return float(text) * multiplier


def count_significant_digits(raw: str) -> int:
    """Count the significant digits in a numeric literal.

    Backs the precision-aware tolerance rule (spec §2): a number with a
    magnitude suffix (``1.24M``) is a *rounded* statement with few
    significant digits, while a fully written number (``1,234,500``) is
    an *exact* statement whose digit count equals its length. Thousand
    separators, currency symbols, and the percent sign do not count; the
    magnitude suffix character itself does not count.

    Args:
        raw: The raw numeric literal, e.g. ``"$1.24M"`` or
            ``"1,234,500"``.

    Returns:
        The number of significant digit characters.
    """
    text = nfkc_normalize(raw).strip()
    text = text.replace(",", "")
    text = _CURRENCY_AND_PERCENT_RE.sub("", text)
    text = text.strip()
    if text and text[-1].lower() in _MAGNITUDE_SUFFIXES:
        text = text[:-1]
    return len(_DIGIT_RE.findall(text))


def normalize_date(raw: str) -> str:
    """Normalize a date literal in common en-US formats to ISO-8601.

    Supported input formats: ``MM/DD/YYYY``, ``Month DD, YYYY`` (full or
    abbreviated month names), and ``YYYY-MM-DD`` (validated pass-through).

    Args:
        raw: The raw date literal as it appeared in text.

    Returns:
        The ISO-8601 date string (``YYYY-MM-DD``).

    Raises:
        ValueError: If *raw* does not match any supported date format, or
            names an unrecognized month.
    """
    text = nfkc_normalize(raw).strip()

    match = _ISO_DATE_RE.match(text)
    if match:
        year, month, day = (int(group) for group in match.groups())
        return date(year, month, day).isoformat()

    match = _SLASH_DATE_RE.match(text)
    if match:
        month, day, year = (int(group) for group in match.groups())
        return date(year, month, day).isoformat()

    match = _MONTH_NAME_DATE_RE.match(text)
    if match:
        month_name, day, year = match.groups()
        month = _MONTH_NAMES.get(month_name.lower())
        if month is None:
            raise ValueError(f"Unrecognized month name: {month_name!r}")
        return date(int(year), month, int(day)).isoformat()

    raise ValueError(f"Cannot normalize date literal: {raw!r}")


def normalize_identifier(raw: str) -> str:
    """Normalize an identifier (email, URL, ticket/SKU code) for comparison.

    Applies the NFKC pre-pass then case-folds, so identifiers compare
    case-insensitively across answer and evidence.

    Args:
        raw: The raw identifier literal.

    Returns:
        The NFKC-normalized, case-folded identifier.
    """
    return nfkc_normalize(raw).casefold()
