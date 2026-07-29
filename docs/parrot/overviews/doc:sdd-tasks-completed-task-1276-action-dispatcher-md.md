---
type: Wiki Overview
title: 'TASK-1276: NotifyAction / TicketAction dispatcher by action_metadata["kind"]'
id: doc:sdd-tasks-completed-task-1276-action-dispatcher-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements §3 module **C3**. Replaces the two simulated stubs
relates_to:
- concept: mod:parrot.human.actions.backends
  rel: mentions
- concept: mod:parrot.human.actions.base
  rel: mentions
- concept: mod:parrot.human.actions.notify
  rel: mentions
---

# TASK-1276: NotifyAction / TicketAction dispatcher by action_metadata["kind"]

**Feature**: FEAT-194 — HITL Multi-Tier Escalation Policy
**Spec**: `sdd/specs/hitl-escalation-tier.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1275
**Assigned-to**: unassigned

---

## Context

Implements §3 module **C3**. Replaces the two simulated stubs
(`NotifyAction`, `TicketAction` at `parrot/human/actions/notify.py:6-25`
and `ticket.py:7-28`) with dispatchers that pick the right
`ActionBackend` based on `tier.action_metadata["kind"]`.

Must maintain backwards compatibility with the example doc
(`documentation/hitl_tiered_escalation_example.md`) which uses the
legacy keys `channel="email"` / `platform="jira"` instead of `kind`.

---

## Scope

- Rewrite `NotifyAction.execute` to:
  - Read `kind = tier.action_metadata.get("kind") or tier.action_metadata.get("channel")`.
  - Route `email` → `EmailBackend`; `webhook` → `WebhookBackend`.
  - Unknown `kind` → raise a typed error captured by the caller.
- Rewrite `TicketAction.execute` to:
  - Read `kind = tier.action_metadata.get("kind") or tier.action_metadata.get("platform")`.
  - Route `zammad` → `ZammadBackend`.
  - For `platform="jira"` (legacy example doc), log a warning and treat
    as `zammad` (V1 does not ship Jira/Zendesk).
- Both actions instantiate their backends lazily on first use, reading
  config from the action-level constructor (so manager can inject config
  once at startup).
- Translate any `ActionBackendError` into a return dict with
  `{"message": "[escalated:<kind>] failed: <reason>", "error": True}` —
  the manager (TASK-1277) inspects `error=True` to advance to the next
  tier.

**NOT in scope**: Manager-level handling of action failure (TASK-1277).
Adding new action_type enum values.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/human/actions/notify.py` | MODIFY | Replace stub with dispatcher |
| `packages/ai-parrot/src/parrot/human/actions/ticket.py` | MODIFY | Replace stub with dispatcher |
| `packages/ai-parrot/tests/human/actions/test_notify_action.py` | CREATE | Dispatcher tests + legacy-key back-compat |
| `packages/ai-parrot/tests/human/actions/test_ticket_action.py` | CREATE | Dispatcher tests + legacy `platform=jira` warning |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Existing:
from parrot.human.actions.base import EscalationAction               # actions/base.py:9
from navconfig.logging import logging                                 # actions/notify.py:4
# New (from TASK-1275):
from parrot.human.actions.backends import (
    EmailBackend, ZammadBackend, WebhookBackend,
    ActionBackendError,
)
```

### Existing Signatures to Use

```python
# parrot/human/actions/notify.py:6-25 — CURRENT STUB to REPLACE
class NotifyAction(EscalationAction):
    def __init__(self): ...
    async def execute(self, interaction, tier) -> Dict[str, Any]:
        channel = tier.action_metadata.get("channel", "email")
        # returns simulated dict

# parrot/human/actions/ticket.py:7-28 — CURRENT STUB to REPLACE
class TicketAction(EscalationAction):
    def __init__(self): ...
    async def execute(self, interaction, tier) -> Dict[str, Any]:
        platform = tier.action_metadata.get("platform", "zammad")
        # returns {"ticket_id": "SIM-12345", ...}

