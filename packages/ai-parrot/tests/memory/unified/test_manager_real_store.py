"""Regression tests: UnifiedMemoryManager records a REAL conversation episode (FEAT-571 M0, AC02).

These tests use a real ``EpisodicMemoryStore`` over an in-memory ``FAISSBackend`` — no
``AsyncMock`` of the store — so a signature mismatch between the manager and the store
surfaces as a failure instead of being swallowed by ``record_interaction``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from parrot.memory.agent_memory.models import MemoryEvent, MemoryRequestScope
from parrot.memory.episodic.models import EpisodeCategory, EpisodeOutcome, MemoryNamespace
from parrot.memory.agent_memory.runtime import bind_memory_scope, reset_memory_scope
from parrot.memory.episodic.store import EpisodicMemoryStore
from parrot.memory.episodic.tools import EpisodicMemoryToolkit
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


# ── Episodic recall visibility (TASK-5703, issue:2a40a9f62877) ──

_QUERY = "deploy rollout"


@pytest.fixture
def recall_manager(store: EpisodicMemoryStore) -> UnifiedMemoryManager:
    return UnifiedMemoryManager(namespace=MemoryNamespace(tenant_id="acme", agent_id="planner"), episodic_store=store)


def _scope(user_id: str | None = None, session_id: str | None = None) -> MemoryRequestScope:
    return MemoryRequestScope(
        tenant_id="acme",
        agent_id="planner",
        user_id=user_id,
        session_id=session_id,
        turn_id="turn-1",
        identity_provenance="runtime_derived",
    )


async def _failure(store: EpisodicMemoryStore, **dimensions: str) -> str:
    """Record one failure the query matches, under the given namespace dimensions."""
    episode = await store.record_episode(
        namespace=MemoryNamespace(tenant_id="acme", agent_id="planner", **dimensions),
        situation="deploy rollout failed",
        action_taken="ran the rollout",
        outcome=EpisodeOutcome.FAILURE,
        error_message="rollout timed out",
        generate_reflection=False,
    )
    return episode.episode_id


async def _recalled(manager: UnifiedMemoryManager, scope: MemoryRequestScope) -> dict[str, str]:
    """Return ``episode_id -> candidate source`` for one request scope."""
    candidates = await manager._get_episodic_candidates(_QUERY, scope)
    return {candidate.memory_id: candidate.source for candidate in candidates}


async def test_recall_crosses_sessions_of_the_same_user(recall_manager, store) -> None:
    """A lesson recorded in one session reaches the same user's next session, and nobody else."""
    earlier = await _failure(store, user_id="u1", session_id="s1")
    await _failure(store, user_id="u2", session_id="s9")

    assert await _recalled(recall_manager, _scope("u1", "s2")) == {earlier: "episodic"}
    assert await _recalled(recall_manager, _scope("u3", "s3")) == {}


async def test_recall_includes_agent_level_episodes(recall_manager, store) -> None:
    """Episodes with neither a user nor a session are visible to every request of the agent."""
    agent_level = await _failure(store)
    anonymous = await _failure(store, session_id="anon-1")
    await _failure(store, user_id="u2", session_id="s9")

    assert set(await _recalled(recall_manager, _scope("u1", "s2"))) == {agent_level}
    assert set(await _recalled(recall_manager, _scope(None, "anon-1"))) == {agent_level, anonymous}
    assert set(await _recalled(recall_manager, _scope(None, "anon-2"))) == {agent_level}
    # A request without a user never reads an identified user's episode, even inside the same session.
    assert set(await _recalled(recall_manager, _scope(None, "s9"))) == {agent_level}
    assert set(await _recalled(recall_manager, _scope())) == {agent_level}


async def test_set_room_keeps_narrowing_every_recall_scope(recall_manager, store) -> None:
    """A room on the request narrows the own and the agent-level filters alike."""
    in_room = await _failure(store, user_id="u1", session_id="s1", room_id="room-7")
    await _failure(store, user_id="u1", session_id="s1")
    await _failure(store)
    scope = _scope("u1", "s2").model_copy(update={"room_id": "room-7"})

    assert set(await _recalled(recall_manager, scope)) == {in_room}


