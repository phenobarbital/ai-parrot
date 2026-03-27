"""Import smoke tests for the unified memory package."""


def test_unified_package_imports():
    from parrot.memory.unified import (
        ContextAssembler,
        LongTermMemoryMixin,
        MemoryConfig,
        MemoryContext,
        UnifiedMemoryManager,
    )
    assert UnifiedMemoryManager is not None
    assert ContextAssembler is not None
    assert LongTermMemoryMixin is not None
    assert MemoryContext is not None
    assert MemoryConfig is not None


def test_parent_package_imports():
    from parrot.memory import UnifiedMemoryManager, LongTermMemoryMixin
    assert UnifiedMemoryManager is not None
    assert LongTermMemoryMixin is not None


def test_existing_imports_not_broken():
    from parrot.memory import (
        ConversationMemory,
        ConversationHistory,
        ConversationTurn,
        InMemoryConversation,
        RedisConversation,
        EpisodicMemoryMixin,
        EpisodicMemoryStore,
    )
    assert ConversationMemory is not None
    assert ConversationHistory is not None
    assert ConversationTurn is not None
    assert InMemoryConversation is not None
    assert RedisConversation is not None
    assert EpisodicMemoryMixin is not None
    assert EpisodicMemoryStore is not None
