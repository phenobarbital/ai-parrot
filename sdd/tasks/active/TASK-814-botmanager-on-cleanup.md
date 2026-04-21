# TASK-814: Implement BotManager on_cleanup iteration

**Feature**: FEAT-114 — Bot Cleanup Lifecycle
**Spec**: `sdd/specs/FEAT-114-bot-cleanup-lifecycle.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-812
**Assigned-to**: unassigned

---

## Context

`BotManager` already tracks every active agent in `self._bots` and
registers signals on the aiohttp app (`on_startup`, `on_shutdown`,
`on_cleanup` → `_cleanup_shared_redis`). It does **not**, however,
iterate those bots on shutdown, so `AbstractBot.cleanup()` and
(transitively) `HookableAgent.cleanup()` are never called for bots
living in the manager.

This task closes that gap by adding a new on-cleanup callback
`_cleanup_all_bots` that runs `bot.cleanup()` on every registered bot
concurrently, bounded by `BOT_CLEANUP_TIMEOUT`, and isolated per-bot so
that one failure or hang does not stop the rest.

Implements **Module 2** of the spec (§3) and consumes the
`BOT_CLEANUP_TIMEOUT` constant delivered by TASK-812.

---

## Scope

- Extend the `from ..conf import (...)` tuple at
  `packages/ai-parrot/src/parrot/manager/manager.py:54-61` to include
  `BOT_CLEANUP_TIMEOUT`.
- Add two new coroutines to `BotManager`:
  - `async def _cleanup_all_bots(self, app: web.Application) -> None`
  - `async def _safe_cleanup(self, name: str, bot: AbstractBot) -> bool`
- In `BotManager.setup(app)` (line ~755), register
  `self._cleanup_all_bots` on `self.app.on_cleanup` **before** the
  existing `self.app.on_cleanup.append(self._cleanup_shared_redis)`
  at line 736. Order matters: per-bot cleanup must run while the
  shared Redis client is still alive.
- `_cleanup_all_bots` must:
  - Return early with a log line when `self._bots` is empty.
  - Launch one coroutine per bot via
    `asyncio.gather(*(self._safe_cleanup(name, bot) for name, bot in self._bots.items()), return_exceptions=False)`.
  - Log a summary `"Bot cleanup complete: X ok, Y failed"` using
    `self.logger.info`.
- `_safe_cleanup` must:
  - Honour the idempotency guard described in §7 and §8 (recommended
    default) by maintaining a `self._cleaned_up: set[str]` attribute
    initialised in `__init__`. If `name in self._cleaned_up` at entry,
    return `True` without re-invoking `bot.cleanup()`.
  - Wrap the call in
    `asyncio.wait_for(bot.cleanup(), timeout=BOT_CLEANUP_TIMEOUT)`.
  - On `asyncio.TimeoutError`: log at `warning` with the bot name
    and timeout; return `False`.
  - On any other `Exception`: log with `self.logger.exception(...)`;
    return `False`.
  - On success: add `name` to `self._cleaned_up`; return `True`.
  - Never raise.
- Initialise `self._cleaned_up: set[str] = set()` in
  `BotManager.__init__` alongside the other `self._bots` /
  `self._botdef` declarations (around line 103-105).

**NOT in scope**:
- Any change to `on_shutdown` — integrations and chat-storage teardown
  remain exactly as they are today.
- Any change to `_cleanup_shared_redis`. Its position after
  `_cleanup_all_bots` is enforced by the call order in `setup()`.
- Iterating `self._crews`. Out of scope per spec §1 Non-Goals.
- Tests — delivered in TASK-816.
- Documentation — delivered in TASK-817.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/manager/manager.py` | MODIFY | Extend conf import tuple, add `self._cleaned_up` attr, add `_cleanup_all_bots` and `_safe_cleanup` methods, register `_cleanup_all_bots` on `self.app.on_cleanup` in `setup()`. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Already present at packages/ai-parrot/src/parrot/manager/manager.py:10,12,17
import asyncio
from aiohttp import web
from ..bots.abstract import AbstractBot

