# TASK-2157: Render + validation core — `prepare()`, partial render, wire payloads

**Feature**: FEAT-417 — CommCenter — Bulk Notification Sender over NotifyWorker
**Spec**: `sdd/specs/commcenter-notify.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2155, TASK-2156
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 — **the heart of the feature**. This is the "partial-render
gateway" the whole architecture is named after (spec §2 Overview).

`async-notify` cannot render a Jinja2 *string* today, and even when it can, the
computed functions must resolve **handler-side** so `{{today}}` is fixed once
per batch and a malformed template fails before anything is published.

This task also owns `build_wire_payload()`, which encodes the per-provider
recipient shapes. **Three verified traps** live here — get them wrong and
messages go to nobody, or ship a UUID inside the text. They are documented
below with executed evidence.

Everything downstream (bulk send, single send, dry-run) routes through the
`prepare()` this task creates.

---

## Scope

- Implement `resolve_functions(now=None)` → the 7 computed values.
- Implement `partial_render(template_string, context)` using
  `Environment(undefined=DebugUndefined, autoescape=False, enable_async=True)`.
- Implement provider resolution + contact-field validation →
  `(queued, skipped)`.
- Implement `build_wire_payload()` per the per-provider shape table.
- Implement `prepare()` orchestrating the above into a `PreparedBatch`.
- Unit tests, including regression guards for all three traps.

**NOT in scope**:
- Publishing / `xadd` / tracking rows (TASK-2158).
- HTTP layer (TASK-2159).
- The `dry_run` short-circuit (TASK-2162) — but keep `prepare()` free of any
  publishing so that task is a pure addition.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/services/comm_center/render.py` | CREATE | Functions, partial render, validation, payloads, `prepare()` |
| `packages/ai-parrot-server/src/parrot/services/comm_center/models.py` | MODIFY | Add `PreparedBatch`, `PreparedMessage` |
| `packages/ai-parrot-server/tests/handlers/test_comm_center_render.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified fresh 2026-08-06 — the three traps below were reproduced by
> execution in `.venv`, not inferred.

### Verified Imports

```python
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from jinja2 import Environment, DebugUndefined, TemplateSyntaxError  # jinja2 3.1.6
from datamodel import BaseModel, Field

from parrot.outputs.a2ui.recipes.params import resolve_date, DATE_RESOLVERS
from parrot.services.comm_center.models import RecipientIn, SkippedRow  # TASK-2156
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/outputs/a2ui/recipes/params.py:30,39 — VERIFIED live
DATE_RESOLVERS = ("current_month", "previous_month", "today",
                  "yesterday", "first_of_month")
def resolve_date(resolver: str, *, tz: str = "UTC",
                 now: datetime | None = None) -> str: ...
```

```python
# /home/jesuslara/proyectos/notify/notify/server/wrapper.py:40-58
# The consumer of our payload. Discriminator order is LOAD-BEARING:
class NotifyWrapper:
    def __init__(self, provider: str, *args, **kwargs):
        recipients = kwargs.pop('recipient', [])    # line 43 ← SINGULAR key
        # line 45-58:
        #   'chat_id'    → Chat
        #   'team_id'    → TeamsChannel      ← checked BEFORE channel_id
        #   'channel_id' → Channel
        #   else         → Actor
        # non-dict, non-BaseModel recipients are PRINTED AND DISCARDED (line 58)
```

```python
# /home/jesuslara/proyectos/notify/notify/models.py — VERIFIED live annotations
class Account(BaseModel):     # line 28
    provider: str; enabled: bool
    address: Union[str, list[str]]   # ← EMAIL goes here
    number:  Union[str, list[str]]   # ← PHONE goes here
    userid: str; attributes: dict
class Actor(BaseModel):       # line 43
    userid: uuid.UUID; name: str
    account: Optional[Account]; accounts: Optional[list[Account]]
