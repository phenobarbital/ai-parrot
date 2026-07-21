---
type: Wiki Overview
title: 'TASK-1052: BotManager._load_database_bots — wire policy registration'
id: doc:sdd-tasks-completed-task-1052-load-database-bots-policy-wiring-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements §3 Module 4. Closes the loop between the DB row and the
relates_to:
- concept: mod:parrot.manager.manager
  rel: mentions
---

# TASK-1052: BotManager._load_database_bots — wire policy registration

**Feature**: FEAT-153 — botmanager-pbac-permissions
**Spec**: `sdd/specs/botmanager-pbac-permissions.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1049, TASK-1051
**Assigned-to**: unassigned

---

## Context

Implements §3 Module 4. Closes the loop between the DB row and the
evaluator: when `_load_database_bots()` materialises a bot from
`navigator.ai_bots`, its `permissions` JSONB value is registered with
the evaluator BEFORE the bot is inserted into `self._bots`. Without
this wiring, bots loaded from DB stay invisible to PBAC even after
TASK-1051 ships — exactly the gap the spec exists to close.

The behaviour on malformed `permissions` is **WARNING + skip the bot**
(resolved §8 Q3): one bad row never blocks the rest of the load.

---

## Scope

- In `BotManager._load_database_bots()`
  (`packages/ai-parrot/src/parrot/manager/manager.py:307-487`), after
  `await bot_instance.configure(app)` succeeds (line 426) and BEFORE
  the bot is added to `self._bots`, call:

  ```python
  try:
      self.registry.register_db_bot_policies(
          bot_model.name,
          bot_model.permissions,
      )
  except ValueError as exc:
      self.logger.warning(
          "Bot %r has malformed permissions JSON, skipping policy "
          "registration AND skipping the bot from the manager: %s",
          bot_model.name, exc,
      )
      continue   # skip this bot — do NOT add to self._bots
  ```

  Use `continue` (skip this iteration of the outer `for bot_model in
  all_bots:` loop) so the rest of the loop carries on with remaining
  bots.
- The wiring must happen on the DB-load path only. Leave
  `add_bot(...)` calls in unrelated code paths (registry-config,
  startup_agents) untouched.
- Add an integration test
  (`packages/ai-parrot/tests/manager/test_load_database_bots_pbac.py`)
  with at least 3 cases: empty permissions → bot loaded with 0
  policies; valid permissions → bot loaded with N policies; malformed
  permissions → bot SKIPPED and other bots in the same batch still load.

**NOT in scope**:
- `get_bot()` enforcement (TASK-1053).
- Hot-reload / refresh of `permissions` on UPDATE — out of scope per
  spec §1 Non-Goals.
- The `user_bots` path (`get_user_bot`, `_build_user_bot_instance`) —
  must stay untouched.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/manager/manager.py` | MODIFY | Inject `register_db_bot_policies` call inside `_load_database_bots` (around line 426–487). |
| `packages/ai-parrot/tests/manager/test_load_database_bots_pbac.py` | CREATE | 3 integration tests. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Already imported at parrot/manager/manager.py:53
from ..registry import agent_registry, AgentRegistry, BotConfigStorage

# Already imported at parrot/manager/manager.py:49
from ..handlers.models import BotModel, UserBotModel

# self.registry: AgentRegistry assigned at manager.py:121
# Use self.registry.register_db_bot_policies(...) — no new import needed.
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/manager/manager.py
class BotManager:                                     # line 81
    self.registry: AgentRegistry = agent_registry    # line 121

    async def _load_database_bots(                   # line 307
        self, app: web.Application
    ) -> None:
        # Iterates bot_model in all_bots (line 323).
        # bot_model.permissions read at line 407 (passed to constructor).
        # bot_instance.configure(app) at line 426.
        # The loop continues with reranker patching (line 430-432) and
        # parent_searcher build (line 434+).
        # add_bot(...) happens further down in the same iteration —
        # confirm exact location at implementation time.
```

### Does NOT Exist

- ~~`BotManager.add_bot_with_policies`~~ — does not exist; use the
  existing `add_bot(...)` after registering policies separately.
- ~~A `permissions=` kwarg on `add_bot`~~ — `add_bot` only takes the
  bot instance.
- ~~`bot_model.permissions_dict`~~ / `.policies` — the canonical
  attribute is `bot_model.permissions` (already read at line 407).

---

## Implementation Notes

### Insertion point

Place the `register_db_bot_policies` call after `bot_instance.configure(app)`
returns (line 426) and AFTER any post-configure patching that the bot
needs to be functional (LLMReranker patch at line 430-432,
parent_searcher build at line 434+). The exact placement should be just
before `self.add_bot(bot_instance)` (find the call at impl time).

```python
# inside the for-loop in _load_database_bots, schematic:
await bot_instance.configure(app)
# ... existing reranker / parent_searcher post-configure patches ...

