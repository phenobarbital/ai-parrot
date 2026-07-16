---
type: Wiki Overview
title: 'TASK-002: Minimal async Microsoft Graph client (email→AAD resolution)'
id: doc:sdd-tasks-completed-task-002-graph-client-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module 1. The channel receives an **email** as `recipient` (decision
---

# TASK-002: Minimal async Microsoft Graph client (email→AAD resolution)

**Feature**: FEAT-205 — TeamsHumanChannel
**Spec**: `sdd/specs/hitl-teams-channel.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. The channel receives an **email** as `recipient` (decision
D4) and must resolve it to an Azure AD object id (+ `serviceUrl`) before it can
open a proactive 1:1. No `GraphClient` exists in the repo — this is net-new.
Also exposes `get_user_manager` as the future backend for the escalation
`TargetResolver` (out of scope to wire here).

---

## Scope

- Implement an async `aiohttp` Microsoft Graph client:
  - client-credentials token acquisition (app creds, may differ from bot creds).
  - `get_user_by_email(email) -> ResolvedTeamsUser | None`: try `/users/{upn}`;
    on 404 (email ≠ UPN) fall back to `/users?$filter=mail eq '{email}'`.
  - `get_user_manager(upn)`: `/users/{upn}/manager` (offered as resolver backend).
- Return `None` (never raise) on lookup failure so the channel can fail-fast to
  `False` (spec §5).
- Pydantic `ResolvedTeamsUser` model (`aad_object_id`, `upn`, `email`,
  `service_url`).
- Unit tests with a stubbed Graph HTTP layer.

**NOT in scope**: convref cache / proactive send (TASK-004), card rendering
(TASK-003), `TargetResolver` wiring (escalation feature).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/graph.py` | CREATE | `GraphClient` + `ResolvedTeamsUser` |
| `packages/ai-parrot-integrations/tests/test_graph_client.py` | CREATE | Resolution + fallback + failure tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import aiohttp                      # async HTTP only — NO requests/httpx (project rule)
from pydantic import BaseModel, Field
# navconfig supplies Graph creds (graph_client_id/secret/tenant) at boot.
```

### Existing Signatures to Use
```python
# Target return shape (defined in spec §2 Data Models — implement as Pydantic):
class ResolvedTeamsUser(BaseModel):
    aad_object_id: str
    upn: str
    email: str
    service_url: Optional[str] = None
```

### Does NOT Exist
- ~~`azure_teambots.GraphClient` / `get_user_by_upn` / `get_user_manager`~~ — do NOT import; build net-new here.
- ~~any existing Graph client in `parrot.*`~~ — none; this is the first.
- ~~`requests` / `httpx`~~ — forbidden; use `aiohttp`.

---

## Implementation Notes

### Key Constraints
- async/await throughout; `self.logger` for diagnostics (no secrets logged).
- Token caching with expiry is fine; keep it in-process (Redis not required here).
- Graph app needs `User.Read.All` (documented in spec §7 Configuration).

### References in Codebase
- Spec §2 Data Models (`ResolvedTeamsUser`), §5 acceptance criteria (fail-fast → None).

---

## Acceptance Criteria

- [ ] `get_user_by_email` resolves via `/users/{upn}` when email == UPN.
- [ ] Falls back to `mail eq` filter on 404.
- [ ] Returns `None` (no raise) on any Graph error.
- [ ] `get_user_manager(upn)` implemented.
- [ ] No linting errors: `ruff check .../msteams/graph.py`
- [ ] Tests pass: `pytest packages/ai-parrot-integrations/tests/test_graph_client.py -v`

---

## Test Specification
```python
# packages/ai-parrot-integrations/tests/test_graph_client.py
import pytest

async def test_resolve_by_upn(graph_client_with_stub): ...
async def test_resolve_mail_filter_fallback_on_404(graph_client_with_stub): ...
async def test_resolve_failure_returns_none(graph_client_with_stub): ...
async def test_get_user_manager(graph_client_with_stub): ...
```

---

## Agent Instructions
Standard SDD flow. Verify the contract, implement, move to `completed/`, update index.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-29
**Notes**: Implemented GraphClient with client-credentials token caching, get_user_by_email (UPN direct + mail-filter fallback),
and get_user_manager. ResolvedTeamsUser Pydantic model included. All 7 unit tests pass with stubbed aiohttp sessions.
No real HTTP calls in tests. Fork's graph.py used as structural reference only (it lacked Pydantic model and mail-filter fallback).
**Deviations from spec**: none
