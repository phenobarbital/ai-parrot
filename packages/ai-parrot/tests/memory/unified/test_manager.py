"""Unit tests for UnifiedMemoryManager — mocked and isolated subsystems."""

import asyncio
from datetime import datetime, timezone

import pytest
from unittest.mock import AsyncMock, MagicMock, create_autospec

from parrot.memory.agent_memory.models import MemoryEvent, MemoryRequestScope
from parrot.memory.episodic.models import EpisodeCategory, EpisodeOutcome, MemoryNamespace
from parrot.memory.episodic.store import EpisodicMemoryStore
from parrot.memory.unified.manager import UnifiedMemoryManager
from parrot.memory.unified.models import MemoryConfig
from parrot.memory.user.models import UserKnowledgeCandidate, UserKnowledgeCommand
from parrot.memory.user.store import UserMemoryStore

@pytest.fixture
def namespace() -> MemoryNamespace:
    return MemoryNamespace(tenant_id="test", agent_id="test-agent", user_id="user1")


@pytest.fixture
def mock_episodic() -> MagicMock:
    """Autospecced store: a call with keywords the real store lacks raises TypeError instead of passing silently."""
    store = create_autospec(EpisodicMemoryStore, instance=True)
    store.get_failure_warnings.return_value = "Warning: API rate limit hit"
    store.configure = AsyncMock()
    store.cleanup = AsyncMock()
    return store


@pytest.fixture
def mock_skills() -> AsyncMock:
    registry = AsyncMock()
    registry.get_relevant_skills = AsyncMock(return_value="Skill: use pagination for large queries")
    registry.configure = AsyncMock()
    registry.cleanup = AsyncMock()
    return registry


@pytest.fixture
def mock_conversation() -> AsyncMock:
    memory = AsyncMock()
    history = MagicMock()
    history.turns = []
    memory.get_history = AsyncMock(return_value=history)
    memory.configure = AsyncMock()
    memory.cleanup = AsyncMock()
    return memory


