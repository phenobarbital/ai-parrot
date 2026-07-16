---
type: Wiki Overview
title: 'TASK-1275: Action backends (Email / Zammad / Webhook)'
id: doc:sdd-tasks-completed-task-1275-action-backends-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements §3 module **C2**. Today `NotifyAction` and `TicketAction`
relates_to:
- concept: mod:parrot.clients
  rel: mentions
- concept: mod:parrot.human
  rel: mentions
- concept: mod:parrot.human.actions.backends
  rel: mentions
- concept: mod:parrot.human.actions.base
  rel: mentions
- concept: mod:parrot.human.models
  rel: mentions
---

# TASK-1275: Action backends (Email / Zammad / Webhook)

**Feature**: FEAT-194 — HITL Multi-Tier Escalation Policy
**Spec**: `sdd/specs/hitl-escalation-tier.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1274
**Assigned-to**: unassigned

---

## Context

Implements §3 module **C2**. Today `NotifyAction` and `TicketAction`
(B3) are stubs that log and return simulated payloads. This task adds
the real backend implementations they will dispatch to in TASK-1276.
Creates a new submodule `parrot/human/actions/backends/`.

---

## Scope

- Create `parrot/human/actions/backends/__init__.py` (empty re-exports).
- Create `parrot/human/actions/backends/base.py`: `ActionBackend` ABC with
  `async def execute(interaction, tier) -> Dict[str, Any]`; shared
  exception hierarchy (`ActionBackendError`, `EmailBackendError`,
  `ZammadBackendError`, `WebhookBackendError`).
- Create `parrot/human/actions/backends/email.py`: `EmailBackend`
  using `aiosmtplib`. Reads SMTP config from constructor (no global
  module reads). Renders `subject_template` and body from
  `interaction.question` + `interaction.context`. Validates `to` is
  non-empty list of strings.
- Create `parrot/human/actions/backends/zammad.py`: `ZammadBackend`
  using `aiohttp`. POSTs to `{base_url}/api/v1/tickets` with
  `Authorization: Token token={api_token}` header. Reads `queue`,
  `title_template`, `body_template` from `tier.action_metadata` /
  constructor.
- Create `parrot/human/actions/backends/webhook.py`: `WebhookBackend`
  using `aiohttp`. POSTs `{interaction_id, question, severity, user_id}`
  to configured `url`; expects `{deep_link: str}` response.
- Each backend returns at minimum `{"message": "<string for LLM>", ...}`.
- Each backend raises its typed exception on failure (HTTP non-2xx,
  SMTP refusal, network error). No silent failures.

**NOT in scope**: Wiring the backends into `NotifyAction` /
`TicketAction` (TASK-1276). Manager-level failure handling (TASK-1277).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/human/actions/backends/__init__.py` | CREATE | Re-export `ActionBackend`, `EmailBackend`, `ZammadBackend`, `WebhookBackend`, exception types |
| `packages/ai-parrot/src/parrot/human/actions/backends/base.py` | CREATE | `ActionBackend` ABC + exception hierarchy |
| `packages/ai-parrot/src/parrot/human/actions/backends/email.py` | CREATE | `EmailBackend` aiosmtplib send |
| `packages/ai-parrot/src/parrot/human/actions/backends/zammad.py` | CREATE | `ZammadBackend` aiohttp REST |
| `packages/ai-parrot/src/parrot/human/actions/backends/webhook.py` | CREATE | `WebhookBackend` generic POST |
| `packages/ai-parrot/tests/human/actions/test_backend_email.py` | CREATE | Unit tests w/ mocked aiosmtplib |
| `packages/ai-parrot/tests/human/actions/test_backend_zammad.py` | CREATE | Unit tests w/ `aiohttp_server` fixture |
| `packages/ai-parrot/tests/human/actions/test_backend_webhook.py` | CREATE | Unit tests w/ `aiohttp_server` fixture |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Existing — confirmed at HEAD:
from parrot.human.actions.base import EscalationAction
from parrot.human.models import HumanInteraction, EscalationTier
# New from TASK-1274:
from parrot.human import Severity, BusinessHours
# External:
import aiohttp                       # in deps
import aiosmtplib                    # >=3.0 — verify in pyproject.toml; add if missing
```

### Existing Signatures to Use

```python
# parrot/human/actions/base.py:9-22 — ABSTRACT BASE
class EscalationAction(ABC):
    @abstractmethod
    async def execute(
        self,
        interaction: "HumanInteraction",
        tier: "EscalationTier",
    ) -> Dict[str, Any]: ...

# parrot/handlers/agents/abstract.py:581-584 — SMTP config keys
# "hostname": config.get('smtp_host'),
# "port":     config.get('smtp_port'),
# "username": config.get('smtp_host_user'),
# "password": config.get('smtp_host_password')
# EmailBackend should accept these in its __init__ (keep keys consistent
# across the codebase).

