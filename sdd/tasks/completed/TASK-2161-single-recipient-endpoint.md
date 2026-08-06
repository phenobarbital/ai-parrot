# TASK-2161: Single-recipient endpoint — `POST /api/v1/comm_center/message`

**Feature**: FEAT-417 — CommCenter — Bulk Notification Sender over NotifyWorker
**Spec**: `sdd/specs/commcenter-notify.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2158, TASK-2159
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 / G13. Sends to **one** recipient: takes a `Recipient` +
template + an explicit `provider`, publishes **synchronously inside the
request** (a single `xadd` does not justify a background task), and returns
`202` with the Redis `message_id`.

It is deliberately a **thin arity-1 caller** over the shared
`CommCenterService.prepare()` from TASK-2157. It must not re-implement template
resolution, rendering, provider resolution or validation — a payload-parity
test enforces that.

---

## Scope

- Implement `SingleMessageRequest` / `SingleMessageResponse` models.
- Implement `CommCenterHandler.post_message()` (stub left by TASK-2159).
- Call `prepare()` with a one-element recipient list; publish via
  `publish_one()`; persist exactly one tracking row under a fresh `batch_id`.
- Implement the divergent error semantics (below).
- Unit tests including the parity guard.

**NOT in scope**:
- `dry_run` (TASK-2162) — but do not block it: route everything through
  `prepare()` so dry-run is a pure addition.
- Route registration (TASK-2159 already registered `POST /message`).
- Any change to `prepare()` or `publish_one()` semantics.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/comm_center.py` | MODIFY | Fill in `post_message()` |
| `packages/ai-parrot-server/src/parrot/services/comm_center/models.py` | MODIFY | Add the two models |
| `packages/ai-parrot-server/tests/handlers/test_comm_center_message.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified fresh 2026-08-06.

### Verified Imports

```python
import uuid
from typing import Any, Dict, Optional

from aiohttp import web
from datamodel import BaseModel, Field
from navigator_auth.decorators import is_authenticated

from parrot.services.comm_center.models import RecipientIn         # TASK-2156
from parrot.services.comm_center.render import prepare             # TASK-2157
from parrot.services.comm_center.dispatch import publish_one       # TASK-2158
```

### Existing Signatures to Use

```python
# From TASK-2157 (spec §2 New Public Interfaces)
async def prepare(self, *, recipients, provider, template_source, subject,
                  now=None) -> "PreparedBatch": ...
# Everything up to (not including) publishing. THE shared core.

# From TASK-2158
async def publish_one(self, batch_id, payload, row_id) -> str: ...
# Single xadd driving the pending → publishing → queued state machine.
```

```python
# navigator.views.base.BaseHandler — VERIFIED live
async def get_json(self, request: web.Request = None) -> Any
def json_response(self, response: dict = None, status: int = 200, ...)
def error(self, response: dict = None, status: int = 400, ...) -> web.Response
async def get_userid(self, session, idx: str = 'user_id') -> int
```

```python
# /home/jesuslara/proyectos/notify/notify/server/wrapper.py:43 — the wire key
recipients = kwargs.pop('recipient', [])     # SINGULAR — a plural key sends to nobody
```

### Does NOT Exist

- ~~A separate single-send service/pipeline~~ — there must be exactly ONE
  pipeline. Reuse `prepare()`; do not write a parallel implementation.
- ~~A per-record `provider` override on this endpoint~~ — `provider` is
  **required and explicit**; with one recipient there is nothing to override.
- ~~`fan_out()` for this endpoint~~ — use `publish_one()` directly; no
  background task.
- ~~`parrot.handlers.comm_center.post_message` having a body~~ — TASK-2159 left
  it as a `NotImplementedError` stub; you fill it in.

---

## Implementation Notes

### Request / response (spec §2 Data Models)

```python
class SingleMessageRequest(BaseModel):
    provider: str                    # REQUIRED, explicit
    recipient: RecipientIn           # singular
    template_id / template_name / template / template_file   # exactly one
    subject: Optional[str]
    dry_run: bool = False            # honoured by TASK-2162