try:
    n_policies = self.registry.register_db_bot_policies(
        bot_model.name,
        bot_model.permissions,
    )
    if n_policies:
        self.logger.info(
            "Bot %r: registered %d DB-declared policy rule(s).",
            bot_model.name, n_policies,
        )
except ValueError as exc:
    self.logger.warning(
        "Bot %r has malformed 'permissions' JSON: %s. "
        "Skipping this bot.",
        bot_model.name, exc,
    )
    continue   # skip — do NOT add to self._bots

self.add_bot(bot_instance)   # existing call — leave as-is
```

### Why register BEFORE add_bot

A concurrent `get_bot(name, request=req)` call could race the load
loop. If `add_bot` ran before `register_db_bot_policies`, the resolver
would briefly see a bot with NO policies registered against it (so
`enforce_agent_access` would short-circuit to "allow"). Register
first; add second.

### Test design

Mock the database to return a hand-crafted list of `BotModel`-like
objects with controlled `permissions` values. Spy on
`self.registry.register_db_bot_policies(...)` (or on the underlying
`evaluator.load_policies(...)`) to verify the call shape.

The malformed-permissions test must assert two things:
1. The malformed bot is NOT in `manager._bots`.
2. A subsequent well-formed bot in the same batch IS in `manager._bots`
   (the loop continued).

### Patterns to Follow

- Mirror the existing reranker error handling at
  `manager.py:348-354` (catch a specific exception, log, continue).
  The difference is reranker errors `raise` (fail-fast) but the spec
  resolved §8 Q3 to `continue` for permissions errors.
- Use `self.logger` already initialized higher in the file.

---

## Acceptance Criteria

- [ ] `BotManager._load_database_bots` calls
  `self.registry.register_db_bot_policies(bot_model.name, bot_model.permissions)`
  for every loaded bot before `self.add_bot(bot_instance)`.
- [ ] `permissions = {}` → bot loads, `register_db_bot_policies`
  returns 0, bot ends up in `self._bots`.
- [ ] Valid `{"permissions": [...]}` → bot loads, N policies
  registered, bot ends up in `self._bots`.
- [ ] Malformed `permissions` → WARNING logged, bot NOT added to
  `self._bots`, the loop continues with remaining bots.
- [ ] No change to the user_bots path (`get_user_bot`,
  `_build_user_bot_instance`).
- [ ] Tests pass: `pytest packages/ai-parrot/tests/manager/test_load_database_bots_pbac.py -v`.
- [ ] `ruff check` passes on `parrot/manager/manager.py`.

---

## Test Specification

```python
# packages/ai-parrot/tests/manager/test_load_database_bots_pbac.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.manager.manager import BotManager


@pytest.mark.asyncio
async def test_load_with_empty_permissions_loads_bot():
    """permissions={} → bot loads and 0 policies are registered."""
    ...

@pytest.mark.asyncio
async def test_load_with_valid_permissions_registers_policies():
    """Non-empty permissions → register_db_bot_policies called with
    the JSONB value and returns N>0; bot present in manager._bots."""
    ...

@pytest.mark.asyncio
async def test_malformed_permissions_skips_bot_and_continues():
    """One bot with malformed permissions is skipped and not in
    manager._bots; another well-formed bot in the same batch IS loaded."""
    ...
```

---

## Agent Instructions

When you pick up this task:

1. Confirm TASK-1049 and TASK-1051 are done.
2. Re-read `manager.py:307-487` to find the exact line where
   `add_bot` is called inside the loop. The spec gives the
   neighbourhood (after line 426); you must find the precise insertion
   point.
3. Implement the wiring with `try/except ValueError → continue`.
4. Write the 3 integration tests.
5. Run pytest + ruff.
6. Move this file to `sdd/tasks/completed/`, update the per-spec
   index, fill the Completion Note.

---

## Completion Note

Implemented by sdd-worker (claude-sonnet-4-6) on 2026-05-07.

Added `register_db_bot_policies` call with `try/except ValueError → continue` in
`_load_database_bots` before `self.add_bot(bot_instance)`. Placement is after
`await bot_instance.configure(app)` on the confirmed line. The WARNING log and
`continue` skip the bot when permissions are malformed.

Also fixed the manager `tests/manager/conftest.py` stub for `navigator.background`
to add `BackgroundService`, `TaskWrapper`, `JobRecord` class stubs (pre-existing
gap that prevented any manager tests from importing `BotManager`).

3 integration tests created in `test_load_database_bots_pbac.py`. One test was
updated to use `patch.object` (auto-restoring) instead of direct attribute
assignment on the singleton registry to avoid state leakage between tests.

All 3 tests pass. ruff reports no errors on `manager.py`.
