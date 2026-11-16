from typing import TYPE_CHECKING

from .abstract import ConversationHistory, ConversationMemory, ConversationTurn
from .agent import AgentMemory, AnswerMemory
from .compaction import (
    CompactionCommit,
    CompactionResult,
    ContextBudget,
    Limit,
    OmissionStore,
    TokenCount,
    TokenCounter,
    ToolInvocation,
    ToolStatus,
    TurnState,
    TurnView,
    compact_history,
)
from .episodic import (
    EpisodicMemoryMixin,
    EpisodicMemoryStore,
    EpisodicMemoryToolkit,
)
from .file import FileConversationMemory
from .persistence import (
    CONVERSATION_DELETED_TOPIC,
    TURN_COMPLETED_TOPIC,
    BusTurnPublisher,
    TurnPresentation,
    TurnPublisher,
    turn_event_id,
)
from .mem import InMemoryConversation
from .redis import RedisConversation
from .hydration import (
    HydrationError,
    HydrationNotReadyError,
    HydrationSource,
    HydrationUnavailableError,
    LocalSequenceAllocator,
    RedisSequenceAllocator,
    SequenceAllocator,
    SessionDeletedError,
)
from .render import HistoryMessage, render_history
from .parts import MessagePart, render_parts_text
from .unified import (
    ContextAssembler,
    LongTermMemoryMixin,
    MemoryConfig,
    MemoryContext,
    UnifiedMemoryManager,
)

if TYPE_CHECKING:
    from .dream import (
        BrainStore,
        DistilledKnowledge,
        DreamConfig,
        DreamCycleReport,
        DreamCycleRunner,
        DreamScheduler,
        DreamState,
        load_state,
        save_state,
    )

# Dream-cycle (FEAT-390) re-exports are resolved lazily (PEP 562) so that
# `import parrot.memory` does NOT unconditionally pull in the wiki
# retrieval plane / aiosqlite for every consumer — only agents that
# actually touch the brain (`enable_brain=True`) trigger this import.
# Post-review fix: this block used to be a plain eager `from .dream import
# (...)`, which broke the "enable_brain=False is byte-identical to today"
# requirement at import time, not just at runtime.
_DREAM_EXPORTS: dict[str, str] = {
    name: "parrot.memory.dream"
    for name in (
        "BrainStore",
        "DistilledKnowledge",
        "DreamConfig",
        "DreamCycleReport",
        "DreamCycleRunner",
        "DreamScheduler",
        "DreamState",
        "load_state",
        "save_state",
    )
}


def __getattr__(name: str):
    """Resolve dream-cycle exports lazily; everything else is a plain module attr."""
    module_path = _DREAM_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    import importlib

    module = importlib.import_module(module_path)
    value = getattr(module, name)
    globals()[name] = value  # cache for subsequent lookups
    return value


def __dir__() -> list[str]:
    """Expose lazy dream exports to :func:`dir`."""
    return sorted(set(globals()) | set(_DREAM_EXPORTS))


__all__ = [
    "AgentMemory",
    "AnswerMemory",
    "BusTurnPublisher",
    "BrainStore",
    "CompactionCommit",
    "CompactionResult",
    "ContextAssembler",
    "ContextBudget",
    "ConversationHistory",
    "ConversationMemory",
    "ConversationTurn",
    "CONVERSATION_DELETED_TOPIC",
    "DistilledKnowledge",
    "DreamConfig",
    "DreamCycleReport",
    "DreamCycleRunner",
    "DreamScheduler",
    "DreamState",
    "EpisodicMemoryMixin",
    "EpisodicMemoryStore",
    "EpisodicMemoryToolkit",
    "FileConversationMemory",
    "HistoryMessage",
    "HydrationError",
    "HydrationNotReadyError",
    "HydrationSource",
    "HydrationUnavailableError",
    "LocalSequenceAllocator",
    "RedisSequenceAllocator",
    "SequenceAllocator",
    "SessionDeletedError",
    "InMemoryConversation",
    "Limit",
    "LongTermMemoryMixin",
    "MemoryConfig",
    "MemoryContext",
    "MessagePart",
    "OmissionStore",
    "RedisConversation",
    "TokenCount",
    "TokenCounter",
    "TURN_COMPLETED_TOPIC",
    "ToolInvocation",
    "ToolStatus",
    "TurnPresentation",
    "TurnPublisher",
    "TurnState",
    "TurnView",
    "UnifiedMemoryManager",
    "compact_history",
    "render_history",
    "render_parts_text",
    "turn_event_id",
    "load_state",
    "save_state",
]
