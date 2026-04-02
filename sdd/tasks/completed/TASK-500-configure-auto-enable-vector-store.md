# TASK-500: Fix configure() to auto-enable vector store when config is present

**Feature**: chatbot-rag-api-integration
**Spec**: `sdd/specs/chatbot-rag-api-integration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> This is the **primary fix** for FEAT-072. When bots are loaded from YAML definitions
> or the database, `vector_store_config` is passed to `__init__` but `use_vectorstore`
> is not set to `True`. As a result, `configure()` skips `configure_store()` and
> `self.store` stays `None` — RAG is silently disabled.
>
> Implements spec Module 1 and Module 3.

---

## Scope

- In `AbstractBot.configure()`, add a guard **before** the existing `if self._use_vector:` check: if `self._vector_store` is a non-empty dict or list, set `self._use_vector = True`.
- In `AbstractBot._build_vector_context()`, add a `self.logger.debug()` message when returning early, stating the reason (`store is None` vs `use_vectors is False`).
- Write unit tests to verify both behaviors.

**NOT in scope**: Changing the registry/YAML parsing (that's TASK-501). Changing vector store query logic. Changing the HTTP handler.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | Add auto-detection in `configure()` (~line 959) and diagnostic logging in `_build_vector_context()` (~line 1985) |
| `packages/ai-parrot/tests/bots/test_vector_context_integration.py` | CREATE | Unit tests for auto-enable and diagnostic logging |

---

## Implementation Notes

### Pattern to Follow

In `configure()`, around line 959-967:

```python
# BEFORE the existing guard:
# Auto-enable vector store when config is present
if not self._use_vector and self._vector_store:
    self._use_vector = True
    self.logger.info(
        "Auto-enabled vector store from existing config"
    )

# Existing code:
if self._use_vector:
    try:
        self.configure_store()
    except Exception as e:
        ...
```

In `_build_vector_context()`, around line 1985:

```python
if not (use_vectors and self.store):
    if not self.store:
        self.logger.debug(
            "Vector context skipped: no vector store configured"
        )
    elif not use_vectors:
        self.logger.debug(
            "Vector context skipped: use_vectors=False"
        )
    return "", {}
```

### Key Constraints
- The auto-detection must run AFTER `define_store_config()` / `_apply_store_config()` so declarative configs are captured
- The auto-detection must run BEFORE the `if self._use_vector:` guard
- Logging must be at DEBUG level to avoid noise

### References in Codebase
- `packages/ai-parrot/src/parrot/bots/abstract.py:959-967` — configure() vector store section
- `packages/ai-parrot/src/parrot/bots/abstract.py:1971-2007` — _build_vector_context()
- `packages/ai-parrot/src/parrot/interfaces/vector.py:77-96` — configure_store()

---

## Acceptance Criteria

- [ ] A bot created with `vector_store_config={'vector_store': 'postgres', ...}` (no `use_vectorstore=True`) has `self.store` set after `configure()`
- [ ] A bot created with NO vector config does NOT attempt store configuration
- [ ] `_build_vector_context()` logs reason when returning early
- [ ] All existing tests pass
- [ ] No breaking changes

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/test_vector_context_integration.py
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


class TestConfigureAutoEnablesVectorStore:
    """Test that configure() auto-enables vector store when config is present."""

    @pytest.mark.asyncio
    async def test_auto_enable_with_vector_store_config(self):
        """Bot with vector_store_config but no use_vectorstore should auto-enable."""
        from parrot.bots.chatbot import Chatbot
        bot = Chatbot(
            name='test_bot',
            vector_store_config={
                'name': 'postgres',
                'table': 'test_table',
            }
        )
        assert bot._use_vector is False  # Before configure
        assert bot._vector_store is not None

        with patch.object(bot, 'configure_store'):
            await bot.configure()

        assert bot._use_vector is True

    @pytest.mark.asyncio
    async def test_no_auto_enable_without_config(self):
        """Bot without vector config should NOT auto-enable."""
        from parrot.bots.chatbot import Chatbot
        bot = Chatbot(name='test_bot')

        await bot.configure()
        assert bot._use_vector is False
        assert bot.store is None


class TestBuildVectorContextLogging:
    """Test diagnostic logging when vector context is skipped."""

    @pytest.mark.asyncio
    async def test_logs_when_store_is_none(self):
        """Should log debug message when store is None."""
        from parrot.bots.chatbot import Chatbot
        bot = Chatbot(name='test_bot')
        bot.store = None

        with patch.object(bot.logger, 'debug') as mock_debug:
            result = await bot._build_vector_context("test query")
            assert result == ("", {})
            mock_debug.assert_called()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/chatbot-rag-api-integration.spec.md` for full context
2. **Check dependencies** — none
3. **Update status** in `tasks/.index.json` → `"in-progress"`
4. **Implement** the two changes in `abstract.py` and write the tests
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-500-configure-auto-enable-vector-store.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-03-31
**Notes**: Added auto-enable guard in `configure()` and diagnostic logging in `_build_vector_context()`.
Created unit tests using importlib to load the worktree abstract.py directly (bypassing conftest stubs). All 8 tests pass.

**Deviations from spec**: Prior work had already partially implemented abstract.py changes in commit f5f4a70a. Test file was refined to use importlib-based loading for reliable worktree testing.
