"""Narrative figure guard — numeric derivability check (FEAT-420 Module 4).

Mechanical fence around the probabilistic narrative layer (spec criterion
G-H): after an LLM writes prose over the deterministic ``narrative_facts``
(see :mod:`parrot.outputs.a2ui.recipes.library`), every numeric literal in
that prose is checked for derivability from the facts. Any single figure
that is NOT derivable discards the **entire** narrative, not just the
offending sentence — a partially-scrubbed paragraph is a new artifact nobody
reviewed, and it collapses into the same degraded state as "no narrator" (one
fallback path to reason about and test).

**Known limitation (accepted by the spec, §7 Known Risks)**: this guard
catches invented *figures*, not a fluent mis-characterisation of a correct
figure — e.g. it cannot tell "EBITDA improved by $42.0K" from "EBITDA
worsened by $42.0K" when both prose figures are numerically derivable. This
module validates ONLY that every number in the prose traces back to a real
fact; it never judges the surrounding sentence.

Pure, dependency-free (stdlib only) so it can be used from a mixin without
dragging in a dataframe library or any LLM client.
"""

from __future__ import annotations

import logging
import re
from typing import Any

__all__ = ["extract_figures", "figures_are_derivable"]

logger = logging.getLogger(__name__)

#: Relative tolerance for matching a displayed figure against a fact.
#: Accounts for TWO independent roundings: the facts' own 2dp rounding
#: (`library.py`'s money convention) AND the prose's display rounding
#: (`$1.23M` from a raw `1_234_567.89` loses up to ~5_000 of precision at
#: the millions scale, a ~0.4% relative error). 1% comfortably absorbs both
#: without being loose enough to wave through an unrelated number.
_RELATIVE_TOLERANCE = 0.01

#: The reference artifact's negative-sign glyph (`fmt_money`/`fmt_pct` use
#: U+2212 MINUS SIGN for every negative value, never ASCII hyphen-minus).
_MINUS = "−"

#: Matches $1.23M / $45.6K / $1,234.5K / +12.3% / -12.3% / bare integers,
#: with an optional leading '+', ASCII '-', or U+2212 MINUS SIGN.
_FIGURE_RE = re.compile(rf"[+\-{_MINUS}]?\$?\d[\d,]*(?:\.\d+)?\s*[MK%]?")


def extract_figures(prose: str) -> list[str]:
    """Return every numeric literal appearing in ``prose``, in order.

    Args:
        prose: The generated narrative text to scan.

    Returns:
        The raw matched substrings (e.g. ``"$1.23M"``, ``"+12.3%"``, ``"3"``),
        in the order they appear. Does not mutate ``prose``.
    """
    return [match.group(0) for match in _FIGURE_RE.finditer(prose)]


def _to_float(figure: str) -> float | None:
    """Normalise a displayed figure to a float (``"$1.23M"`` -> ``1_230_000.0``).

    Args:
        figure: A raw figure substring as returned by :func:`extract_figures`.

    Returns:
        The signed numeric value the figure represents, or ``None`` if it
        cannot be parsed (defensive — should not happen for anything
        :func:`extract_figures` produced).
    """
    text = figure.strip()
    if not text:
        return None

    sign = 1.0
    if text[0] in ("+", "-", _MINUS):
        if text[0] in ("-", _MINUS):
            sign = -1.0
        text = text[1:]

    text = text.strip()
    if text.endswith("%"):
        text = text[:-1]
        multiplier = 1.0
    elif text.endswith("M"):
        text = text[:-1]
        multiplier = 1_000_000.0
    elif text.endswith("K"):
        text = text[:-1]
        multiplier = 1_000.0
    else:
        multiplier = 1.0

    text = text.strip().replace("$", "").replace(",", "").strip()
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return sign * value * multiplier


def _numeric_leaves(value: Any) -> list[float]:
    """Recursively collect numeric leaves from ``value``, EXCLUDING bools.

    ``bool`` is a subclass of ``int`` in Python — checked FIRST so a flag
    like ``both_improving=True`` never makes the figure ``1`` derivable.

    Args:
        value: Any JSON-shaped value (dict/list/scalar).

    Returns:
        Every ``int``/``float`` leaf found, as floats.
    """
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        return [float(value)]
    if isinstance(value, dict):
        return [leaf for item in value.values() for leaf in _numeric_leaves(item)]
    if isinstance(value, list):
        return [leaf for item in value for leaf in _numeric_leaves(item)]
    return []


def _is_derivable(value: float, leaves: list[float]) -> bool:
    """Return whether ``value`` matches any of ``leaves`` within tolerance.

    Comparison is on the SIGNED value — a figure carrying the opposite sign
    of every matching-magnitude fact is never considered derivable, so a
    sign flip (e.g. prose claiming an improvement where the fact records a
    worsening of the same magnitude) is not silently waved through.
    """
    for leaf in leaves:
        if leaf == 0.0:
            if abs(value) <= _RELATIVE_TOLERANCE:
                return True
            continue
        if abs(value - leaf) / abs(leaf) <= _RELATIVE_TOLERANCE:
            return True
    return False


def figures_are_derivable(prose: str, facts: dict[str, Any]) -> tuple[bool, list[str]]:
    """Check every figure in ``prose`` against the numeric leaves of ``facts``.

    Args:
        prose: The generated narrative text to validate.
        facts: The deterministic facts (e.g. the ``narrative_facts``
            transformer's output) every figure must trace back to.

    Returns:
        ``(ok, offending)``. ``ok`` is ``False`` if ANY figure is not
        derivable; ``offending`` lists those figures (raw, as they appear in
        ``prose``). Callers MUST discard the WHOLE narrative when ``ok`` is
        ``False`` (spec criterion G-H) — this function never edits or
        mutates ``prose``/``facts``; it only reports.
    """
    leaves = _numeric_leaves(facts)
    offending: list[str] = []
    for raw_figure in extract_figures(prose):
        value = _to_float(raw_figure)
        if value is None or not _is_derivable(value, leaves):
            offending.append(raw_figure)

    if offending:
        logger.warning(
            "Narrative figure guard rejected %d non-derivable figure(s): %r",
            len(offending),
            offending,
        )
    return (not offending, offending)
