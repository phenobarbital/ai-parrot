---
type: Wiki Overview
title: 'TASK-1205: Test Updates — PBAC Migration + ContextVar Isolation Tests'
id: doc:sdd-tasks-completed-task-1205-test-updates-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Existing PBAC tests call `bot.retrieval()` and must be migrated to
relates_to:
- concept: mod:parrot.utils.helpers
  rel: mentions
---

# TASK-1205: Test Updates — PBAC Migration + ContextVar Isolation Tests

**Feature**: FEAT-175 — Migrate RequestBot to ContextVar-based RequestContext
**Spec**: `sdd/specs/migrate-requestbot-contextvars.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1202, TASK-1203, TASK-1204
**Assigned-to**: sdd-worker

---

## Context

Existing PBAC tests call `bot.retrieval()` and must be migrated to
`bot.session()`. This task also creates new tests for ContextVar isolation,
fallback semantics, and concurrent task safety. This is the final task
that validates the entire migration.

Implements Spec §3 Module 5.

---

## Scope

- Update `tests/bots/test_abstractbot_policy.py` — replace all `bot.retrieval(...)` calls with `bot.session(...)`
- Update `tests/auth/test_policy_rules_integration.py` — replace all `bot.retrieval(...)` calls with `bot.session(...)`
- Create or extend `tests/bots/test_session_contextvar.py` with comprehensive ContextVar isolation tests
- Remove any `RequestBot` references from test files
- Verify all tests pass

**NOT in scope**: modifying production code (that's TASK-1201 through TASK-1204).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/bots/test_abstractbot_policy.py` | MODIFY | Replace retrieval() → session() (5 call sites) |
| `tests/auth/test_policy_rules_integration.py` | MODIFY | Replace retrieval() → session() (3 call sites) |
| `tests/bots/test_session_contextvar.py` | CREATE | New ContextVar isolation and fallback tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# After TASK-1201, these are available:
from parrot.utils.helpers import RequestContext, current_context, _current_ctx

# After TASK-1202, this is available:
# AbstractBot.session() context manager
```

### Existing Test Call Sites

```python
# tests/bots/test_abstractbot_policy.py
# Lines 166, 185, 202, 220, 230 — all follow this pattern:
async with bot.retrieval(request=request) as wrapper:
    # ...assertions on wrapper or access...

# tests/auth/test_policy_rules_integration.py
# Lines 137, 160, 361 — all follow this pattern:
async with bot.retrieval(request=request) as wrapper:
    # ...assertions...
```

### Migration Pattern

**Before:**
```python
async with bot.retrieval(request=request) as wrapper:
    # wrapper is a RequestBot proxy
    assert isinstance(wrapper, AbstractBot)  # True via virtual subclass
```

**After:**
```python
async with bot.session(request=request) as b:
    # b IS the real bot — isinstance check is naturally True
    assert isinstance(b, AbstractBot)
    assert b is bot  # same instance
```

### Does NOT Exist
- ~~`tests/bots/test_session_contextvar.py`~~ — does not exist yet; this task creates it
- ~~`RequestBot` in test imports~~ — verify; may not be imported directly

---

## Implementation Notes

### PBAC Test Migration

The PBAC tests verify that `retrieval()`/`session()` denies unauthorized
requests. The core assertion logic is the same — only the context manager
name changes. Watch for:

1. Variable name: tests may use `wrapper` — rename to `bot` or `b` for clarity
2. `isinstance` checks: if any test checks `isinstance(wrapper, RequestBot)`,
   change to `isinstance(b, AbstractBot)` — or just `assert b is bot`
3. Argument names: `retrieval(request=request)` → `session(request=request)` — same keyword

### New ContextVar Tests

Consolidate all tests from TASK-1201, TASK-1202, and TASK-1204 test specs
into `tests/bots/test_session_contextvar.py`. Categories:

1. **Infrastructure** — `current_context()` default, set, reset
2. **Session lifecycle** — yields real bot, sets/resets ContextVar, concurrent isolation
3. **Fallback semantics** — explicit ctx wins, ambient fallback, no-session returns None
4. **PBAC in session** — session denies unauthorized, allows authorized

### Key Constraints
- Tests must not leave ContextVar in a dirty state — always reset in `finally`
- Use `asyncio.gather()` to test concurrent isolation
- Mock PBAC evaluator for PBAC tests (follow existing patterns in test_abstractbot_policy.py)

---

## Acceptance Criteria

- [ ] All `bot.retrieval()` calls replaced with `bot.session()` in both test files
- [ ] No references to `RequestBot` remain in test files
- [ ] `tests/bots/test_session_contextvar.py` exists with comprehensive tests
- [ ] `pytest tests/bots/test_abstractbot_policy.py -v` passes
- [ ] `pytest tests/auth/test_policy_rules_integration.py -v` passes
- [ ] `pytest tests/bots/test_session_contextvar.py -v` passes
- [ ] `ruff check tests/bots/ tests/auth/` passes

---

## Test Specification

```python
# tests/bots/test_session_contextvar.py
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from parrot.utils.helpers import RequestContext, current_context, _current_ctx


