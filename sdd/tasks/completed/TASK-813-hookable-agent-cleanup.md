# TASK-813: Add cooperative HookableAgent.cleanup()

**Feature**: FEAT-114 — Bot Cleanup Lifecycle
**Spec**: `sdd/specs/FEAT-114-bot-cleanup-lifecycle.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`HookableAgent` currently exposes `stop_hooks()` but has no
`cleanup()` method. As a result `stop_hooks()` is only wired into the
`AutonomousOrchestrator`; any agent hosted elsewhere (Telegram
Integration, REST API) leaks background hook tasks on shutdown.

This task adds a cooperative `async def cleanup(self)` to
`HookableAgent` that stops the hooks and delegates to `super().cleanup()`
via MRO. When `BotManager._cleanup_all_bots` (TASK-814) iterates
registered bots and calls `bot.cleanup()`, any bot that mixes in
`HookableAgent` will stop its hooks first and then let the bot base's
`cleanup()` run (LLM / store / KBs / MCP).

Implements **Module 1** of the spec (§3).

---

## Scope

- Add `async def cleanup(self) -> None` to `HookableAgent` in
  `packages/ai-parrot/src/parrot/core/hooks/mixins.py`.
- Guard the call with
  `getattr(self, "_hook_manager", None) is not None`. The mixin must be
  safe when a subclass forgets to call `_init_hooks()`.
- Swallow exceptions from `stop_hooks()` via
  `self._hooks_logger.exception(...)` (never re-raise during teardown).
- After stopping hooks, chain to `super().cleanup()` **only if the next
  class in MRO defines `cleanup`**, guarded by
  `callable(getattr(super(), "cleanup", None))`. This belt-and-braces
  check keeps the mixin safe whether it is declared before or after
  the bot base, per the spec's "MRO ordering" risk (§7).
- Update the class-level docstring of `HookableAgent` with one short
  paragraph documenting the MRO contract:
  *"Declare `HookableAgent` before the bot base, e.g.
  `class MyAgent(HookableAgent, JiraSpecialist):`, so `super().cleanup()`
  chains into `AbstractBot.cleanup()`."*

**NOT in scope**:
- Any change to `AbstractBot.cleanup()` or `AbstractBot.shutdown()`.
- Any change to `HookManager.stop_all()`.
- Registering the new method on `BotManager.on_cleanup` — that is TASK-814.
- Unit tests — they belong to TASK-815.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/core/hooks/mixins.py` | MODIFY | Add `cleanup()` method and update class docstring with MRO contract note. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# All already present at packages/ai-parrot/src/parrot/core/hooks/mixins.py:1-6
import logging
from .base import BaseHook
from .manager import HookManager
from .models import HookEvent
# No new imports are required.
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/core/hooks/mixins.py
class HookableAgent:
    def _init_hooks(self) -> None:                    # line 26
        # Creates:
        #   self._hook_manager: HookManager
        #   self._hooks_logger: logging.Logger

    @property
    def hook_manager(self) -> HookManager:            # line 35
        # Raises RuntimeError if _init_hooks was not called.

    def attach_hook(self, hook: BaseHook) -> str:     # line 48

    async def start_hooks(self) -> None:              # line 59
        # Calls self.hook_manager.start_all()

    async def stop_hooks(self) -> None:               # line 63
        # Calls self.hook_manager.stop_all()

    async def handle_hook_event(self, event: HookEvent) -> None:  # line 67
```

```python
# packages/ai-parrot/src/parrot/core/hooks/manager.py
class HookManager:
    async def stop_all(self) -> None:                 # line 159
    # Iterates self._hooks.values(), calls hook.stop(),
    # logs per-hook failures but does not re-raise.
```

```python
# packages/ai-parrot/src/parrot/bots/abstract.py
class AbstractBot(ABC):
    async def cleanup(self) -> None:                  # line 3134
    # Closes _llm, _llm.session, self.store, knowledge bases,
    # kb_store, and tool_manager.disconnect_all_mcp().
    # This is the method super().cleanup() will resolve to via MRO
    # when HookableAgent is declared first in the bases.