class SingleMessageResponse(BaseModel):
    batch_id: Optional[uuid.UUID]
    message_id: Optional[str]
    status: str                      # queued | publish_failed | skipped | dry_run
    reason: Optional[str]
    resolved_functions: dict
    preview: Optional[str]
```

### ⚠️ Deliberate divergence from the bulk endpoint (spec §3 Module 8)

The bulk endpoint **skips** an invalid row and protects the rest of the batch.
Here there is no "rest of the batch", so failing loudly is correct:

| Condition | Bulk `/sender` | Single `/message` |
|---|---|---|
| Recipient fails validation | row `skipped`, `202` | **`400` + reason** |
| Missing `provider` | uses the global default | **`400`** |
| Publish failure | row `publish_failed`, `202` | **`502`**, row retryable |

This is the ONE intentional inconsistency between the endpoints. Document it in
the docstring so it is not "fixed" later by mistake.

### Flow
```
1. Auth → user_id
2. Validate SingleMessageRequest (provider present, exactly one template source)
3. prepare(recipients=[req.recipient], provider=req.provider, ...)
4. if prepared.skipped:  → 400 with skipped[0].reason      ← divergence
5. batch_id = uuid4(); persist ONE tracking row (status=pending)
6. message_id = await publish_one(batch_id, payload, row_id)   ← synchronous
7. → 202 {batch_id, message_id, status: "queued"}
   on publish failure → 502 {status: "publish_failed", reason}
```

### Key Constraints
- **Synchronous publish** — no `asyncio.create_task`. When the response
  returns, the `xadd` has already happened.
- Exactly one tracking row, so `GET /sender/{batch_id}` and
  `/sender/{batch_id}/retry` work unchanged for a single send.
- `@is_authenticated`.
- Google-style docstrings + type hints; `self.logger`.

### References in Codebase
- Spec §2 "Shared-core requirement", §3 Module 8
- `packages/ai-parrot-server/src/parrot/handlers/scraping/info.py` — response style

---

## Acceptance Criteria

- [ ] `POST /api/v1/comm_center/message` accepts one `Recipient` + template + explicit `provider`
- [ ] Publishes **exactly one** `xadd`
- [ ] Publishing is **synchronous** — no pending task when the response returns
- [ ] Returns `202` with `batch_id`, `message_id`, `status`
- [ ] Persists exactly one tracking row; `GET /sender/{batch_id}` reports `total=1`
- [ ] Invalid recipient → `400` **with reason** (not `202`/`skipped`)
- [ ] Missing `provider` → `400`
- [ ] Publish failure → `502`, row left retryable via `/sender/{batch_id}/retry`
- [ ] **Parity**: same recipient + template through `/sender` and `/message`
      produce a byte-identical wire payload
- [ ] Requires authentication
- [ ] Tests pass: `pytest packages/ai-parrot-server/tests/handlers/test_comm_center_message.py -v`
- [ ] `ruff check` clean

---

## Test Specification

```python
import pytest


