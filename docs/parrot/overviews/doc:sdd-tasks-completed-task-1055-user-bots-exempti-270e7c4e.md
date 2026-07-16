---
type: Wiki Overview
title: 'TASK-1055: user_bots exemption regression test'
id: doc:sdd-tasks-completed-task-1055-user-bots-exemption-regression-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements §3 Module 7. `user_bots` (`navigator.users_bots`) are
relates_to:
- concept: mod:parrot.handlers.models.users_bots
  rel: mentions
- concept: mod:parrot.manager.manager
  rel: mentions
---

# TASK-1055: user_bots exemption regression test

**Feature**: FEAT-153 — botmanager-pbac-permissions
**Spec**: `sdd/specs/botmanager-pbac-permissions.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1052, TASK-1053, TASK-1054
**Assigned-to**: unassigned

---

## Context

Implements §3 Module 7. `user_bots` (`navigator.users_bots`) are
per-user bots already scoped by `(user_id, chatbot_id)`. They are
resolved through a different code path — `BotManager.get_user_bot()`
(`manager.py:737-788`) and `_build_user_bot_instance()`
(`manager.py:721-735`) — which never goes through `get_bot()`,
`_load_database_bots()`, or `AgentRegistry.get_instance()`.

The new agent-level PBAC check therefore does NOT apply to user_bots
by virtue of code-path separation. This task locks that property in
with a regression test so a future refactor can't accidentally route
user_bots through `get_bot()` and start enforcing agent policies on
owner-scoped bots.

**This task adds a test only — no production code change.**

---

## Scope

- Add a test in
  `packages/ai-parrot/tests/manager/test_user_bots_pbac_exempt.py`
  that:
  1. Builds a `BotManager` with a working PBAC evaluator.
  2. Registers a deny-all `agent:<chatbot_id>` policy directly on the
     evaluator (so the bot's `agent:resolve` action is denied for any
     subject).
  3. Inserts a `UserBotModel` row owned by user X with that
     `chatbot_id`.
  4. Calls `manager.get_user_bot(request=req_for_user_X, chatbot_id=cid)`.
  5. Asserts the bot IS returned (not denied) — the user_bots path
     ignores agent-level PBAC.
- Document in the test docstring WHY the exemption exists (owner-scope
  via composite primary key is itself the access control).

**NOT in scope**:
- Any production code change. If `get_user_bot` accidentally calls
  `enforce_agent_access`, this test will fail and the implementation
  task that introduced the regression must fix the root cause.
- A separate per-user PBAC check on `user_bots`. That is a future
  feature, not part of FEAT-153.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/manager/test_user_bots_pbac_exempt.py` | CREATE | One regression test (`test_user_bot_path_unaffected_by_agent_policies`). |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from parrot.manager.manager import BotManager
from parrot.handlers.models.users_bots import UserBotModel
# verified: packages/ai-parrot/src/parrot/handlers/models/users_bots.py:26
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/manager/manager.py
class BotManager:
    USER_BOTS_SESSION_KEY = "_user_bots"            # line 703

    async def _fetch_user_bot_model(                # line 705
        self, user_id: int, chatbot_id: str,
    ) -> Optional[UserBotModel]:
        # Reads from navigator.users_bots — mock for tests.

    async def _build_user_bot_instance(             # line 721
        self, bot_model: UserBotModel,
    ) -> AbstractBot:
        # Builds and configures the bot from the row.

    async def get_user_bot(                         # line 737
        self, request: web.Request, chatbot_id: Any,
    ) -> Optional[AbstractBot]:
        # 1. session cache lookup
        # 2. _fetch_user_bot_model(user_id, chatbot_id)
        # 3. _build_user_bot_instance(bot_model)
        # MUST NOT call enforce_agent_access — verify by absence.
```

### Does NOT Exist

- ~~`UserBotModel.permissions`~~ used by FEAT-153 — the field exists at
  `users_bots.py:104` but is OUT OF SCOPE for this feature. Do not
  exercise it in this test.
- ~~`get_user_bot(name=...)` by name~~ — the method takes `chatbot_id`
  (UUID), not name.

---

## Implementation Notes

### Test design

```python
# packages/ai-parrot/tests/manager/test_user_bots_pbac_exempt.py
import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.manager.manager import BotManager


