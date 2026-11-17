"""Grade selection after trusted evidence and attribution admission."""

from __future__ import annotations

import unicodedata
from typing import Literal

from .models import Grade, ReviewSignal

Attribution = Literal["cited", "overlap"]


def _normalize_signature(value: str | None) -> str | None:
    """Normalize an error signature exactly as ``ReviewSignal`` does.

    Args:
        value: Raw signature recorded on the memory, or ``None``.

    Returns:
        The NFKC-folded, lowercased, whitespace-collapsed signature, or ``None`` when it is absent or empty.
    """
    if value is None:
        return None
    normalized = " ".join(unicodedata.normalize("NFKC", value).lower().split())
    return normalized[:200] or None


def select_grade(
    signal: ReviewSignal,
    *,
    attribution: Attribution | None,
    memory_error_signature: str | None,
    verified_recovery: bool,
) -> Grade | None:
    """Choose AGAIN/EASY/HARD/GOOD in contract order, or no review.

    The caller has already admitted the scope, the final exposure and the outcome evidence. This function
    only orders the grade rules; it never reads a store and never trusts a model-provided grade.

    Args:
        signal: Verified outcome evidence for one attempt.
        attribution: How the memory was attributed to the outcome. ``"cited"`` is an explicit validated
            citation, ``"overlap"`` is the opt-in heuristic, and ``None`` means the memory was not attributed.
        memory_error_signature: Error signature recorded on the memory under review, if any.
        verified_recovery: Whether attribution verified a structural link between this memory and the
            recovery artifacts of the outcome.

    Returns:
        The selected grade, or ``None`` when the outcome earns no review.
    """
    if attribution is None:
        return None
    if signal.outcome in ("cancelled", "incomplete"):
        return None

    if signal.outcome == "failure":
        memory_signature = _normalize_signature(memory_error_signature)
        if memory_signature is not None and signal.error_signature == memory_signature:
            return Grade.AGAIN
        return None

    if verified_recovery and signal.recovery_refs:
        return Grade.EASY if attribution == "cited" else Grade.GOOD
    if signal.correction_count > 0:
        return Grade.HARD
    if signal.first_attempt:
        return Grade.GOOD
    return None
