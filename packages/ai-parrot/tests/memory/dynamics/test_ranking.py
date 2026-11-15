"""Behavioral acceptance tests for experiential candidate ranking."""

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from parrot.memory.agent_memory.models import MemoryRequestScope
from parrot.memory.dynamics.fsrs import retrievability, transition
from parrot.memory.dynamics.models import Grade, MemoryParameters, MemoryState
from parrot.memory.dynamics.ranking import rank_candidates
from parrot.memory.unified.models import MemoryCandidate

_REVIEWED_AT = datetime(2026, 1, 1, tzinfo=timezone.utc)
_NOW = _REVIEWED_AT + timedelta(days=30)


def _parameters() -> MemoryParameters:
    """Return the accepted immutable parameter set."""
    return MemoryParameters(
        algorithm="fsrs-6",
        time_policy="days-v1",
        parameter_id="fsrs-6-default",
        provenance="py-fsrs-v6.3.2",
    )


def _candidate(memory_id: str, **overrides: Any) -> MemoryCandidate:
    """Build one episodic candidate in a trusted scope, overridden per case."""
    data: dict[str, Any] = {
        "scope": MemoryRequestScope(
            tenant_id="tenant-a",
            agent_id="agent-a",
            user_id="user-a",
            session_id="session-a",
            turn_id="turn-a",
            identity_provenance="runtime_derived",
        ),
        "memory_id": memory_id,
        "content_version": "v1",
        "source": "episodic",
        "text": f"lesson {memory_id}",
        "relevance": 0.5,
    }
    data.update(overrides)
    return MemoryCandidate(**data)


def _reviewed_state(parameters: MemoryParameters) -> MemoryState:
    """Return a state with one earned review, so retrievability decays over time."""
    return transition(MemoryState(), Grade.GOOD, reviewed_at=_REVIEWED_AT, parameters=parameters)


def test_ranking_formula_and_stable_ties() -> None:
    """Score relevance x retrievability x (1 + importance/10) and break ties by stable ID."""
    parameters = _parameters()
    state = _reviewed_state(parameters)
    recall = retrievability(state, now=_NOW, parameters=parameters)
    assert 0.0 < recall < 1.0

    decayed = _candidate("decayed", relevance=0.8, similarity=0.42, importance=5, dynamics_state_ref="state-1")
    tie_b = _candidate("tie-b", relevance=0.6)
    tie_a = _candidate("tie-a", relevance=0.6)
    originals = [decayed, tie_b, tie_a]

    ranked = rank_candidates(originals, now=_NOW, parameters=parameters, states={"state-1": state})

    by_id = {candidate.memory_id: candidate for candidate in ranked}
    assert by_id["decayed"].ranking_score == pytest.approx(0.8 * recall * 1.5)
    assert by_id["tie-a"].ranking_score == pytest.approx(0.6)
    assert by_id["tie-a"].ranking_score == by_id["tie-b"].ranking_score
    assert [c.memory_id for c in ranked].index("tie-a") < [c.memory_id for c in ranked].index("tie-b")
    assert [c.ranking_score for c in ranked] == sorted((c.ranking_score for c in ranked), reverse=True)

    assert by_id["decayed"].similarity == 0.42
    assert by_id["decayed"].relevance == 0.8
    assert all(candidate.ranking_score is None for candidate in originals)
    assert [candidate.memory_id for candidate in originals] == ["decayed", "tie-b", "tie-a"]

    reversed_ranked = rank_candidates(originals[::-1], now=_NOW, parameters=parameters, states={"state-1": state})
    assert [c.memory_id for c in reversed_ranked] == [c.memory_id for c in ranked]


def test_legacy_state_is_neutral() -> None:
    """Rank candidates without earned state as fully retrievable."""
    parameters = _parameters()
    candidates = [
        _candidate("no-ref", relevance=0.4),
        _candidate("unresolved", relevance=0.4, dynamics_state_ref="missing"),
        _candidate("uninitialized", relevance=0.4, dynamics_state_ref="legacy"),
    ]

    ranked = rank_candidates(candidates, now=_NOW, parameters=parameters, states={"legacy": MemoryState()})

    assert [candidate.ranking_score for candidate in ranked] == pytest.approx([0.4, 0.4, 0.4])
    assert [candidate.memory_id for candidate in ranked] == ["no-ref", "uninitialized", "unresolved"]


def test_anti_patterns_group_first_and_exclusions() -> None:
    """Group anti-patterns first with the same rank inside, and keep non-experiential candidates out of FSRS."""
    parameters = _parameters()
    user_fact = _candidate("user-fact", candidate_type="user", source="user_knowledge", relevance=0.99)
    skill = _candidate("skill", candidate_type="skill", source="skills", relevance=0.95)
    candidates = [
        user_fact,
        _candidate("strong", relevance=0.9),
        _candidate("warn-low", relevance=0.1),
        skill,
        _candidate("warn-high", relevance=0.3, candidate_type="brain", source="brain"),
    ]

    ranked = rank_candidates(
        candidates,
        now=_NOW,
        parameters=parameters,
        states={},
        anti_pattern_ids={"warn-low", "warn-high"},
    )

    assert [candidate.memory_id for candidate in ranked] == ["warn-high", "warn-low", "strong", "user-fact", "skill"]
    assert ranked[3] is user_fact
    assert ranked[4] is skill
    assert user_fact.ranking_score is None
    assert skill.ranking_score is None
