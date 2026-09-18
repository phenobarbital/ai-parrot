"""Regression tests: UnifiedMemoryManager records a REAL conversation episode (FEAT-571 M0, AC02).

These tests use a real ``EpisodicMemoryStore`` over an in-memory ``FAISSBackend`` — no
``AsyncMock`` of the store — so a signature mismatch between the manager and the store
surfaces as a failure instead of being swallowed by ``record_interaction``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from parrot.memory.episodic.models import EpisodeCategory, EpisodeOutcome, MemoryNamespace
from parrot.memory.episodic.store import EpisodicMemoryStore
from parrot.memory.unified.manager import UnifiedMemoryManager

pytest.importorskip("faiss")

from parrot.memory.episodic.backends.faiss import FAISSBackend  # noqa: E402


@pytest.fixture
async def backend() -> FAISSBackend:
    be = FAISSBackend(dimension=8)
    await be.configure()
    return be


@pytest.fixture
def store(backend: FAISSBackend) -> EpisodicMemoryStore:
    return EpisodicMemoryStore(backend=backend, default_ttl_days=0)


@pytest.fixture
def namespace() -> MemoryNamespace:
    return MemoryNamespace(tenant_id="acme", agent_id="planner", room_id="room-7", crew_id="crew-3")


@pytest.fixture
def manager(namespace: MemoryNamespace, store: EpisodicMemoryStore) -> UnifiedMemoryManager:
    return UnifiedMemoryManager(namespace=namespace, episodic_store=store)


def _expected_filter(namespace: MemoryNamespace, user_id: str, session_id: str) -> dict:
    return MemoryNamespace(
        tenant_id=namespace.tenant_id,
        agent_id=namespace.agent_id,
        user_id=user_id,
        session_id=session_id,
        room_id=namespace.room_id,
        crew_id=namespace.crew_id,
    ).build_filter()


async def test_unified_records_real_episode(manager, backend, namespace) -> None:
    """A conversation turn is persisted as a PARTIAL QUERY_RESOLUTION episode with room/crew retained."""
    await manager.record_interaction("What is the rollout plan?", "Ship on Tuesday.", [], "u1", "s1")

    episodes = await backend.get_recent(_expected_filter(namespace, "u1", "s1"), limit=10)
    assert len(episodes) == 1
    episode = episodes[0]
    assert episode.outcome == EpisodeOutcome.PARTIAL
    assert episode.category == EpisodeCategory.QUERY_RESOLUTION
    assert episode.situation == "What is the rollout plan?"
    assert "Ship on Tuesday." in episode.action_taken
    assert (episode.room_id, episode.crew_id) == ("room-7", "crew-3")
    assert (episode.user_id, episode.session_id) == ("u1", "s1")
    assert 1 <= episode.importance <= 10
    assert episode.is_failure is False


async def test_record_episodic_does_not_raise_signature_error(manager) -> None:
    """Calling the private recorder directly surfaces any store-signature mismatch (nothing swallows it here)."""
    await manager._record_episodic("q", "a", [], "u2", "s2")


async def test_response_object_content_is_used(manager, backend, namespace) -> None:
    """Objects exposing ``.content`` are stringified through that attribute."""
    await manager.record_interaction("q", SimpleNamespace(content="structured answer"), [], "u3", "s3")
    episodes = await backend.get_recent(_expected_filter(namespace, "u3", "s3"), limit=10)
    assert len(episodes) == 1
    assert "structured answer" in episodes[0].action_taken


async def test_tool_calls_are_not_recorded_as_tool_episodes(manager, backend, namespace) -> None:
    """Tool calls passed to record_interaction are not proof of success and produce no extra episodes."""
    tool_calls = [SimpleNamespace(name="search", args={"q": "x"})]
    await manager.record_interaction("q", "a", tool_calls, "u4", "s4")
    episodes = await backend.get_recent(_expected_filter(namespace, "u4", "s4"), limit=10)
    assert len(episodes) == 1
    assert episodes[0].category == EpisodeCategory.QUERY_RESOLUTION