class Chat(BaseModel):         chat_name, chat_id           # line 61
class Channel(BaseModel):      channel_name, channel_id     # line 69
class TeamsChannel(BaseModel): name, channel_id, team_id
```

```python
# /home/jesuslara/proyectos/notify/notify/providers/base.py:177-183 — pass-2 context
self._templateargs = {
    "recipient": to, "username": to,
    "message": message, "subject": subject,
    **kwargs,                       # ← LAST, so our row fields override
}
msg = await self._template.render_async(**self._templateargs)
```

### ⚠️ Three verified traps — regression-test each

**Trap 1 — `{{username}}` leaks an `Actor` repr.**
`username` defaults to the Actor **object**. Executed evidence:
```python
# row HAS username  → "Hola agomez"                                    ✅
# row LACKS username→ "Hola <Ana Gomez: c1c4f2c8-deda-46e8-bda2-c9b5f6018b97>"  ⚠️
```
⇒ `build_wire_payload()` MUST **always** emit `username`, falling back to `name`.

**Trap 2 — the wire key is `recipient`, SINGULAR.**
`NotifyWrapper` pops `'recipient'` (`wrapper.py:43`). Emitting `recipients`
means the message goes out with **zero** recipients, silently.

**Trap 3 — `team_id` precedes `channel_id`.**
A dict carrying both always becomes `TeamsChannel`, never `Channel`. Emit only
the keys the target provider needs.

### Does NOT Exist

- ~~`notify.templates.TemplateParser.from_string()`~~ — verified methods are
  exactly `add_filter`, `environment`, `get_template`, `render`, `render_async`
  — all filename-based. **Do not call a string-render API on notify.**
- ~~`template=` accepting a Jinja2 string in async-notify 1.5.5~~ — not yet.
  We build against a future release (spec §7 gating); this task's job is to
  produce the partially-rendered string, not to make notify consume it.
- ~~`Actor.email` / `Actor.phone`~~ — not fields. Use nested
  `Account.address` / `Account.number`.
- ~~`resolve_date("now")` / `resolve_date("current_year")`~~ — not resolver
  names; implement those two locally.
- ~~Enabling `autoescape` in pass 1~~ — would HTML-escape the preserved `{{ }}`
  braces and corrupt the template. Pass 2 is `autoescape=False`
  (`notify/templates.py:7-10` sets no autoescape), so pass 1 must match.

---

## Implementation Notes

### The partial-render mechanism (verified working)

```python
env = Environment(undefined=DebugUndefined, autoescape=False, enable_async=True)
env.from_string("Hola {{ name }}, hoy es {{ today }} - {{ email }}").render(today="2026-08-06")
# → 'Hola {{ name }}, hoy es 2026-08-06 - {{ email }}'     ✅ EXECUTED, CONFIRMED
```

Bind **only** the computed-function context in pass 1. Everything else survives
literally for the worker.

`TemplateSyntaxError` must surface as a typed error the handler maps to `400` —
**nothing may be published when the template is malformed**.

### Per-provider recipient shape (spec §2)

| Provider | Emitted dict | Builds |
|---|---|---|
| `email`, `gmail`, `smtp`, `ses`, `sendgrid`, `office365`, `outlook` | `{"name":…, "account":{"provider":…, "address":<email>}}` | `Actor`+`Account` |
| `twilio` / SMS-like | `{"name":…, "account":{"provider":…, "number":<phone>}}` | `Actor`+`Account` |
| `teams` | `{"name":…, "team_id":…, "channel_id":…}` | `TeamsChannel` |
| `telegram` | `{"chat_name":…, "chat_id":…}` | `Chat` |
| `slack`, `zoom` | `{"channel_name":…, "channel_id":…}` | `Channel` |

### Full wire payload

```python
{
  "provider": "email",
  "recipient": [ <shape above> ],      # SINGULAR key, list value
  "template":  "<partially-rendered string>",
  "subject":   "...",
  # row fields forwarded as pass-2 render kwargs — username ALWAYS present:
  "name": "...", "username": "...", "email": "...", "phone": "...",
  **extra_columns,
}
```

### Provider resolution + validation (spec G5)
- `provider = row.provider or default_provider`.
- **Unknown provider → `skipped` with a reason. Never fall back to the default.**
- Missing the provider's required contact field → `skipped` with a reason.
- Skips never abort the batch; the remaining rows still send.

### Key Constraints
- Pure — **no** Redis, no DB, no aiohttp. `prepare()` must be callable from a
  plain unit test (this is what makes G12/dry-run possible).
- `now` injectable everywhere for determinism.
- Google-style docstrings + full type hints; `self.logger` (or module logger).

### References in Codebase
- Spec §2 "Pass-2 binding precedence", "Per-provider recipient shape", §6 executed verifications

---

## Acceptance Criteria

- [ ] `partial_render` resolves functions and preserves `{{name}}`/`{{email}}` literally
- [ ] Malformed template raises a typed error (→ `400`), publishing nothing
- [ ] `resolve_functions()` returns the 7 values; deterministic under injected `now`
- [ ] Wire payload uses the **singular** `recipient` key
- [ ] `username` **always** present, falling back to `name`
- [ ] Each provider class produces a dict that builds the right Notify type,
      asserted via a real `NotifyWrapper`
- [ ] Unknown provider → `skipped`, never defaulted
- [ ] Missing contact field → `skipped` with reason; batch proceeds
- [ ] `prepare()` performs no I/O and publishes nothing
- [ ] Tests pass: `pytest packages/ai-parrot-server/tests/handlers/test_comm_center_render.py -v`
- [ ] `ruff check` clean

---

## Test Specification

```python
from datetime import datetime
import pytest
from notify.server.wrapper import NotifyWrapper
from notify.models import Actor, TeamsChannel, Chat, Channel

