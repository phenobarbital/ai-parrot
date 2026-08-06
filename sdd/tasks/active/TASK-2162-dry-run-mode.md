# TASK-2162: Dry-run mode on both send endpoints

**Feature**: FEAT-417 — CommCenter — Bulk Notification Sender over NotifyWorker
**Spec**: `sdd/specs/commcenter-notify.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2159, TASK-2161
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9 / G14. `dry_run=true` runs the whole pipeline — ingest,
template resolution, partial render, provider resolution, validation — then
**stops before any `xadd` and before any tracking write**, returning the
outcome plus a `preview` of the exact text that would be delivered.

This is the safety backstop for an endpoint whose failure mode is "we sent
20 000 broken emails". It must be **impossible to bypass**, which is why the
guard lives in the service layer, not only in the handler.

---

## Scope

- Implement the `dry_run` short-circuit in `CommCenterService`.
- Honour it on **both** `POST /sender` and `POST /message`.
- Build the `preview`: the first queued recipient rendered through **both**
  passes, so the caller sees delivered text.
- Return `200` (not `202`) with `batch_id`/`message_id` = `null`,
  `status="dry_run"`.
- Guarantee no tracking rows are written.
- Unit + integration tests, including a preview-fidelity test.

**NOT in scope**:
- Changing `prepare()` semantics (TASK-2157) — dry-run is a pure addition
  around it.
- New endpoints or routes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/services/comm_center/render.py` | MODIFY | Preview builder + service-layer guard |
| `packages/ai-parrot-server/src/parrot/services/comm_center/dispatch.py` | MODIFY | Refuse to publish when the prepared batch is dry-run |
| `packages/ai-parrot-server/src/parrot/handlers/comm_center.py` | MODIFY | Honour `dry_run` in both endpoints |
| `packages/ai-parrot-server/tests/handlers/test_comm_center_dryrun.py` | CREATE | Unit + integration tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified fresh 2026-08-06.

### Verified Imports

```python
from datetime import datetime
from typing import Any, Dict, Optional

from jinja2 import Environment, DebugUndefined     # jinja2 3.1.6 — pass 1
from parrot.services.comm_center.render import prepare, partial_render   # TASK-2157
from parrot.services.comm_center.models import RecipientIn               # TASK-2156
```

### Existing Signatures to Use

```python
# TASK-2157 — the shared core dry-run wraps
async def prepare(self, *, recipients, provider, template_source, subject,
                  now=None) -> "PreparedBatch": ...

# /home/jesuslara/proyectos/notify/notify/providers/base.py:177-183
# Pass-2 context — the preview MUST simulate this exactly:
{"recipient": to, "username": to, "message": message, "subject": subject, **kwargs}
# NOTE: **kwargs LAST → row fields override. `username` defaults to the Actor
# object, so a row without it renders "<Ana Gomez: c1c4f2c8-…>".
```

```python
# notify/templates.py:7-10 — pass-2 Jinja config (VERIFIED)
jinja_config = {"enable_async": True,
                "extensions": ["jinja2.ext.i18n", "jinja2.ext.loopcontrols"]}
# NO autoescape key → autoescape=False in pass 2. The preview must match,
# otherwise it would not reflect the real output.
```

### Does NOT Exist

- ~~A handler-only `dry_run` check being sufficient~~ — the spec requires the
  guard at the **service** layer so no future caller of `CommCenterService`
  (e.g. the toolkit contemplated by G12) can bypass it.
- ~~`202` as the dry-run status code~~ — dry-run returns **`200`**; nothing was
  accepted for delivery.
- ~~A `preview` for a batch with zero queued rows~~ — must be `None`, not a
  crash on `queued[0]`.
- ~~Writing a `batch_id` for a dry run~~ — no batch is persisted; the field is
  `null`.

---

## Implementation Notes

### Behavior (spec §3 Module 9)

| Aspect | Real send | Dry run |
|---|---|---|
| Status code | `202` | **`200`** |
| `status` | `publishing` / `queued` | `"dry_run"` |
| `batch_id` | UUID | `null` |
| `message_id` (single) | Redis entry id | `null` |
| `xadd` calls | N (or 1) | **0** |
| Tracking rows written | N (or 1) | **0** |
| `resolved_functions` | present | present |
| `skipped_details` | present | present |
| `preview` | absent | **present** |

### Building the preview
Take the first **queued** recipient and render the partially-rendered template
through a simulated pass 2, binding exactly what Notify would bind (see the
contract above), so the preview equals the delivered text.

Because `username` defaults to the Actor object upstream, the preview must use
the **same** payload `build_wire_payload()` produces — i.e. with `username`
already defaulted to `name`. Do not construct a separate context, or the
preview will silently differ from reality.

### Service-layer enforcement
```python
# dispatch.py
if prepared.dry_run:
    raise RuntimeError("Refusing to publish a dry-run batch")   # defence in depth
```
The handler should never reach this, but a future caller might.

