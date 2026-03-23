# TASK-383: LongTermMemoryMixin

**Feature**: long-term-memory
**Spec**: `sdd/specs/long-term-memory.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-382
**Assigned-to**: unassigned

---

## Context

This task implements the `LongTermMemoryMixin` (Module 4 from the spec) — a single opt-in mixin that any `AbstractBot` subclass can use to gain long-term memory capabilities. It wires the `UnifiedMemoryManager` into the agent lifecycle: configuring subsystems at startup, injecting context before LLM calls, and recording interactions after responses.

---

## Scope

- Create `parrot/memory/unified/mixin.py` with `LongTermMemoryMixin` class:
  - Configuration attributes: `enable_long_term_memory`, `episodic_inject_warnings`, `skill_inject_context`, `skill_auto_extract`, `skill_expose_tools`, `memory_max_context_tokens`
  - `async _configure_long_term_memory()` — creates and configures `UnifiedMemoryManager` with appropriate subsystems based on agent config
  - `async get_memory_context(query, user_id, session_id)` — returns assembled context string for injection into system prompt
  - `async _post_response_memory_hook(query, response, user_id, session_id)` — fire-and-forget interaction recording
  - `_create_namespace()` — builds `MemoryNamespace` from agent attributes
  - Optionally registers skill tools with agent's tool manager when `skill_expose_tools=True`
- Write unit tests

**NOT in scope**: Modifying `AbstractBot.ask()` (TASK-385), modifying existing episodic/skills stores

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/memory/unified/mixin.py` | CREATE | LongTermMemoryMixin implementation |
| `tests/memory/unified/test_mixin.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow
```python
# Follow existing mixin pattern from parrot/memory/episodic/mixin.py
from typing import Optional
import logging

from parrot.memory.episodic.models import MemoryNamespace
from .manager import UnifiedMemoryManager
from .models import MemoryConfig

logger = logging.getLogger(__name__)


class LongTermMemoryMixin:
    """Single opt-in mixin for long-term memory in any bot/agent.

    Usage:
        class MyAgent(LongTermMemoryMixin, Agent):
            enable_long_term_memory = True
    """

    # Configuration flags
    enable_long_term_memory: bool = False
    episodic_inject_warnings: bool = True
    episodic_auto_record: bool = True
    episodic_max_warnings: int = 3
    skill_inject_context: bool = True
    skill_auto_extract: bool = False
    skill_expose_tools: bool = True
    skill_max_context: int = 3
    memory_max_context_tokens: int = 2000

    # Runtime
    _memory_manager: Optional[UnifiedMemoryManager] = None
```

### Key Constraints
- Mixin must appear **before** `AbstractBot` in MRO: `class MyAgent(LongTermMemoryMixin, Agent)`
- `_configure_long_term_memory()` is meant to be called from the agent's `configure()` method
- When `enable_long_term_memory = False`, all methods are no-ops
- `_post_response_memory_hook()` must never raise — wrap in try/except
- Use existing `EpisodicMemoryMixin` as pattern reference but do NOT inherit from it
- Default reflection LLM is `gemini-3.1-flash-lite`
- Create episodic store only if `episodic_inject_warnings` or `episodic_auto_record` is True
- Create skill registry only if `skill_inject_context` or `skill_expose_tools` is True

### References in Codebase
- `parrot/memory/episodic/mixin.py` — existing mixin pattern to follow
- `parrot/memory/episodic/store.py` — `EpisodicMemoryStore` creation
- `parrot/memory/skills/store.py` — `SkillRegistry` creation
- Brainstorm section 4.5 for `LongTermMemoryMixin` design

---

## Acceptance Criteria

- [ ] `LongTermMemoryMixin` provides `_configure_long_term_memory()` lifecycle method
- [ ] `get_memory_context()` returns formatted context string
- [ ] Returns empty string when `enable_long_term_memory = False`
- [ ] `_post_response_memory_hook()` never raises exceptions
- [ ] Creates only needed subsystems based on configuration flags
- [ ] All tests pass: `pytest tests/memory/unified/test_mixin.py -v`
- [ ] Import works: `from parrot.memory.unified.mixin import LongTermMemoryMixin`

---

## Test Specification

```python
# tests/memory/unified/test_mixin.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.memory.unified.mixin import LongTermMemoryMixin


class MockAgent(LongTermMemoryMixin):
    """Test agent with mixin."""
    name = "test-agent"
    enable_long_term_memory = True

    def __init__(self):
        self._llm = MagicMock()
        self.conversation_memory = None
        self.logger = MagicMock()


class TestLongTermMemoryMixin:
    @pytest.mark.asyncio
    async def test_disabled_is_noop(self):
        agent = MockAgent()
        agent.enable_long_term_memory = False
        await agent._configure_long_term_memory()
        assert agent._memory_manager is None

    @pytest.mark.asyncio
    async def test_configure_creates_manager(self):
        agent = MockAgent()
        with patch("parrot.memory.unified.mixin.UnifiedMemoryManager") as MockManager:
            MockManager.return_value.configure = AsyncMock()
            await agent._configure_long_term_memory()
            assert agent._memory_manager is not None

    @pytest.mark.asyncio
    async def test_get_memory_context_no_manager(self):
        agent = MockAgent()
        agent._memory_manager = None
        result = await agent.get_memory_context("query", "user1", "s1")
        assert result == ""

    @pytest.mark.asyncio
    async def test_post_response_hook_exception_safe(self):
        agent = MockAgent()
        agent._memory_manager = AsyncMock()
        agent._memory_manager.record_interaction = AsyncMock(side_effect=Exception("fail"))
        # Should not raise
        await agent._post_response_memory_hook("query", MagicMock(), "user1", "s1")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/long-term-memory.spec.md` for full context
2. **Check dependencies** — verify TASK-382 is completed
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-383-long-term-memory-mixin.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-sonnet-4-6
**Date**: 2026-03-23
**Notes**: Implemented `LongTermMemoryMixin` with all lifecycle methods. Subsystem factory helpers use lazy imports with try/except to handle missing modules gracefully. All 11 tests pass.

**Deviations from spec**: Minor — `test_create_namespace_fallback` uses `agent.name = ""` instead of `del agent.name` since `name` is a class attribute (not deletable from instance).
