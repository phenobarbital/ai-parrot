# TASK-815: Unit tests for HookableAgent.cleanup()

**Feature**: FEAT-114 — Bot Cleanup Lifecycle
**Spec**: `sdd/specs/FEAT-114-bot-cleanup-lifecycle.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-813
**Assigned-to**: unassigned

---

## Context

TASK-813 adds `HookableAgent.cleanup()`. This task ships the unit tests
that guarantee the four contract points agreed in the spec §4:

1. `stop_hooks()` is called when hooks exist.
2. Safe no-op when `_init_hooks()` was never called.
3. `super().cleanup()` is chained via MRO.
4. Exceptions from `stop_hooks()` are swallowed; `super().cleanup()`
   still runs.

---

## Scope

- Create `packages/ai-parrot/tests/core/hooks/test_hookable_cleanup.py`.
- Implement the four tests named in spec §4 under module 1:
  - `test_hookable_cleanup_calls_stop_hooks`
  - `test_hookable_cleanup_no_hooks_initialized`
  - `test_hookable_cleanup_chains_super`
  - `test_hookable_cleanup_swallows_stop_hooks_error`
- Use `pytest-asyncio` (already used by sibling tests such as
  `test_hookable_agent.py`) — tests are `async def`, wrapped in the
  project's existing async mode.
- Keep tests isolated from `AbstractBot`: build minimal classes that
  mix in `HookableAgent` with a plain synthetic base that exposes an
  `async def cleanup(self)` to assert MRO chaining, and a separate
  class without a `cleanup` to assert the `super()` guard is safe.

**NOT in scope**:
- Tests for `BotManager._cleanup_all_bots` — they belong to TASK-816.
- Tests for `BOT_CLEANUP_TIMEOUT` — they belong to TASK-816.
- Integration tests that spin up an aiohttp app — TASK-816.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/core/hooks/test_hookable_cleanup.py` | CREATE | Four unit tests validating `HookableAgent.cleanup()`. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Verified sibling test file uses these patterns:
# packages/ai-parrot/tests/core/hooks/test_hookable_agent.py
import pytest
import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock
from parrot.core.hooks.mixins import HookableAgent
# Confirm path via: grep -n "from parrot.core.hooks.mixins" packages/ai-parrot/tests/core/hooks/test_hookable_agent.py
```

```python
# pytest-asyncio marker — check packages/ai-parrot/tests/conftest.py or pyproject.toml
# If asyncio_mode = "auto", no @pytest.mark.asyncio decorator is needed.
# Otherwise decorate async tests with @pytest.mark.asyncio.
# The sibling file test_hookable_agent.py is the ground truth — follow its convention.
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/core/hooks/mixins.py
class HookableAgent:
    def _init_hooks(self) -> None:                    # line 26
    async def stop_hooks(self) -> None:               # line 63
    async def cleanup(self) -> None:                  # NEW — added by TASK-813

# Internal fields created by _init_hooks():
#   self._hook_manager: HookManager
#   self._hooks_logger: logging.Logger
```

```python
# packages/ai-parrot/src/parrot/core/hooks/manager.py
class HookManager:
    async def stop_all(self) -> None:                 # line 159
