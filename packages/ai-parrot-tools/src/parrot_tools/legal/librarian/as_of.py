"""Regex-first ``as_of`` extraction (FEAT-449 §3 M5, R9).

Explicit dates in a query are resolved deterministically via regex, tried
in order (ISO, numeric ES day-first, long-form ES). A structured LLM
micro-call is used ONLY as a fallback when the regexes are ambiguous
(zero or more than one distinct date found) — at most one call per
``extract_as_of`` invocation.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

from pydantic import BaseModel

_ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_NUMERIC_ES_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_MONTHS_ES = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}
_LONG_ES_RE = re.compile(
    r"\b(\d{1,2})\s+de\s+(" + "|".join(_MONTHS_ES) + r")\s+de\s+(\d{4})\b",
    re.IGNORECASE,
)


class AsOfExtraction(BaseModel):
    """Structured output shape for the LLM fallback micro-call.

    Args:
        as_of: The extracted date, or ``None`` when the model could not
            determine one (the caller then defaults to ``date.today()``).
    """

    as_of: date | None


def regex_dates(query: str) -> list[date]:
    """Extract every explicit, valid calendar date found in ``query``.

    Tries all three regex forms (ISO, numeric ES day-first, long-form
    ES), in that order, over the query. Invalid calendar dates (e.g.
    ``31/02``) are discarded as non-matches, not errors.

    Args:
        query: The user's query text.

    Returns:
        Every valid date found, in the order the regexes matched
        (duplicates included — callers that need distinctness should
        dedupe).
    """
    dates: list[date] = []

    for m in _ISO_RE.finditer(query):
        year, month, day = (int(g) for g in m.groups())
        try:
            dates.append(date(year, month, day))
        except ValueError:
            continue

    for m in _NUMERIC_ES_RE.finditer(query):
        day, month, year = (int(g) for g in m.groups())
        try:
            dates.append(date(year, month, day))
        except ValueError:
            continue

    for m in _LONG_ES_RE.finditer(query):
        day_str, month_name, year_str = m.groups()
        month = _MONTHS_ES[month_name.lower()]
        try:
            dates.append(date(int(year_str), month, int(day_str)))
        except ValueError:
            continue

    return dates


def _unwrap_as_of(result: Any) -> date | None:
    """Normalise an ``llm_ask`` result into an ``as_of`` date or ``None``.

    Accepts either an ``AsOfExtraction``-shaped object directly (tests
    inject this) or an ``AIMessage``-like object exposing
    ``.structured_output`` (the real ``AbstractBot.ask`` return shape —
    TASK-2497).

    Args:
        result: Whatever ``llm_ask`` returned.

    Returns:
        The extracted ``as_of`` date, or ``None``.
    """
    structured = getattr(result, "structured_output", result)
    return getattr(structured, "as_of", None)


async def extract_as_of(
    query: str,
    llm_ask: Callable[..., Awaitable[Any]],
) -> date | None:
    """Extract the ``as_of`` date a query refers to (R9).

    Regex-first: exactly one distinct date found across all three regex
    forms is returned immediately, no LLM call. Zero or more than one
    distinct date triggers exactly ONE structured micro-call to
    ``llm_ask``.

    Args:
        query: The user's query text.
        llm_ask: Injected async callable,
            ``await llm_ask(prompt, structured_output=AsOfExtraction)``
            — kept injected so tests never touch a real LLM client.

    Returns:
        The resolved date, or ``None`` when neither the regexes nor the
        LLM fallback could determine one (the caller then defaults to
        ``date.today()``).
    """
    distinct_dates = set(regex_dates(query))
    if len(distinct_dates) == 1:
        return next(iter(distinct_dates))

    prompt = "Extract the single date (as_of) that the following legal query " f"refers to, if any. Query: {query!r}"
    result = await llm_ask(prompt, structured_output=AsOfExtraction)
    return _unwrap_as_of(result)
