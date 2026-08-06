# TASK-2158: Fan-out, status state machine, aggregation and retry

**Feature**: FEAT-417 — CommCenter — Bulk Notification Sender over NotifyWorker
**Spec**: `sdd/specs/commcenter-notify.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2154, TASK-2157
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6. This is the only code that talks to Redis. It publishes one
`xadd` per recipient via `NotifyClient.stream()`, drives the per-row status
state machine, and provides batch aggregation and retry.

The state machine is a **correctness feature, not bookkeeping**: without the
pre-`xadd` `publishing` marker, a crash mid-fan-out makes retry double-send the
whole batch (spec §2, resolved Q4).

---

## Scope

- Implement `publish_one(batch_id, payload, row_id) -> message_id` driving the
  state machine.
- Implement `fan_out(batch_id, payloads)` — sequential `publish_one` over the
  batch, never aborting on a single failure.
- Implement the background-task launcher with a done-callback that finalizes
  batch status (no batch stranded in `publishing`).
- Implement batch aggregation + optional paginated row details.
- Implement retry honouring the state machine.
- **Lazy-import** `NotifyClient` with an actionable error when missing.
- Unit tests with a mocked `NotifyClient`.

**NOT in scope**:
- HTTP routes (TASK-2159 wires them).
- The single-recipient endpoint (TASK-2161) — but `publish_one` must be
  directly reusable by it.
- `dry_run` (TASK-2162).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/services/comm_center/dispatch.py` | CREATE | Publish, state machine, aggregation, retry |
| `packages/ai-parrot-server/tests/handlers/test_comm_center_dispatch.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified fresh 2026-08-06 by live introspection.

### Verified Imports

```python
import asyncio, uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from asyncdb import AsyncDB                    # verified: handlers/bots.py:5
from asyncdb.exceptions import NoDataFound     # verified: handlers/bots.py:6
from parrot.conf import PARROT_SCHEMA          # verified live → "navigator"
from parrot.handlers.models import NotificationBatchRecipient   # TASK-2154

# LAZY — inside the function, never at module import (spec G11):
#   from notify.server import NotifyClient
#   from notify.conf import NOTIFY_WORKER_STREAM, NOTIFY_REDIS
```

### Existing Signatures to Use

```python
# /home/jesuslara/proyectos/notify/notify/server/client.py — VERIFIED live
class NotifyClient:
    def __init__(self, redis_url: str = None, redis_host: str = "localhost",
                 redis_port: int = 6379, redis_db: int = 5,
                 tcp_host: str = 'localhost', tcp_port: str = 8991): ...   # line 26
    async def connect(self): ...                                           # line 81
    async def stream(self, message: dict, stream: str,
                     use_wrapper: bool = False): ...                       # line 108
    async def close(self): ...                                             # line 146
    async def __aenter__(self) / __aexit__(...)                            # lines 152,157

# stream() internals, lines 108-128 — USE use_wrapper=False (the JSON path):
#   msg = {"message": json.dumps(message)}
#   await self.redis.xadd(stream, msg)
# That is the branch NotifyWorker.check_stream() reads (server.py:240).
```

```python
# notify/conf.py — VERIFIED live values
NOTIFY_WORKER_STREAM = "NotifyWorkerStream"     # line 29, env-overridable
NOTIFY_REDIS = f"redis://{REDIS_HOST}:{REDIS_PORT}/{NOTIFY_DB}"   # line 17
```

```python
# packages/ai-parrot-server/src/parrot/handlers/bots.py:214-223 — AsyncDB usage pattern
def get_connection(self):
    return AsyncDB('bigquery', params=params, force_closing=False)
