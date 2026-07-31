"""Unit tests for the unified-layer brain retrieval integration (TASK-1988).

Covers MemoryConfig's conditional 4-weight validation, ContextAssembler's
fourth section, and UnifiedMemoryManager's brain-retrieval branch. Does
NOT modify or duplicate pre-existing unified tests — those keep passing
unmodified (verified as a baseline before implementing this task).
"""
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


class FakeBrain:
    def __init__(self, text: str = "", raise_error: bool = False):
        self._text = text
        self._raise_error = raise_error
        self.calls: list[str] = []

    async def search(self, query: str, **kw) -> str:
        self.calls.append(query)
        if self._raise_error:
            raise RuntimeError("brain store unavailable")
        return self._text


@pytest.fixture
def namespace() -> MemoryNamespace:
    return MemoryNamespace(agent_id="test-agent")


class TestManagerBrainRetrieval:
    async def test_brain_queried_in_parallel(self, namespace):
        brain = FakeBrain("distilled insight")
        manager = UnifiedMemoryManager(namespace=namespace, brain=brain)
        ctx = await manager.get_context_for_query("query", "u1", "s1")
        assert ctx.semantic_knowledge == "distilled insight"
        assert brain.calls == ["query"]

    async def test_brain_failure_degrades(self, namespace):
        brain = FakeBrain(raise_error=True)
        manager = UnifiedMemoryManager(namespace=namespace, brain=brain)
        ctx = await manager.get_context_for_query("query", "u1", "s1")
        assert ctx.semantic_knowledge == ""

    async def test_org_brain_merged(self, namespace):
        brain = FakeBrain("agent knowledge")
        org_brain = FakeBrain("org knowledge")
        manager = UnifiedMemoryManager(namespace=namespace, brain=brain, org_brain=org_brain)
        ctx = await manager.get_context_for_query("query", "u1", "s1")
        assert "agent knowledge" in ctx.semantic_knowledge
        assert "org knowledge" in ctx.semantic_knowledge

    async def test_no_brain_configured_noop(self, namespace):
        manager = UnifiedMemoryManager(namespace=namespace)
        ctx = await manager.get_context_for_query("query", "u1", "s1")
        assert ctx.semantic_knowledge == ""

    async def test_brain_in_subsystems_when_configured(self, namespace):
        brain = FakeBrain("x")
        manager = UnifiedMemoryManager(namespace=namespace, brain=brain)
        names = {name for name, _ in manager._subsystems()}
        assert "brain" in names

    async def test_brain_absent_from_subsystems_by_default(self, namespace):
        manager = UnifiedMemoryManager(namespace=namespace)
        names = {name for name, _ in manager._subsystems()}
        assert "brain" not in names
        assert "org_brain" not in names