class TestUnifiedMemoryManager:

    @staticmethod
    def _scope(
        *,
        tenant_id: str = "test",
        agent_id: str = "test-agent",
        user_id: str | None = "user1",
        turn_id: str = "turn-1",
    ) -> MemoryRequestScope:
        """Build a deterministic trusted request scope for scoped-path tests."""
        return MemoryRequestScope(
            tenant_id=tenant_id,
            agent_id=agent_id,
            user_id=user_id,
            session_id="session-1",
            turn_id=turn_id,
            identity_provenance="server_resolved",
        )

    @pytest.mark.asyncio
    async def test_parallel_retrieval(self, namespace, mock_episodic, mock_skills):
        """get_context_for_query retrieves from all subsystems."""
        manager = UnifiedMemoryManager(
            namespace=namespace,
            episodic_store=mock_episodic,
            skill_registry=mock_skills,
        )
        ctx = await manager.get_context_for_query("test query", "user1", "session1")
        assert "rate limit" in ctx.episodic_warnings
        assert "pagination" in ctx.relevant_skills

    @pytest.mark.asyncio
    async def test_partial_subsystems(self, namespace, mock_episodic):
        """Works with only episodic store; skills section is empty."""
        manager = UnifiedMemoryManager(
            namespace=namespace,
            episodic_store=mock_episodic,
            skill_registry=None,
        )
        ctx = await manager.get_context_for_query("test query", "user1", "session1")
        assert ctx.episodic_warnings != ""
        assert ctx.relevant_skills == ""

    @pytest.mark.asyncio
    async def test_record_interaction_safe(self, namespace, mock_episodic):
        """record_interaction does not raise when episodic raises."""
        mock_episodic.record_episode.side_effect = Exception("Redis down")
        manager = UnifiedMemoryManager(
            namespace=namespace,
            episodic_store=mock_episodic,
        )
        # Should not raise
        await manager.record_interaction("query", MagicMock(), [], "user1", "session1")

    @pytest.mark.asyncio
    async def test_record_interaction_calls_record_episode(self, namespace, mock_episodic):
        """record_interaction records ONE PARTIAL query episode via record_episode (FEAT-571 M0)."""
        manager = UnifiedMemoryManager(namespace=namespace, episodic_store=mock_episodic)
        await manager.record_interaction("what now?", "do this", [], "user1", "session1")
        mock_episodic.record_episode.assert_awaited_once()
        kwargs = mock_episodic.record_episode.await_args.kwargs
        assert kwargs["outcome"] == EpisodeOutcome.PARTIAL
        assert kwargs["category"] == EpisodeCategory.QUERY_RESOLUTION
        assert kwargs["situation"] == "what now?"
        assert "do this" in kwargs["action_taken"]
        assert kwargs["namespace"].user_id == "user1"
        assert kwargs["namespace"].session_id == "session1"
        mock_episodic.record_tool_episode.assert_not_called()

    @pytest.mark.asyncio
    async def test_all_none_subsystems(self, namespace):
        """All-None config returns empty MemoryContext."""
        manager = UnifiedMemoryManager(namespace=namespace)
        ctx = await manager.get_context_for_query("test", "user1", "s1")
        assert ctx.tokens_used == 0

    @pytest.mark.asyncio
    async def test_configure_calls_subsystems(self, namespace, mock_episodic, mock_skills):
        """configure() calls configure on each subsystem that has it."""
        manager = UnifiedMemoryManager(
            namespace=namespace,
            episodic_store=mock_episodic,
            skill_registry=mock_skills,
        )
        await manager.configure()
        mock_episodic.configure.assert_called_once()
        mock_skills.configure.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_calls_subsystems(self, namespace, mock_episodic, mock_skills):
        """cleanup() calls cleanup on each subsystem that has it."""
        manager = UnifiedMemoryManager(
            namespace=namespace,
            episodic_store=mock_episodic,
            skill_registry=mock_skills,
        )
        await manager.cleanup()
        mock_episodic.cleanup.assert_called_once()
        mock_skills.cleanup.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_within_token_budget(self, namespace, mock_episodic):
        """Assembled context respects token budget."""
        config = MemoryConfig(max_context_tokens=500)
        manager = UnifiedMemoryManager(
            namespace=namespace,
            episodic_store=mock_episodic,
            config=config,
        )
        ctx = await manager.get_context_for_query("query", "user1", "s1")
        assert ctx.tokens_used <= 500

    @pytest.mark.asyncio
    async def test_conversation_formatted_as_turns(self, namespace, mock_conversation):
        """Conversation turns are formatted as User/Assistant lines."""
        turn = MagicMock()
        turn.user_message = "hello"
        turn.assistant_response = "hi there"
        mock_conversation.get_history.return_value = MagicMock(turns=[turn])

        manager = UnifiedMemoryManager(
            namespace=namespace,
            conversation_memory=mock_conversation,
        )
        ctx = await manager.get_context_for_query("q", "user1", "s1")
        assert "User: hello" in ctx.conversation_summary
        assert "Assistant: hi there" in ctx.conversation_summary

    @pytest.mark.asyncio
    async def test_episodic_retrieval_error_returns_empty(self, namespace, mock_episodic):
        """When episodic retrieval raises, section is empty (not an exception)."""
        mock_episodic.get_failure_warnings.side_effect = Exception("timeout")
        manager = UnifiedMemoryManager(
            namespace=namespace,
            episodic_store=mock_episodic,
        )
        ctx = await manager.get_context_for_query("q", "user1", "s1")
        assert ctx.episodic_warnings == ""

    @pytest.mark.asyncio
    async def test_independent_capabilities_and_scoped_context(self, namespace, tmp_path):
        """User-only requests use their trusted scope without mutating manager state."""
        store = UserMemoryStore(tmp_path / "user-memory.sqlite3")
        scope_a = self._scope(user_id="user-a", turn_id="turn-a")
        scope_b = self._scope(user_id="user-b", turn_id="turn-b")
        for scope, value in ((scope_a, "vegetarian"), (scope_b, "allergic to peanuts")):
            candidate = UserKnowledgeCandidate(
                kind="preference",
                value=value,
                provenance="explicit",
                evidence_refs=(f"event:{scope.turn_id}",),
            )
            await store.upsert(
                UserKnowledgeCommand(event_id=f"seed-{scope.turn_id}", candidate=candidate),
                scope=scope,
            )

        manager = UnifiedMemoryManager(
            namespace=namespace,
            user_memory_store=store,
            config=MemoryConfig(
                enable_episodic=False,
                enable_skills=False,
                enable_conversation=False,
                enable_user_memory=True,
            ),
        )
        context_a, context_b = await asyncio.gather(
            manager.prepare_context("vegetarian", scope=scope_a),
            manager.prepare_context("allergic", scope=scope_b),
        )

        assert "vegetarian" in context_a.user_knowledge
        assert "peanuts" not in context_a.user_knowledge
        assert "peanuts" in context_b.user_knowledge
        assert "vegetarian" not in context_b.user_knowledge
        assert manager.namespace is namespace
        assert manager.namespace.user_id == "user1"
        await store.close()

    @pytest.mark.asyncio
    async def test_single_partial_response_event(self, namespace, mock_episodic):
        """One unverified response creates one PARTIAL episode and never replays tool work."""
        mock_episodic.record_episode.return_value = MagicMock(episode_id="episode-1")
        manager = UnifiedMemoryManager(namespace=namespace, episodic_store=mock_episodic)
        event = MemoryEvent(
            event_id="response-1",
            kind="response",
            scope=self._scope(),
            observed_at=datetime(2026, 11, 15, tzinfo=timezone.utc),
            payload={"query": "Plan dinner", "response": "Try pasta"},
        )

        receipt = await manager.record_event(event)

        assert receipt.status == "applied"
        assert receipt.episode_ids == ("episode-1",)
        kwargs = mock_episodic.record_episode.await_args.kwargs
        assert kwargs["outcome"] == EpisodeOutcome.PARTIAL
        assert kwargs["category"] == EpisodeCategory.QUERY_RESOLUTION
        mock_episodic.record_tool_episode.assert_not_called()
        mock_episodic.review.assert_not_called()

    @pytest.mark.asyncio
    async def test_brain_service_tenant_and_no_history_duplication(self, namespace, mock_conversation):
        """Scoped brain recall binds the request tenant and never reloads conversation history."""
        brain_service = MagicMock()
        brain_service.search = AsyncMock(return_value="Tenant-specific knowledge")
        manager = UnifiedMemoryManager(
            namespace=namespace,
            conversation_memory=mock_conversation,
            brain_service=brain_service,
            config=MemoryConfig(
                enable_episodic=False,
                enable_skills=False,
                enable_conversation=False,
                enable_brain=True,
            ),
        )
        scope = self._scope(tenant_id="tenant-a")

        context = await manager.prepare_context("where are we?", scope=scope)

        assert context.semantic_knowledge == "Tenant-specific knowledge"
        assert context.conversation_summary == ""
        assert not any(ref.startswith("brain_text:") for ref in context.delivered_refs)
        brain_service.search.assert_awaited_once_with("where are we?", "tenant-a", 2000)
        mock_conversation.get_history.assert_not_awaited()

    def test_import(self):
        """Import path works as specified."""
        from parrot.memory.unified.manager import UnifiedMemoryManager as UMM  # noqa: F401

        assert UMM is UnifiedMemoryManager


