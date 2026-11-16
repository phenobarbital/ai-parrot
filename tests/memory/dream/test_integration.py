"""Offline dream-cycle and FEAT-892 service-boundary integration tests.

Runs fully offline: FAISS episodic backend (no embedding provider, so
clustering uses the category+tools fallback — no model downloads) + SQLite
brain wiki in tmpdir, heuristic distill (no LLM client, no API keys).
"""

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from parrot.memory.agent_memory import AgentMemoryMixin
from parrot.knowledge.wiki import SQLiteWikiStore
from parrot.memory.dream import BrainStore, DreamCycleRunner, DreamScheduler, DreamState
from parrot.memory.episodic.backends.faiss import FAISSBackend
from parrot.memory.episodic.models import (
    EpisodeOutcome,
    EpisodicMemory,
    MemoryNamespace,
)
from parrot.memory.episodic.store import EpisodicMemoryStore
from parrot.memory.unified import MemoryConfig, UnifiedMemoryManager


def _make_episode(**overrides: Any) -> EpisodicMemory:
    """Build a successful episode suitable for offline consolidation."""
    defaults = {
        "agent_id": "test-agent",
        "situation": "user asked about pgvector JSONB merges",
        "action_taken": "explained the || merge operator",
        "outcome": EpisodeOutcome.SUCCESS,
        "importance": 8,
        "lesson_learned": "Always use JSONB || for concurrent-safe metadata merges",
    }
    defaults.update(overrides)
    return EpisodicMemory(**defaults)


class TestEndToEnd:
    """Keep real consolidation, recovery, and SQLite interoperability coverage."""

    async def test_dream_end_to_end(self, tmp_path: Path) -> None:
        """Surface a real consolidated page through an injected search boundary."""
        backend = FAISSBackend(dimension=4)
        store = EpisodicMemoryStore(backend=backend)
        ep = _make_episode()
        await backend.store(ep)

        namespace = MemoryNamespace(agent_id="test-agent")
        brain = BrainStore(tmp_path / "brain", wiki_name="brain-test-agent")
        runner = DreamCycleRunner(store, brain, namespace)

        state_path = tmp_path / "dream_state.json"
        scheduler = DreamScheduler(runner, state_path, interval_hours=24)
        report = await scheduler.run_now()

        assert report.aborted is False
        assert len(report.pages_written) == 1

        # The page must be readable via the brain, AND directly via
        # SQLiteWikiStore (interop — same wiki.db format as LLMWikiToolkit).
        direct = SQLiteWikiStore(brain.storage_dir / "wiki.db", wiki_name="brain-test-agent")
        page = await direct.get_page(report.pages_written[0], include_body=True)
        assert page is not None
        assert "JSONB" in page["body"]

        # The concrete BrainService belongs to FEAT-889. Adapt the real store
        # only in this test to exercise the FEAT-892 manager boundary offline.
        async def search(query: str, tenant_id: str, max_tokens: int) -> str:
            """Bind the test service to this dream cycle's namespace."""
            assert tenant_id == namespace.tenant_id
            return await brain.search(query, max_tokens=max_tokens)

        service = MagicMock()
        service.search = AsyncMock(side_effect=search)
        manager = UnifiedMemoryManager(
            namespace=namespace, brain_service=service, config=MemoryConfig(enable_brain=True)
        )
        ctx = await manager.get_context_for_query("JSONB merges", "u1", "s1")
        assert "JSONB" in ctx.semantic_knowledge
        assert "brain_knowledge" in ctx.to_prompt_string()
        service.search.assert_awaited_once_with("JSONB merges", namespace.tenant_id, manager.config.max_context_tokens)

    async def test_dream_crash_recovery(self, tmp_path: Path) -> None:
        """Avoid duplicate consolidation after losing scheduler state."""
        backend = FAISSBackend(dimension=4)
        store = EpisodicMemoryStore(backend=backend)
        ep = _make_episode(agent_id="crash-agent")
        await backend.store(ep)

        namespace = MemoryNamespace(agent_id="crash-agent")
        brain = BrainStore(tmp_path / "brain", wiki_name="brain-crash-agent")
        runner = DreamCycleRunner(store, brain, namespace)

        state = DreamState(agent_id="crash-agent")
        report1 = await runner.run_cycle(state)
        assert len(report1.pages_written) == 1

        # Simulate a crash AFTER archive/mark but BEFORE the scheduler
        # persisted state to disk: rerun with a completely fresh (never
        # persisted) DreamState, as if reloaded after the process died.
        fresh_state = DreamState(agent_id="crash-agent")
        report2 = await runner.run_cycle(fresh_state)

        # The episode is already marked consolidated_into on the (durable)
        # episodic backend, independent of the lost DreamState watermark —
        # collect() filters it out, so no duplicate page / no re-mark.
        assert report2.episodes_collected == 0
        assert report2.pages_written == []

    async def test_brain_db_interop(self, tmp_path: Path) -> None:
        """Read BrainStore writes through the standard SQLite wiki store."""
        brain = BrainStore(tmp_path / "brain", wiki_name="brain-interop")
        result = await brain.remember("interop check", title="Interop", category="note")

        direct = SQLiteWikiStore(tmp_path / "brain" / "wiki.db", wiki_name="brain-interop")
        page = await direct.get_page(result["page_id"], include_body=True)
        assert page is not None
        assert page["body"] == "interop check"


