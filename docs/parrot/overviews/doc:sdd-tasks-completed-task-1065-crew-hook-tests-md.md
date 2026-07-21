---
type: Wiki Overview
title: 'TASK-1065: Tests for AgentCrew lifecycle hooks'
id: doc:sdd-tasks-completed-task-1065-crew-hook-tests-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task implements Module 3 from the spec (§3) — comprehensive unit tests
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows.core.result
  rel: mentions
- concept: mod:parrot.bots.flows.crew
  rel: mentions
- concept: mod:parrot.models.crew
  rel: mentions
---

# TASK-1065: Tests for AgentCrew lifecycle hooks

**Feature**: FEAT-157 — AgentCrew Lifecycle Hooks
**Spec**: `sdd/specs/agentcrew-hooks.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1064
**Assigned-to**: unassigned

---

## Context

This task implements Module 3 from the spec (§3) — comprehensive unit tests
for the hook registration, dispatch, and error-handling logic added in TASK-1064.
Tests verify all status-based dispatch rules and ensure hooks work across all
four execution modes.

---

## Scope

- Create `tests/test_crew_hooks.py` with unit tests for:
  - Hook registration (`on_complete`, `on_error`)
  - Status-based dispatch (`completed`, `partial`, `failed`)
  - Sync and async callback support
  - Error isolation (hook exceptions don't block return)
  - Multiple hooks firing in order
  - `_fire_hooks()` direct invocation tests
- Verify hooks fire correctly with a mock AgentCrew

**NOT in scope**: Full integration tests with real LLM agents (too slow and
requires API keys). Focus on unit-level testing with mock agents and direct
`_fire_hooks()` calls.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/test_crew_hooks.py` | CREATE | Unit tests for crew lifecycle hooks |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# From the project:
from parrot.bots.orchestration.crew import AgentCrew  # verified: crew.py:63-68 (__all__)
from parrot.models.crew import CrewResult  # verified: models/crew.py:60

# Test infrastructure:
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/orchestration/crew.py
class AgentCrew(PersistenceMixin, SynthesisMixin):  # line 148
    def __init__(self, name: str = "AgentCrew", ...):  # line 187
        self._on_complete_hooks: List[CrewHookCallback] = []  # ADDED by TASK-1064
        self._on_error_hooks: List[CrewHookCallback] = []     # ADDED by TASK-1064

    def on_complete(self, callback: CrewHookCallback) -> None:  # ADDED by TASK-1064
    def on_error(self, callback: CrewHookCallback) -> None:     # ADDED by TASK-1064
    async def _fire_hooks(self, result: CrewResult) -> None:    # ADDED by TASK-1064

# packages/ai-parrot/src/parrot/models/crew.py
@dataclass
class CrewResult:  # line 60
    output: Any                                             # line 80
    status: Literal['completed', 'partial', 'failed'] = 'completed'  # line 88
    errors: Dict[str, str] = field(default_factory=dict)    # line 95
```

### Does NOT Exist

- ~~`AgentCrew.hooks`~~ — no generic hooks attribute
- ~~`AgentCrew.remove_hook()`~~ — no unregistration method
- ~~`CrewResult.on_complete`~~ — CrewResult has no hook methods

---

## Implementation Notes

### Test Structure

```python
import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock
from parrot.bots.orchestration.crew import AgentCrew
from parrot.models.crew import CrewResult


@pytest.fixture
def crew():
    """Minimal AgentCrew for hook testing."""
    return AgentCrew(name="test-crew")


@pytest.fixture
def completed_result():
    return CrewResult(output="done", status="completed")


@pytest.fixture
def failed_result():
    return CrewResult(output=None, status="failed", errors={"agent1": "boom"})


@pytest.fixture
def partial_result():
    return CrewResult(output="partial output", status="partial", errors={"agent2": "failed"})


class TestHookRegistration:
    def test_on_complete_registration(self, crew):
        hook = MagicMock()
        crew.on_complete(hook)
        assert hook in crew._on_complete_hooks

    def test_on_error_registration(self, crew):
        hook = MagicMock()
        crew.on_error(hook)
        assert hook in crew._on_error_hooks

    def test_multiple_hooks_registered(self, crew):
        h1, h2, h3 = MagicMock(), MagicMock(), MagicMock()
        crew.on_complete(h1)
        crew.on_complete(h2)
        crew.on_complete(h3)
        assert crew._on_complete_hooks == [h1, h2, h3]