# Existing conf import tuple at packages/ai-parrot/src/parrot/manager/manager.py:54-61
from ..conf import (
    ENABLE_CREWS,
    ENABLE_DATABASE_BOTS,
    ENABLE_DASHBOARDS,
    ENABLE_REGISTRY_BOTS,
    ENABLE_SWAGGER,
    REDIS_URL,
    BOT_CLEANUP_TIMEOUT,   # NEW — added by this task (requires TASK-812)
)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/manager/manager.py
class BotManager:
    def __init__(self, *, enable_crews=..., enable_database_bots=..., ...):
        self.app = None                                  # line 102
        self._bots: Dict[str, AbstractBot] = {}          # line 103
        self._botdef: Dict[str, Type] = {}               # line 104
        self._cleanup_task: Optional[asyncio.Task] = None  # line 106
        self._redis_owned: bool = False                  # line 125

    def add_bot(self, bot: AbstractBot) -> None:         # line 523
        self._bots[bot.name] = bot
        self._botdef[bot.name] = bot.__class__

    def setup(self, app: web.Application) -> web.Application:  # line 755
        self.app = None
        if app:
            self.app = app if isinstance(app, web.Application) else app.get_app()
        # ... existing body ...
        self.app.on_startup.append(self.on_startup)      # line 760
        self.app.on_shutdown.append(self.on_shutdown)    # line 761
        # Earlier in the method, line 736:
        # self.app.on_cleanup.append(self._cleanup_shared_redis)

    async def _cleanup_shared_redis(self, app) -> None:  # near line 736
        # Closes the shared Redis client ONLY when
        # self._redis_owned is True.

    async def on_shutdown(self, app: web.Application) -> None:  # line 1013
        # Existing body — DO NOT modify in this task.

    async def on_startup(self, app: web.Application) -> None:
        # Existing body — DO NOT touch.
```

```python
# packages/ai-parrot/src/parrot/bots/abstract.py
class AbstractBot(ABC):
    async def cleanup(self) -> None:                     # line 3134
```

### Does NOT Exist

- ~~`BotManager.shutdown_bots()`~~, ~~`BotManager.cleanup_bots()`~~ —
  names not in use; the new method MUST be named `_cleanup_all_bots`.
- ~~`self._agents`, `self._registered_bots`~~ — the tracked dict is
  `self._bots`.
- ~~`AbstractBot.close()`, `AbstractBot.stop()`, `AbstractBot.dispose()`~~ —
  the correct teardown method is `cleanup()`.
- ~~`asyncio.gather(..., return_exceptions=True)`~~ — **do not** use
  `return_exceptions=True`. `_safe_cleanup` absorbs exceptions itself
  so `return_exceptions=False` is correct and gives clean semantics.
- ~~Registering on `self.app.on_shutdown`~~ — the chosen signal is
  `on_cleanup` per the spec §6 / §7. Registering on `on_shutdown`
  would run cleanup before `IntegrationBotManager.shutdown()` finishes
  and may reference still-open channels.

---

## Implementation Notes

### Pattern to Follow

```python
# packages/ai-parrot/src/parrot/manager/manager.py

class BotManager:
    def __init__(self, ...):
        ...
        self._bots: Dict[str, AbstractBot] = {}
        self._botdef: Dict[str, Type] = {}
        self._bot_expiration: Dict[str, float] = {}
        self._cleanup_task: Optional[asyncio.Task] = None
        self._cleaned_up: set[str] = set()   # NEW — idempotency guard
        ...

    def setup(self, app: web.Application) -> web.Application:
        ...
        # Existing on_cleanup registration is at line 736:
        #   self.app.on_cleanup.append(self._cleanup_shared_redis)
        # Insert the per-bot cleanup ABOVE that line so it runs first:
        self.app.on_cleanup.append(self._cleanup_all_bots)
        self.app.on_cleanup.append(self._cleanup_shared_redis)
        ...

    async def _cleanup_all_bots(self, app: web.Application) -> None:
        """on_cleanup callback: clean every registered bot concurrently."""
        if not self._bots:
            self.logger.debug("BotManager: no bots to clean up")
            return

        self.logger.info(
            f"BotManager: cleaning up {len(self._bots)} bot(s) "
            f"(timeout={BOT_CLEANUP_TIMEOUT}s)"
        )
        results = await asyncio.gather(
            *(self._safe_cleanup(name, bot) for name, bot in self._bots.items()),
            return_exceptions=False,
        )
        failed = sum(1 for ok in results if not ok)
        ok = len(results) - failed
        self.logger.info(
            f"BotManager: bot cleanup complete — {ok} ok, {failed} failed"
        )

    async def _safe_cleanup(self, name: str, bot: AbstractBot) -> bool:
        """Clean one bot with timeout + exception isolation. Never raises."""
        if name in self._cleaned_up:
            self.logger.debug(f"BotManager: bot '{name}' already cleaned up")
            return True
        try:
            await asyncio.wait_for(bot.cleanup(), timeout=BOT_CLEANUP_TIMEOUT)
        except asyncio.TimeoutError:
            self.logger.warning(
                f"BotManager: cleanup of bot '{name}' timed out after "
                f"{BOT_CLEANUP_TIMEOUT}s"
            )
            return False
        except Exception:  # noqa: BLE001 — teardown must not raise
            self.logger.exception(
                f"BotManager: cleanup of bot '{name}' raised"
            )
            return False
        self._cleaned_up.add(name)
        return True