```

### Does NOT Exist

- ~~`HookableAgent.close()`~~ — not present; do not create it.
- ~~`HookableAgent.shutdown()`~~ — not present on the mixin, and the
  spec reserves `shutdown()` for other semantics. Do not create.
- ~~`HookManager.close()`~~ — the method is `stop_all()`.
- ~~`self.hook_manager.stop_all_hooks()`~~ — the correct method name is
  `stop_all()` (no suffix).
- ~~`AbstractBot.close()`~~ — the canonical teardown method is `cleanup()`.

---

## Implementation Notes

### Pattern to Follow

```python
# packages/ai-parrot/src/parrot/core/hooks/mixins.py
class HookableAgent:
    """Mixin that adds hook support to any agent or integration handler.

    ... (existing docstring body kept intact) ...

    Lifecycle
    ---------
    Declare ``HookableAgent`` BEFORE the bot base in the class bases
    so Python MRO routes ``super().cleanup()`` into the bot base's
    teardown:

        class MyAgent(HookableAgent, JiraSpecialist):  # correct
            ...

    When the bot is registered with ``BotManager`` the cleanup chain
    fires automatically on aiohttp ``on_cleanup``.
    """

    # ... existing methods unchanged ...

    async def cleanup(self) -> None:
        """Stop hooks and delegate to the next class in MRO.

        Never raises — any failure from ``stop_hooks()`` is logged
        and swallowed so that the bot's resource cleanup still runs.
        """
        if getattr(self, "_hook_manager", None) is not None:
            try:
                await self.stop_hooks()
            except Exception:  # noqa: BLE001 — teardown must not raise
                self._hooks_logger.exception(
                    "HookableAgent: stop_hooks() failed during cleanup"
                )
        parent = getattr(super(), "cleanup", None)
        if callable(parent):
            await parent()
```

### Key Constraints

- Must be `async def`. The bot base `cleanup()` is async.
- The `super()` guard is required because `HookableAgent` does not
  inherit from `AbstractBot`; if a subclass declares the mixin in the
  wrong order, `super().cleanup` resolves to `object`, which has no
  `cleanup`. Guarding avoids `AttributeError`.
- Do not call `self.hook_manager.stop_all()` directly — use
  `self.stop_hooks()` so future changes to the wrapper remain
  in one place.
- Log levels: use `self._hooks_logger.exception(...)` for failures.
  Do not downgrade to `warning`/`error` — `.exception` emits the
  traceback.

### References in Codebase

- `packages/ai-parrot/src/parrot/core/hooks/mixins.py:59-65` — existing
  `start_hooks` / `stop_hooks` pattern to mirror for style.
- `packages/ai-parrot/src/parrot/autonomous/orchestrator.py:243` —
  current sole caller of `stop_hooks`; shows the shape of the call but
  is NOT what we emulate here (the orchestrator owns its own manager).

---

## Acceptance Criteria

- [ ] `HookableAgent.cleanup()` exists and is `async`.
- [ ] Calling `await hookable_bot.cleanup()` with hooks registered
  invokes `HookManager.stop_all()` exactly once.
- [ ] Calling `await hookable_bot.cleanup()` without ever calling
  `_init_hooks()` does NOT raise (safe no-op on the hook portion).
- [ ] `super().cleanup()` is awaited when the next class in MRO
  defines `cleanup`; skipped otherwise.
- [ ] If `stop_hooks()` raises, the exception is logged (not
  re-raised) and `super().cleanup()` still runs.
- [ ] Class docstring updated with the MRO contract note.
- [ ] `ruff check packages/ai-parrot/src/parrot/core/hooks/mixins.py` is clean.
- [ ] Imports work:
  `from parrot.core.hooks.mixins import HookableAgent` and
  `HookableAgent.cleanup` resolves to a coroutine function.
- [ ] Unit tests in TASK-815 pass (validated there).

---

## Test Specification

Tests live in TASK-815 — `packages/ai-parrot/tests/core/hooks/test_hookable_cleanup.py`.
This task delivers the implementation; TASK-815 delivers the coverage.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context.
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** — re-read
   `packages/ai-parrot/src/parrot/core/hooks/mixins.py` and confirm
   `stop_hooks` is still at line ~63 and the class has no `cleanup` method.
4. **Update status** in `sdd/tasks/.index.json` → `in-progress`.
5. **Implement** the `cleanup()` method per the pattern above.
6. **Verify** `ruff check` passes and the import/resolves-coroutine checks pass.
7. **Move this file** to `sdd/tasks/completed/TASK-813-hookable-agent-cleanup.md`.
8. **Update index** → `done`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-04-21
**Notes**: Added `async def cleanup(self) -> None` to `HookableAgent` in `parrot/core/hooks/mixins.py`. Guards `_hook_manager` with `getattr`, swallows `stop_hooks()` exceptions, chains `super().cleanup()` via `getattr(super(), "cleanup", None)`. Updated class docstring with MRO contract note. ruff clean.

**Deviations from spec**: none