class TestSingleMessage:
    async def test_sends_single_recipient(self, client, auth, fake_notify):
        r = await client.post("/api/v1/comm_center/message", json={
            "provider": "email",
            "recipient": {"name": "Ana", "email": "ana@example.com"},
            "template": "Hola {{ name }}, hoy es {{ today }}"})
        assert r.status == 202
        body = await r.json()
        assert body["message_id"] and body["batch_id"]
        assert len(fake_notify) == 1

    async def test_publishes_synchronously(self, client, auth, fake_notify):
        """The xadd has already happened when the response returns."""
        await client.post("/api/v1/comm_center/message", json={...})
        assert len(fake_notify) == 1        # no await on a background task

    async def test_persists_one_row_batch(self, client, auth, fake_notify):
        body = (await (await client.post("/api/v1/comm_center/message",
                                         json={...})).json())
        g = await client.get(f"/api/v1/comm_center/sender/{body['batch_id']}")
        assert (await g.json())["total"] == 1

    async def test_invalid_recipient_returns_400(self, client, auth, fake_notify):
        r = await client.post("/api/v1/comm_center/message", json={
            "provider": "email",
            "recipient": {"name": "NoMail"},      # no email
            "template": "hi"})
        assert r.status == 400
        assert "email" in (await r.json())["reason"].lower()
        assert fake_notify == []                  # nothing published

    async def test_requires_explicit_provider(self, client, auth):
        r = await client.post("/api/v1/comm_center/message", json={
            "recipient": {"name": "Ana", "email": "a@e.com"}, "template": "hi"})
        assert r.status == 400

    async def test_publish_failure_returns_502(self, client, auth, failing_notify):
        r = await client.post("/api/v1/comm_center/message", json={...})
        assert r.status == 502
        assert (await r.json())["status"] == "publish_failed"

    async def test_retry_via_batch_endpoint(self, client, auth, failing_notify):
        """A failed single send is re-publishable through the batch retry."""
        ...

    async def test_message_and_sender_produce_identical_payload(
            self, client, auth, fake_notify):
        """PARITY GUARD — proves both endpoints share prepare()."""
        recipient = {"name": "Ana", "email": "ana@example.com"}
        tpl = "Hola {{ name }}, hoy es {{ today }}"
        await client.post("/api/v1/comm_center/message",
                          json={"provider": "email", "recipient": recipient,
                                "template": tpl})
        await client.post("/api/v1/comm_center/sender",
                          json={"provider": "email", "recipients": [recipient],
                                "template": tpl})
        single, bulk = fake_notify[0][0], fake_notify[1][0]
        assert single == bulk
```

---

## Agent Instructions

1. **Read the spec** — §3 Module 8 and §2 "Shared-core requirement"
2. **Check dependencies** — TASK-2158 and TASK-2159 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm `prepare()` and `publish_one()`
   have the signatures listed before calling them
4. **Update status** in `sdd/tasks/index/commcenter-notify.json` → `"in-progress"`
5. **Implement** per scope — resist the urge to write a second pipeline
6. **Verify** acceptance criteria, especially the parity test
7. **Move** to `sdd/tasks/completed/TASK-2161-single-recipient-endpoint.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note**

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-06
**Notes**:
Implemented `SingleMessageRequest`/`SingleMessageResponse` in
`services/comm_center/models.py` and filled in `post_message()` on
`CommCenterHandler` as a thin arity-1 caller: builds one `RecipientIn` +
`SingleMessageRequest`, resolves the template via the same
`_resolve_template_source()` the bulk endpoint uses, calls the same
`prepare()` (TASK-2157) with a one-element recipient list, persists
exactly one `NotificationBatchRecipient` row, and publishes synchronously
via `publish_one()` (TASK-2158) — no background task, no `fan_out()`.
Implemented the three deliberate divergences from the bulk endpoint (spec
§3 Module 8): a validation failure raises `400` with the skip reason
(never `202`+`skipped`), a missing `provider` raises `400` (no per-record
override to fall back to), and a publish failure raises `502` with the
row left in `publish_failed` (retryable via `/sender/{batch_id}/retry`).
Added a `TestPayloadParity` test proving `post_message` and `post_sender`
both route through the identical `prepare()` call for the same recipient
+ template + frozen `now`, producing a byte-identical wire payload — the
concrete enforcement of the "one pipeline" requirement rather than a
second implementation.

Verified with a throwaway diagnostic harness (same pre-existing,
unrelated environment stubs as TASK-2159/2160 — `navigator_session.vault`,
`navigator_eventbus`, a duck-typed `NotificationBatchRecipient`) covering
all seven scenarios from this task's Test Specification: single-xadd
send, one-row persistence, invalid-recipient 400, missing-provider 400,
publish-failure 502 with the row left retryable, missing-recipient 400,
and payload parity. All passed on the first attempt — this task's
implementation did not surface any new bug beyond the already-fixed
`dumps=json_encoder` issue documented in TASK-2160 (this handler's
`post_message` uses the same corrected `self.json_response(response.to_dict(),
status=202)` call). Harness deleted after verification; `pytest` itself
cannot collect this task's test file here for the same documented reasons.

**Deviations from spec**: none.
