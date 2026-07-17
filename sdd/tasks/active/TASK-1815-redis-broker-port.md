# TASK-1815: Port Redis broker with PR #393 fixes (kwargs.pop, XAUTOCLAIM, creds keyword)

**Feature**: FEAT-316 — EventBus Brokers Port
**Spec**: `sdd/specs/eventbus-brokers-port.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1814
**Assigned-to**: unassigned

> **Repo**: `/home/jesuslara/proyectos/navigator-eventbus`
> (worktree `.claude/worktrees/feat-FEAT-316-eventbus-brokers-port`).
> Source: `/home/jesuslara/proyectos/navigator/navigator/brokers/redis/`.

---

## Context

Spec §3 Module 3. The Redis broker carries all three PR navigator#393 bugs.
This task ports `redis/{connection,consumer,producer}.py` (284+146+38 LOC)
applying fix #1 (kwargs.pop), fix #2 (XAUTOCLAIM PEL sweep), and inheriting
fix #3 from TASK-1814, plus the navconfig/serialization/ValidationError desacoples.

---

## Scope

- Create `src/navigator_eventbus/brokers/redis/__init__.py` re-exporting
  `RedisConnection`, `RedisConsumer`, `RedisProducer`.
- Create `redis/connection.py` — port `RedisConnection`:
  - Credentials from navconfig locally (`REDIS_BROKER_HOST/PORT/PASSWORD/DB`,
    build `REDIS_BROKER_URL`) — via `brokers/_conf.py` (TASK-1814), NOT `navigator.conf`.
  - Replace `from datamodel.parsers.json import json_encoder, json_decoder` with
    `navigator_eventbus.serialization.dumps/loads`.
  - Drop `from navigator.exceptions import ValidationError` — catch `Exception`,
    log a warning (spec §3 Module 3).
  - **Fix #2**: add `async def reclaim_pending_messages(self, queue_name, callback, *,
    min_idle_time=30_000, count=10) -> int` using `self._connection.xautoclaim()`;
    opt-in (callers schedule it); handle `ResponseError` on Redis < 6.2 gracefully.
- Create `redis/consumer.py` — port `RedisConsumer`:
  - **Fix #1**: `kwargs.pop('queue_name', 'message_stream')` (and group/consumer)
    instead of `kwargs.get()`, and do NOT re-forward them as explicit kwargs AND
    inside `**kwargs` to `super().__init__()`.
- Create `redis/producer.py` — port `RedisProducer` (inherits fix #3).
- Tests: `tests/brokers/test_redis_consumer.py` (kwargs fix, defaults),
  `tests/brokers/test_redis_reclaim.py` (XAUTOCLAIM sweep with mocked redis).

**NOT in scope**: rabbitmq/sqs ports; hook rewiring; live-Redis integration
tests (TASK-1819).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `src/navigator_eventbus/brokers/redis/__init__.py` | CREATE | Re-exports |
| `src/navigator_eventbus/brokers/redis/connection.py` | CREATE | `RedisConnection` + fix #2 |
| `src/navigator_eventbus/brokers/redis/consumer.py` | CREATE | `RedisConsumer` + fix #1 |
| `src/navigator_eventbus/brokers/redis/producer.py` | CREATE | `RedisProducer` |
| `tests/brokers/test_redis_consumer.py` | CREATE | kwargs fix tests |
| `tests/brokers/test_redis_reclaim.py` | CREATE | XAUTOCLAIM sweep tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-07-18.

### Verified Imports

```python
# Keep:
from redis import asyncio as aioredis         # navigator/brokers/redis/connection.py:9
from datamodel import Model, BaseModel        # :10
from navconfig.logging import logging         # :11

# REPLACE during port:
# from datamodel.parsers.json import json_encoder, json_decoder  # :12 → serialization.dumps/loads
# from navigator.exceptions import ValidationError               # :13 → local Exception handling
# from ...conf import (REDIS_BROKER_HOST, REDIS_BROKER_PORT,     # :16-22 → brokers/_conf.py
#     REDIS_BROKER_PASSWORD, REDIS_BROKER_DB, REDIS_BROKER_URL)