class MemoryHost:
    """Provide the cooperative host lifecycle required by AgentMemoryMixin."""

    async def configure(self, app: Any = None) -> None:
        """Allow memory configuration without acquiring external host resources."""
        self.configure_skipped = False

    async def cleanup(self) -> None:
        """Observe completion of cooperative resource cleanup."""
        self.host_cleaned = True


class MockBrainAgent(AgentMemoryMixin, MemoryHost):
    """Minimal host using real memory storage and an injected brain service."""

    name = "mixin-agent"
    tenant_id = "test-tenant"
    enable_episodic_memory = True

    def __init__(self, storage_path: Path, enable_brain: bool = False) -> None:
        """Isolate persistence and keep brain capability independently configurable."""
        self.logger = MagicMock()
        self.enable_brain = enable_brain
        self.agent_memory_config = {"storage_path": str(storage_path)}


class TestMixinLifecycle:
    """Check service lifecycle ownership with the replacement memory facade."""

    async def test_brain_disabled_noop(self, tmp_path: Path) -> None:
        """Keep episodic memory usable without constructing a brain service."""
        agent = MockBrainAgent(tmp_path / "memory.sqlite3", enable_brain=False)
        try:
            await agent.configure()
            assert agent.brain_service is None
            assert agent._memory_manager is not None
            assert agent._memory_manager.brain_service is None
        finally:
            await agent.cleanup()
        assert agent._memory_manager is None
        assert agent.host_cleaned is True

    async def test_brain_lifecycle_start_stop(self, tmp_path: Path) -> None:
        """Start the injected service once and stop it before closing memory."""
        agent = MockBrainAgent(tmp_path / "memory.sqlite3", enable_brain=True)
        service = MagicMock(spec=["start", "stop", "search", "forget_derived"])
        service.start = AsyncMock()
        service.stop = AsyncMock()
        service.search = AsyncMock(return_value="distilled insight")
        service.forget_derived = AsyncMock(return_value=[])
        agent.brain_service = service
        try:
            await agent.configure()
            await agent.configure()
            service.start.assert_awaited_once_with()
            assert agent._memory_manager is not None
            assert agent._memory_manager.brain_service is service
            assert agent._memory_manager.episodic is not None
        finally:
            await agent.cleanup()
        await agent.cleanup()
        service.stop.assert_awaited_once_with()
        assert agent._memory_manager is None
        assert agent.host_cleaned is True