### Key Constraints
- Zero side effects: no Redis connection opened, no DB write.
- `preview` is `None` when nothing is queued.
- Both endpoints share one implementation.
- Google-style docstrings + type hints; `self.logger.info` noting a dry run.

### References in Codebase
- Spec §3 Module 9, §5 dry-run criteria
- `notify/providers/base.py:177-183` — the pass-2 context to simulate

---

## Acceptance Criteria

- [ ] `dry_run=true` on `POST /sender` → `200`, **zero** `xadd`, **zero** tracking rows
- [ ] `dry_run=true` on `POST /message` → same guarantees; `batch_id`/`message_id` null
- [ ] Response carries `resolved_functions`, `skipped_details` and `preview`
- [ ] `status == "dry_run"`
- [ ] Preview reflects **both** render passes
- [ ] **Preview fidelity**: dry-run preview is byte-identical to what the
      subsequent real send publishes for the same input
- [ ] `preview is None` when zero rows are queued (no crash)
- [ ] Guard enforced in `CommCenterService` — calling the service directly with
      a dry-run batch cannot publish
- [ ] No Redis connection opened during a dry run
- [ ] Tests pass: `pytest packages/ai-parrot-server/tests/handlers/test_comm_center_dryrun.py -v`
- [ ] `ruff check` clean

---

## Test Specification

```python
import pytest


class TestDryRunBulk:
    async def test_publishes_nothing(self, client, auth, fake_notify):
        r = await client.post("/api/v1/comm_center/sender", json={
            "provider": "email", "dry_run": True,
            "recipients": [{"name": "Ana", "email": "ana@example.com"}],
            "template": "Hola {{ name }}, hoy es {{ today }}"})
        assert r.status == 200
        assert fake_notify == []                      # zero xadd

    async def test_writes_no_tracking_rows(self, client, auth, fake_notify, db):
        before = await db.count("notification_batch_recipients")
        await client.post("/api/v1/comm_center/sender",
                          json={..., "dry_run": True})
        assert await db.count("notification_batch_recipients") == before

    async def test_returns_preview_and_validation(self, client, auth, fake_notify):
        body = await (await client.post("/api/v1/comm_center/sender", json={
            "provider": "email", "dry_run": True,
            "recipients": [{"name": "Ana", "email": "a@e.com"},
                           {"name": "NoMail"}],
            "template": "Hola {{ name }}, hoy es {{ today }}"})).json()
        assert body["status"] == "dry_run"
        assert body["batch_id"] is None
        assert "Ana" in body["preview"] and "{{" not in body["preview"]
        assert len(body["skipped_details"]) == 1

    async def test_preview_none_when_nothing_queued(self, client, auth):
        body = await (await client.post("/api/v1/comm_center/sender", json={
            "provider": "email", "dry_run": True,
            "recipients": [{"name": "NoMail"}], "template": "hi"})).json()
        assert body["preview"] is None


class TestDryRunSingle:
    async def test_message_endpoint_dry_run(self, client, auth, fake_notify):
        r = await client.post("/api/v1/comm_center/message", json={
            "provider": "email", "dry_run": True,
            "recipient": {"name": "Ana", "email": "a@e.com"},
            "template": "Hola {{ name }}"})
        assert r.status == 200
        body = await r.json()
        assert body["batch_id"] is None and body["message_id"] is None
        assert fake_notify == []


class TestEnforcement:
    async def test_service_layer_refuses_to_publish(self):
        """Guard is not handler-only."""
        from parrot.services.comm_center.render import prepare
        from parrot.services.comm_center.dispatch import fan_out
        prepared = await prepare(..., dry_run=True)
        with pytest.raises(RuntimeError, match="dry-run"):
            await fan_out(None, prepared)

    async def test_no_redis_connection_opened(self, client, auth, monkeypatch):
        ...


class TestFidelity:
    async def test_dry_run_then_real_send_same_payload(self, client, auth,
                                                       fake_notify):
        """The preview must be trustworthy."""
        payload = {"provider": "email",
                   "recipients": [{"name": "Ana", "email": "a@e.com"}],
                   "template": "Hola {{ name }}, hoy es {{ today }}"}
        dry = await (await client.post("/api/v1/comm_center/sender",
                                       json={**payload, "dry_run": True})).json()
        await client.post("/api/v1/comm_center/sender", json=payload)
        published = fake_notify[0][0]
        assert dry["preview"] == rendered_pass2(published)
```

---

## Agent Instructions

1. **Read the spec** — §3 Module 9 and the dry-run criteria in §5
2. **Check dependencies** — TASK-2159 and TASK-2161 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — re-read `notify/providers/base.py:177-183`
   so the preview simulates the real pass-2 context exactly
4. **Update status** in `sdd/tasks/index/commcenter-notify.json` → `"in-progress"`
5. **Implement** per scope — the guard goes in the SERVICE, not just the handler
6. **Verify** acceptance criteria, especially preview fidelity
7. **Move** to `sdd/tasks/completed/TASK-2162-dry-run-mode.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note**

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
