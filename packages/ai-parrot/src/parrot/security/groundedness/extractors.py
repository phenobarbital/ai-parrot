"""Deterministic hard-data atom extraction for groundedness scoring.

Implements FEAT-398 spec Module 1: extract verifiable hard-data atoms
(money, percent, number, date, identifier) from free text, with span
de-overlap so a money hit (``$1,243,500``) is never double-counted as a
bare number. Stdlib only (``re``, ``datetime``, ``unicodedata``).
"""
from __future__ import annotations

import logging
import re

from .models import Atom, AtomKind
from .normalize import (
    nfkc_normalize,
    normalize_date,
    normalize_identifier,
    normalize_number,
)

logger = logging.getLogger(__name__)

#: Default noise floor for bare integers/decimals (spec §2 GroundednessPolicy).
DEFAULT_MIN_NUMBER_DIGITS = 4

# ---------------------------------------------------------------------------
# Extraction patterns (applied to the NFKC-normalized text)
# ---------------------------------------------------------------------------

_MONEY_RE = re.compile(r"-?[$€£¥₹]\d[\d,]*(?:\.\d+)?[kKmMbB]?")
_PERCENT_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?%")

_MONTH_NAMES_PATTERN = (
    r"(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|"
    r"Oct|Nov|Dec)"
)
_DATE_ISO_RE = re.compile(r"\d{4}-\d{1,2}-\d{1,2}")
_DATE_SLASH_RE = re.compile(r"\d{1,2}/\d{1,2}/\d{4}")
_DATE_MONTHNAME_RE = re.compile(
    rf"{_MONTH_NAMES_PATTERN}\.?\s+\d{{1,2}},?\s+\d{{4}}", re.IGNORECASE,
)
# Claim priority within Date: ISO, then slash, then month-name.
_DATE_PATTERNS: tuple[re.Pattern, ...] = (
    _DATE_ISO_RE, _DATE_SLASH_RE, _DATE_MONTHNAME_RE,
)

_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_URL_RE = re.compile(r"\bhttps?://[^\s<>\"']+")
_TICKET_CODE_RE = re.compile(r"\b[A-Z]{2,}-\d{2,}\b")
# Claim priority within Identifier: email, then URL, then ticket/SKU code.
_IDENTIFIER_PATTERNS: tuple[re.Pattern, ...] = (
    _EMAIL_RE, _URL_RE, _TICKET_CODE_RE,
)

#: Bare numbers also accept a magnitude suffix (like money) so an
#: unprefixed abbreviated figure ("2.5M downloads") is not silently
#: dropped; such literals are exempt from the min_number_digits floor
#: below (see extract_atoms) since they are inherently non-noise.
_NUMBER_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?[kKmMbB]?")
_DIGIT_ONLY_RE = re.compile(r"\d")
_MAGNITUDE_SUFFIX_CHARS = ("k", "m", "b")


def _spans_overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    """Return True if the two half-open character spans overlap."""
    return a[0] < b[1] and b[0] < a[1]


def _overlaps_any(span: tuple[int, int], claimed: list[tuple[int, int]]) -> bool:
    """Return True if *span* overlaps any span already claimed."""
    return any(_spans_overlap(span, other) for other in claimed)


def extract_atoms(
    text: str,
    min_number_digits: int = DEFAULT_MIN_NUMBER_DIGITS,
) -> list[Atom]:
    """Extract verifiable hard-data atoms from *text*.

    Runs the five stdlib atom extractors in claim-priority order —
    money, percent, date, identifier, then number — so a value like
    ``$1,243,500`` yields exactly one ``money`` atom, never a money atom
    plus a bare-number atom. An NFKC Unicode pre-pass is applied first so
    fullwidth digits/currency signs are recognized. Money/percent/number
    literals accept an optional leading ``-`` sign so a sign flip
    ("+15.3%" vs "-15.3%") is preserved rather than silently discarded.

    Args:
        text: The source text to extract atoms from (an agent answer or
            a tool-result value rendered to text).
        min_number_digits: Bare integers/decimals with fewer digit
            characters than this are skipped as noise. Default 4.

    Returns:
        The extracted atoms, ordered by their start offset in the
        NFKC-normalized text.
    """
    normalized_text = nfkc_normalize(text)
    atoms: list[Atom] = []
    claimed_spans: list[tuple[int, int]] = []

    # 1. Money — highest claim priority.
    for match in _MONEY_RE.finditer(normalized_text):
        raw = match.group(0)
        try:
            normalized: str | float = normalize_number(raw)
        except ValueError:
            logger.debug("Skipping unparsable money literal: %r", raw)
            continue
        span = (match.start(), match.end())
        atoms.append(
            Atom(kind=AtomKind.MONEY, raw=raw, normalized=normalized,
                 start=span[0], end=span[1])
        )
        claimed_spans.append(span)

    # 2. Percent.
    for match in _PERCENT_RE.finditer(normalized_text):
        span = (match.start(), match.end())
        if _overlaps_any(span, claimed_spans):
            continue
        raw = match.group(0)
        try:
            normalized = normalize_number(raw)
        except ValueError:
            logger.debug("Skipping unparsable percent literal: %r", raw)
            continue
        atoms.append(
            Atom(kind=AtomKind.PERCENT, raw=raw, normalized=normalized,
                 start=span[0], end=span[1])
        )
        claimed_spans.append(span)

    # 3. Date — ISO, then slash, then month-name forms.
    for pattern in _DATE_PATTERNS:
        for match in pattern.finditer(normalized_text):
            span = (match.start(), match.end())
            if _overlaps_any(span, claimed_spans):
                continue
            raw = match.group(0)
            try:
                normalized = normalize_date(raw)
            except ValueError:
                logger.debug("Skipping unparsable date literal: %r", raw)
                continue
            atoms.append(
                Atom(kind=AtomKind.DATE, raw=raw, normalized=normalized,
                     start=span[0], end=span[1])
            )
            claimed_spans.append(span)

    # 4. Identifier — email, then URL, then ticket/SKU-style code.
    for pattern in _IDENTIFIER_PATTERNS:
        for match in pattern.finditer(normalized_text):
            span = (match.start(), match.end())
            if _overlaps_any(span, claimed_spans):
                continue
            raw = match.group(0)
            atoms.append(
                Atom(kind=AtomKind.IDENTIFIER, raw=raw,
                     normalized=normalize_identifier(raw),
                     start=span[0], end=span[1])
            )
            claimed_spans.append(span)

    # 5. Number — bare numerics not already claimed, above the noise floor.
    #    Magnitude-suffixed literals ("2.5M", "3.2B") are exempt from the
    #    floor: they are inherently non-noise regardless of raw digit
    #    count, matching money's identical suffix handling.
    for match in _NUMBER_RE.finditer(normalized_text):
        span = (match.start(), match.end())
        if _overlaps_any(span, claimed_spans):
            continue
        raw = match.group(0)
        has_magnitude_suffix = raw[-1].lower() in _MAGNITUDE_SUFFIX_CHARS
        digit_count = len(_DIGIT_ONLY_RE.findall(raw))
        if not has_magnitude_suffix and digit_count < min_number_digits:
            continue
        try:
            normalized = normalize_number(raw)
        except ValueError:
            logger.debug("Skipping unparsable number literal: %r", raw)
            continue
        atoms.append(
            Atom(kind=AtomKind.NUMBER, raw=raw, normalized=normalized,
                 start=span[0], end=span[1])
        )
        claimed_spans.append(span)

    atoms.sort(key=lambda atom: atom.start)
    return atoms
