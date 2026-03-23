# TASK-385: Bot Integration Hooks for Long-Term Memory

**Feature**: long-term-memory
**Spec**: `sdd/specs/long-term-memory.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-383, TASK-384
**Assigned-to**: unassigned

---

## Context

This task implements the integration hooks in `AbstractBot` / bot base classes (Module 6 from the spec) that wire the `LongTermMemoryMixin` into the actual agent lifecycle. These are minimal, additive, backward-compatible changes that allow agents using the mixin to automatically inject memory context and record interactions.

---

## Scope

- Modify `AbstractBot.create_system_prompt()` (or equivalent) to accept an optional `memory_context: str = None` parameter and include it in the assembled prompt
- Add a post-response hook point in `AbstractBot.ask()` (or equivalent) that calls `_post_response_memory_hook()` if the agent has a `_memory_manager`
- Add a pre-LLM hook point in `ask()` that calls `get_memory_context()` if the agent has a `_memory_manager`
- All changes are additive with default `None` / no-op — existing agents unchanged
- Write integration tests with a mock agent using the mixin

**NOT in scope**: Modifying `EpisodicMemoryStore`, `SkillRegistry`, or `ConversationMemory` internals

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/bots/` (relevant base class) | MODIFY | Add memory_context parameter and hooks |
| `tests/memory/unified/test_bot_integration.py` | CREATE | Integration tests |

---

## Implementation Notes

### Research Required First
Before implementing, read these files to find the exact integration points:
- `parrot/bots/base.py` or `parrot/bots/bot.py` — find `create_system_prompt()` and `ask()` methods
- `parrot/bots/agent.py` — agent loop, tool execution

### Pattern to Follow
```python
# Additive change to create_system_prompt — add parameter, inject if present
async def create_system_prompt(
    self,
    conversation_context: str = "",
    user_context: str = "",
    kb_context: str = "",
    memory_context: str = None,  # NEW — optional
    **kwargs
) -> str:
    base_prompt = self._build_base_system_prompt(**kwargs)

    # Inject memory context if provided
    if memory_context:
        base_prompt += f"\n\n{memory_context}"

    return base_prompt

# Additive change to ask — add pre/post hooks
async def ask(self, question: str, user_id: str = "anonymous", session_id: str = None, **kwargs):
    session_id = session_id or str(uuid.uuid4())

    # Pre-LLM: get memory context if available
    memory_context = None
    if hasattr(self, 'get_memory_context') and hasattr(self, '_memory_manager') and self._memory_manager:
        memory_context = await self.get_memory_context(question, user_id, session_id)

    # ... existing logic with memory_context passed to create_system_prompt ...

    # Post-response: record interaction (fire-and-forget)
    if hasattr(self, '_post_response_memory_hook') and hasattr(self, '_memory_manager') and self._memory_manager:
        import asyncio
        asyncio.create_task(self._post_response_memory_hook(question, response, user_id, session_id))

    return response
```

### Key Constraints
- **Backward compatible**: All changes must use `hasattr()` checks or default `None` — existing agents MUST work without changes
- Changes are minimal — don't restructure `ask()` or `create_system_prompt()`
- Use `asyncio.create_task()` for post-response hooks (non-blocking)
- Wrap `create_task()` callback in try/except to prevent silent failures
- Do NOT modify `AbstractBot.__init__()` — the mixin handles its own state

### References in Codebase
- `parrot/bots/` — find the actual class hierarchy
- `parrot/memory/episodic/mixin.py` — how existing mixin integrates
- Brainstorm sections 5.1 and 5.2 for the modified agent loop design

---

## Acceptance Criteria

- [ ] `create_system_prompt()` accepts `memory_context` parameter
- [ ] Memory context is injected into system prompt when provided
- [ ] Pre-LLM hook retrieves memory context if mixin is active
- [ ] Post-response hook fires asynchronously for interaction recording
- [ ] Existing agents without the mixin work unchanged (backward compatible)
- [ ] All tests pass: `pytest tests/memory/unified/test_bot_integration.py -v`
- [ ] No breaking changes to existing bot/agent public API

---

## Test Specification

```python
# tests/memory/unified/test_bot_integration.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestBotIntegrationHooks:
    @pytest.mark.asyncio
    async def test_system_prompt_without_memory_context(self):
        """Existing behavior unchanged when no memory context."""
        # Test that create_system_prompt works with memory_context=None
        ...

    @pytest.mark.asyncio
    async def test_system_prompt_with_memory_context(self):
        """Memory context injected into system prompt."""
        ...

    @pytest.mark.asyncio
    async def test_agent_without_mixin_unchanged(self):
        """Agent without LongTermMemoryMixin works as before."""
        ...

    @pytest.mark.asyncio
    async def test_post_response_hook_fires(self):
        """Post-response hook is called after ask()."""
        ...

    @pytest.mark.asyncio
    async def test_post_response_hook_exception_safe(self):
        """Post-response hook failure doesn't break ask()."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/long-term-memory.spec.md` for full context
2. **Check dependencies** — verify TASK-383 and TASK-384 are completed
3. **Research the bot class hierarchy** — read `parrot/bots/` to find exact integration points
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope and notes above — keep changes minimal
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-385-bot-integration-hooks.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-sonnet-4-6
**Date**: 2026-03-23
**Notes**: Added `memory_context` param to `create_system_prompt()` in `abstract.py` (both prompt-builder and legacy paths). Added pre-LLM and post-response hooks in `ask()` in `base.py` using `hasattr()` guards — fully backward compatible. Post-response uses `asyncio.create_task()` with a closure for exception safety. Full suite: 57/57 pass.

**Deviations from spec**: none