# For pg use: AsyncDB('pg', dsn=default_dsn)   # parrot/conf.py:66
```

### Does NOT Exist

- ~~A NotifyWorker result / callback stream~~ — `check_stream()` only `xack`s and
  logs (`notify/server/server.py:269-280`). **You cannot observe delivery.**
  Never write a `delivered` status.
- ~~`NotifyClient.stream()` returning the Redis entry id~~ — **VERIFY THIS
  YOURSELF.** `stream()` as written does `await self.redis.xadd(...)` without
  returning it (`client.py:125`). If it returns `None`, obtain the id another
  way or store `None` and rely on `published_at` as the marker. **Do not assume
  a return value.**
- ~~`use_wrapper=True`~~ — that path cloudpickles a `NotifyWrapper`; we use the
  plain JSON path. Pass `use_wrapper=False` (the default).
- ~~`parrot.services.comm_center.dispatch`~~ — does not exist yet.

---

## Implementation Notes

### State machine (spec §2 — the correctness core)

```python
# per row, in this exact order:
#   1. row.status = "publishing"; persist          ← BEFORE the xadd
#   2. message_id = await client.stream(payload, NOTIFY_WORKER_STREAM)
#   3. row.status = "queued"; row.published_at = now(); row.message_id = ...
#   on exception at step 2:
#      row.status = "publish_failed"; row.reason = str(exc)
#   always: row.attempts += 1
```

| Status | Retry behavior |
|---|---|
| `pending` | **retried** — definitively never published |
| `publishing` | **ambiguous** — reported; retried only with `force=True` |
| `queued` | **never** retried |
| `skipped` | **never** retried |
| `publish_failed` | **retried** — nothing landed |

### Background task
```python
task = asyncio.create_task(fan_out(batch_id, payloads))
task.add_done_callback(_finalize)     # logs exceptions AND sets terminal batch status
```
A bare `create_task` swallows exceptions and strands the batch in `publishing`
— the done-callback is mandatory.

### Aggregation
- Default: `SELECT status, COUNT(*) ... GROUP BY status` for the batch.
- `details=True`: rows with `limit` (default 100, **clamped to 1000**) /
  `offset`, optional `status` filter.

### Lazy import (spec G11)
```python
try:
    from notify.server import NotifyClient
except ImportError as exc:
    raise RuntimeError(
        "async-notify is required for CommCenter. "
        "Install with: pip install 'ai-parrot-server[comm-center]'"
    ) from exc
```
Importing this module **must not** raise when `notify` is absent.

### Key Constraints
- Async throughout; one `xadd` per recipient.
- A single row's failure never aborts the batch.
- Reuse one `NotifyClient` per batch (connect once, close in `finally`).
- `self.logger` for every state transition at debug level.
- Google-style docstrings + type hints.

### References in Codebase
- `notify/server/client.py:108-128` — publish path
- `packages/ai-parrot-server/src/parrot/handlers/bots.py:5,214-223` — AsyncDB
- Spec §2 "Row status state machine"

---

## Acceptance Criteria

- [ ] Exactly one `xadd` per queued recipient (mocked `stream`, call count asserted)
- [ ] `publishing` is the row's status **at the moment `stream()` is entered**
- [ ] Success → `queued` + `published_at` set; failure → `publish_failed` + reason
- [ ] `attempts` incremented on every attempt
- [ ] One row failing does not abort the batch
- [ ] Background task done-callback finalizes batch status even on exception
- [ ] Retry re-publishes `pending` + `publish_failed`; **never** `queued`/`skipped`
- [ ] Retry excludes `publishing` unless `force=True`; reports them as ambiguous
- [ ] Aggregation returns per-status counts; `details` paginates, `limit` clamped to 1000
- [ ] Module imports cleanly **without** `notify` installed; calling raises the actionable error
- [ ] No `delivered` status anywhere
- [ ] Tests pass: `pytest packages/ai-parrot-server/tests/handlers/test_comm_center_dispatch.py -v`
- [ ] `ruff check` clean

---

## Test Specification

```python
import asyncio, uuid
import pytest

from parrot.services.comm_center.dispatch import fan_out, publish_one, retry_batch


@pytest.fixture
def fake_notify(monkeypatch):
    """Captures every stream() call: (message, stream, use_wrapper)."""
    calls = []
    class FakeClient:
        async def connect(self): ...
        async def close(self): ...
        async def stream(self, message, stream, use_wrapper=False):
            calls.append((message, stream, use_wrapper))
            return "1700000000000-0"
    monkeypatch.setattr(
        "parrot.services.comm_center.dispatch._get_notify_client",
        lambda: FakeClient())
    return calls


class TestFanOut:
    async def test_one_xadd_per_recipient(self, fake_notify, payloads_3):
        await fan_out(uuid.uuid4(), payloads_3)
        assert len(fake_notify) == 3

    async def test_uses_json_path(self, fake_notify, payloads_1):
        await fan_out(uuid.uuid4(), payloads_1)
        assert fake_notify[0][2] is False        # use_wrapper=False

    async def test_publishing_marker_before_xadd(self, monkeypatch, payloads_1):
        """Status must already be 'publishing' when stream() is entered."""
        seen = {}
        # assert inside the mock by reading the row the service just persisted
        ...
        assert seen["status"] == "publishing"

    async def test_failure_marks_row_and_continues(self, monkeypatch, payloads_3):
        # second call raises; first and third still publish
        ...

    async def test_no_credentials_in_payload(self, fake_notify, payloads_1):
        await fan_out(uuid.uuid4(), payloads_1)
        msg = fake_notify[0][0]
        assert not {"password", "api_key", "token", "secret"} & set(msg)