# New internal imports:
from ..connection import BaseConnection       # from TASK-1814
from ..wrapper import BaseWrapper             # from TASK-1814
from navigator_eventbus.serialization import dumps, loads
```

### Existing Signatures to Use (source: navigator repo)

```python
# navigator/brokers/redis/connection.py:25
class RedisConnection(BaseConnection):
    def __init__(self, credentials=None, timeout=5, **kwargs)
    async def connect(self)
    async def disconnect(self)
    async def ensure_group_exists(self)
    async def publish_message(self, body, queue_name=None, **kwargs)
    async def process_message(self, message_data)
    async def consume_messages(self, queue_name, callback, count=1, block=1000, **kwargs)
    async def cleanup_old_messages(self, stream)

# navigator/brokers/redis/consumer.py:15 — THE BUG (verified :30-41):
#     self._queue_name = kwargs.get('queue_name', 'message_stream')
#     self._group_name = kwargs.get('group_name', 'default_group')
#     self._consumer_name = kwargs.get('consumer_name', 'default_consumer')
#     super().__init__(credentials=..., timeout=..., callback=...,
#         queue_name=self._queue_name, group_name=self._group_name,
#         consumer_name=self._consumer_name, **kwargs)   # ← duplicates → TypeError
class RedisConsumer(RedisConnection, BrokerConsumer):
    _name_: str = "redis_consumer"
    def __init__(self, credentials=None, timeout=5, callback=None, **kwargs)
    async def subscriber_callback(self, message_id, body)
    def wrap_callback(self, callback)
    async def event_subscribe(self, queue_name, callback, **kwargs)
    async def subscribe_to_events(self, queue_name, callback, **kwargs)
    async def stop_consumer(self)

# navigator/brokers/redis/producer.py:11
class RedisProducer(RedisConnection, BrokerProducer):

# navigator/conf.py:235-239 — values to localize in brokers/_conf.py:
REDIS_BROKER_HOST = config.get("REDIS_BROKER_HOST", fallback=CACHE_HOST)   # localize fallback to "localhost"
REDIS_BROKER_PORT = config.get("REDIS_BROKER_PORT", fallback=CACHE_PORT)   # localize fallback to 6379
REDIS_BROKER_PASSWORD = config.get("REDIS_BROKER_PASSWORD", fallback=None)
REDIS_BROKER_DB = config.get("REDIS_BROKER_DB", fallback=CACHE_DB)         # localize fallback to 0
REDIS_BROKER_URL = f"redis://{REDIS_BROKER_HOST}:{REDIS_BROKER_PORT}/{REDIS_BROKER_DB}"
```

### New Public Interface (spec §2, implement exactly)

```python
class RedisConnection(BaseConnection):
    async def reclaim_pending_messages(
        self,
        queue_name: str,
        callback: Callable,
        *,
        min_idle_time: int = 30_000,
        count: int = 10,
    ) -> int:
        """FIX #2: XAUTOCLAIM-based redelivery of stuck PEL entries."""