class TestContextVarInfrastructure:
    """Tests for TASK-1201 — ContextVar basics."""

    def test_current_context_default_none(self):
        assert current_context() is None

    def test_set_and_get(self):
        ctx = RequestContext(user_id="test")
        token = _current_ctx.set(ctx)
        try:
            assert current_context() is ctx
        finally:
            _current_ctx.reset(token)

    def test_reset_clears(self):
        ctx = RequestContext()
        token = _current_ctx.set(ctx)
        _current_ctx.reset(token)
        assert current_context() is None


class TestSessionContextManager:
    """Tests for TASK-1202 — session() behavior."""

    @pytest.mark.asyncio
    async def test_yields_real_bot(self, configured_bot):
        async with configured_bot.session(request=MagicMock()) as b:
            assert b is configured_bot

    @pytest.mark.asyncio
    async def test_sets_contextvar(self, configured_bot):
        async with configured_bot.session(user_id="u1") as b:
            assert current_context() is not None
            assert current_context().user_id == "u1"

    @pytest.mark.asyncio
    async def test_resets_contextvar(self, configured_bot):
        async with configured_bot.session(user_id="u1") as b:
            pass
        assert current_context() is None

    @pytest.mark.asyncio
    async def test_concurrent_isolation(self, configured_bot):
        results = {}
        async def worker(uid):
            async with configured_bot.session(user_id=uid) as b:
                await asyncio.sleep(0.01)
                results[uid] = current_context().user_id
        await asyncio.gather(worker("alice"), worker("bob"))
        assert results["alice"] == "alice"
        assert results["bob"] == "bob"

    @pytest.mark.asyncio
    async def test_prebuilt_ctx(self, configured_bot):
        ctx = RequestContext(user_id="pre")
        async with configured_bot.session(ctx=ctx) as b:
            assert current_context() is ctx


class TestFallbackSemantics:
    """Tests for TASK-1204 — BaseBot fallback."""

    @pytest.mark.asyncio
    async def test_explicit_ctx_wins(self, configured_bot):
        ambient = RequestContext(user_id="ambient")
        explicit = RequestContext(user_id="explicit")
        token = _current_ctx.set(ambient)
        try:
            with patch.object(configured_bot, '_build_kb_context',
                            new_callable=AsyncMock, return_value=("", {})):
                await configured_bot.ask("test", ctx=explicit)
                ctx_passed = configured_bot._build_kb_context.call_args.kwargs['ctx']
                assert ctx_passed is explicit
        finally:
            _current_ctx.reset(token)

    @pytest.mark.asyncio
    async def test_ambient_fallback(self, configured_bot):
        ambient = RequestContext(user_id="ambient")
        token = _current_ctx.set(ambient)
        try:
            with patch.object(configured_bot, '_build_kb_context',
                            new_callable=AsyncMock, return_value=("", {})):
                await configured_bot.ask("test")
                ctx_passed = configured_bot._build_kb_context.call_args.kwargs['ctx']
                assert ctx_passed is ambient
        finally:
            _current_ctx.reset(token)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/migrate-requestbot-contextvars.spec.md`
2. **Check dependencies** — TASK-1202, TASK-1203, TASK-1204 must all be complete
3. **Read existing PBAC tests** to understand the assertion patterns before modifying
4. **Update PBAC tests** — mechanical replacement of retrieval() → session()
5. **Create new test file** — `tests/bots/test_session_contextvar.py`
6. **Run all tests**: `pytest tests/bots/test_abstractbot_policy.py tests/auth/test_policy_rules_integration.py tests/bots/test_session_contextvar.py -v`
7. **Commit** with message: `test(FEAT-175): migrate PBAC tests to session(), add ContextVar tests`

---

## Completion Note

Completed 2026-05-16 by sdd-worker (continuation worktree).

- `tests/bots/test_abstractbot_policy.py` — replaced all 5 `bot.retrieval()` calls with
  `bot.session()`, renamed class `TestRetrievalPBAC` → `TestSessionPBAC`, removed unused
  `AsyncMock` import, fixed unused `as b` variable in the deny assertion.
- `tests/auth/test_policy_rules_integration.py` — replaced all 3 `bot.retrieval()` calls
  with `bot.session()`, updated scenario docstrings and class name
  (`TestScenario1RetrievalEnforcement`), fixed unused `as b` variable.
- `tests/bots/test_session_contextvar.py` — created from scratch with 17 tests across
  three classes:
  - `TestContextVarInfrastructure` (5 tests): set/get/reset, nested tokens, copy_context
  - `TestSessionContextManager` (7 tests): yields real bot, sets/resets ContextVar,
    exception safety, concurrent isolation, pre-built ctx, request fail-open
  - `TestFallbackSemantics` (5 tests): explicit ctx wins, ambient fallback, no-ambient
    stays None, session sets ambient, no-session fallback yields None

All 38 tests pass. Ruff clean on all three files.