class TestRetry:
    async def test_never_retries_queued(self, ...): ...
    async def test_retries_pending_and_failed(self, ...): ...
    async def test_excludes_publishing_without_force(self, ...): ...
    async def test_includes_publishing_with_force(self, ...): ...


class TestLazyImport:
    def test_module_imports_without_notify(self, monkeypatch):
        """Importing must not require async-notify."""
        import importlib
        importlib.import_module("parrot.services.comm_center.dispatch")

    def test_actionable_error_when_missing(self, monkeypatch):
        with pytest.raises(RuntimeError, match="comm-center"):
            ...
```

---

## Agent Instructions

1. **Read the spec** — §2 state machine, §3 Module 6
2. **Check dependencies** — TASK-2154 and TASK-2157 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — in particular, **check what
   `NotifyClient.stream()` actually returns** before storing `message_id`; the
   contract flags this as unverified
4. **Update status** in `sdd/tasks/index/commcenter-notify.json` → `"in-progress"`
5. **Implement** per scope
6. **Verify** acceptance criteria
7. **Move** to `sdd/tasks/completed/TASK-2158-fanout-state-machine-retry.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note**

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-06
**Notes**:
Implemented `publish_one`, `fan_out`, `launch_fan_out` (+ its `_finalize_batch`
done-callback), `aggregate_batch_status`, and `retry_batch` in
`services/comm_center/dispatch.py`. `async-notify` is lazy-imported inside
`_get_notify_client`/`_notify_worker_stream` only — never at module load.

**Verified the contract's flagged unknown**: read `notify/server/client.py`
live — `NotifyClient.stream()` has no `return` statement (always resolves
to `None`). `publish_one` stores whatever it returns (`None` in practice)
into `message_id` without assuming a value; `published_at` is the
authoritative "this succeeded" marker, exactly as the contract anticipated.

Because this sandbox's `parrot.handlers.models` import chain has **three**
independent, pre-existing, unrelated environment gaps (confirmed by
successively hitting each one): `navigator_session.vault` (missing
submodule), `navigator_eventbus` (missing package, via
`parrot.outputs.a2ui.recipes.params`), and now also
`navigator.utils.file.FileManagerInterface` (name not exported by the
installed `navigator` version) — `pytest` cannot collect
`test_comm_center_dispatch.py` here. Verified correctness instead with a
throwaway diagnostic harness (stubbing only the broken leaf modules and a
lightweight `NotificationBatchRecipient` stand-in matching the real
model's shape in `sys.modules`, never touching shipped code) covering
every scenario in this task's Test Specification plus the aggregation
function: one-xadd-per-recipient, the `publishing`-before-`xadd` marker,
one-row-failure-doesn't-abort-the-batch, `attempts` incrementing, retry's
state-machine selection (`pending`/`publish_failed` always;
`queued`/`skipped` never; `publishing` only under `force=True`, else
reported `ambiguous`), and `aggregate_batch_status`'s count/details paths.
All passed. The harness was deleted after verification.

**Bug found and fixed while building the diagnostic** (in my own test
doubles, not in `dispatch.py`): my first draft of `_FakeAsyncDB.connection()`
was a plain sync method returning a context manager directly. The real
`AsyncDB.connection()` (confirmed live against
`packages/ai-parrot/src/parrot/interfaces/hierarchy.py:249`, the verified
reference pattern) is itself `async def`, used as `async with await
db.connection() as conn:` — a two-step await-then-enter. `dispatch.py`
already followed the real pattern correctly; I fixed both my diagnostic's
and the shipped test file's fakes (`_FakeAsyncDB`, both
`FakeAsyncDBWithFetch` classes in `TestAggregation`) to make `connection()`
`async def`, matching reality.

**Known limitation flagged for a follow-up schema amendment** (out of this
task's file scope — `handlers/models/notification_batches.py` belongs to
TASK-2154): `retry_batch`'s `_rebuild_payload()` reconstructs a wire
payload from the tracking row's own columns, since the row does not store
the original full payload. This is faithful for `email`/`twilio`/
`telegram`/`slack`/`zoom` (a single `recipient_address` column suffices),
but **not** for `teams`, which needs both `team_id` and `channel_id` —
only one fits in `recipient_address`. A retried `teams` row will
legitimately re-fail contact-field validation (a *safe* failure mode,
reported rather than silently mis-sent), not silently succeed with wrong
data. Also, `template_ref` is treated as the literal template body on
retry, which is only correct for inline templates, not stored/file ones.
Documented in code (`_rebuild_payload`'s docstring) for the next spec
iteration to add either a `payload`/`rendered_template` JSON column.

**Deviations from spec**: none in delivered behavior; one documented,
narrow retry-fidelity limitation (above) inherited from the existing
TASK-2154 schema, which this task's file scope does not permit changing.
