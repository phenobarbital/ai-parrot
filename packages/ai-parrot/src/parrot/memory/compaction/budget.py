"""Budget resolution and calibration math for per-turn conversation compaction (FEAT-525).

``MODEL_WINDOWS`` did not exist anywhere in the repo before this feature;
this module creates the per-model context-window table together with the
pure calibration functions that both ``ConversationMemory.add_turn``
(TASK-2826) and ``report_usage`` use.
"""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import datetime, timezone
from typing import Dict, Optional

from parrot.memory.compaction.models import (
    CALIBRATION_MAX,
    CALIBRATION_MIN,
    EWMA_ALPHA,
    FALLBACK_WINDOW,
    CompactionCommit,
    CompactionState,
    ContextBudget,
)

__all__ = [
    "CALIBRATION_MAX",
    "CALIBRATION_MIN",
    "EWMA_ALPHA",
    "FALLBACK_WINDOW",
    "MODEL_WINDOWS",
    "apply_commit",
    "apply_usage",
    "build_default_budget",
    "compaction_disabled_by_env",
    "resolve_window",
]

#: Lower-cased model-name prefixes mapped to their context window, in
#: tokens. Longest matching prefix wins; unknown models fall back to
#: :data:`FALLBACK_WINDOW`. Intentionally a small, tested starter table —
#: an incomplete table is safe by construction.
MODEL_WINDOWS: Dict[str, int] = {
    "claude-": 200_000,
    "gpt-4o": 128_000,
    "gpt-4.1": 1_047_576,
    "gpt-5": 400_000,
    "o1": 200_000,
    "o3": 200_000,
    "o4": 200_000,
    "gemini-": 1_048_576,
    "llama-3.1": 131_072,
    "llama-3.3": 131_072,
    "mistral-large": 128_000,
}

#: Prefixes sorted longest-first so the most specific match wins.
_SORTED_PREFIXES = sorted(MODEL_WINDOWS, key=len, reverse=True)


def resolve_window(model: Optional[str]) -> int:
    """Resolve a model name to its context window.

    Args:
        model: The model name (e.g. ``"claude-sonnet-5"``). ``None`` or
            empty resolves to the fallback.

    Returns:
        The window in tokens from :data:`MODEL_WINDOWS` (longest matching
        prefix), or :data:`FALLBACK_WINDOW` when the model is unknown.
    """
    if not model:
        return FALLBACK_WINDOW
    lowered = model.lower()
    for prefix in _SORTED_PREFIXES:
        if lowered.startswith(prefix):
            return MODEL_WINDOWS[prefix]
    return FALLBACK_WINDOW


def build_default_budget(model: Optional[str], *, max_turns: Optional[int] = None) -> ContextBudget:
    """Build the default :class:`ContextBudget` for a model.

    Args:
        model: The model name used to resolve the window.
        max_turns: Overrides :class:`ContextBudget`'s default ceiling (30)
            when given.

    Returns:
        A :class:`ContextBudget` with ``window=resolve_window(model)``.
    """
    kwargs = {"window": resolve_window(model)}
    if max_turns is not None:
        kwargs["max_turns"] = max_turns
    return ContextBudget(**kwargs)


def compaction_disabled_by_env() -> bool:
    """Return whether the ``PARROT_COMPACTION_DISABLED`` kill switch is set.

    Mirrors FEAT-380's ``PARROT_COMPRESSION_DISABLED``
    (``tools/compression/stage.py:148``) but is a **different** variable
    for a different feature.

    Returns:
        ``True`` only when the environment variable equals ``"1"``.
    """
    return os.getenv("PARROT_COMPACTION_DISABLED") == "1"


def apply_usage(state: CompactionState, prompt_estimate: int, provider_prompt_tokens: Optional[int]) -> CompactionState:
    """Fold one observed (estimate, provider) pair into the EWMA calibration.

    Pure. Returns ``state`` unchanged (same object) when the sample is
    degenerate (``prompt_estimate <= 0`` or ``provider_prompt_tokens`` is
    ``None``/``<= 0``).

    Args:
        state: The current calibration state.
        prompt_estimate: The bot's own token estimate for the round.
        provider_prompt_tokens: The provider-reported prompt token count
            for the same round, when available.

    Returns:
        A new :class:`CompactionState` with ``calibration`` updated via
        EWMA (``alpha=0.2``, clamped to ``[0.5, 2.0]``; the first sample
        sets ``calibration = ratio`` directly), ``samples`` incremented,
        and ``updated_at`` stamped — or ``state`` unchanged for a
        degenerate sample.
    """
    if prompt_estimate <= 0 or not provider_prompt_tokens or provider_prompt_tokens <= 0:
        return state

    ratio = provider_prompt_tokens / prompt_estimate
    if state.samples == 0:
        new_calibration = ratio
    else:
        new_calibration = EWMA_ALPHA * ratio + (1 - EWMA_ALPHA) * state.calibration
    new_calibration = max(CALIBRATION_MIN, min(CALIBRATION_MAX, new_calibration))

    return replace(
        state,
        calibration=new_calibration,
        samples=state.samples + 1,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )


def apply_commit(
    state: Optional[CompactionState],
    commit: CompactionCommit,
    tokenizer: str,
    provider_prompt_tokens: Optional[int],
) -> CompactionState:
    """Fold a bot round's :class:`CompactionCommit` into the persisted compaction state.

    ``compact_history`` (TASK-2828) already guarantees ``commit.boundary_turn_id``
    never regresses relative to the persisted boundary (it starts the walk
    from the persisted boundary). This function therefore treats a non-``None``
    commit boundary as authoritative and only refuses to replace an existing
    boundary with ``None`` — it does not itself compare turn order.

    Args:
        state: The current persisted state, or ``None`` on the first write.
        commit: The bot's commit for this round.
        tokenizer: The counter name to stamp on the resulting state.
        provider_prompt_tokens: The provider-reported prompt token count
            for this round, when available.

    Returns:
        The new :class:`CompactionState`: calibration updated via
        :func:`apply_usage`; ``boundary_turn_id`` replaced by
        ``commit.boundary_turn_id`` when it is not ``None``, otherwise
        kept; ``stage2_needed`` OR'd with the commit's flag (never
        cleared here); ``tokenizer`` set to ``tokenizer``.
    """
    base = state or CompactionState(tokenizer=tokenizer)
    updated = apply_usage(base, commit.prompt_estimate, provider_prompt_tokens)

    boundary_turn_id = commit.boundary_turn_id if commit.boundary_turn_id is not None else updated.boundary_turn_id
    stage2_needed = updated.stage2_needed or commit.stage2_needed

    return replace(
        updated,
        tokenizer=tokenizer,
        boundary_turn_id=boundary_turn_id,
        stage2_needed=stage2_needed,
    )