```

### Does NOT Exist

- ~~`XCLAIM`/`XAUTOCLAIM` anywhere in `navigator/brokers/`~~ — bug #2; the only
  existing XAUTOCLAIM reference in the ecosystem is
  `navigator_eventbus/backends/redis_streams.py` (`RedisStreamsBackend`) — you
  may READ it as a pattern reference but must NOT consolidate with it (non-goal,
  deferred to `eventbus-streams-consolidation`).
- ~~`navigator_eventbus.brokers.redis`~~ — created by THIS task.
- ~~CACHE_HOST/CACHE_PORT/CACHE_DB in navigator_eventbus~~ — those fallbacks are
  navigator-only; use plain defaults ("localhost", 6379, 0) in `_conf.py`.

---

## Implementation Notes

### Pattern to Follow (fix #1)

```python
self._queue_name = kwargs.pop('queue_name', 'message_stream')
self._group_name = kwargs.pop('group_name', 'default_group')
self._consumer_name = kwargs.pop('consumer_name', 'default_consumer')
super().__init__(credentials=credentials, timeout=timeout, callback=callback, **kwargs)
```

### Key Constraints

- `redis.asyncio.Redis.xautoclaim(name, groupname, consumername, min_idle_time,
  start_id='0-0', count=None)` returns `(next_start_id, claimed_messages, deleted_ids)`
  on redis-py >= 5 — verify against the installed redis version in the venv.
- Wrap XAUTOCLAIM in try/except for `redis.exceptions.ResponseError` (Redis < 6.2):
  log a warning and return 0.
- MRO caution (spec §7): `RedisConsumer(RedisConnection, BrokerConsumer)` and
  `RedisProducer(RedisConnection, BrokerProducer)` — cooperative `super()` chain;
  run the constructor tests early.

### References in Codebase

- `navigator/brokers/redis/*.py` (navigator repo) — sources; read IN FULL.
- `src/navigator_eventbus/backends/redis_streams.py` — existing XAUTOCLAIM usage pattern.

---

## Acceptance Criteria

- [ ] `RedisConsumer(queue_name="q", group_name="g", consumer_name="c")` does
  NOT raise `TypeError` (fix #1) and defaults apply when omitted.
- [ ] `RedisConnection.reclaim_pending_messages()` exists, uses XAUTOCLAIM,
  invokes the callback per claimed message, returns the claimed count (fix #2).
- [ ] Empty PEL → `reclaim_pending_messages` returns 0.
- [ ] No `navigator.*` imports in `src/navigator_eventbus/brokers/redis/`.
- [ ] All tests pass: `pytest tests/brokers/test_redis_consumer.py tests/brokers/test_redis_reclaim.py -v`
- [ ] `ruff check src/navigator_eventbus/brokers/redis/` passes.

---

## Test Specification

```python
# tests/brokers/test_redis_consumer.py
import pytest
from navigator_eventbus.brokers.redis import RedisConsumer


def test_redis_consumer_kwargs_pop():
    """PR #393 fix #1: explicit stream kwargs must not raise TypeError."""
    c = RedisConsumer(
        queue_name="test_stream",
        group_name="test_group",
        consumer_name="test_consumer",
    )
    assert c._queue_name == "test_stream"
    assert c._group_name == "test_group"
    assert c._consumer_name == "test_consumer"


def test_redis_consumer_default_kwargs():
    c = RedisConsumer()
    assert c._queue_name == "message_stream"
    assert c._group_name == "default_group"
    assert c._consumer_name == "default_consumer"


# tests/brokers/test_redis_reclaim.py
from unittest.mock import AsyncMock
from navigator_eventbus.brokers.redis import RedisConnection


async def test_reclaim_pending_messages(mock_redis):
    conn = RedisConnection()
    conn._connection = mock_redis
    mock_redis.xautoclaim = AsyncMock(
        return_value=(b"0-0", [(b"1-0", {b"data": b"{}"})], [])
    )
    seen = []
    async def cb(mid, body): seen.append(mid)
    n = await conn.reclaim_pending_messages("test_stream", cb)
    assert n == 1 and len(seen) == 1


async def test_reclaim_pending_empty_pel(mock_redis):
    conn = RedisConnection()
    conn._connection = mock_redis
    mock_redis.xautoclaim = AsyncMock(return_value=(b"0-0", [], []))
    n = await conn.reclaim_pending_messages("test_stream", lambda *a: None)
    assert n == 0
```

Fixture (spec §4): `mock_redis` — `AsyncMock` standing in for `aioredis.Redis`.

---

## Agent Instructions

1. Read spec §2, §3 Module 3, §7. Read the three redis source files IN FULL.
2. Check TASK-1814 is in `sdd/tasks/completed/`.
3. Verify the Codebase Contract; update index → `"in-progress"`.
4. Implement, run tests, move this file to `sdd/tasks/completed/`, index → `"done"`, fill Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
