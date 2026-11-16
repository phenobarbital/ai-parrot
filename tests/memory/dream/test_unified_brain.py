"""Unit tests for unified-layer brain retrieval through the FEAT-892 service boundary.

Covers MemoryConfig's conditional 4-weight validation, ContextAssembler's
fourth section, and UnifiedMemoryManager's concurrent brain-service retrieval.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from parrot.memory.episodic.models import MemoryNamespace
from parrot.memory.unified import ContextAssembler, MemoryConfig, UnifiedMemoryManager


class TestMemoryConfigBrain:
    def test_legacy_three_weight_validation_intact(self):
        cfg = MemoryConfig()
        assert cfg.enable_brain is False
        assert cfg.episodic_weight == 0.3
        assert cfg.skill_weight == 0.3
        assert cfg.conversation_weight == 0.4

        with pytest.raises(ValueError):
            MemoryConfig(episodic_weight=0.5, skill_weight=0.5, conversation_weight=0.5)

    def test_enable_brain_rebalanced_defaults(self):
        cfg = MemoryConfig(enable_brain=True)
        assert cfg.episodic_weight == 0.25
        assert cfg.skill_weight == 0.25
        assert cfg.conversation_weight == 0.30
        assert cfg.brain_weight == 0.20

    def test_enable_brain_custom_weights_must_sum_to_one(self):
        cfg = MemoryConfig(
            enable_brain=True,
            episodic_weight=0.25,
            skill_weight=0.25,
            conversation_weight=0.25,
            brain_weight=0.25,
        )
        assert cfg.brain_weight == 0.25

        with pytest.raises(ValueError):
            MemoryConfig(
                enable_brain=True,
                episodic_weight=0.5,
                skill_weight=0.5,
                conversation_weight=0.5,
                brain_weight=0.5,
            )


class TestAssemblerFourSections:
    def test_semantic_knowledge_budgeted(self):
        assembler = ContextAssembler(MemoryConfig(enable_brain=True, max_context_tokens=2000))
        ctx = assembler.assemble(
            episodic_warnings="",
            relevant_skills="",
            conversation="",
            semantic_knowledge="Always check X before Y",
        )
        assert ctx.semantic_knowledge == "Always check X before Y"
        assert ctx.tokens_used > 0
        assert "brain_knowledge" in ctx.to_prompt_string()

    def test_three_section_call_unchanged(self):
        assembler = ContextAssembler(MemoryConfig())
        ctx = assembler.assemble(
            episodic_warnings="warn",
            relevant_skills="skill",
            conversation="conv",
        )
        assert ctx.semantic_knowledge == ""
        assert "brain_knowledge" not in ctx.to_prompt_string()


class FakeBrainService:
    """Return service-owned knowledge and observe the tenant-bound search contract."""

    def __init__(self, text: str = "", raise_error: bool = False) -> None:
        """Configure the response or an unavailable-service failure."""
        self._text = text
        self._raise_error = raise_error
        self.calls: list[tuple[str, str, int]] = []

    async def search(self, query: str, tenant_id: str, max_tokens: int) -> str:
        """Record the full service call before returning or raising."""
        self.calls.append((query, tenant_id, max_tokens))
        if self._raise_error:
            raise RuntimeError("brain store unavailable")
        return self._text


@pytest.fixture
def namespace() -> MemoryNamespace:
    """Use a non-default tenant so lost scoping is observable."""
    return MemoryNamespace(agent_id="test-agent", tenant_id="test-tenant")


class TestManagerBrainRetrieval:
    """Exercise service retrieval without restoring the removed direct-store API."""

    async def test_brain_queried_in_parallel(self, namespace: MemoryNamespace) -> None:
        """Require skills and brain to start before either retrieval can finish."""
        brain_started = asyncio.Event()
        skills_started = asyncio.Event()

        async def search(query: str, tenant_id: str, max_tokens: int) -> str:
            """Wait for the other subsystem to prove concurrent scheduling."""
            brain_started.set()
            await skills_started.wait()
            return "distilled insight"

        async def get_skills(query: str, max_skills: int) -> str:
            """Wait for the brain search to start."""
            skills_started.set()
            await brain_started.wait()
            return "relevant skill"

        brain = MagicMock()
        brain.search = AsyncMock(side_effect=search)
        skills = MagicMock()
        skills.get_relevant_skills = AsyncMock(side_effect=get_skills)
        config = MemoryConfig(enable_brain=True, max_context_tokens=1200)
        manager = UnifiedMemoryManager(namespace=namespace, brain_service=brain, skill_registry=skills, config=config)
        async with asyncio.timeout(2):
            ctx = await manager.get_context_for_query("query", "u1", "s1")
        assert ctx.semantic_knowledge == "distilled insight"
        assert ctx.relevant_skills == "relevant skill"
        brain.search.assert_awaited_once_with("query", "test-tenant", 1200)

    async def test_brain_failure_degrades(self, namespace: MemoryNamespace, caplog: pytest.LogCaptureFixture) -> None:
        """Keep other context when the service fails and report the failure."""
        brain = FakeBrainService(raise_error=True)
        skills = MagicMock()
        skills.get_relevant_skills = AsyncMock(return_value="surviving skill")
        manager = UnifiedMemoryManager(namespace=namespace, brain_service=brain, skill_registry=skills)
        ctx = await manager.get_context_for_query("query", "u1", "s1")
        assert ctx.semantic_knowledge == ""
        assert ctx.relevant_skills == "surviving skill"
        assert "Brain retrieval failed" in caplog.text

    async def test_service_combined_knowledge_preserved(self, namespace: MemoryNamespace) -> None:
        """Preserve combined text; the service owns agent/org store composition."""
        brain = FakeBrainService("agent knowledge\n\norg knowledge")
        manager = UnifiedMemoryManager(namespace=namespace, brain_service=brain)
        ctx = await manager.get_context_for_query("query", "u1", "s1")
        assert ctx.semantic_knowledge == "agent knowledge\n\norg knowledge"
        assert brain.calls == [("query", "test-tenant", manager.config.max_context_tokens)]

    async def test_no_brain_configured_noop(self, namespace: MemoryNamespace) -> None:
        """Leave brain context empty without an injected service."""
        manager = UnifiedMemoryManager(namespace=namespace)
        ctx = await manager.get_context_for_query("query", "u1", "s1")
        assert ctx.semantic_knowledge == ""

    async def test_brain_lifecycle_owned_by_agent(self, namespace: MemoryNamespace) -> None:
        """Manager lifecycle must not configure or stop the agent-owned service."""
        brain = MagicMock()
        brain.configure = AsyncMock()
        brain.cleanup = AsyncMock()
        brain.start = AsyncMock()
        brain.stop = AsyncMock()
        manager = UnifiedMemoryManager(namespace=namespace, brain_service=brain)
        assert all(subsystem is not brain for _, subsystem in manager._subsystems())
        await manager.configure()
        await manager.cleanup()
        brain.configure.assert_not_awaited()
        brain.cleanup.assert_not_awaited()
        brain.start.assert_not_awaited()
        brain.stop.assert_not_awaited()

    async def test_brain_absent_from_subsystems_by_default(self, namespace: MemoryNamespace) -> None:
        """Default manager construction must not acquire a brain store."""
        manager = UnifiedMemoryManager(namespace=namespace)
        names = {name for name, _ in manager._subsystems()}
        assert "brain" not in names
        assert "org_brain" not in names
