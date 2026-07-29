---
type: Wiki Overview
title: 'TASK-1380: SuspendedExecution model + SuspendedExecutionStore (Redis)'
id: doc:sdd-tasks-completed-task-1380-suspended-execution-store-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module 2. `answer_memory[turn_id]` stores `{question, answer}` —
  enough
relates_to:
- concept: mod:parrot.human.manager
  rel: mentions
---

# TASK-1380: SuspendedExecution model + SuspendedExecutionStore (Redis)

**Feature**: FEAT-204 — HITL over Stateless Web Request/Response (AgentTalk HTTP)
**Spec**: `sdd/specs/hitl_web.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2. `answer_memory[turn_id]` stores `{question, answer}` — enough
to rebuild a follow-up *prompt*, but HITL resume needs the *tool-loop* state. This
task adds a Pydantic `SuspendedExecution` model and a Redis-backed store keyed by
`hitl:suspended:{interaction_id}`, with TTL aligned to `hitl:interaction:{id}` so
expiry stays coherent and lazy (spec Decision B / OQ-2 resolved: dedicated key,
not folded into `hitl:callback:`).

---

## Scope

- Define `SuspendedExecution(BaseModel)` with fields: `interaction_id: str`,
  `session_id: str`, `user_id: str`, `agent_name: str`, `tool_call_id: str`,
  `messages: list[dict]`, `created_at: datetime`.
- Implement `SuspendedExecutionStore` with async methods:
  - `save(record: SuspendedExecution, ttl: int) -> None` → `setex` JSON at
    `hitl:suspended:{interaction_id}`.
  - `load(interaction_id: str) -> Optional[SuspendedExecution]` → `get` + parse;
    `None` when absent.
  - `delete(interaction_id: str) -> None` → `del` the suspended key ONLY.
    Must NOT delete `hitl:interaction:{id}` (escalation seam — let TTL own it).
- Store accepts a `redis.asyncio` client (constructor injection), mirroring
  `RedisTokenStore` in `parrot/mcp/oauth.py`.
- Key helper `_key(interaction_id) -> "hitl:suspended:{id}"`.
- Unit tests with `fakeredis.aioredis`.

**NOT in scope**: computing the TTL (caller passes it, sourced from
`manager._compute_ttl`); the handler that calls save/load (TASK-1382/1383);
the tool (TASK-1379/1381).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/human/suspended_store.py` | CREATE | `SuspendedExecution` + `SuspendedExecutionStore` |
| `packages/ai-parrot-server/tests/test_suspended_store.py` | CREATE | Unit tests (fakeredis) |

> Place the module under the ai-parrot-server `parrot/human/` namespace. If that
> directory does not exist in ai-parrot-server, co-locate next to
> `handlers/web_hitl.py` instead and adjust the import path — verify before
> creating.

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import redis.asyncio as aioredis            # used by parrot.human.manager (manager.py:138)
from pydantic import BaseModel, Field
# TTL source (caller-provided): HumanInteractionManager._compute_ttl  (human/manager.py:141)
```

### Existing Signatures to Use
```python
# Pattern reference — packages/ai-parrot/src/parrot/mcp/oauth.py
class RedisTokenStore(TokenStore):
    def __init__(self, redis): self.redis = redis
    @staticmethod
    def _key(user_id, server_name) -> str: return f"mcp:oauth:{server_name}:{user_id}"
    async def get(self, ...): raw = await self.redis.get(self._key(...)); return json.loads(raw) if raw else None
    async def set(self, ...): await self.redis.set(self._key(...), json.dumps(token))
    async def delete(self, ...): await self.redis.delete(self._key(...))

# Existing HITL Redis keys (DO NOT collide / DO NOT delete the interaction key)
#   hitl:interaction:{id}  (manager.py:165)   hitl:responses:{id} (188)
#   hitl:result:{id}       (manager.py:215)   hitl:callback:{id}  (498)
# NEW key owned by this task: hitl:suspended:{id}
```

### Does NOT Exist
- ~~`SuspendedExecution` / `SuspendedExecutionStore`~~ — you are creating them.
- ~~`hitl:suspended:{id}` key~~ — new; no other code reads/writes it yet.
- ~~a Redis store base class in parrot/~~ — none; follow `RedisTokenStore` by
  hand, the manager itself just uses `redis.asyncio` directly.
- ~~`redis.setex` with a Pydantic object~~ — serialize with
  `record.model_dump_json()` (Pydantic v2) first.

---

## Implementation Notes

### Pattern to Follow
```python
class SuspendedExecutionStore:
    def __init__(self, redis):
        self.redis = redis
        self.logger = logging.getLogger(__name__)

    @staticmethod
    def _key(interaction_id: str) -> str:
        return f"hitl:suspended:{interaction_id}"

    async def save(self, record: SuspendedExecution, ttl: int) -> None:
        await self.redis.setex(self._key(record.interaction_id), ttl, record.model_dump_json())
```

### Key Constraints
- Async throughout; Pydantic v2 (`model_dump_json` / `model_validate_json`).
- `datetime` must serialize/deserialize cleanly (Pydantic handles ISO-8601).
- `delete` removes ONLY `hitl:suspended:{id}`.
- `self.logger`, never `print`.

### References in Codebase
- `parrot/mcp/oauth.py` — `RedisTokenStore` pattern.
- `parrot/human/manager.py:141` — `_compute_ttl` (TTL source for callers).
- `parrot/human/manager.py:138` — `redis.asyncio.from_url(..., decode_responses=True)`.

---

## Acceptance Criteria

- [ ] `SuspendedExecution` has exactly the 7 fields listed in scope.
- [ ] `save`→`load` round-trips an equal record; TTL is applied via `setex`.
- [ ] `load` of a missing id returns `None`.
- [ ] `delete` removes only the `hitl:suspended:{id}` key.
- [ ] Key format is `hitl:suspended:{interaction_id}`.
- [ ] Tests pass: `pytest packages/ai-parrot-server/tests/test_suspended_store.py -v`
- [ ] No lint errors: `ruff check packages/ai-parrot-server/src/parrot/human/suspended_store.py`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/test_suspended_store.py
import pytest
from datetime import datetime, timezone

async def test_roundtrip(store):
    rec = SuspendedExecution(interaction_id="i1", session_id="s", user_id="u",
        agent_name="a", tool_call_id="t1", messages=[{"role":"user","content":"hi"}],
        created_at=datetime.now(timezone.utc))
    await store.save(rec, ttl=120)
    loaded = await store.load("i1")
    assert loaded == rec

async def test_load_missing_returns_none(store):
    assert await store.load("nope") is None

async def test_delete_only_suspended_key(store, fake_redis):
    await fake_redis.set("hitl:interaction:i1", "{}")
    rec = SuspendedExecution(interaction_id="i1", ...)
    await store.save(rec, ttl=120); await store.delete("i1")
    assert await store.load("i1") is None
    assert await fake_redis.get("hitl:interaction:i1") is not None  # untouched
```

---

## Agent Instructions

Standard flow: read the spec, confirm the ai-parrot-server `parrot/human/`
location (or co-locate by `web_hitl.py`), implement, test, move this file to
`sdd/tasks/completed/`, update `sdd/tasks/index/hitl_web.json` to `done`, fill
the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