from parrot.services.comm_center.render import (
    partial_render, resolve_functions, build_wire_payload, prepare,
)
from parrot.services.comm_center.models import RecipientIn

FROZEN = datetime(2026, 8, 6, 12, 0, 0)


class TestPartialRender:
    def test_preserves_record_placeholders(self):
        out = partial_render("Hola {{ name }}, hoy es {{ today }} - {{ email }}",
                             resolve_functions(now=FROZEN))
        assert "2026-08-06" in out
        assert "{{ name }}" in out and "{{ email }}" in out

    def test_syntax_error_raises(self):
        with pytest.raises(Exception):
            partial_render("Hola {{ name ", resolve_functions(now=FROZEN))

    def test_functions_deterministic(self):
        assert resolve_functions(now=FROZEN) == resolve_functions(now=FROZEN)


class TestWirePayload:
    def test_recipient_key_is_singular(self):
        p = build_wire_payload(RecipientIn(name="Ana", email="a@e.com"),
                               "email", "hi", None)
        assert "recipient" in p and "recipients" not in p

    def test_username_always_emitted_falls_back_to_name(self):
        p = build_wire_payload(RecipientIn(name="Ana Gomez", email="a@e.com"),
                               "email", "hi", None)
        assert p["username"] == "Ana Gomez"       # Trap 1 guard

    def test_email_builds_actor_with_account(self):
        p = build_wire_payload(RecipientIn(name="Ana", email="a@e.com"),
                               "email", "hi", None)
        r = NotifyWrapper(**p).recipients[0]
        assert isinstance(r, Actor)
        assert r.account.address == "a@e.com"

    def test_teams_builds_teamschannel(self):
        p = build_wire_payload(RecipientIn(name="Ops", extra={"team_id": "T1",
                                                              "channel_id": "C1"}),
                               "teams", "hi", None)
        assert isinstance(NotifyWrapper(**p).recipients[0], TeamsChannel)

    def test_telegram_and_slack_shapes(self):
        chat = build_wire_payload(RecipientIn(name="x", extra={"chat_id": "1"}),
                                  "telegram", "hi", None)
        assert isinstance(NotifyWrapper(**chat).recipients[0], Chat)
        ch = build_wire_payload(RecipientIn(name="x", extra={"channel_id": "C9"}),
                                "slack", "hi", None)
        assert isinstance(NotifyWrapper(**ch).recipients[0], Channel)


class TestValidation:
    async def test_missing_contact_field_skipped(self):
        b = await prepare(recipients=[RecipientIn(name="NoMail")],
                          provider="email", template_source="hi",
                          subject=None, now=FROZEN)
        assert len(b.queued) == 0 and len(b.skipped) == 1
        assert "email" in b.skipped[0].reason

    async def test_unknown_provider_skipped_not_defaulted(self):
        b = await prepare(recipients=[RecipientIn(name="A", email="a@e.com",
                                                  provider="carrier-pigeon")],
                          provider="email", template_source="hi",
                          subject=None, now=FROZEN)
        assert len(b.skipped) == 1

    async def test_row_provider_overrides_global(self):
        b = await prepare(recipients=[RecipientIn(name="A", extra={"chat_id": "1"},
                                                  provider="telegram")],
                          provider="email", template_source="hi",
                          subject=None, now=FROZEN)
        assert b.queued[0].payload["provider"] == "telegram"

    async def test_partial_send_valid_rows_survive(self):
        b = await prepare(recipients=[RecipientIn(name="Bad"),
                                      RecipientIn(name="Good", email="g@e.com")],
                          provider="email", template_source="Hola {{ name }}",
                          subject=None, now=FROZEN)
        assert len(b.queued) == 1 and len(b.skipped) == 1
```

---

## Agent Instructions

1. **Read the spec** — §2 Overview, "Pass-2 binding precedence", "Per-provider
   recipient shape", and §6 executed verifications
2. **Check dependencies** — TASK-2155 and TASK-2156 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — re-run the three trap reproductions before
   coding; if upstream `notify` changed, update the contract FIRST
4. **Update status** in `sdd/tasks/index/commcenter-notify.json` → `"in-progress"`
5. **Implement** per scope
6. **Verify** acceptance criteria
7. **Move** to `sdd/tasks/completed/TASK-2157-render-validation-core.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note**

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
