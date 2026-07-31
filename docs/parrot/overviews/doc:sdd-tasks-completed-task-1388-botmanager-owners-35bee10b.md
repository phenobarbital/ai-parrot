---
type: Wiki Overview
title: 'TASK-1388: BotManager ownership-aware methods'
id: doc:sdd-tasks-completed-task-1388-botmanager-ownership-aware-methods-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: With `EphemeralAgentStatus` generalized (TASK-1387), the three `BotManager`
relates_to:
- concept: mod:parrot.manager.ephemeral
  rel: mentions
- concept: mod:parrot.manager.manager
  rel: mentions
---

# TASK-1388: BotManager ownership-aware methods

**Feature**: FEAT-208 — Spawn Ephemeral Sub-Agent Tool
**Spec**: `sdd/specs/FEAT-208-spawn-ephemeral-subagent-tool.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1387
**Assigned-to**: unassigned

---

## Context

> Implements Module 2 of FEAT-208 (§3).

With `EphemeralAgentStatus` generalized (TASK-1387), the three `BotManager`
methods that manage the ephemeral lifecycle still only accept `user_id: int`.
This task generalizes them to accept typed ownership (`owner_id: str` +
`owner_kind`) while keeping the existing `user_id: int` signatures working
for the HTTP handler.

---

## Scope

- Generalize `BotManager.create_ephemeral_user_bot()` to accept either
  `user_id: int` (legacy) or `owner_id: str` + `owner_kind` (new). Internally
  normalize to `owner_id`/`owner_kind` before constructing `EphemeralAgentStatus`.
- Generalize `BotManager.get_ephemeral_status()` similarly — accept `user_id`
  or `owner_id` for lookup, delegate to the updated `EphemeralRegistry.get()`.
- Generalize `BotManager.discard_ephemeral_user_bot()` — accept `user_id` or
  `owner_id` for ownership verification before discard.
- Ensure the HTTP handler (`EphemeralUserAgentHandler`) continues to call these
  methods with `user_id: int` without any changes.
- Write unit tests for the agent-owner path through `BotManager`.

**NOT in scope**: `SpawnSubAgentTool` (TASK-1389), changes to `promote_user_bot`
(out of scope per spec — never used by this feature), HTTP handler changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | Generalize `create_ephemeral_user_bot`, `get_ephemeral_status`, `discard_ephemeral_user_bot` |
| `packages/ai-parrot-server/tests/test_botmanager_ephemeral_owner.py` | CREATE | Unit tests for agent-owner path |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.manager.ephemeral import (
    EphemeralAgentStatus,   # verified: ephemeral.py:75
    EphemeralRegistry,      # verified: ephemeral.py:106
    OwnerKind,              # ADDED by TASK-1387 (does not exist yet in codebase)
    _warm_up,               # verified: ephemeral.py:232
)
from parrot.manager.manager import BotManager  # verified: manager.py:95
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/manager/manager.py

class BotManager:                                        # line 95
    def _ephemeral_registry(self)                        # line 879 (property; returns EphemeralRegistry)
    async def create_ephemeral_user_bot(self, user_id: int,
        config: Dict[str, Any], uploaded_paths: List[dict], *,
        ttl_seconds: int = 86400)                        # line 888 (returns EphemeralAgentStatus)
    def get_ephemeral_status(self, chatbot_id: str, user_id: int)  # line 1147 (SYNC; returns Optional[EphemeralAgentStatus])
    async def discard_ephemeral_user_bot(self, chatbot_id: str, user_id: int) -> bool  # line 1163
    def get_bots(self) -> Dict[str, AbstractBot]         # line 857
    def add_agent(self, agent: AbstractBot) -> None      # line 866

# Warm-up skip when app is None (test/standalone path):
# manager.py:993-995:
#   else:
#       status.phase = "ready"

# remove_bot_callback at manager.py:991:
#   remove_bot_callback=lambda cid: self._bots.pop(cid, None),
```

### Does NOT Exist
- ~~`BotManager.create_ephemeral_agent_bot()`~~ — no separate method; generalize the existing one.
- ~~`BotManager.spawn_sub_agent()`~~ — does not exist; the tool orchestrates this.
- ~~`BotManager.get_ephemeral_by_owner()`~~ — no such method; update existing `get_ephemeral_status`.

---

## Implementation Notes

### Pattern to Follow
Use keyword-only parameters with defaults so callers can pass either form:

```python
async def create_ephemeral_user_bot(
    self,
    user_id: int = None,     # legacy path (HTTP handler)
    config: Dict[str, Any] = None,
    uploaded_paths: List[dict] = None,
    *,
    owner_id: str = None,    # new path (agent owner)
    owner_kind: OwnerKind = "user",
    ttl_seconds: int = 86400,
):
    # Normalize: if user_id provided and owner_id not, convert
    if owner_id is None and user_id is not None:
        owner_id = str(user_id)
        owner_kind = "user"
    elif owner_id is None:
        raise ValueError("Either user_id or owner_id must be provided")
    # ... rest uses owner_id/owner_kind
```