async def test_visible_episodes_enter_the_review_manifest_with_original_identity(recall_manager, store) -> None:
    """Visible episodes retain their recorded identity regardless of the requesting session."""
    same_session = await _failure(store, user_id="u1", session_id="s1")
    other_session = await _failure(store, user_id="u1", session_id="s0")
    agent_level = await _failure(store)
    scope = _scope("u1", "s1")

    context = await recall_manager.prepare_context(_QUERY, scope=scope)
    assert set(context.delivered_refs) == {
        f"episodic:{same_session}:v1",
        f"episodic:{other_session}:v1",
        f"episodic:{agent_level}:v1",
    }

    committed = recall_manager.commit_memory_exposure(context, scope=scope)
    exposure = recall_manager._memory_exposures[committed.exposure_id]
    refs = {ref.memory_id: ref for ref in exposure.refs}
    assert set(refs) == {same_session, other_session, agent_level}
    assert refs[same_session].namespace == recall_manager._namespace_for_scope(scope)
    assert refs[other_session].namespace.session_id == "s0"
    assert refs[agent_level].namespace.user_id is None
    assert refs[agent_level].namespace.session_id is None
    later = _scope("u1", "s2")
    later_context = await recall_manager.prepare_context(_QUERY, scope=later)
    later_committed = recall_manager.commit_memory_exposure(later_context, scope=later)
    later_refs = {ref.memory_id: ref for ref in recall_manager._memory_exposures[later_committed.exposure_id].refs}
    assert refs == later_refs


async def test_backend_ignoring_unset_filters_cannot_widen_recall(recall_manager, store, backend) -> None:
    """A backend that treats an unset-only dimension as unconstrained must not leak another user's episode."""
    mine = await _failure(store, user_id="u1", session_id="s1")
    await _failure(store, user_id="u2", session_id="s9")
    count, get_recent = backend.count, backend.get_recent

    def _lenient(namespace_filter: dict) -> dict:
        return {field: value for field, value in namespace_filter.items() if value is not None}

    async def lenient_count(namespace_filter: dict) -> int:
        return await count(_lenient(namespace_filter))

    async def lenient_get_recent(namespace_filter: dict, limit: int = 10, since=None) -> list:
        return await get_recent(_lenient(namespace_filter), limit=limit, since=since)

    backend.count = lenient_count
    backend.get_recent = lenient_get_recent

    assert set(await _recalled(recall_manager, _scope("u1", "s2"))) == {mine}


async def test_one_failing_recall_scope_does_not_hide_the_other(recall_manager, store, monkeypatch) -> None:
    """The own-scope recall is still delivered when the agent-level one fails."""
    mine = await _failure(store, user_id="u1", session_id="s1")
    recall_similar = store.recall_similar

    async def flaky(*args, null_dimensions=(), **kwargs):
        if null_dimensions:
            raise RuntimeError("agent-level recall is unavailable")
        return await recall_similar(*args, null_dimensions=null_dimensions, **kwargs)

    monkeypatch.setattr(store, "recall_similar", flaky)

    assert set(await _recalled(recall_manager, _scope("u1", "s2"))) == {mine}


async def test_response_episode_is_still_recorded_under_the_full_request_namespace(recall_manager, backend) -> None:
    """Writes are unchanged: a response is persisted with the request's user and session."""
    scope = _scope("u1", "s1")
    receipt = await recall_manager.record_event(
        MemoryEvent(
            event_id="response-1",
            kind="response",
            scope=scope,
            observed_at=datetime(2026, 11, 16, tzinfo=timezone.utc),
            payload={"query": "What is the rollout plan?", "response": "Ship on Tuesday."},
        )
    )
    stored = await backend.get_recent({"tenant_id": "acme", "agent_id": "planner"}, limit=10)
    assert [episode.episode_id for episode in stored] == list(receipt.episode_ids)
    assert (stored[0].user_id, stored[0].session_id, stored[0].room_id) == ("u1", "s1", None)


def test_recall_scopes_follow_the_request_identity(recall_manager) -> None:
    """The recall filters are derived from the request, never from the manager's static namespace."""
    scope = _scope("u1", "s1")
    namespace = recall_manager._namespace_for_scope(scope)
    own, agent_level = recall_manager._recall_scopes(scope)
    assert own == (namespace.model_copy(update={"session_id": None}), ())
    assert agent_level == (
        namespace.model_copy(update={"user_id": None, "session_id": None}),
        ("user_id", "session_id"),
    )
    anonymous = _scope(None, "anon-1")
    assert recall_manager._recall_scopes(anonymous)[0] == (recall_manager._namespace_for_scope(anonymous), ("user_id",))


# ── Agent-facing tools follow the request's visibility (TASK-5708, issue:3b9765e02458) ──


@pytest.fixture
def toolkit(store: EpisodicMemoryStore) -> EpisodicMemoryToolkit:
    """The toolkit as ``AgentMemoryMixin`` registers it: namespace = (tenant, agent)."""
    return EpisodicMemoryToolkit(store=store, namespace=MemoryNamespace(tenant_id="acme", agent_id="planner"))


async def _private_failure(store: EpisodicMemoryStore, secret: str, **dimensions: str) -> None:
    await store.record_episode(
        namespace=MemoryNamespace(tenant_id="acme", agent_id="planner", **dimensions),
        situation=f"deploy rollout failed for {secret}",
        action_taken="ran the rollout",
        outcome=EpisodeOutcome.FAILURE,
        error_message=f"rollout timed out for {secret}",
        generate_reflection=False,
    )