@pytest.mark.asyncio
async def test_user_bot_path_unaffected_by_agent_policies():
    """user_bots are owner-scoped by (user_id, chatbot_id) and MUST
    NOT be subject to agent-level PBAC enforcement.

    Reason: a user owning their bot is itself the access control.
    A future refactor that accidentally routes user_bots through
    get_bot() / get_instance() would break this property; this
    regression test catches that.
    """
    # 1. Build manager with PBAC evaluator that DENIES everything for
    #    a specific agent name.
    cid = str(uuid.uuid4())
    manager = BotManager(...)
    manager.registry._evaluator = MagicMock()
    manager.registry._evaluator.check_access.return_value = MagicMock(
        allowed=False,
        matched_policy="deny-all",
        reason="test",
    )

    # 2. Register a deny-all policy for `agent:<cid>` (so if the
    #    user_bots path ever called enforce_agent_access, it would
    #    raise).

    # 3. Mock _fetch_user_bot_model to return a fake UserBotModel.
    fake_user_bot = MagicMock()
    with patch.object(
        manager, "_fetch_user_bot_model",
        new=AsyncMock(return_value=fake_user_bot),
    ), patch.object(
        manager, "_build_user_bot_instance",
        new=AsyncMock(return_value=MagicMock()),
    ):
        # 4. Build a fake request that resolves to user X.
        req = MagicMock()
        req.session = {"user_id": 42}

        # 5. Call get_user_bot — should succeed despite the deny-all
        #    policy because the user_bots path doesn't consult PBAC.
        bot = await manager.get_user_bot(req, cid)

    assert bot is not None
    # The evaluator should NEVER have been queried for this resolution.
    manager.registry._evaluator.check_access.assert_not_called()
```

### Why mock the database

`get_user_bot` calls `_fetch_user_bot_model` which acquires a real DB
connection (manager.py:711-719). Mock it via `patch.object` to keep
the test hermetic and fast.

### Why the evaluator must not be called

The check `check_access.assert_not_called()` is the strongest assertion
we can make: it doesn't depend on what the evaluator would return; it
asserts the user_bots code path never even consulted PBAC. That's
exactly the property §3 Module 7 codifies.

---

## Acceptance Criteria

- [ ] `test_user_bot_path_unaffected_by_agent_policies` exists and
  passes.
- [ ] Test docstring explains the owner-scope rationale.
- [ ] Test asserts `evaluator.check_access` was **not called** for the
  `get_user_bot` path.
- [ ] Test passes: `pytest packages/ai-parrot/tests/manager/test_user_bots_pbac_exempt.py -v`.
- [ ] No production code is modified by this task. `git diff
  packages/ai-parrot/src/` should be empty after this task.
- [ ] `ruff check` passes on the new test file.

---

## Test Specification

The single regression test scaffold is shown in §Implementation Notes
above. The agent should expand it into a working test against the
actual `BotManager` constructor signature.

---

## Agent Instructions

When you pick up this task:

1. Confirm TASK-1052, TASK-1053, TASK-1054 are done. The exemption
   only matters once the enforcement is live — running this test
   before those land would not detect a regression.
2. Read `manager.py:737-788` carefully — confirm `get_user_bot` does
   NOT call `enforce_agent_access` anywhere.
3. Write the regression test against a mocked manager.
4. Run pytest + ruff.
5. Move this file to `sdd/tasks/completed/`, update the per-spec
   index, fill the Completion Note.

---

## Completion Note

Implemented by sdd-worker (claude-sonnet-4-6) on 2026-05-07.

Created `test_user_bots_pbac_exempt.py` with one regression test:
`test_user_bot_path_unaffected_by_agent_policies`. The test:
  1. Builds a BotManager with a deny-all PBAC evaluator.
  2. Mocks `_fetch_user_bot_model` and `_build_user_bot_instance` for hermeticity.
  3. Provides a request mock with `.session` pre-set (avoids need for navigator_session).
  4. Calls `get_user_bot(req, cid)` and asserts the bot is returned.
  5. Asserts `evaluator.check_access` was never called.

Also installed a minimal `navigator_session` stub so the lazy import inside
`get_user_bot` succeeds; the stub's `get_session` is never called because
`request.session` is truthy.

No production code was modified. Test passes. ruff reports no errors.
