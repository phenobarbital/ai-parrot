# TASK-5033: RedisConnectionPush — per-principal Redis pub/sub sink

**Feature**: FEAT-777 — Connections — Web + Slack
**Spec**: `sdd/specs/connections-web-slack.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5032
**Assigned-to**: unassigned

---

## Context

Spec §2 "Push (M1, D1)": every connection event is published to the Redis channel
`parrot:connections:user:{user_id}` so that any gunicorn worker serving an SSE stream for that principal
receives it. `RedisConnectionPush` is the server-side `ConnectionEventSink` (from TASK-5032) that publishes,
and also the subscription source the SSE handler (TASK-5040) iterates. Implements spec §3 Module 1 (server service).

---

## Scope

- Create `packages/ai-parrot-server/src/parrot/services/connection_push.py` with `CHANNEL_TEMPLATE` and
  `RedisConnectionPush(redis_url)`: `start()`, `close()`, `deliver(event)`, `subscribe(user_id)`.
- `deliver` publishes `event.model_dump_json()` on `CHANNEL_TEMPLATE.format(user_id=event.user_id)`; it is a logged
  no-op before `start()` and swallows nothing silently (errors are logged and re-raised so the publisher's isolation logs them).
- `subscribe(user_id)` is an async generator with **its own** pubsub per call; it yields `ConnectionEvent`
  instances parsed with `ConnectionEvent.model_validate_json`; malformed messages are logged and skipped;
  it always unsubscribes and closes the pubsub in `finally` (cancellation included).
- Write tests against a real Redis (db 15, skip if unreachable — `fakeredis` is not installed).

**NOT in scope**: SSE handler, route, startup/cleanup wiring and `add_sink` registration (TASK-5040).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/services/connection_push.py` | CREATE | `RedisConnectionPush` + `CHANNEL_TEMPLATE` |
| `packages/ai-parrot-server/tests/unit/test_connection_push.py` | CREATE | Real-Redis unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import redis.asyncio as aioredis                                   # redis 5.2.1 in .venv; pattern: manager/manager.py:1730, handlers/liveavatar_output.py:126
from parrot.auth.oauth2.events import ConnectionEvent              # verified: packages/ai-parrot/src/parrot/auth/oauth2/events.py:17
from parrot.auth.oauth2.events import ConnectionEventSink          # created by TASK-5032 (events.py)
from parrot.conf import REDIS_URL                                  # verified: packages/ai-parrot/src/parrot/conf.py:308
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/oauth2/events.py:17 — pydantic v2 model; no token material
class ConnectionEvent(BaseModel):
    kind; user_id: str; canonical_identity; tenant_id; provider: str; account_id; display_name; channel: str; occurred_at: float; reason

# Pattern — packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/output_transport.py:100-137
#   pubsub = redis_client.pubsub(); await pubsub.subscribe(channel)
#   async for raw in pubsub.listen(): if raw.get("type") != "message": continue ...
#   finally: await pubsub.unsubscribe(channel)
# Pattern — packages/ai-parrot-server/src/parrot/handlers/liveavatar_output.py:126-156
#   aioredis.from_url(url, decode_responses=True); close via getattr(redis, "aclose", None) or "close"
```

### Does NOT Exist
- ~~`parrot.services.connection_push`~~ — created here.
- ~~`fakeredis`~~ — not installed in the venv; do not import it.
- ~~A shared/broadcast Redis channel for all users~~ — the channel is per principal only (spec D1).
- ~~Message buffering/replay~~ — the stream is a hint; `GET /api/v1/connections` is authoritative (spec §2).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/services/connection_push.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/tests/unit/test_connection_push.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/events.py#ConnectionEvent"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- One Redis client for publishing (created in `start()`); every `subscribe()` call opens its own `pubsub()` on that client
  (spec §7 "one pubsub connection per open panel tab").
- Payload equals `ConnectionEvent.model_dump_json()` exactly — no extra keys, never token material (AC-3).
- `decode_responses=True` so `raw["data"]` is `str`.
- `self.logger = logging.getLogger(__name__)`; no `print`.

---

## Implementation Blueprint

### Steps (in order)
1. Create the module from the block below — *why*: the skeleton fixes the public names the SSE handler (TASK-5040) imports.
2. Complete `subscribe` (FILL IN) — *why*: cancellation safety is a judgement call per spec ("unsubscribes and closes on cancellation").
3. Write the tests with the real-Redis fixture and run them.

### `packages/ai-parrot-server/src/parrot/services/connection_push.py` (CREATE)
```python
"""Per-principal Redis fan-out of connection events (FEAT-777 M1)."""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Optional

import redis.asyncio as aioredis

from parrot.auth.oauth2.events import ConnectionEvent

CHANNEL_TEMPLATE = "parrot:connections:user:{user_id}"


