"""S1 spike: pure FSRS-6 candidate transitions (prototype for FEAT-571 M1 — NOT importable from parrot.*)."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime
from enum import IntEnum

DECAY_INDEX = 20  # w20 is the learnable decay in FSRS-6 (21 parameters)
STABILITY_MIN = 0.001  # mirrors reference scheduler.py:56
MIN_DIFFICULTY = 1.0  # mirrors reference scheduler.py MIN_DIFFICULTY
MAX_DIFFICULTY = 10.0  # mirrors reference scheduler.py MAX_DIFFICULTY


class Grade(IntEnum):
    """Spec §2 Data Models: AGAIN=1, HARD=2, GOOD=3, EASY=4."""

    AGAIN = 1
    HARD = 2
    GOOD = 3
    EASY = 4


@dataclass(frozen=True)
class CandidateState:
    """Minimal D/S state for parity checks (M1's MemoryState adds bookkeeping)."""

    stability: float
    difficulty: float
    last_review: datetime | None


def elapsed(state: CandidateState, now: datetime, *, time_policy: str) -> float:
    """Return t for the retrievability curve under `time_policy` ('days-v1' | 'hours-v1')."""
    if state.last_review is None:
        return 0.0
    delta = now - state.last_review
    if time_policy == "days-v1":
        # Whole elapsed days, exactly as reference `review_card`'s `days_since_last_review`
        # (`(review_datetime - card.last_review).days`, unclamped).
        return float(delta.days)
    if time_policy == "hours-v1":
        # Fractional agent-time adaptation (spec §2): explicitly versioned, measured
        # side-by-side with the reference-exact policy, never silently substituted.
        return delta.total_seconds() / 86400.0
    raise ValueError(f"Unknown time_policy: {time_policy!r}")


def retrievability(state: CandidateState, now: datetime, w: tuple[float, ...], *, time_policy: str) -> float:
    """R(t, S) = (1 + factor * t / S) ** -decay with decay = -w[20], factor = 0.9 ** (1/decay) - 1."""
    if state.last_review is None:
        return 1.0
    decay = -w[DECAY_INDEX]
    factor = 0.9 ** (1.0 / decay) - 1.0
    # Mirrors vendored `get_card_retrievability`'s own `max(0, elapsed_days)` clamp.
    t = max(0.0, elapsed(state, now, time_policy=time_policy))
    return (1.0 + factor * t / state.stability) ** decay


def _initial_difficulty_raw(grade: Grade, w: tuple[float, ...]) -> float:
    """Unclamped D0 for `grade` — mirrors reference `_initial_difficulty(clamp=False)`."""
    return w[4] - (math.e ** (w[5] * (int(grade) - 1))) + 1


def initial_state(grade: Grade, w: tuple[float, ...], reviewed_at: datetime) -> CandidateState:
    """First review: S0 = w[grade-1], D0 = clamp(w4 - e^(w5*(grade-1)) + 1)."""
    stability = max(w[int(grade) - 1], STABILITY_MIN)
    difficulty = min(max(_initial_difficulty_raw(grade, w), MIN_DIFFICULTY), MAX_DIFFICULTY)
    return CandidateState(stability=stability, difficulty=difficulty, last_review=reviewed_at)


def _next_difficulty(difficulty: float, grade: Grade, w: tuple[float, ...]) -> float:
    """Mirrors reference `_next_difficulty`: linear damping + mean reversion toward D(EASY)."""

    def _linear_damping(delta_difficulty: float, difficulty: float) -> float:
        return (10.0 - difficulty) * delta_difficulty / 9.0

    arg_1 = _initial_difficulty_raw(Grade.EASY, w)
    delta_difficulty = -(w[6] * (int(grade) - 3))
    arg_2 = difficulty + _linear_damping(delta_difficulty=delta_difficulty, difficulty=difficulty)
    next_difficulty = w[7] * arg_1 + (1 - w[7]) * arg_2
    return min(max(next_difficulty, MIN_DIFFICULTY), MAX_DIFFICULTY)


def _short_term_stability(stability: float, grade: Grade, w: tuple[float, ...]) -> float:
    """Same-day successful multiplier, clamped to >= 1.0; mirrors reference `_short_term_stability`."""
    increase = (math.e ** (w[17] * (int(grade) - 3 + w[18]))) * (stability ** -w[19])
    if grade in (Grade.HARD, Grade.GOOD, Grade.EASY):
        increase = max(increase, 1.0)
    return max(stability * increase, STABILITY_MIN)


def _next_forget_stability(
    difficulty: float, stability: float, retrievability_value: float, w: tuple[float, ...]
) -> float:
    """Lapse branch (w11..w14) with the short-term floor; mirrors reference `_next_forget_stability`."""
    long_term = (
        w[11]
        * (difficulty ** -w[12])
        * (((stability + 1) ** w[13]) - 1)
        * (math.e ** ((1 - retrievability_value) * w[14]))
    )
    short_term = stability / (math.e ** (w[17] * w[18]))
    return min(long_term, short_term)


def _next_recall_stability(
    difficulty: float, stability: float, retrievability_value: float, grade: Grade, w: tuple[float, ...]
) -> float:
    """Successful-review branch (w8..w10, w15/w16); mirrors reference `_next_recall_stability`."""
    hard_penalty = w[15] if grade == Grade.HARD else 1
    easy_bonus = w[16] if grade == Grade.EASY else 1
    return stability * (
        1
        + (math.e ** w[8])
        * (11 - difficulty)
        * (stability ** -w[9])
        * ((math.e ** ((1 - retrievability_value) * w[10])) - 1)
        * hard_penalty
        * easy_bonus
    )


def transition(
    state: CandidateState, grade: Grade, w: tuple[float, ...], reviewed_at: datetime, *, time_policy: str
) -> CandidateState:
    """Apply one review: same-day branch, recall branch (w8..w10, w15/w16), lapse branch (w11..w14, floor)."""
    if state.last_review is None:
        return initial_state(grade, w, reviewed_at)

    t = elapsed(state, reviewed_at, time_policy=time_policy)
    if t < 1:
        new_stability = _short_term_stability(state.stability, grade, w)
        new_difficulty = _next_difficulty(state.difficulty, grade, w)
    else:
        r = retrievability(state, reviewed_at, w, time_policy=time_policy)
        if grade == Grade.AGAIN:
            new_stability = _next_forget_stability(state.difficulty, state.stability, r, w)
        else:
            new_stability = _next_recall_stability(state.difficulty, state.stability, r, grade, w)
        new_difficulty = _next_difficulty(state.difficulty, grade, w)

    new_stability = max(new_stability, STABILITY_MIN)
    return replace(state, stability=new_stability, difficulty=new_difficulty, last_review=reviewed_at)