# ---------------------------------------------------------------------------
# Feature-level review fixes (FEAT-892)
# ---------------------------------------------------------------------------


def _review_scope(*, turn_id: str = "turn-1", user_id: str | None = "user1") -> MemoryRequestScope:
    """Build a runtime-derived scope for the review-fix tests."""
    return MemoryRequestScope(
        tenant_id="test",
        agent_id="test-agent",
        user_id=user_id,
        session_id="session-1",
        turn_id=turn_id,
        identity_provenance="runtime_derived",
    )


def _response_event(scope: MemoryRequestScope, *, event_id: str = "event-1") -> MemoryEvent:
    """Build one completed-response event."""
    return MemoryEvent(
        event_id=event_id,
        kind="response",
        scope=scope,
        observed_at=datetime.now(timezone.utc),
        payload={"query": "How do I deploy?", "response": "Run the pipeline.", "user_message": "I prefer dark mode"},
    )


@pytest.mark.asyncio
async def test_cleanup_releases_every_subsystem_and_reports_the_first_failure(namespace: MemoryNamespace) -> None:
    """One failing subsystem must not leave the others open; its error still propagates."""
    failing = AsyncMock()
    failing.cleanup = AsyncMock(side_effect=RuntimeError("episodic close failed"))
    later = AsyncMock()
    later.cleanup = AsyncMock()
    manager = UnifiedMemoryManager(namespace, episodic_store=failing, skill_registry=later)

    with pytest.raises(RuntimeError, match="episodic close failed"):
        await manager.cleanup()

    later.cleanup.assert_awaited_once()


@pytest.mark.asyncio
async def test_retried_response_event_writes_one_episode(tmp_path, namespace: MemoryNamespace) -> None:
    """The same response event recorded twice (a retried turn) yields a single episode on a real SQLite store."""
    from parrot.memory.episodic.backends.sqlite import SQLiteEpisodeBackend

    backend = SQLiteEpisodeBackend(tmp_path / "episodes.sqlite")
    await backend.configure()
    try:
        store = EpisodicMemoryStore(backend, default_ttl_days=0)
        manager = UnifiedMemoryManager(namespace, episodic_store=store, config=MemoryConfig(enable_episodic=True))
        scope = _review_scope()
        event = _response_event(scope)

        first = await manager.record_event(event)
        second = await manager.record_event(event)

        assert first.episode_ids == second.episode_ids
        assert await backend.count(manager._namespace_for_scope(scope).build_filter()) == 1
        other = await manager.record_event(_response_event(scope, event_id="event-2"))
        assert other.episode_ids != first.episode_ids
        assert await backend.count(manager._namespace_for_scope(scope).build_filter()) == 2
    finally:
        await backend.close()


class _EnteredClient:
    """LLM client double that, like a real AbstractClient, must be entered before ask()."""

    def __init__(self) -> None:
        self.entered = False
        self.asked_while_entered: list[bool] = []

    async def __aenter__(self) -> "_EnteredClient":
        self.entered = True
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        self.entered = False

    async def ask(self, *_args: object, **_kwargs: object) -> str:
        self.asked_while_entered.append(self.entered)
        return "[]"


@pytest.mark.asyncio
async def test_user_extraction_enters_the_client_context(tmp_path, namespace: MemoryNamespace) -> None:
    """Extraction goes through the client's async context, as every bot call does."""
    user_store = UserMemoryStore(tmp_path / "user.sqlite")
    client = _EnteredClient()
    manager = UnifiedMemoryManager(
        namespace,
        user_memory_store=user_store,
        extraction_client=client,
        config=MemoryConfig(enable_user_memory=True, enable_episodic=False),
    )
    try:
        await manager.record_event(_response_event(_review_scope()))
    finally:
        await user_store.close()

    assert client.asked_while_entered == [True]
    assert client.entered is False