# parrot/human/models.py:135-185 — HumanInteraction fields used:
#   interaction_id, question, context, source_agent, severity (NEW)
```

### Does NOT Exist

- ~~`parrot.human.actions.backends`~~ — submodule to be created.
- ~~`parrot.clients.zammad`~~ — NOT a separate client module; Zammad
  REST goes inside `backends/zammad.py`.
- ~~`parrot.clients.zendesk`~~ — out of scope for V1.
- ~~`requests` / `httpx`~~ — forbidden by project policy; use `aiohttp`.
- ~~Global SMTP singleton~~ — backend instances receive config via
  constructor; no module-level state.

---

## Implementation Notes

### Pattern to Follow

```python
# Existing async tool / async aiohttp pattern across the codebase:
#   - aiohttp.ClientSession() inside an `async with` per call (no shared session).
#   - Typed exception hierarchy: BaseError → ConcreteError.
#   - Backend constructors take config dicts/typed params; no global state.

class EmailBackend(ActionBackend):
    def __init__(self, *, host, port, username, password, default_from): ...
    async def execute(self, interaction, tier) -> Dict[str, Any]:
        meta = tier.action_metadata
        to = meta.get("to") or []
        if not to:
            raise EmailBackendError("EmailBackend: empty 'to' list")
        # ... aiosmtplib.send(...)
        return {
            "message": f"[escalated:email] Notified {', '.join(to)}.",
            "to": to,
            "status": "sent",
        }
```

### Key Constraints

- All methods async.
- No `requests` / `httpx`. Use `aiohttp` for HTTP, `aiosmtplib` for SMTP.
- `subject_template` / `title_template` are Python f-string-like with
  `.format(interaction=interaction, tier=tier)` — keep it simple, no
  Jinja.
- Validate `to`, `url`, `queue` at the top of `execute`; raise typed
  exception if missing.
- All HTTP requests use a per-call `aiohttp.ClientSession()` (no module
  globals); apply a reasonable timeout (default 10s).
- Loggers: `self.logger = logging.getLogger("parrot.human.actions.backends.<name>")`.
- Do NOT leak SMTP passwords / Zammad tokens in log messages.

### References in Codebase

- `parrot/human/actions/notify.py` and `ticket.py` — current stub
  patterns to replace (stay consistent on return-shape).
- `parrot/handlers/agents/abstract.py:581-584` — canonical SMTP config
  keys; `EmailBackend.__init__` parameter names should align.

---

## Acceptance Criteria

- [ ] `from parrot.human.actions.backends import EmailBackend, ZammadBackend, WebhookBackend` works.
- [ ] `EmailBackend.execute()` against a mocked aiosmtplib send returns a
  dict with `message` containing every recipient.
- [ ] `EmailBackend.execute()` with empty `to` raises `EmailBackendError`.
- [ ] `ZammadBackend.execute()` against an `aiohttp_server` stub returns
  a dict whose `message` contains the ticket id and URL.
- [ ] `ZammadBackend.execute()` against an HTTP 500 stub raises
  `ZammadBackendError`.
- [ ] `WebhookBackend.execute()` POSTs the documented payload shape
  (`{interaction_id, question, severity, user_id}`) and surfaces the
  returned `deep_link` in `message`.
- [ ] `WebhookBackend.execute()` against an HTTP 502 stub raises
  `WebhookBackendError`.
- [ ] No SMTP password / Zammad token appears in captured logs.
- [ ] `ruff check packages/ai-parrot/src/parrot/human/actions/backends/` passes.
- [ ] All tests pass:
  `pytest packages/ai-parrot/tests/human/actions/ -v`.

---

## Test Specification

```python
# tests/human/actions/test_backend_email.py
import pytest
from unittest.mock import AsyncMock, patch
from parrot.human.actions.backends import EmailBackend, EmailBackendError

class TestEmailBackend:
    @pytest.fixture
    def backend(self):
        return EmailBackend(host="localhost", port=25, username="u", password="p", default_from="bot@x")

    async def test_send_returns_message_with_recipients(self, backend):
        # patch aiosmtplib.send
        ...

    async def test_empty_to_raises(self, backend):
        ...

# tests/human/actions/test_backend_zammad.py
async def test_create_ticket_returns_id(aiohttp_server):
    ...

# tests/human/actions/test_backend_webhook.py
async def test_post_returns_deep_link(aiohttp_server):
    ...
```

---

## Agent Instructions

1. Read spec §3 C2 and §6 Codebase Contract.
2. Verify TASK-1274 is completed (Severity / BusinessHours available).
3. Confirm `aiosmtplib` is in `pyproject.toml`; if not, add `>=3.0`.
4. Implement each backend, write its tests, run them locally.
5. Move task file to `sdd/tasks/completed/` and update the index.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-22
**Notes**: All 16 tests pass. EmailBackend uses aiosmtplib.send(), ZammadBackend and
WebhookBackend use per-call aiohttp.ClientSession(). Exception hierarchy rooted at
ActionBackendError with typed subclasses EmailBackendError, ZammadBackendError,
WebhookBackendError. aiosmtplib>=3.0 already in deps (found 5.1.0).
**Deviations from spec**: none
