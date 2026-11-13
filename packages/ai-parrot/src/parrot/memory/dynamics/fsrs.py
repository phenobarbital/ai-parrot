"""Pure FSRS calculations using an explicit clock and immutable parameters.

The equations are adapted from ``open-spaced-repetition/py-fsrs`` v6.3.2,
commit ``9446cb06605c597a063aeee49f7d188d42e34dc2``. Copyright (c) 2022
Open Spaced Repetition, licensed under the MIT License. The pinned reference
and license are retained in ``sdd/state/FEAT-571/spikes/s1-fsrs-parity/reference``.
"""

from datetime import datetime

from .models import Grade, MemoryParameters, MemoryState

_EXP_BASE = 2.718281828459045
_STABILITY_MIN = 0.001
_MIN_DIFFICULTY = 1.0
_MAX_DIFFICULTY = 10.0


def _elapsed_days(state: MemoryState, now: datetime, parameters: MemoryParameters) -> float:
    """Return elapsed days under the parameters' explicit time policy."""
    if state.reviewed_at is None:
        return 0.0

    delta = now - state.reviewed_at
    if parameters.time_policy == "days-v1":
        return float(delta.days)
    return delta.total_seconds() / 86_400.0


def _clamp_difficulty(difficulty: float) -> float:
    """Clamp difficulty to the accepted FSRS scale."""
    return min(max(difficulty, _MIN_DIFFICULTY), _MAX_DIFFICULTY)


def _initial_difficulty(grade: Grade, weights: tuple[float, ...]) -> float:
    """Return the unclamped initial difficulty for a grade."""
    return weights[4] - (_EXP_BASE ** (weights[5] * (int(grade) - 1))) + 1


def _next_difficulty(difficulty: float, grade: Grade, weights: tuple[float, ...]) -> float:
    """Return difficulty after linear damping and mean reversion."""
    easy_difficulty = _initial_difficulty(Grade.EASY, weights)
    delta_difficulty = -(weights[6] * (int(grade) - 3))
    damped_difficulty = difficulty + (10.0 - difficulty) * delta_difficulty / 9.0
    next_difficulty = weights[7] * easy_difficulty + (1.0 - weights[7]) * damped_difficulty
    return _clamp_difficulty(next_difficulty)


def _short_term_stability(stability: float, grade: Grade, weights: tuple[float, ...]) -> float:
    """Return same-day stability, clamping successful-review growth to one."""
    increase = (_EXP_BASE ** (weights[17] * (int(grade) - 3 + weights[18]))) * (stability ** -weights[19])
    if grade in (Grade.HARD, Grade.GOOD, Grade.EASY):
        increase = max(increase, 1.0)
    return max(stability * increase, _STABILITY_MIN)


def _next_forget_stability(
    difficulty: float,
    stability: float,
    retrievability_value: float,
    weights: tuple[float, ...],
) -> float:
    """Return stability after an AGAIN review."""
    long_term = (
        weights[11]
        * (difficulty ** -weights[12])
        * (((stability + 1.0) ** weights[13]) - 1.0)
        * (_EXP_BASE ** ((1.0 - retrievability_value) * weights[14]))
    )
    short_term = stability / (_EXP_BASE ** (weights[17] * weights[18]))
    return min(long_term, short_term)


def _next_recall_stability(
    difficulty: float,
    stability: float,
    retrievability_value: float,
    grade: Grade,
    weights: tuple[float, ...],
) -> float:
    """Return stability after a successful review."""
    hard_penalty = weights[15] if grade == Grade.HARD else 1.0
    easy_bonus = weights[16] if grade == Grade.EASY else 1.0
    return stability * (
        1.0
        + (_EXP_BASE**weights[8])
        * (11.0 - difficulty)
        * (stability ** -weights[9])
        * ((_EXP_BASE ** ((1.0 - retrievability_value) * weights[10])) - 1.0)
        * hard_penalty
        * easy_bonus
    )


def retrievability(state: MemoryState, *, now: datetime, parameters: MemoryParameters) -> float:
    """Return bounded retrievability, with neutral treatment of uninitialized legacy state."""
    if now.utcoffset() is None or now.utcoffset().total_seconds() != 0:
        raise ValueError("now must be an aware UTC datetime")
    if state.parameter_id is not None and state.parameter_id != parameters.parameter_id:
        raise ValueError("existing state parameter_id does not match parameters")
    if state.reviewed_at is None or state.stability is None:
        return 1.0

    decay = -parameters.weights[20]
    factor = 0.9 ** (1.0 / decay) - 1.0
    elapsed_days = max(0.0, _elapsed_days(state, now, parameters))
    value = (1.0 + factor * elapsed_days / state.stability) ** decay
    return min(max(value, 0.0), 1.0)


def transition(
    state: MemoryState,
    grade: Grade,
    *,
    reviewed_at: datetime,
    parameters: MemoryParameters,
) -> MemoryState:
    """Compute a new state without I/O or modifying the input parameter/state objects."""
    if reviewed_at.utcoffset() is None or reviewed_at.utcoffset().total_seconds() != 0:
        raise ValueError("reviewed_at must be an aware UTC datetime")
    if state.parameter_id is not None and state.parameter_id != parameters.parameter_id:
        raise ValueError("existing state parameter_id does not match parameters")

    weights = parameters.weights
    if state.reviewed_at is None or state.stability is None or state.difficulty is None:
        stability = max(weights[int(grade) - 1], _STABILITY_MIN)
        difficulty = _clamp_difficulty(_initial_difficulty(grade, weights))
    else:
        elapsed_days = _elapsed_days(state, reviewed_at, parameters)
        difficulty = _next_difficulty(state.difficulty, grade, weights)
        if elapsed_days < 1.0:
            stability = _short_term_stability(state.stability, grade, weights)
        else:
            current_retrievability = retrievability(state, now=reviewed_at, parameters=parameters)
            if grade == Grade.AGAIN:
                stability = _next_forget_stability(
                    state.difficulty,
                    state.stability,
                    current_retrievability,
                    weights,
                )
            else:
                stability = _next_recall_stability(
                    state.difficulty,
                    state.stability,
                    current_retrievability,
                    grade,
                    weights,
                )
            stability = max(stability, _STABILITY_MIN)

    return MemoryState(
        difficulty=difficulty,
        stability=stability,
        reviewed_at=reviewed_at,
        review_count=state.review_count + 1,
        apply_revision=state.apply_revision + 1,
        status="reviewed",
        parameter_id=parameters.parameter_id,
    )
