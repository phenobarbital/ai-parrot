"""End-to-end and mixin-lifecycle integration tests for FEAT-390 (TASK-1989).

Runs fully offline: FAISS episodic backend (no embedding provider, so
clustering uses the category+tools fallback — no model downloads) + SQLite
brain wiki in tmpdir, heuristic distill (no LLM client, no API keys).
"""
import sys
from unittest.mock import MagicMock

# Worktree environment gotcha (see TASK-1985/1986/1987 completion notes):
# force a fresh re-import of the FAISS backend so a stale
# `_FAISS_AVAILABLE=False` cached during an earlier conftest.py import race
# doesn't poison this test module.
sys.modules.pop("parrot.memory.episodic.backends.faiss", None)

from parrot.knowledge.wiki import SQLiteWikiStore
from parrot.memory.dream import BrainStore, DreamCycleRunner, DreamScheduler, DreamState
from parrot.memory.episodic.backends.faiss import FAISSBackend
from parrot.memory.episodic.models import (
    EpisodeOutcome,
    EpisodicMemory,
    MemoryNamespace,
)
from parrot.memory.episodic.store import EpisodicMemoryStore
from parrot.memory.unified import UnifiedMemoryManager
from parrot.memory.unified.mixin import LongTermMemoryMixin


def _make_episode(**overrides) -> EpisodicMemory:
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
    async def test_dream_end_to_end(self, tmp_path):
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

        # Retrieval half: UnifiedMemoryManager surfaces it in semantic_knowledge.
        manager = UnifiedMemoryManager(namespace=namespace, brain=brain)
        ctx = await manager.get_context_for_query("JSONB merges", "u1", "s1")
        assert "JSONB" in ctx.semantic_knowledge
        assert "brain_knowledge" in ctx.to_prompt_string()

    async def test_dream_crash_recovery(self, tmp_path):
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

    async def test_brain_db_interop(self, tmp_path):
        brain = BrainStore(tmp_path / "brain", wiki_name="brain-interop")
        result = await brain.remember("interop check", title="Interop", category="note")

        direct = SQLiteWikiStore(tmp_path / "brain" / "wiki.db", wiki_name="brain-interop")
        page = await direct.get_page(result["page_id"], include_body=True)
        assert page is not None
        assert page["body"] == "interop check"


class MockBrainAgent(LongTermMemoryMixin):
    """Minimal test agent exercising the brain/dream wiring (TASK-1989)."""

    name = "mixin-agent"
    enable_long_term_memory = True
    episodic_backend = "faiss"
    episodic_faiss_path = None
    skill_inject_context = False
    skill_expose_tools = False

    def __init__(self, brain_storage_dir: str | None = None, enable_brain: bool = False):
        self._llm = None
        self.conversation_memory = None
        self.logger = MagicMock()
        self.enable_brain = enable_brain
        self.brain_storage_dir = brain_storage_dir


class TestMixinLifecycle:
    async def test_brain_disabled_noop(self):
        agent = MockBrainAgent(enable_brain=False)
        await agent._configure_long_term_memory()
        assert agent._dream_scheduler is None
        assert agent._memory_manager is not None
        await agent._cleanup_long_term_memory()

    async def test_brain_lifecycle_start_stop(self, tmp_path):
        agent = MockBrainAgent(
            brain_storage_dir=str(tmp_path / "brain"), enable_brain=True
        )
        await agent._configure_long_term_memory()
        assert agent._dream_scheduler is not None
        assert agent._memory_manager is not None

        await agent._cleanup_long_term_memory()
        assert agent._dream_scheduler is None