### Key Constraints
- The HTTP handler calls `create_ephemeral_user_bot(user_id=req.user_id, config=..., ...)`.
  This path MUST still work identically.
- `get_ephemeral_status` is **synchronous** — do not make it async.
- The `_warm_up` coroutine and `remove_bot_callback` lambda stay unchanged.
- `promote_user_bot` is NOT touched (out of scope per spec).

### References in Codebase
- `packages/ai-parrot-server/src/parrot/handlers/agents/ephemeral.py` — HTTP handler
  that calls these methods. Read to understand the caller signatures (DO NOT modify).
- `packages/ai-parrot-server/src/parrot/manager/ephemeral.py` — updated by TASK-1387.

---

## Acceptance Criteria

- [ ] `create_ephemeral_user_bot(owner_id="agent:p", owner_kind="agent", config=..., ttl_seconds=300)` works
- [ ] `create_ephemeral_user_bot(user_id=42, config=..., uploaded_paths=[])` still works (backward compat)
- [ ] `get_ephemeral_status(chatbot_id, owner_id="agent:p")` returns status for agent-owned bot
- [ ] `get_ephemeral_status(chatbot_id, user_id=42)` still works (backward compat)
- [ ] `discard_ephemeral_user_bot(chatbot_id, owner_id="agent:p")` discards and returns True
- [ ] HTTP handler (`EphemeralUserAgentHandler`) is NOT modified and continues to work
- [ ] Existing FEAT-149 tests pass: `pytest packages/ai-parrot-server/tests/ -k ephemeral -v`
- [ ] New tests pass: `pytest packages/ai-parrot-server/tests/test_botmanager_ephemeral_owner.py -v`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/test_botmanager_ephemeral_owner.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.manager.manager import BotManager


@pytest.fixture
def bot_manager():
    """BotManager with app=None (skip warm-up, phase='ready' immediate)."""
    bm = BotManager.__new__(BotManager)
    bm.app = None
    bm._bots = {}
    bm._registry = None  # lazy init
    # ... minimal setup
    return bm


class TestBotManagerAgentOwner:
    @pytest.mark.asyncio
    async def test_create_with_agent_owner(self, bot_manager):
        config = {"system_prompt": "You are a helper."}
        status = await bot_manager.create_ephemeral_user_bot(
            owner_id="agent:parent-123",
            owner_kind="agent",
            config=config,
            uploaded_paths=[],
            ttl_seconds=300,
        )
        assert status.owner_kind == "agent"
        assert status.owner_id == "agent:parent-123"
        assert status.phase == "ready"  # app=None → skip warm-up

    @pytest.mark.asyncio
    async def test_create_with_user_id_compat(self, bot_manager):
        config = {"system_prompt": "You are a helper."}
        status = await bot_manager.create_ephemeral_user_bot(
            user_id=42,
            config=config,
            uploaded_paths=[],
        )
        assert status.owner_kind == "user"
        assert status.user_id == 42

    def test_get_status_agent_owner(self, bot_manager):
        # After create, get_ephemeral_status should find by owner_id
        ...

    @pytest.mark.asyncio
    async def test_discard_agent_owner(self, bot_manager):
        # After create + discard, bot and registry entry are gone
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/FEAT-208-spawn-ephemeral-subagent-tool.spec.md` §2-§3 (M2)
2. **Check dependencies** — TASK-1387 must be in `sdd/tasks/completed/`
3. **Read** `packages/ai-parrot-server/src/parrot/handlers/agents/ephemeral.py` to
   understand the HTTP handler's caller signatures (DO NOT modify it)
4. **Verify the Codebase Contract** — confirm all signatures, especially after TASK-1387 changes
5. **Update status** in `sdd/tasks/index/spawn-ephemeral-subagent-tool.json` → `"in-progress"`
6. **Implement** the ownership-aware methods
7. **Run**: `pytest packages/ai-parrot-server/tests/ -k ephemeral -v`
8. **Verify** all acceptance criteria
9. **Move this file** to `sdd/tasks/completed/` and update index → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-06-01
**Notes**: Generalized `create_ephemeral_user_bot`, `get_ephemeral_status`, and
`discard_ephemeral_user_bot` to accept `owner_id: str` + `owner_kind: str` keyword
args alongside legacy `user_id: int` positional args. For agent-owned bots,
`UserBotModel` receives `user_id=0` as placeholder (never persisted). All three
methods normalize `user_id` → `owner_id` internally. HTTP handler unchanged.
9 new tests, all passing.

**Deviations from spec**: none
