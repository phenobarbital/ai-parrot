"""Behavioral acceptance tests for Dynamics state and immutable parameter models."""

import pytest

from parrot.memory.dynamics.models import (
    DEFAULT_PARAMETERS,
    MemoryParameters,
    MemoryRef,
    MemoryState,
)
from parrot.memory.episodic.models import MemoryNamespace


def test_parameter_bounds_and_immutability() -> None:
    """Verify parameter bounds and immutability."""
    parameters = MemoryParameters(
        algorithm="fsrs-6",
        time_policy="days-v1",
        parameter_id="fsrs-6-default",
        provenance="pinned-reference",
    )

    assert parameters.weights == DEFAULT_PARAMETERS
    with pytest.raises(ValueError, match="exactly 21"):
        MemoryParameters(
            algorithm="fsrs-6",
            time_policy="days-v1",
            parameter_id="invalid-length",
            weights=DEFAULT_PARAMETERS[:-1],
            provenance="pinned-reference",
        )
    with pytest.raises(ValueError, match="within the accepted"):
        MemoryParameters(
            algorithm="fsrs-6",
            time_policy="days-v1",
            parameter_id="invalid-bound",
            weights=(*DEFAULT_PARAMETERS[:-1], 0.81),
            provenance="pinned-reference",
        )
    with pytest.raises(ValueError):
        parameters.provenance = "refit"


def test_neutral_legacy_state() -> None:
    """Verify neutral legacy state."""
    state = MemoryState()

    assert state.status == "uninitialized"
    assert state.review_count == 0
    assert state.difficulty is None
    assert state.stability is None
    assert state.parameter_id is None
    with pytest.raises(ValueError, match="cannot carry earned reviews"):
        MemoryState(review_count=1)
    with pytest.raises(ValueError, match="requires parameter_id"):
        MemoryState(
            status="reviewed",
            difficulty=5.0,
            stability=1.0,
            reviewed_at="2026-11-13T00:00:00+00:00",
        )


def test_versioned_namespace_identity() -> None:
    """Verify versioned namespace identity."""
    namespace = MemoryNamespace(tenant_id="tenant", agent_id="agent", user_id="user", session_id="session")
    episode = MemoryRef(namespace=namespace, kind="episode", memory_id="episode-1", content_version="v1")
    next_version = MemoryRef(
        namespace=namespace,
        kind="brain",
        memory_id="page-1",
        content_version="a" * 40,
    )
    changed_namespace = MemoryRef(
        namespace=MemoryNamespace(tenant_id="tenant", agent_id="agent", user_id="other", session_id="session"),
        kind="brain",
        memory_id="page-1",
        content_version="a" * 40,
    )

    assert episode.canonical_key.startswith("mref-v1-")
    assert next_version.canonical_key != changed_namespace.canonical_key
    with pytest.raises(ValueError, match="episode content_version"):
        MemoryRef(namespace=namespace, kind="episode", memory_id="episode-1", content_version="v2")


def test_reviewed_state_bounds_and_utc() -> None:
    """Verify reviewed state accepts valid values and rejects non-finite, out-of-range and non-UTC input."""
    valid = MemoryState(
        status="reviewed",
        difficulty=5.0,
        stability=1.0,
        reviewed_at="2026-11-13T00:00:00+00:00",
        parameter_id="fsrs-6-default",
        review_count=1,
    )

    assert valid.review_count == 1
    for field, value in (("stability", float("inf")), ("stability", float("nan")), ("stability", 0.0005)):
        with pytest.raises(ValueError, match="stability"):
            MemoryState(**{**valid.model_dump(), field: value})
    for value in (0.5, 10.5, float("nan")):
        with pytest.raises(ValueError, match="difficulty"):
            MemoryState(**{**valid.model_dump(), "difficulty": value})
    with pytest.raises(ValueError, match="aware UTC"):
        MemoryState(**{**valid.model_dump(), "reviewed_at": "2026-11-13T00:00:00"})
    with pytest.raises(ValueError):
        valid.review_count = 2