# parrot/human/manager.py:72-75 — manager wires both actions today:
self._actions: Dict[EscalationActionType, Any] = {
    EscalationActionType.TICKET: TicketAction(),
    EscalationActionType.NOTIFY: NotifyAction(),
}
# This task changes the constructors to accept backend config dicts; the
# manager wiring change is part of TASK-1277.
```

### Does NOT Exist

- ~~`parrot.human.actions.backends.JiraBackend`~~ — Jira is not in V1.
- ~~`parrot.human.actions.backends.ZendeskBackend`~~ — V2.
- ~~A new `EscalationActionType` value~~ — do NOT add enum members;
  dispatch happens by `action_metadata["kind"]` within existing enum
  members.

---

## Implementation Notes

### Pattern to Follow

```python
class NotifyAction(EscalationAction):
    def __init__(self, *, email_cfg=None, webhook_cfg=None):
        self._email_cfg = email_cfg or {}
        self._webhook_cfg = webhook_cfg or {}
        self._cache: Dict[str, Any] = {}
        self.logger = logging.getLogger("parrot.human.actions.notify")

    def _get_backend(self, kind: str):
        if kind in self._cache: return self._cache[kind]
        if kind == "email":
            self._cache[kind] = EmailBackend(**self._email_cfg)
        elif kind == "webhook":
            self._cache[kind] = WebhookBackend(**self._webhook_cfg)
        else:
            raise ActionBackendError(f"NotifyAction: unknown kind {kind!r}")
        return self._cache[kind]

    async def execute(self, interaction, tier) -> Dict[str, Any]:
        meta = tier.action_metadata
        kind = meta.get("kind") or meta.get("channel") or "email"
        try:
            return await self._get_backend(kind).execute(interaction, tier)
        except ActionBackendError as exc:
            self.logger.warning("NotifyAction backend failed: %s", exc)
            return {"message": f"[escalated:{kind}] failed: {exc}", "error": True}
```

### Key Constraints

- Backends instantiated lazily and cached per kind (avoid re-allocating
  `aiohttp.ClientSession` per call — though the session itself is
  per-call inside the backend).
- Legacy keys (`channel`, `platform`) are honoured at top of `execute`
  before falling back to defaults.
- Unknown `kind` → log + return `error=True` dict so the manager can
  recover (TASK-1277).
- Loggers MUST NOT include backend credentials.

### References in Codebase

- Spec §7 Known Risks: "Backwards compat with the example doc" — keep
  legacy `channel`/`platform` working.

---

## Acceptance Criteria

- [ ] `NotifyAction` with `action_metadata={"kind":"email","to":["x@y"]}` routes to `EmailBackend`.
- [ ] `NotifyAction` with `action_metadata={"channel":"email","to":["x@y"]}` (legacy) routes to `EmailBackend`.
- [ ] `NotifyAction` with `action_metadata={"kind":"webhook","url":"..."}` routes to `WebhookBackend`.
- [ ] `TicketAction` with `action_metadata={"kind":"zammad","queue":"Q"}` routes to `ZammadBackend`.
- [ ] `TicketAction` with `action_metadata={"platform":"jira","project":"OPS"}` logs a warning and routes to `ZammadBackend`.
- [ ] Backend exception → return dict has `error=True` and a `message` describing the failure (manager will handle in TASK-1277).
- [ ] Unknown `kind` → `error=True` dict, NOT an unhandled exception.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/human/actions/ -v`.
- [ ] `ruff check` clean.

---

## Test Specification

```python
# tests/human/actions/test_notify_action.py
async def test_routes_to_email_by_kind(): ...
async def test_routes_to_email_by_legacy_channel_key(): ...
async def test_routes_to_webhook(): ...
async def test_unknown_kind_returns_error_dict(): ...
async def test_backend_exception_returns_error_dict(): ...

# tests/human/actions/test_ticket_action.py
async def test_routes_to_zammad_by_kind(): ...
async def test_legacy_jira_platform_logs_warning_and_routes_zammad(caplog): ...
```

---

## Agent Instructions

1. Read spec §3 C3 + §6 Codebase Contract + §7 backwards-compat note.
2. Verify TASK-1275 completed.
3. Implement, test, lint.
4. Move file to completed, update index.

---

## Completion Note
