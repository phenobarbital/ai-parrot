"""Deterministic ranking for experiential candidates, separate from fact validity."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from datetime import datetime, timezone

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


def _recency_key(memory_id: str, recency: Mapping[str, datetime]) -> float:
    """Return the tie-break key that orders newer candidates first.

    Args:
        memory_id: Candidate identity.
        recency: Caller-resolved creation times keyed by ``memory_id``.

    Returns:
        The negated UTC timestamp, so an ascending sort puts the newest first; ``inf`` when the caller
        supplied no creation time, which orders the candidate after every dated one.
    """
    created_at = recency.get(memory_id)
    if created_at is None:
        return float("inf")
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return -created_at.timestamp()


def rank_candidates(
    candidates: list[MemoryCandidate],
    *,
    now: datetime,
    parameters: MemoryParameters,
    states: Mapping[str, MemoryState],
    anti_pattern_ids: Collection[str] = frozenset(),
    recency: Mapping[str, datetime] | None = None,
) -> list[MemoryCandidate]:
    """Rank experiential candidates with recency-then-stable-ID ties and anti-pattern grouping.

    The score is ``relevance * retrievability * (1 + importance / 10)``. Anti-pattern candidates form the
    first group and the same score orders each group; ties resolve by creation time (newest first), then
    ``memory_id``, then ``content_version``. Raw ``similarity`` and ``relevance`` are preserved. The function
    is pure: it reads no store and returns copies, leaving the input list and its candidates untouched.

    Args:
        candidates: Retrieved candidates of any type.
        now: Aware UTC ranking time.
        parameters: Immutable dynamics parameters.
        states: Dynamics states resolved by the caller, keyed by ``MemoryCandidate.dynamics_state_ref``.
            A missing entry is treated as uninitialized legacy state and ranks neutrally.
        anti_pattern_ids: ``memory_id`` values the caller identified as anti-patterns from episode metadata.
        recency: Creation times resolved by the caller, keyed by ``memory_id``. It only breaks score ties: a
            candidate without an entry orders after the dated ones, so a truncated result keeps the newest.

    Returns:
        Ranked experiential candidates with ``ranking_score`` set, followed by the non-experiential
        candidates (user knowledge, skills) unchanged and in their input order.
    """
    created = recency or {}
    scored: list[tuple[int, float, float, str, str, MemoryCandidate]] = []
    passthrough: list[MemoryCandidate] = []
    for candidate in candidates:
        if not _is_experiential(candidate):
            passthrough.append(candidate)
            continue
        recall = _retrievability(candidate, now=now, parameters=parameters, states=states)
        score = candidate.relevance * recall * (1.0 + (candidate.importance or 0) / 10.0)
        group = 0 if candidate.memory_id in anti_pattern_ids else 1
        ranked = candidate.model_copy(update={"ranking_score": score})
        scored.append(
            (
                group,
                -score,
                _recency_key(candidate.memory_id, created),
                candidate.memory_id,
                candidate.content_version,
                ranked,
            )
        )

    scored.sort(key=lambda item: item[:5])
    return [item[5] for item in scored] + passthrough
