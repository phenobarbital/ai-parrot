"""Deterministic ranking for experiential candidates, separate from fact validity."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from datetime import datetime

from parrot.memory.unified.models import MemoryCandidate

from .fsrs import retrievability
from .models import MemoryParameters, MemoryState

_EXPERIENTIAL_TYPES = frozenset({"episodic", "brain"})


def _is_experiential(candidate: MemoryCandidate) -> bool:
    """Return whether dynamics may rank this candidate.

    Args:
        candidate: Retrieved candidate.

    Returns:
        ``True`` for episodic and brain candidates; user knowledge and skills are never ranked by dynamics.
    """
    return candidate.candidate_type in _EXPERIENTIAL_TYPES


def _retrievability(
    candidate: MemoryCandidate,
    *,
    now: datetime,
    parameters: MemoryParameters,
    states: Mapping[str, MemoryState],
) -> float:
    """Resolve the retrievability of one candidate, neutral when it has no earned state.

    Args:
        candidate: Experiential candidate.
        now: Aware UTC ranking time.
        parameters: Immutable dynamics parameters.
        states: Caller-resolved states keyed by ``dynamics_state_ref``.

    Returns:
        Retrievability in ``[0, 1]``; ``1.0`` when the candidate has no state reference or no resolved state.
    """
    if candidate.dynamics_state_ref is None:
        return 1.0
    state = states.get(candidate.dynamics_state_ref)
    if state is None:
        return 1.0
    return retrievability(state, now=now, parameters=parameters)


def rank_candidates(
    candidates: list[MemoryCandidate],
    *,
    now: datetime,
    parameters: MemoryParameters,
    states: Mapping[str, MemoryState],
    anti_pattern_ids: Collection[str] = frozenset(),
) -> list[MemoryCandidate]:
    """Rank experiential candidates with stable-ID ties and anti-pattern grouping.

    The score is ``relevance * retrievability * (1 + importance / 10)``. Anti-pattern candidates form the
    first group and the same score orders each group; ties resolve by ``memory_id`` then ``content_version``.
    Raw ``similarity`` and ``relevance`` are preserved. The function is pure: it reads no store and returns
    copies, leaving the input list and its candidates untouched.

    Args:
        candidates: Retrieved candidates of any type.
        now: Aware UTC ranking time.
        parameters: Immutable dynamics parameters.
        states: Dynamics states resolved by the caller, keyed by ``MemoryCandidate.dynamics_state_ref``.
            A missing entry is treated as uninitialized legacy state and ranks neutrally.
        anti_pattern_ids: ``memory_id`` values the caller identified as anti-patterns from episode metadata.

    Returns:
        Ranked experiential candidates with ``ranking_score`` set, followed by the non-experiential
        candidates (user knowledge, skills) unchanged and in their input order.
    """
    scored: list[tuple[int, float, str, str, MemoryCandidate]] = []
    passthrough: list[MemoryCandidate] = []
    for candidate in candidates:
        if not _is_experiential(candidate):
            passthrough.append(candidate)
            continue
        recall = _retrievability(candidate, now=now, parameters=parameters, states=states)
        score = candidate.relevance * recall * (1.0 + (candidate.importance or 0) / 10.0)
        group = 0 if candidate.memory_id in anti_pattern_ids else 1
        ranked = candidate.model_copy(update={"ranking_score": score})
        scored.append((group, -score, candidate.memory_id, candidate.content_version, ranked))

    scored.sort(key=lambda item: item[:4])
    return [item[4] for item in scored] + passthrough