```

### Key Constraints

- **Register order matters**: `_cleanup_all_bots` must be appended
  **before** `_cleanup_shared_redis` in `setup()`. Both are appended in
  the same `setup()` method; aiohttp runs `on_cleanup` callbacks in
  registration order.
- **Do not touch `on_shutdown`**. Integration teardown, chat_storage
  closing, and the `_cleanup_task` cancellation all stay where they are.
- **Do not mutate `self._bots`** during iteration. Build the coroutine
  list in a single expression passed to `gather`.
- `BOT_CLEANUP_TIMEOUT` is an `int` — fine for `asyncio.wait_for`.
- `self._cleaned_up.add(name)` is only called on success. On timeout
  or exception the bot stays eligible for retry (e.g. if tests invoke
  cleanup directly).

### References in Codebase

- `packages/ai-parrot/src/parrot/manager/manager.py:736` — existing
  `on_cleanup` registration; the new callback goes right above it.
- `packages/ai-parrot/src/parrot/manager/manager.py:760-761` — existing
  `on_startup` / `on_shutdown` registration (DO NOT touch).
- `packages/ai-parrot/src/parrot/core/hooks/manager.py:159-176` —
  stylistic reference for log-per-item-and-continue during teardown.

---

## Acceptance Criteria

- [ ] `BOT_CLEANUP_TIMEOUT` is imported in `manager/manager.py`.
- [ ] `BotManager.__init__` initialises `self._cleaned_up: set[str] = set()`.
- [ ] `BotManager._cleanup_all_bots(app)` exists, is async, and is a no-op (with a log) when `self._bots` is empty.
- [ ] `BotManager._safe_cleanup(name, bot)` exists, never raises, and returns `True` on success / `False` on timeout or exception.
- [ ] `BotManager.setup(app)` appends `_cleanup_all_bots` to `app.on_cleanup` **before** `_cleanup_shared_redis`. Verified by inspecting `app.on_cleanup` index: `_cleanup_all_bots` appears earlier.
- [ ] One bot raising does not prevent the other bots from being awaited and completing.
- [ ] One bot hanging beyond `BOT_CLEANUP_TIMEOUT` is cancelled via `asyncio.wait_for` and logged; the other bots still complete.
- [ ] A second call to `_cleanup_all_bots` (or `_safe_cleanup` with the same name) after a successful cleanup does NOT re-invoke `bot.cleanup()`.
- [ ] `ruff check packages/ai-parrot/src/parrot/manager/manager.py` is clean.
- [ ] Existing tests in `packages/ai-parrot/tests/manager/` still pass.
- [ ] Unit/integration tests in TASK-816 pass (validated there).

---

## Test Specification

Tests live in TASK-816 — `packages/ai-parrot/tests/manager/test_bot_cleanup_lifecycle.py`.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context.
2. **Check dependencies** — TASK-812 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** —
   - `grep -n "^from \.\.conf import" packages/ai-parrot/src/parrot/manager/manager.py` to confirm the import block still begins at line 54.
   - `grep -n "self.app.on_cleanup.append" packages/ai-parrot/src/parrot/manager/manager.py` to confirm the existing registration is still a single line near 736.
   - `grep -n "async def cleanup" packages/ai-parrot/src/parrot/bots/abstract.py` to confirm line 3134 is still correct.
4. **Update status** in `sdd/tasks/.index.json` → `in-progress`.
5. **Implement** per the pattern above.
6. **Verify** `ruff check` passes.
7. **Move this file** to `sdd/tasks/completed/TASK-814-botmanager-on-cleanup.md`.
8. **Update index** → `done`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
