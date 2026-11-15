"""Behavioral acceptance tests for episode model scope and optional reviews."""

import pytest

from parrot.memory.episodic.backends.abstract import AbstractEpisodeBackend
from parrot.memory.episodic.models import EpisodicMemory, EpisodeSearchResult, MemoryNamespace


def _episode(**overrides: object) -> EpisodicMemory:
    """Create a minimal episodic memory with optional field overrides."""
    return EpisodicMemory(
        agent_id="agent-a",
        situation="A task needed a response.",
        action_taken="Answered the task.",
        outcome="success",
        **overrides,
    )


def _search_result(**overrides: object) -> EpisodeSearchResult:
    """Create a minimal search result with optional ranking field overrides."""
    data = _episode().model_dump()
    data["score"] = 0.8
    data.update(overrides)
    return EpisodeSearchResult(**data)


def test_legacy_and_model_scoped_round_trip() -> None:
    """Verify legacy and model-scoped episode serialization round trips."""
    legacy = _episode()
    legacy_data = legacy.to_dict()

    assert legacy_data["model_id"] is None
    restored_legacy = EpisodicMemory.from_dict({key: value for key, value in legacy_data.items() if key != "model_id"})
    assert restored_legacy.model_id is None

    scoped = _episode(model_id="openai:gpt-4o")
    restored = EpisodicMemory.from_dict(scoped.to_dict())

    assert restored.model_id == "openai:gpt-4o"
    assert restored.to_dict()["model_id"] == "openai:gpt-4o"
    with pytest.raises(ValueError, match="at least 1 character"):
        _episode(model_id="")


def test_namespace_encoding_no_collisions() -> None:
    """Verify model scope filters and Redis prefixes use collision-safe encoding."""
    legacy = MemoryNamespace(tenant_id="tenant", agent_id="agent")
    scoped = MemoryNamespace(tenant_id="tenant", agent_id="agent", model_id="openai:gpt-4o/mini")
    other = MemoryNamespace(tenant_id="tenant", agent_id="agent", model_id="openai:gpt-4o%2Fmini")

    assert legacy.build_filter() == {"tenant_id": "tenant", "agent_id": "agent"}
    assert legacy.redis_prefix == "tenant:agent"
    assert scoped.build_filter()["model_id"] == "openai:gpt-4o/mini"
    assert scoped.redis_prefix == "tenant:agent:model:openai%3Agpt-4o%2Fmini"
    assert scoped.redis_prefix != other.redis_prefix
    assert scoped.scope_label == "agent:agent"
    with pytest.raises(ValueError, match="at least 1 character"):
        MemoryNamespace(tenant_id="tenant", agent_id="agent", model_id="")


@pytest.mark.parametrize("field", ("score", "ranking_score", "retrievability", "stability"))
@pytest.mark.parametrize("value", (float("inf"), float("nan")))
def test_search_result_rejects_non_finite_float_fields(field: str, value: float) -> None:
    """Verify every floating-point search field rejects infinity and NaN."""
    with pytest.raises(ValueError):
        _search_result(**{field: value})


@pytest.mark.parametrize("value", (float("inf"), float("nan"), -1))
def test_search_result_rejects_invalid_review_count(value: float) -> None:
    """Verify the separate review count remains a non-negative integer."""
    with pytest.raises(ValueError):
        _search_result(review_count=value)


@pytest.mark.asyncio
async def test_baseline_backend_without_review() -> None:
    """Verify a baseline backend remains valid without review capability."""

    class BaselineBackend:
        """Minimal implementation of the baseline episode backend protocol."""

        async def store(self, episode: EpisodicMemory) -> str:
            """Return the stored episode identifier."""
            return episode.episode_id

        async def search_similar(
            self,
            embedding: list[float],
            namespace_filter: dict[str, object],
            top_k: int = 5,
            score_threshold: float = 0.3,
            include_failures_only: bool = False,
        ) -> list[EpisodeSearchResult]:
            """Return no results from the isolated baseline backend."""
            return []

        async def get_recent(
            self,
            namespace_filter: dict[str, object],
            limit: int = 10,
            since: object = None,
        ) -> list[EpisodicMemory]:
            """Return no stored records from the isolated baseline backend."""
            return []

        async def get_failures(
            self,
            agent_id: str,
            tenant_id: str = "default",
            limit: int = 5,
        ) -> list[EpisodicMemory]:
            """Return no failures from the isolated baseline backend."""
            return []

        async def delete_expired(self) -> int:
            """Return no deletions from the isolated baseline backend."""
            return 0

        async def count(self, namespace_filter: dict[str, object]) -> int:
            """Return no records from the isolated baseline backend."""
            return 0

        async def update_metadata(self, episode_ids: list[str], patch: dict[str, object]) -> int:
            """Report no metadata updates from the isolated baseline backend."""
            return 0

    backend = BaselineBackend()

    assert isinstance(backend, AbstractEpisodeBackend)
    assert not hasattr(backend, "apply_review")
    assert await backend.store(_episode())
