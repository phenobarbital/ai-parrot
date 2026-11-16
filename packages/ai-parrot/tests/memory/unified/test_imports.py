"""Public import tests for the AgentMemoryMixin hard cut."""

import importlib

import pytest


def test_unified_package_imports() -> None:
    """Keep unified store APIs public while removing the old facade export."""
    from parrot.memory.unified import ContextAssembler, MemoryConfig, MemoryContext, UnifiedMemoryManager

    assert all((ContextAssembler, MemoryConfig, MemoryContext, UnifiedMemoryManager))
    unified = importlib.import_module("parrot.memory.unified")
    assert not hasattr(unified, "LongTermMemoryMixin")


def test_top_level_memory_imports() -> None:
    """Re-export AgentMemoryMixin without changing AnswerMemory compatibility."""
    from parrot.memory import AgentMemory, AgentMemoryMixin, AnswerMemory, UnifiedMemoryManager
    from parrot.memory.agent_memory import AgentMemoryMixin as PackageAgentMemoryMixin

    assert AgentMemoryMixin is PackageAgentMemoryMixin
    assert AgentMemory is AnswerMemory
    assert UnifiedMemoryManager is not None


def test_episodic_package_imports() -> None:
    """Keep episodic stores and tools public while removing their old mixin."""
    from parrot.memory.episodic import EpisodicMemoryStore, EpisodicMemoryToolkit, MemoryNamespace

    assert all((EpisodicMemoryStore, EpisodicMemoryToolkit, MemoryNamespace))
    episodic = importlib.import_module("parrot.memory.episodic")
    assert not hasattr(episodic, "EpisodicMemoryMixin")


@pytest.mark.parametrize(
    "module_name",
    ("parrot.memory.episodic.mixin", "parrot.memory.unified.mixin"),
)
def test_old_mixin_modules_are_removed(module_name: str) -> None:
    """Fail legacy direct imports instead of providing compatibility shims."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module_name)
