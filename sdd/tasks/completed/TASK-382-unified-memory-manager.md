# TASK-382: Unified Memory Manager

**Feature**: long-term-memory
**Spec**: `sdd/specs/long-term-memory.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-380, TASK-381
**Assigned-to**: unassigned

---

## Context

This task implements the `UnifiedMemoryManager` (Module 3 from the spec) — the central coordinator that orchestrates parallel retrieval from episodic memory, skill registry, and conversation memory, then passes results through `ContextAssembler` for token-budgeted context assembly. It also handles post-response interaction recording.

---

## Scope

- Create `parrot/memory/unified/manager.py` with `UnifiedMemoryManager` class:
  - `__init__()` accepts optional `EpisodicMemoryStore`, `SkillRegistry`, `ConversationMemory`, namespace, and config
  - `async configure(**kwargs)` — initializes all subsystems
  - `async get_context_for_query(query, user_id, session_id)` — parallel retrieval via `asyncio.gather()`, returns `MemoryContext`
  - `async record_interaction(query, response, tool_calls, user_id, session_id)` — records to episodic and conversation
  - `async cleanup()` — cleanup all subsystems
  - Works gracefully when some subsystems are `None` (partial config)
- Write unit tests with mocked subsystems

**NOT in scope**: Mixin wiring (TASK-383), bot integration hooks (TASK-385), modifying existing stores

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/memory/unified/manager.py` | CREATE | UnifiedMemoryManager implementation |
| `tests/memory/unified/test_manager.py` | CREATE | Unit tests with mocked subsystems |

---

## Implementation Notes

### Pattern to Follow
```python
import asyncio
import logging
from typing import Any, List, Optional

from parrot.memory.abstract import ConversationMemory
from parrot.memory.episodic.store import EpisodicMemoryStore
from parrot.memory.episodic.models import MemoryNamespace
from parrot.memory.skills.store import SkillRegistry

from .context import ContextAssembler
from .models import MemoryConfig, MemoryContext

logger = logging.getLogger(__name__)


class UnifiedMemoryManager:
    """Coordinates episodic memory, skill registry, and conversation memory."""

    def __init__(
        self,
        namespace: MemoryNamespace,
        conversation_memory: Optional[ConversationMemory] = None,
        episodic_store: Optional[EpisodicMemoryStore] = None,
        skill_registry: Optional[SkillRegistry] = None,
        config: Optional[MemoryConfig] = None,
    ):
        self.namespace = namespace
        self.conversation = conversation_memory
        self.episodic = episodic_store
        self.skills = skill_registry
        self.config = config or MemoryConfig()
        self._assembler = ContextAssembler(self.config)
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
```

### Key Constraints
- All retrieval in `get_context_for_query()` must use `asyncio.gather()` for parallelism
- If a subsystem is `None`, skip it (return empty string for that section)
- `record_interaction()` should catch and log exceptions — never raise (it's called fire-and-forget)
- Use `self.logger` for all logging, not print
- Episodic retrieval uses `get_failure_warnings(query, namespace, max_warnings)`
- Skill retrieval uses `get_relevant_skills(query, max_skills)`
- Conversation retrieval uses `get_history(user_id, session_id)` then formats recent turns
- Default reflection LLM: `gemini-3.1-flash-lite` (from open questions)

### References in Codebase
- `parrot/memory/episodic/store.py` — `EpisodicMemoryStore` API
- `parrot/memory/skills/store.py` — `SkillRegistry` API
- `parrot/memory/abstract.py` — `ConversationMemory` ABC
- Brainstorm section 4.4 for `UnifiedMemoryManager` design

---

## Acceptance Criteria

- [ ] `UnifiedMemoryManager` retrieves context from all three subsystems in parallel
- [ ] Works with partial configuration (e.g., only episodic, no skills)
- [ ] `get_context_for_query()` returns `MemoryContext` within token budget
- [ ] `record_interaction()` is exception-safe (logs errors, never raises)
- [ ] `configure()` initializes all non-None subsystems
- [ ] `cleanup()` cleans up all non-None subsystems
- [ ] All tests pass: `pytest tests/memory/unified/test_manager.py -v`
- [ ] Import works: `from parrot.memory.unified.manager import UnifiedMemoryManager`

---

## Test Specification

```python
# tests/memory/unified/test_manager.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.memory.unified.manager import UnifiedMemoryManager
from parrot.memory.unified.models import MemoryConfig
from parrot.memory.episodic.models import MemoryNamespace


@pytest.fixture
def namespace():
    return MemoryNamespace(org_id="test", agent_id="test-agent", user_id="user1")


@pytest.fixture
def mock_episodic():
    store = AsyncMock()
    store.get_failure_warnings = AsyncMock(return_value="Warning: API rate limit hit")
    store.record_tool_episode = AsyncMock()
    store.configure = AsyncMock()
    store.cleanup = AsyncMock()
    return store


@pytest.fixture
def mock_skills():
    registry = AsyncMock()
    registry.get_relevant_skills = AsyncMock(return_value="Skill: use pagination for large queries")
    registry.configure = AsyncMock()
    registry.cleanup = AsyncMock()
    return registry


class TestUnifiedMemoryManager:
    @pytest.mark.asyncio
    async def test_parallel_retrieval(self, namespace, mock_episodic, mock_skills):
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
        mock_episodic.record_tool_episode.side_effect = Exception("Redis down")
        manager = UnifiedMemoryManager(
            namespace=namespace,
            episodic_store=mock_episodic,
        )
        # Should not raise
        await manager.record_interaction("query", MagicMock(), [], "user1", "session1")

    @pytest.mark.asyncio
    async def test_all_none_subsystems(self, namespace):
        manager = UnifiedMemoryManager(namespace=namespace)
        ctx = await manager.get_context_for_query("test", "user1", "s1")
        assert ctx.tokens_used == 0
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/long-term-memory.spec.md` for full context
2. **Check dependencies** — verify TASK-380 and TASK-381 are completed
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-382-unified-memory-manager.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-sonnet-4-6
**Date**: 2026-03-22
**Notes**: Implemented `UnifiedMemoryManager` with parallel asyncio.gather retrieval. Uses `SkillRegistry` Protocol for duck-typed skill registry. `configure`/`cleanup` use getattr for graceful subsystem compatibility. All 10 tests pass.

**Deviations from spec**: `MemoryNamespace` has `tenant_id` not `org_id` — tests updated accordingly. `SkillRegistry` defined as a Protocol since the skills module does not exist yet.
