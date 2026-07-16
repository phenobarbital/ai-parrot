---
type: Wiki Overview
title: 'TASK-1035: BotManager ephemeral methods + save_user_bot'
id: doc:sdd-tasks-completed-task-1035-botmanager-ephemeral-methods-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'from parrot.manager.manager import BotManager # parrot/manager/manager.py:81'
relates_to:
- concept: mod:parrot.bots.abstract
  rel: mentions
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.handlers.models._encrypted_field
  rel: mentions
- concept: mod:parrot.handlers.models.users_bots
  rel: mentions
- concept: mod:parrot.manager.ephemeral
  rel: mentions
- concept: mod:parrot.manager.manager
  rel: mentions
---

# TASK-1035: BotManager ephemeral methods + save_user_bot

**Feature**: FEAT-149 — Ephemeral User Agents
**Spec**: `sdd/specs/ephemeral-agents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1034
**Assigned-to**: unassigned

---

## Context

> This is the core business logic layer (spec §3 Module 2). It adds five new methods to
> `BotManager` that manage the ephemeral lifecycle: create, promote, status, discard, and
> a new `save_user_bot` that writes `navigator.users_bots` (distinct from `save_agent`
> which writes `navigator.ai_bots`).

---

## Scope

- Add `_ephemeral_registry: EphemeralRegistry` attribute to `BotManager.__init__`.
- Implement `create_ephemeral_user_bot(user_id, config, uploaded_paths, *, ttl_seconds=86400) -> EphemeralAgentStatus`.
  - Build a `UserBotModel` in-memory (no DB write).
  - Instantiate the `AbstractBot` via the same pipeline as `_build_user_bot_instance`.
  - Call `self.add_agent(bot)` to register in `self._bots`.
  - Register `EphemeralAgentStatus` with phase `"creating"`.
  - Schedule warm-up via `asyncio.create_task` (the coroutine itself is Module 3 / TASK-1036; for now, create a placeholder `_warm_up` stub).
  - Return the status object.
- Implement `save_user_bot(model: UserBotModel) -> UserBotModel`.
  - INSERT (or UPSERT) into `navigator.users_bots` via `UserBotModel`.
  - Uses `self.app['database']` connection pool, same pattern as `save_agent` but targeting `UserBotModel` not `BotModel`.
- Implement `promote_user_bot(chatbot_id, user_id) -> UserBotModel`.
  - Verify ephemeral status is `"ready"` (reject if `"creating"`, `"warming"`, or `"error"`).
  - Delegate DB write to `save_user_bot`.
  - Remove from ephemeral registry.
  - Return the persisted `UserBotModel`.
- Implement `get_ephemeral_status(chatbot_id, user_id) -> Optional[EphemeralAgentStatus]`.
- Implement `discard_ephemeral_user_bot(chatbot_id, user_id) -> bool`.
  - Remove from `_ephemeral_registry` and `self._bots`.
  - Return `True` on success, `False` if not found.
- Integrate expired-ephemeral cleanup into the existing `_cleanup_expired_bots` hook.
- Write unit tests for all five methods.

**NOT in scope**: Warm-up logic (Module 3 / TASK-1036), HTTP handlers (Module 4), FAISS S3 persistence (Module 6).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/manager/manager.py` | MODIFY | Add 5 new methods + `_ephemeral_registry` init |
| `tests/unit/test_botmanager_ephemeral.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.manager.manager import BotManager                        # parrot/manager/manager.py:81
from parrot.manager.ephemeral import EphemeralAgentStatus, EphemeralRegistry  # TASK-1034 creates this
from parrot.handlers.models.users_bots import UserBotModel           # parrot/handlers/models/users_bots.py:26
from parrot.handlers.models._encrypted_field import seal, unseal     # used by users_bots.py:23
from parrot.bots.abstract import AbstractBot                         # parrot/bots/abstract.py:146
from parrot.conf import PARROT_SCHEMA                                # used in users_bots.py:21
```

### Existing Signatures to Use
```python
# parrot/manager/manager.py:81
class BotManager:
    def __init__(self, ...) -> None:                                 # line 88
        self._bots: Dict[str, AbstractBot] = {}                      # line 113
        # ... (add _ephemeral_registry here)

    def add_agent(self, agent: AbstractBot) -> None:                 # line 809
        self._bots[str(agent.chatbot_id)] = agent

    def remove_agent(self, agent: AbstractBot) -> None:              # line 813
        del self._bots[str(agent.chatbot_id)]

    async def save_agent(self, name: str, **kwargs) -> None:         # line 817
        # Writes navigator.ai_bots via BotModel — DO NOT reuse for users_bots

    async def get_user_bot(self, request, chatbot_id) -> Optional[AbstractBot]:  # line 737
        # Session cache → DB lookup → _build_user_bot_instance

    async def _build_user_bot_instance(self, bot_model) -> AbstractBot:  # ~line 700
        # Reuse this pipeline for ephemeral instantiation

# parrot/handlers/models/users_bots.py:26
class UserBotModel(Model):
    chatbot_id: uuid.UUID                                            # PK
    user_id: int                                                     # PK
    # ... all fields in spec §6
    class Meta:
        schema = PARROT_SCHEMA                                       # line 115
        name = "users_bots"
```