class RedisConnectionPush:
    """``ConnectionEventSink`` that publishes every event on the principal's Redis channel.

    Any gunicorn worker may publish; any worker may serve the subscriber (``subscribe``).
    """

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._redis: Optional[Any] = None
        self.logger = logging.getLogger(__name__)

    async def start(self) -> None:
        """Create the Redis client (aiohttp ``on_startup``)."""
        if self._redis is None:
            self._redis = aioredis.from_url(self._redis_url, decode_responses=True)

    async def close(self) -> None:
        """Close the Redis client (aiohttp ``on_cleanup``); safe to call twice."""
        redis, self._redis = self._redis, None
        if redis is not None:
            close = getattr(redis, "aclose", None) or getattr(redis, "close", None)
            if close is not None:
                result = close()
                if hasattr(result, "__await__"):
                    await result

    async def deliver(self, event: ConnectionEvent) -> None:
        """PUBLISH ``event.model_dump_json()`` on ``CHANNEL_TEMPLATE.format(user_id=event.user_id)``."""
        if self._redis is None:
            self.logger.warning("RedisConnectionPush.deliver before start(); event for provider %s dropped", event.provider)
            return
        await self._redis.publish(CHANNEL_TEMPLATE.format(user_id=event.user_id), event.model_dump_json())

    async def subscribe(self, user_id: str) -> AsyncIterator[ConnectionEvent]:
        """Yield the principal's events; own pubsub per call; unsubscribes and closes on exit/cancellation."""
        if self._redis is None:
            raise RuntimeError("RedisConnectionPush.subscribe before start()")
        channel = CHANNEL_TEMPLATE.format(user_id=user_id)
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(channel)
        try:
            # FILL IN: `async for raw in pubsub.listen()`, skip non-"message" types, parse with
            #   ConnectionEvent.model_validate_json(raw["data"]); log+skip malformed; yield — bounded by spec M1 skeleton
            ...
        finally:
            # FILL IN: await pubsub.unsubscribe(channel) then close the pubsub (aclose/close, awaited if awaitable);
            #   never raise from finally — bounded by "unsubscribes and closes on cancellation"
            ...
```
**Why this shape**: `subscribe` is declared `def` in the spec skeleton returning `AsyncIterator`; implementing it as
an `async def` generator satisfies that contract (calling it returns an async iterator). Keep `deliver` raising on Redis
errors — the publisher (TASK-5032) logs sink failures; swallowing here would hide outages.

### `packages/ai-parrot-server/tests/unit/test_connection_push.py` (CREATE)
```python
"""Real-Redis tests for RedisConnectionPush (FEAT-777 M1). Skips when Redis db 15 is unreachable."""

from __future__ import annotations

import asyncio
import time
import uuid

import pytest

from parrot.auth.oauth2.events import ConnectionEvent, ConnectionEventSink
from parrot.services.connection_push import CHANNEL_TEMPLATE, RedisConnectionPush

REDIS_TEST_URL = "redis://localhost:6379/15"


@pytest.fixture
async def push():
    p = RedisConnectionPush(REDIS_TEST_URL)
    await p.start()
    try:
        await p._redis.ping()
    except Exception as exc:  # noqa: BLE001
        await p.close()
        pytest.skip(f"Redis unreachable: {exc}")
    yield p
    await p.close()


def _event(user_id: str) -> ConnectionEvent:
    return ConnectionEvent(kind="connection.completed", user_id=user_id, provider="jira", channel="telegram", occurred_at=time.time())


@pytest.mark.asyncio
async def test_redis_push_channel_per_principal(push) -> None:
    """deliver publishes on the principal's channel only; payload equals ConnectionEvent fields (no token keys)."""
    # FILL IN: unique user ids (uuid); subscribe user A and B; deliver for A; A receives equal event within 2 s; B receives nothing
    ...


@pytest.mark.asyncio
async def test_subscribe_unsubscribes_on_cancel(push) -> None:
    """Cancelling the consumer task unsubscribes (PUBSUB NUMSUB drops to 0)."""
    # FILL IN: consume in a task, cancel it, then assert (await push._redis.pubsub_numsub(channel)) count == 0
    ...


def test_is_a_connection_event_sink() -> None:
    assert isinstance(RedisConnectionPush(REDIS_TEST_URL), ConnectionEventSink)
    assert CHANNEL_TEMPLATE.format(user_id="7") == "parrot:connections:user:7"
```

### FILL IN checklist
- [ ] `subscribe` body and `finally` — bounded by spec M1 (own pubsub per call, unsubscribe on cancellation).
- [ ] Tests — bounded by spec §4 `test_redis_push_channel_per_principal`, AC-3 (2 s, no other principal).

---

## Acceptance Criteria

- [ ] `from parrot.services.connection_push import RedisConnectionPush, CHANNEL_TEMPLATE` works.
- [ ] Events reach only `parrot:connections:user:{user_id}`; payload is exactly `ConnectionEvent.model_dump_json()`.
- [ ] Cancelled subscribers unsubscribe; malformed messages are skipped, not fatal.
- [ ] Tests pass (or skip cleanly without Redis); `ruff check` clean on both files.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/unit/test_connection_push.py -q`

---

## Test Specification

See the CREATE test block above.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug connections-web-slack --feature-id FEAT-777`)
2. **Read the spec** (§2 "Push (M1, D1)", §3 Module 1, §7 Redis connection count)
3. **Check dependencies** — TASK-5032 must be `"done"` in `sdd/tasks/index/connections-web-slack.json`
4. **Verify the Codebase Contract** before writing code
5. **Update status** → `"in-progress"` and commit only the index file
6. **Implement** from the blueprint; complete every `# FILL IN:`
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`
8. **Commit the code** — only the listed files
9. **Close the task** with `scripts/sdd/close_task.sh TASK-5033 connections-web-slack verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker orchestrator; seats codex terra/sol/luna + native sonnet
**Date**: 2026-10-31
**Notes**: Implemented per task; merged and merge-tier validated (only red: 3 failures that also fail on origin/dev: test_o365_refresh x2, slack test_manager_payload_drives_identity_and_dm).

**Deviations from spec**: none | describe if any
