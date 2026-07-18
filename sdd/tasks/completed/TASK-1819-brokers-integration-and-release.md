# TASK-1819: Integration tests, acceptance sweep and 0.1.0rc release prep

**Feature**: FEAT-316 — EventBus Brokers Port
**Spec**: `sdd/specs/eventbus-brokers-port.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1818
**Assigned-to**: unassigned

> **Repo**: `/home/jesuslara/proyectos/navigator-eventbus`
> (worktree `.claude/worktrees/feat-FEAT-316-eventbus-brokers-port`).

---

## Context

Spec §3 Module 8 + §5. Per-module unit tests landed with TASK-1813…1818; this
task adds the Redis integration smoke tests, runs the full acceptance-criteria
sweep from the spec, and prepares the `0.1.0rc` (editable) release marker.

---

## Scope

- Create `tests/brokers/test_redis_integration.py` (marked `@pytest.mark.redis`,
  skipped when no live Redis):
  - `test_redis_publish_consume_roundtrip` — `RedisConnection.connect()` →
    `publish_message()` → `consume_messages()` → ACK.
  - `test_redis_consumer_subscribe_events` — `RedisConsumer.subscribe_to_events()`
    starts a background task and processes messages.
- Register the `redis` marker in pyproject/pytest config if not already present.
- Run the full acceptance sweep (spec §5) and record evidence:
  - `pytest tests/brokers/ -v` all green.
  - `ruff check src/navigator_eventbus/brokers/` clean.
  - `mypy src/navigator_eventbus/brokers/` passes or matches project baseline.
  - Import isolation proof: `python -c "from navigator_eventbus.brokers.redis import RedisConnection"`
    in an environment WITHOUT navigator installed (fresh venv or
    `pip uninstall navigator` in a throwaway venv — do NOT break the main venv).
  - `grep -rn "from navigator\.\|import navigator\." src/navigator_eventbus/brokers/` empty.
- Set version to `0.1.0rc1` in `pyproject.toml` (release-candidate marker per
  spec "Publish 0.1.0rc (editable) at close") and reinstall editable:
  `uv pip install -e ".[brokers,rabbitmq,sqs,serializer,dev]"`.

**NOT in scope**: publishing to PyPI; migrating ai-parrot imports (FEAT-317);
removing `navigator/brokers/` (phase 5); streams consolidation.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/brokers/test_redis_integration.py` | CREATE | Live-Redis smoke tests (`@pytest.mark.redis`) |
| `pyproject.toml` | MODIFY | `version = "0.1.0rc1"`; register `redis` pytest marker if missing |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-07-18.

### Verified Imports

```python
# Available after TASK-1815:
from navigator_eventbus.brokers.redis import RedisConnection, RedisConsumer, RedisProducer
```

### Existing Signatures to Use

```python
# From TASK-1815 (port of navigator/brokers/redis/connection.py):
class RedisConnection(BaseConnection):
    async def connect(self)
    async def disconnect(self)
    async def publish_message(self, body, queue_name=None, **kwargs)
    async def consume_messages(self, queue_name, callback, count=1, block=1000, **kwargs)
    async def reclaim_pending_messages(self, queue_name, callback, *,
                                       min_idle_time=30_000, count=10) -> int

class RedisConsumer(RedisConnection, BrokerConsumer):
    async def subscribe_to_events(self, queue_name, callback, **kwargs)
    async def stop_consumer(self)

# pyproject.toml: version = "0.1.0" at line ~7 (verified) → bump to "0.1.0rc1"
# NOTE: "0.1.0rc1" < "0.1.0" in PEP 440 ordering — this is intentional: the rc
# precedes the final 0.1.0 release.
```

### Does NOT Exist

- ~~CI service containers for Redis~~ — do not assume a Redis service in CI;
  the integration tests MUST auto-skip when Redis is unreachable
  (connect attempt with short timeout → `pytest.skip`).
- ~~`pytest.ini`~~ — pytest config lives in `pyproject.toml` (verify the
  `[tool.pytest.ini_options]` section before adding markers).

---

## Implementation Notes

### Pattern to Follow

```python
import pytest

pytestmark = pytest.mark.redis

@pytest.fixture
async def redis_conn():
    conn = RedisConnection()
    try:
        await asyncio.wait_for(conn.connect(), timeout=2)
    except Exception:
        pytest.skip("no live Redis available")
    yield conn
    await conn.disconnect()
```

### Key Constraints

- Use a unique stream name per test run (uuid suffix) and clean up
  (`XTRIM`/`DEL`) after the roundtrip to keep the Redis instance tidy.
- Evidence of the acceptance sweep goes in the Completion Note (paste command
  outputs summary).

---

## Acceptance Criteria

- [ ] `pytest tests/brokers/ -v` — ALL tests pass (integration tests skip
  gracefully without Redis, pass with a live Redis).
- [ ] `ruff check src/navigator_eventbus/brokers/` clean.
- [ ] `mypy src/navigator_eventbus/brokers/` passes or matches baseline.
- [ ] `python -c "from navigator_eventbus.brokers.redis import RedisConnection"`
  works without navigator installed (evidence in Completion Note).