class TestFireHooksDispatch:
    @pytest.mark.asyncio
    async def test_completed_fires_on_complete_only(self, crew, completed_result):
        on_complete = MagicMock()
        on_error = MagicMock()
        crew.on_complete(on_complete)
        crew.on_error(on_error)
        await crew._fire_hooks(completed_result)
        on_complete.assert_called_once_with("test-crew", completed_result)
        on_error.assert_not_called()

    @pytest.mark.asyncio
    async def test_failed_fires_on_error_only(self, crew, failed_result):
        on_complete = MagicMock()
        on_error = MagicMock()
        crew.on_complete(on_complete)
        crew.on_error(on_error)
        await crew._fire_hooks(failed_result)
        on_complete.assert_not_called()
        on_error.assert_called_once_with("test-crew", failed_result)

    @pytest.mark.asyncio
    async def test_partial_fires_both(self, crew, partial_result):
        on_complete = MagicMock()
        on_error = MagicMock()
        crew.on_complete(on_complete)
        crew.on_error(on_error)
        await crew._fire_hooks(partial_result)
        on_complete.assert_called_once_with("test-crew", partial_result)
        on_error.assert_called_once_with("test-crew", partial_result)


class TestHookCallbackTypes:
    @pytest.mark.asyncio
    async def test_sync_hook(self, crew, completed_result):
        called_with = {}
        def sync_hook(name, result):
            called_with['name'] = name
            called_with['result'] = result
        crew.on_complete(sync_hook)
        await crew._fire_hooks(completed_result)
        assert called_with['name'] == "test-crew"
        assert called_with['result'] is completed_result

    @pytest.mark.asyncio
    async def test_async_hook(self, crew, completed_result):
        called_with = {}
        async def async_hook(name, result):
            called_with['name'] = name
            called_with['result'] = result
        crew.on_complete(async_hook)
        await crew._fire_hooks(completed_result)
        assert called_with['name'] == "test-crew"
        assert called_with['result'] is completed_result


class TestHookErrorIsolation:
    @pytest.mark.asyncio
    async def test_exception_does_not_block(self, crew, completed_result):
        calls = []
        def bad_hook(name, result):
            raise RuntimeError("hook exploded")
        def good_hook(name, result):
            calls.append("good")
        crew.on_complete(bad_hook)
        crew.on_complete(good_hook)
        await crew._fire_hooks(completed_result)
        assert calls == ["good"]

    @pytest.mark.asyncio
    async def test_async_exception_does_not_block(self, crew, completed_result):
        calls = []
        async def bad_hook(name, result):
            raise RuntimeError("async hook exploded")
        async def good_hook(name, result):
            calls.append("good")
        crew.on_complete(bad_hook)
        crew.on_complete(good_hook)
        await crew._fire_hooks(completed_result)
        assert calls == ["good"]


class TestHookOrdering:
    @pytest.mark.asyncio
    async def test_hooks_fire_in_registration_order(self, crew, completed_result):
        order = []
        crew.on_complete(lambda n, r: order.append("first"))
        crew.on_complete(lambda n, r: order.append("second"))
        crew.on_complete(lambda n, r: order.append("third"))
        await crew._fire_hooks(completed_result)
        assert order == ["first", "second", "third"]

    @pytest.mark.asyncio
    async def test_no_hooks_is_noop(self, crew, completed_result):
        # Should not raise
        await crew._fire_hooks(completed_result)
```

### Key Constraints

- Tests should be fast — no real LLM calls
- Use `pytest.mark.asyncio` for all async tests
- Use `MagicMock()` for sync hooks, verify with `assert_called_once_with`
- For error isolation tests, ensure the second hook still fires after the first raises

---

## Acceptance Criteria

- [ ] `tests/test_crew_hooks.py` created
- [ ] All tests pass: `pytest tests/test_crew_hooks.py -v`
- [ ] Tests cover: registration, dispatch by status (completed/partial/failed), sync/async support, error isolation, ordering, no-hooks noop
- [ ] No test depends on external services or API keys

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/agentcrew-hooks.spec.md` for full context
2. **Check dependencies** — TASK-1064 must be completed first
3. **Verify the Codebase Contract** — confirm `AgentCrew.on_complete`, `on_error`, `_fire_hooks` exist
4. **Implement** the test file following the scaffold above
5. **Run tests**: `pytest tests/test_crew_hooks.py -v`
6. **Update status** in per-spec index → `"done"`
7. **Move this file** to `sdd/tasks/completed/`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-05-11
**Notes**: Created `tests/test_crew_hooks.py` with 18 tests across 6 classes:
TestHookRegistration (5), TestFireHooksDispatch (4), TestHookArguments (1),
TestHookCallbackTypes (3), TestHookErrorIsolation (3), TestHookOrdering (2).
All 18 pass. Uses `FlowResult`/`FlowStatus` instead of `CrewResult`/string
literals (FEAT-143 migration). `asyncio_mode = auto` in pytest.ini means no
`@pytest.mark.asyncio` decorator is needed but all async methods in classes
work correctly.

**Deviations from spec**: Imports changed from `parrot.bots.orchestration.crew`
/ `parrot.models.crew.CrewResult` to `parrot.bots.flows.crew.AgentCrew` /
`parrot.bots.flows.core.result.FlowResult` (corrected for FEAT-143 migration).
Status values use `FlowStatus` enum instead of raw strings.