```

### Does NOT Exist

- ~~`from parrot.core.hooks import HookableAgent`~~ — the canonical
  import path is `parrot.core.hooks.mixins` (verify with `grep`).
- ~~`HookableAgent.close()`~~ / ~~`HookableAgent.shutdown()`~~ — only
  `cleanup()` (and `stop_hooks()`) exist; do not assert on phantom methods.
- ~~`pytest.mark.asyncio` decorators are mandatory~~ — depends on the
  project's `asyncio_mode` setting. Check `pyproject.toml` or
  `conftest.py` before decorating.

---

## Implementation Notes

### Pattern to Follow

```python
"""Tests for HookableAgent.cleanup() (FEAT-114)."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.core.hooks.mixins import HookableAgent


# --- Test harness classes -------------------------------------------------

class _BaseWithCleanup:
    """Minimal synthetic 'bot base' that records super().cleanup() calls."""
    def __init__(self) -> None:
        self.super_cleanup_called = False

    async def cleanup(self) -> None:
        self.super_cleanup_called = True


class _BaseNoCleanup:
    """Minimal synthetic base with NO cleanup() — exercises the super guard."""
    def __init__(self) -> None:
        pass


class _HookableWithBase(HookableAgent, _BaseWithCleanup):
    """Mixin declared BEFORE the base — correct MRO ordering."""
    def __init__(self, init_hooks: bool = True) -> None:
        _BaseWithCleanup.__init__(self)
        if init_hooks:
            self._init_hooks()


class _HookableNoBase(HookableAgent, _BaseNoCleanup):
    def __init__(self, init_hooks: bool = True) -> None:
        _BaseNoCleanup.__init__(self)
        if init_hooks:
            self._init_hooks()


# --- Tests ----------------------------------------------------------------

async def test_hookable_cleanup_calls_stop_hooks():
    bot = _HookableWithBase(init_hooks=True)
    bot._hook_manager.stop_all = AsyncMock()
    await bot.cleanup()
    bot._hook_manager.stop_all.assert_awaited_once()


async def test_hookable_cleanup_no_hooks_initialized():
    bot = _HookableWithBase(init_hooks=False)
    # Must not raise even though _hook_manager does not exist
    await bot.cleanup()
    assert bot.super_cleanup_called is True


async def test_hookable_cleanup_chains_super():
    bot = _HookableWithBase(init_hooks=True)
    bot._hook_manager.stop_all = AsyncMock()
    await bot.cleanup()
    assert bot.super_cleanup_called is True


async def test_hookable_cleanup_swallows_stop_hooks_error():
    bot = _HookableWithBase(init_hooks=True)
    bot._hook_manager.stop_all = AsyncMock(side_effect=RuntimeError("boom"))
    # Must not raise
    await bot.cleanup()
    # super().cleanup() still reached
    assert bot.super_cleanup_called is True
```

### Key Constraints

- Do **not** import `AbstractBot` in these tests. The point is to test
  the mixin in isolation. Using synthetic bases keeps the tests fast
  and decoupled from LLM / store wiring.
- Verify the async-marker convention by running one test first
  (`pytest packages/ai-parrot/tests/core/hooks/test_hookable_agent.py -v`).
  If the existing tests use `@pytest.mark.asyncio`, mirror that. If
  `asyncio_mode = "auto"` is set, leave tests undecorated.
- For `_HookableNoBase`, do **not** add a test that calls `cleanup()` —
  the current implementation uses a safe `getattr` guard, so calling
  cleanup on it would simply skip the `super().cleanup()` call. If
  desired, add a fifth test that asserts this, but it is not in the
  spec's required four; keep it optional.

### References in Codebase

- `packages/ai-parrot/tests/core/hooks/test_hookable_agent.py` — style
  template for the test file (imports, fixtures, async markers).
- `packages/ai-parrot/tests/core/hooks/test_hookmanager_eventbus.py` —
  example of mocking `HookManager` internals.

---

## Acceptance Criteria

- [ ] File created at `packages/ai-parrot/tests/core/hooks/test_hookable_cleanup.py`.
- [ ] All four spec-mandated tests are present and pass:
  - [ ] `test_hookable_cleanup_calls_stop_hooks`
  - [ ] `test_hookable_cleanup_no_hooks_initialized`
  - [ ] `test_hookable_cleanup_chains_super`
  - [ ] `test_hookable_cleanup_swallows_stop_hooks_error`
- [ ] `pytest packages/ai-parrot/tests/core/hooks/test_hookable_cleanup.py -v` is green.
- [ ] `pytest packages/ai-parrot/tests/core/hooks/ -v` (full directory) stays green — no regressions in sibling tests.
- [ ] `ruff check packages/ai-parrot/tests/core/hooks/test_hookable_cleanup.py` is clean.

---

## Test Specification

See the pattern above. The four tests are self-contained; no shared
fixtures required beyond the two synthetic base classes declared at
module level.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context.
2. **Check dependencies** — TASK-813 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** —
   - Run `pytest packages/ai-parrot/tests/core/hooks/test_hookable_agent.py -q` to confirm the async-test convention.
   - Confirm `from parrot.core.hooks.mixins import HookableAgent` works.
4. **Update status** in `sdd/tasks/.index.json` → `in-progress`.
5. **Create the test file** per the pattern above. Adjust the async
   decorator to match project convention.
6. **Run** `pytest packages/ai-parrot/tests/core/hooks/test_hookable_cleanup.py -v` and iterate until green.
7. **Move this file** to `sdd/tasks/completed/TASK-815-hookable-cleanup-tests.md`.
8. **Update index** → `done`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-04-22
**Notes**: Created `test_hookable_cleanup.py` with 4 tests. Key deviation from spec pattern: mocked `bot.stop_hooks` directly (not `_hook_manager.stop_all`) because the worktree tests run against the installed package (editable install in main repo venv). Tests must use `PYTHONPATH=$WT/packages/ai-parrot/src pytest ...` to pick up worktree changes. All 4 tests pass; 59 sibling tests unaffected. ruff clean.

**Deviations from spec**: Mocked `stop_hooks` directly instead of `_hook_manager.stop_all` — semantically equivalent and more robust against HookManager internals.