- [ ] No file in `src/navigator_eventbus/brokers/` imports `navigator.*`.
- [ ] `pyproject.toml` version is `0.1.0rc1`; editable install with
  `[brokers,rabbitmq,sqs,dev]` succeeds.

---

## Test Specification

```python
# tests/brokers/test_redis_integration.py
import asyncio
import uuid
import pytest
from navigator_eventbus.brokers.redis import RedisConnection, RedisConsumer

pytestmark = pytest.mark.redis


async def test_redis_publish_consume_roundtrip(redis_conn):
    stream = f"it_stream_{uuid.uuid4().hex[:8]}"
    received = []

    async def cb(message_id, body):
        received.append(body)

    await redis_conn.publish_message({"hello": "world"}, queue_name=stream)
    await redis_conn.consume_messages(stream, cb, count=1, block=500)
    assert received and received[0].get("hello") == "world"


async def test_redis_consumer_subscribe_events():
    stream = f"it_stream_{uuid.uuid4().hex[:8]}"
    consumer = RedisConsumer(queue_name=stream)
    # connect (skip if unavailable), subscribe in background, publish, assert
    ...
```

---

## Agent Instructions

1. Read spec §4 (Integration Tests) and §5. Check TASK-1818 is in `sdd/tasks/completed/`.
2. Verify the Codebase Contract; update index → `"in-progress"`.
3. Implement, run the FULL acceptance sweep, record evidence.
4. Move this file to `sdd/tasks/completed/`, index → `"done"`, fill Completion
   Note (this is the last task — `/sdd-done FEAT-316` follows).

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-18
**Notes**: Added `tests/brokers/test_redis_integration.py` (`@pytest.mark.redis`,
gracefully skips without a live Redis — verified both ways: 2 passed against
the local docker Redis, 2 skipped when pointed at an unreachable host) and
bumped `pyproject.toml` to `version = "0.1.0rc1"` (worktree
`feat-FEAT-316-eventbus-brokers-port`, commit `f741baf`). Full acceptance
sweep evidence:
- `pytest tests/ -v` (whole repo, not just `tests/brokers/`) → **228 passed**.
- `ruff check src/navigator_eventbus/brokers/` → clean.
- `mypy src/navigator_eventbus/brokers/` → reduced from 88 to **67 residual
  errors** via a mechanical fix pass (implicit-`Optional` wrapping on ~15
  `credentials`/`app`/`callback` params, a `_name_: str` base attribute so
  subclasses satisfy it, `BaseWrapper.coro` retyped `Any` instead of
  `Optional[Any]` to dodge a mypy None-union quirk, `setup(app: Any)` instead
  of `Optional[web.Application]` since it's genuinely duck-typed, 2×
  `# type: ignore[attr-defined]` on `self.logger.notice()` — a real navconfig
  log level absent from typeshed's `logging` stubs). This got the SHARED base
  modules (`connection.py`, `producer.py`, `consumer.py`, `wrapper.py`,
  `serializers.py`, `__init__.py`) to **0 mypy errors**. The remaining 67 are
  all inside `redis/rabbitmq/sqs` `connection.py`/`consumer.py`: (a)
  `Optional` connection/channel attributes (`self._connection`,
  `self._channel`) used without a null-guard at dozens of call sites — ported
  verbatim from a codebase that was never mypy-checked; (b) genuine Liskov
  violations where each broker's `publish_message`/`consume_messages`/
  `process_message`/`wrap_callback` signature legitimately differs from the
  ABC (different queue models: Redis Streams vs. AMQP vs. SQS long-polling).
  Fixing (a) exhaustively means an `assert self._channel is not None`-style
  guard before nearly every RabbitMQ/Redis channel call; fixing (b) means
  redesigning method signatures to a common cross-broker protocol — both are
  out of scope for a fix-desacouple-and-port task (Cardinal Rule 1: builder,
  not architect) and would risk diverging from "port as-is" for behavior that
  already works (31 broker unit/integration tests + 228 repo-wide tests all
  green). Invoking the acceptance criterion's own "or matches project
  baseline" clause for this residual — happy to file a follow-up task for a
  dedicated typing pass if desired.
- Import isolation: confirmed `navigator` is not installed in this venv at
  all (`ModuleNotFoundError`), then `from navigator_eventbus.brokers.redis
  import RedisConnection` succeeded cleanly.
- `grep -rn "from navigator\.\|import navigator\." src/navigator_eventbus/brokers/` → empty.
- `uv pip install -e ".[brokers,rabbitmq,sqs,serializer,dev]"` and
  `".[brokers,rabbitmq,sqs,dev]"` both succeed against `0.1.0rc1`.

**Deviations from spec**: the mypy acceptance criterion is satisfied via the
"matches project baseline" allowance rather than a fully clean run — see the
detailed breakdown above. No other deviations; this is the last task for
FEAT-316.
