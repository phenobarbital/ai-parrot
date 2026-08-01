# TASK-2049: RedisCheckpointStore — ephemeral tier (TTL, history, lease)

**Feature**: FEAT-399 — AgentsFlow State Checkpointing (Two-Tier Persistence)
**Spec**: `sdd/specs/agentsflow-state-checkpointing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2046, TASK-2047, TASK-2048
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 — the default (ephemeral) tier: happy-path flows write
checkpoints here and let them expire. Per-flow latest pointer + bounded
history + TTL refreshed on every write, and the resume lease (resolved OQ3).

---

## Scope

- Implement `store/redis.py`: `RedisCheckpointStore(CheckpointStore)` using
  the AsyncDB `redis` driver (FEAT-147 `RedisResultStorage` connection
  pattern: lazy `_ensure()`, idempotent `close()`).
- Data layout per flow (all keys share the flow's TTL, refreshed on `put`):
  - `flowckpt:{flow_id}:latest` → latest checkpoint_id
  - `flowckpt:{flow_id}:cp:{checkpoint_id}` → ormsgpack bytes (serializer from TASK-2047)
  - `flowckpt:{flow_id}:history` → zset (score=checkpoint_id), trimmed to N
  - `flowckpt:{flow_id}:lease` → holder id, `SET NX PX` for `acquire_lease`
- TTL default from `FLOW_CHECKPOINT_REDIS_TTL` (86400), history N from
  `FLOW_CHECKPOINT_HISTORY` (10); both overridable via constructor.
- Trimming: on `put`, remove zset members (and their `cp:` keys) beyond N.
- `list_flows(status=...)` — scan `flowckpt:*:latest`, decode status from the
  latest checkpoint of each flow.
- Lease: `acquire_lease` = `SET key holder NX PX ttl*1000`; `renew_lease`
  only when current value == holder; `release_lease` only when holder matches.
- Unit tests against test Redis (skip when unavailable — see existing fixture
  conventions in `packages/ai-parrot/tests/`).

**NOT in scope**: durable stores (TASK-2050), checkpointer (TASK-2051),
dump-to-durable logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/store/redis.py` | CREATE | RedisCheckpointStore |
| `packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/store/__init__.py` | MODIFY | Re-export |
| `packages/ai-parrot/tests/flows/checkpoint/test_redis_store.py` | CREATE | Unit tests (skippable) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from asyncdb import AsyncDB                                     # verified: used at core/storage/backends/redis.py (module header)
from parrot.conf import FLOW_CHECKPOINT_REDIS_TTL, FLOW_CHECKPOINT_HISTORY, FLOW_CHECKPOINT_LEASE_TTL  # from TASK-2048
from parrot.bots.flows.core.checkpoint.store.base import CheckpointStore     # from TASK-2048
from parrot.bots.flows.core.checkpoint.serializer import FlowStateSerializer # from TASK-2047
from parrot.bots.flows.core.checkpoint.model import FlowCheckpoint           # from TASK-2046
```

### Existing Signatures to Use (pattern reference)
```python
# packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/redis.py
class RedisResultStorage(ResultStorage):        # line 21 — CONNECTION PATTERN to copy
    def __init__(self, dsn=None, ttl=None): ... # line 29 — AsyncDB redis driver, lazy _ensure(),
                                                #   TTL default via conf constant
```
Read `backends/redis.py` in full before implementing — reuse its AsyncDB
connection/DSN conventions and `close()` idempotency exactly.

### Does NOT Exist
- ~~`RedisCheckpointStore`~~ — introduced HERE.
- ~~Direct `redis.asyncio` client usage in the FEAT-147 backends~~ — they go through `AsyncDB`; do the same unless a needed primitive (SET NX PX, ZADD/ZREMRANGEBYRANK) is unavailable through AsyncDB — verify first, and if you must drop to the raw connection, document it in the completion note.
- ~~`RedisResultStorage.list()` as a pattern for reads~~ — it full-SCANs (spec Option B con); keep per-flow reads on direct keys, scan ONLY in `list_flows`.

---

## Implementation Notes

### Key Constraints
- Every write path refreshes TTL on ALL of the flow's keys (latest, cp:*, history, NOT the lease — lease has its own PX TTL).
- `latest()`/`get()` return `None` on miss; `history(limit)` newest-first.
- `delete_flow` removes every `flowckpt:{flow_id}:*` key.
- Fire-and-forget discipline lives in the checkpointer, NOT here — store
  methods raise on failure; callers decide.
- `self.logger` for connection lifecycle; no prints.

---

## Acceptance Criteria

- [ ] `test_redis_store_latest_history_trim_ttl` — latest pointer correct, zset trimmed to N=10, TTL present on keys after write.
- [ ] `test_redis_lease_acquire_conflict_renew_expiry` — second acquire False; renew only by holder; expiry allows takeover.
- [ ] Store contract methods all implemented (no `NotImplementedError` left).
- [ ] Tests skip cleanly when Redis is unavailable.
- [ ] `pytest packages/ai-parrot/tests/flows/checkpoint/test_redis_store.py -v` passes; `ruff check` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/checkpoint/test_redis_store.py
pytestmark = pytest.mark.skipif(no_redis(), reason="redis unavailable")

async def test_latest_history_trim_ttl(redis_store, sample_checkpoint):
    for i in range(1, 13):
        await redis_store.put(sample_checkpoint(checkpoint_id=i))
    assert (await redis_store.latest("f1")).checkpoint_id == 12
    hist = await redis_store.history("f1", limit=20)
    assert len(hist) == 10 and hist[0].checkpoint_id == 12

async def test_lease_lifecycle(redis_store):
    assert await redis_store.acquire_lease("f1", "holder-a", ttl=60)
    assert not await redis_store.acquire_lease("f1", "holder-b", ttl=60)
    assert await redis_store.renew_lease("f1", "holder-a", ttl=60)
    assert not await redis_store.renew_lease("f1", "holder-b", ttl=60)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** for full context
2. **Check dependencies** — TASK-2046/2047/2048 in `tasks/completed/`
3. **Verify the Codebase Contract** — read `core/storage/backends/redis.py` in full first
4. **Update status** in `sdd/tasks/index/agentsflow-state-checkpointing.json` → `"in-progress"`
5. **Implement**, then **verify** all acceptance criteria
6. **Move this file** to `sdd/tasks/completed/` and update index → `"done"`
7. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