### Does NOT Exist
- ~~`BotManager.save_user_bot`~~ — does NOT exist yet; this task creates it.
- ~~`BotManager._ephemeral_registry`~~ — does NOT exist yet; this task adds it.
- ~~`navigator.user_bots`~~ — table is `navigator.users_bots` (with `s`).
- ~~`AbstractBot.warm_up()`~~ — the readiness contract is `await agent.configure(app)`.

---

## Implementation Notes

### Pattern to Follow
```python
# save_user_bot follows the same DB pattern as save_agent (line 817)
# but targets UserBotModel instead of BotModel:
async def save_user_bot(self, model: UserBotModel) -> UserBotModel:
    db = self.app['database']
    async with await db.acquire() as conn:
        UserBotModel.Meta.connection = conn
        await model.insert()
    return model
```

### Key Constraints
- `save_user_bot` writes `navigator.users_bots` via `UserBotModel` — NOT `navigator.ai_bots`.
- `promote_user_bot` must reject if phase is not `"ready"` — return 409-compatible error.
- `create_ephemeral_user_bot` must NOT persist to DB. The bot lives only in `self._bots`.
- Use `seal()` from `_encrypted_field` for `mcp_config` and `tools_config` even in memory (byte-compatible with DB row).
- Cleanup integration: extend the existing `_cleanup_expired_bots` (or its scheduling hook) to also call `self._ephemeral_registry.get_expired()` and remove those bots.

### References in Codebase
- `parrot/manager/manager.py:817` — `save_agent` pattern to mirror for `save_user_bot`
- `parrot/manager/manager.py:700` — `_build_user_bot_instance` for instantiation pipeline
- `parrot/handlers/models/users_bots.py:26` — `UserBotModel` schema

---

## Acceptance Criteria

- [ ] `create_ephemeral_user_bot` returns `EphemeralAgentStatus` with `phase="creating"`, bot is in `self._bots`, no DB row exists.
- [ ] `save_user_bot` INSERTs into `navigator.users_bots` via `UserBotModel` (not `ai_bots`).
- [ ] `promote_user_bot` writes DB row via `save_user_bot`, removes ephemeral status entry; rejects non-ready phase.
- [ ] `get_ephemeral_status` returns status for correct user, `None` for wrong user.
- [ ] `discard_ephemeral_user_bot` removes from both `_ephemeral_registry` and `self._bots`.
- [ ] Expired ephemeral bots are cleaned up by the existing cleanup hook.
- [ ] All tests pass: `pytest tests/unit/test_botmanager_ephemeral.py -v`
- [ ] No linting errors: `ruff check parrot/manager/manager.py`
- [ ] Existing `save_agent` callers are untouched and still work.

---

## Test Specification

```python
# tests/unit/test_botmanager_ephemeral.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.manager.ephemeral import EphemeralAgentStatus


@pytest.fixture
def bot_manager():
    # Minimal BotManager setup with mocked app/database
    ...


class TestCreateEphemeralUserBot:
    async def test_returns_creating_status(self, bot_manager):
        status = await bot_manager.create_ephemeral_user_bot(
            user_id=42, config={...}, uploaded_paths=[],
        )
        assert status.phase == "creating"
        assert str(status.chatbot_id) in bot_manager._bots

    async def test_no_db_row_created(self, bot_manager):
        # Verify UserBotModel.insert() was NOT called
        ...


class TestSaveUserBot:
    async def test_inserts_into_users_bots(self, bot_manager):
        # Verify UserBotModel is inserted, not BotModel
        ...


class TestPromoteUserBot:
    async def test_promote_ready_bot(self, bot_manager):
        # Create → mark ready → promote → DB row exists, ephemeral entry removed
        ...

    async def test_promote_non_ready_raises(self, bot_manager):
        # Create (still "creating") → promote → rejected
        ...

    async def test_promote_twice_raises(self, bot_manager):
        # Promote → second promote → 409
        ...


class TestDiscardEphemeralUserBot:
    async def test_discard_removes_bot_and_status(self, bot_manager):
        ...

    async def test_discard_nonexistent_returns_false(self, bot_manager):
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/ephemeral-agents.spec.md` §2, §3 Module 2, §6.
2. **Check dependencies** — verify TASK-1034 is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — read `parrot/manager/manager.py` to confirm line numbers.
4. **Update status** in `sdd/tasks/index/ephemeral-agents.json` → `"in-progress"`
5. **Implement** the five methods in `manager.py`, plus the `_warm_up` stub.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