async def test_search_tool_never_returns_another_users_episode(toolkit, store) -> None:
    """Inside a request the search tool reads the requester's episodes and the agent-level ones only."""
    await _private_failure(store, "alpha", user_id="u1", session_id="s1")
    await _private_failure(store, "bravo", user_id="u2", session_id="s9")
    await _private_failure(store, "charlie")
    await _private_failure(store, "delta", session_id="anon-1")

    token = bind_memory_scope(_scope("u1", "s2"))
    try:
        found = await toolkit.search_episodic_memory(_QUERY, top_k=10)
    finally:
        reset_memory_scope(token)
    assert "alpha" in found and "charlie" in found
    assert "bravo" not in found and "delta" not in found

    token = bind_memory_scope(_scope(None, "anon-1"))
    try:
        anonymous = await toolkit.search_episodic_memory(_QUERY, top_k=10)
    finally:
        reset_memory_scope(token)
    assert "delta" in anonymous and "charlie" in anonymous
    assert "alpha" not in anonymous and "bravo" not in anonymous


async def test_search_tool_respects_top_k_across_scopes(toolkit, store) -> None:
    """The merged result of the visibility scopes is cut to the requested size."""
    for index in range(3):
        await _private_failure(store, f"own-{index}", user_id="u1", session_id="s1")
        await _private_failure(store, f"shared-{index}")

    token = bind_memory_scope(_scope("u1", "s2"))
    try:
        found = await toolkit.search_episodic_memory(_QUERY, top_k=2)
    finally:
        reset_memory_scope(token)
    assert found.startswith("Found 2 relevant experiences")


async def test_warnings_tool_never_returns_another_users_failure(toolkit, store) -> None:
    """Inside a request the warnings tool reads the identified user's failures only."""
    await _private_failure(store, "alpha", user_id="u1", session_id="s1")
    await _private_failure(store, "bravo", user_id="u2", session_id="s9")

    token = bind_memory_scope(_scope("u1", "s2"))
    try:
        warnings = await toolkit.get_warnings(_QUERY)
    finally:
        reset_memory_scope(token)
    assert "alpha" in warnings and "bravo" not in warnings

    token = bind_memory_scope(_scope(None, "s9"))
    try:
        anonymous = await toolkit.get_warnings(_QUERY)
    finally:
        reset_memory_scope(token)
    assert anonymous == "No relevant warnings from past experiences."


async def test_tools_keep_the_configured_namespace_outside_a_request(toolkit, store) -> None:
    """With no request bound, the configured namespace is the caller's choice and is used as is."""
    await _private_failure(store, "bravo", user_id="u2", session_id="s9")

    assert "bravo" in await toolkit.search_episodic_memory(_QUERY, top_k=10)


async def test_configured_namespace_gates_the_request_not_its_visibility(store) -> None:
    """A request inside the configured namespace gets its whole visibility; one outside gets nothing."""
    await _private_failure(store, "alpha", user_id="u1", session_id="s1")
    await _private_failure(store, "charlie")
    bound = EpisodicMemoryToolkit(
        store=store, namespace=MemoryNamespace(tenant_id="acme", agent_id="planner", user_id="u1", session_id="s2")
    )

    token = bind_memory_scope(_scope("u1", "s2"))
    try:
        found = await bound.search_episodic_memory(_QUERY, top_k=10)
        warnings = await bound.get_warnings(_QUERY)
    finally:
        reset_memory_scope(token)
    assert "alpha" in found and "charlie" in found
    assert "alpha" in warnings

    token = bind_memory_scope(_scope("u2", "s2"))
    try:
        outside = await bound.search_episodic_memory(_QUERY, top_k=10)
        outside_warnings = await bound.get_warnings(_QUERY)
    finally:
        reset_memory_scope(token)
    assert outside == "No relevant past experiences found."
    assert outside_warnings == "No relevant warnings from past experiences."


async def test_search_tool_keeps_the_store_ranking_across_scopes(toolkit, store, monkeypatch) -> None:
    """The merged result is ordered by the store's ranking score, not by raw similarity."""
    recall_similar = store.recall_similar

    async def reranked(*args, null_dimensions=(), **kwargs):
        rows = await recall_similar(*args, null_dimensions=null_dimensions, **kwargs)
        boost = 0.5 if null_dimensions else 2.0
        return [row.model_copy(update={"ranking_score": boost}) for row in rows]

    monkeypatch.setattr(store, "recall_similar", reranked)
    await _private_failure(store, "charlie")
    await _private_failure(store, "alpha", user_id="u1", session_id="s1")

    token = bind_memory_scope(_scope("u1", "s2"))
    try:
        found = await toolkit.search_episodic_memory(_QUERY, top_k=1)
    finally:
        reset_memory_scope(token)
    assert "alpha" in found and "charlie" not in found
