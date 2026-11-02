# TASK-5038: Core `ConnectionAuthorizer` Protocol + principal-aware `IntegrationsService`

**Feature**: FEAT-777 — Connections — Web + Slack
**Spec**: `sdd/specs/connections-web-slack.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5035
**Assigned-to**: unassigned

---

## Context

Spec Module 2, "Request-independent authorization contract" (AC-14). Today every `IntegrationsService` PBAC
check goes through `_check_pbac(request, ...)`, which returns `False` when `request is None`
(`service.py:493-495`). Slack commands have no HTTP request, so after S-1 they can never list, connect,
check status or disconnect. This task adds a core Protocol the server implements (TASK-5039) and lets the
service evaluate non-web calls through it — never by fabricating a request, never by treating `request=None`
as permission.

Core must not import server code: the Protocol lives in core, the adapter is injected.

---

## Scope

- In `IntegrationsService._descriptor` (`service.py:138`), pass `grant_origin=integration_row.grant_origin if integration_row else None`
  into `IntegrationDescriptor(...)` — *why*: TASK-5035 adds the field; the Connections panel displays it (spec M3).
- Create `packages/ai-parrot/src/parrot/auth/oauth2/authorization.py` with
  `ConnectionAuthorizer(Protocol)`: `async authorize(principal: Principal, action: str, provider_id: Optional[str], scopes: List[str]) -> bool`.
- `IntegrationsService.__init__` gains keyword-only `authorizer: Optional[ConnectionAuthorizer] = None`
  (keep the positional `vault_token_sync` first for back-compat).
- `list_for_principal`, `status`, `disconnect` gain keyword-only `principal: Optional[Principal] = None`
  (`start_connect` already has it, `service.py:296`).
- Add private `_authorize(request, principal, user_id, action, provider_id=None, scopes=None) -> bool`:
  - `request is not None` → existing `_check_pbac(...)` (web path unchanged).
  - else → require `principal is not None`, `principal.user_id == user_id`, `self._authorizer is not None`,
    and `await self._authorizer.authorize(...) is True` (identity check, not truthiness). Any exception → `False` + log.
- Replace the five `_check_pbac` call sites (lines 102, 113, 326, 366, 391) with `_authorize(...)`.
- Unit tests for every branch.

**NOT in scope**: the navigator-auth adapter (TASK-5039); app wiring (TASK-5041); Slack commands (TASK-5044);
hardening the web `_check_pbac` truthiness (`bool(result)` at :513 — out of scope, spec §7);
changing `ConnectionsHandler`/`IntegrationsHandler` call sites (they pass `request=`, unchanged).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/oauth2/authorization.py` | CREATE | `ConnectionAuthorizer` Protocol |
| `packages/ai-parrot/src/parrot/auth/oauth2/service.py` | MODIFY | inject authorizer; principal kw; `_authorize` helper |
| `packages/ai-parrot/tests/auth/test_integrations_service_authorizer.py` | CREATE | branch tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.principal import Principal                      # verified: auth/principal.py:18; imported in service.py:26
from parrot.auth.oauth2.service import IntegrationsService        # verified: service.py:65 (class); exported by parrot/auth/oauth2/__init__.py
from parrot.auth.oauth2.registry import OAuth2ProviderRegistry    # verified: service.py:38
from parrot.auth.oauth2.models import IntegrationDescriptor, DisconnectResponse   # verified: service.py:29-34
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/oauth2/service.py
from parrot.auth.principal import Principal                                   # :26 (anchor)
class IntegrationsService:
    def __init__(self, vault_token_sync: Any = None) -> None:                  # :77 (anchor)
        self._vault_token_sync = vault_token_sync                              # :78
        self._identity_store_instance: Any = None                              # :79 (anchor)
    async def list_for_principal(self, user_id: str, request: Any = None) -> List[IntegrationDescriptor]:  # :81
        if not await self._check_pbac(request, "integration:list"):            # :102
            if not await self._check_pbac(request, "integration:list", provider.provider_id):   # :113
    async def list_for_user(self, user_id, agent_id, request=None)             # :119 → calls list_for_principal(user_id, request=request)
    async def start_connect(self, user_id, provider_id, return_origin=None, *, channel=_WEB_CHANNEL,
                            principal: Optional[Principal] = None, scopes=None, request=None, extra_state=None)  # :288
        if not await self._check_pbac(request, "integration:connect", provider_id, requested_scopes):  # :326
        # non-web: `elif principal is None: raise ValueError(...)` :338-339 (runs AFTER PBAC today)
    async def status(self, user_id: str, provider_id: str, request: Any = None) -> IntegrationDescriptor:  # :360
        if not await self._check_pbac(request, "integration:list", provider_id):   # :366
    async def disconnect(self, user_id: str, provider_id: str, request: Any = None) -> DisconnectResponse:  # :371
        if not await self._check_pbac(request, "integration:disconnect", provider_id, list(provider.default_scopes)):  # :391
        await provider.manager.revoke(channel=_WEB_CHANNEL, user_id=user_id)   # :393
    async def _check_pbac(self, request, action, provider_id=None, scopes=None) -> bool:  # :471
        # request None → False (:493-495); abac missing → False; result = await abac.is_allowed(request, ctx); return bool(result)
```

### Does NOT Exist
- ~~`parrot.auth.oauth2.authorization`~~ — created by this task.
- ~~`IntegrationsService(authorizer=...)`~~ / ~~`self._authorizer`~~ — added by this task.
- ~~`IntegrationsService._authorize`~~ — added by this task.
- ~~A request-free path inside `_check_pbac`~~ — it must stay request-only; do not add one.
- ~~`parrot.services.connection_authorization`~~ in core — server-only (TASK-5039); core must never import it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/auth/oauth2/authorization.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/auth/oauth2/service.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/auth/test_integrations_service_authorizer.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/service.py#IntegrationsService",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/service.py#IntegrationsService._check_pbac",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/service.py#IntegrationsService.start_connect",
    "sym:packages/ai-parrot/src/parrot/auth/principal.py#Principal"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Web path behaviour (request given) is byte-for-byte unchanged — existing tests
  (`tests/unit/integrations/oauth2/test_service.py`, `packages/ai-parrot/tests/auth/test_integrations_status.py`) must still pass.
- For `start_connect` with `request is None`, `channel != "web"`, and `principal is None`, keep raising the
  existing `ValueError` — but the PBAC check now runs through `_authorize`, which denies first (PermissionError);
  keep that order (authorization before state creation) — spec "missing/denied PDP → no state".
- Only `is True` grants. A `MagicMock()` return (truthy) must deny — test it.
- `_descriptor(..., request)` is called with `request=None` on the Slack path; it already handles `None`.

### References in Codebase
- `service.py:471-520` — fail-closed style and logging to mirror.

---

## Implementation Blueprint

### Steps (in order)
1. Create `authorization.py` — *why*: core Protocol so Slack/core never import server.
2. Add the `authorizer` kw + `_authorizer` attribute — *why*: injected per-service (Slack service factory, TASK-5044).
3. Add `_authorize` next to `_check_pbac` — *why*: one decision point for web and non-web.
4. Add `principal` kw to `list_for_principal`/`status`/`disconnect`; swap the five `_check_pbac` calls — *why*: AC-14.
5. Write the tests.

### `packages/ai-parrot/src/parrot/auth/oauth2/authorization.py` (CREATE)
```python
"""Request-independent authorization for connection operations (FEAT-777 M2).

Core declares the contract; the server injects a navigator-auth PDP adapter
(``parrot.services.connection_authorization.NavigatorConnectionAuthorizer``).
"""

from __future__ import annotations

from typing import List, Optional, Protocol, runtime_checkable

from parrot.auth.principal import Principal


@runtime_checkable
class ConnectionAuthorizer(Protocol):
    """Decide whether ``principal`` may perform a connection ``action`` without an HTTP request."""

    async def authorize(
        self,
        principal: Principal,
        action: str,
        provider_id: Optional[str],
        scopes: List[str],
    ) -> bool:
        """Return ``True`` only for an explicit ALLOW.

        Args:
            principal: Resolved platform principal (never taken from channel input).
            action: ``integration:list`` | ``integration:connect`` | ``integration:disconnect``.
            provider_id: Provider id, or ``None`` for the collection (``integration:*``).
            scopes: Effective requested scopes (provider defaults included for connect).
        """
        ...
```
**Why this shape**: the signature is fixed by spec M2 ("Request-independent authorization contract").

### `packages/ai-parrot/src/parrot/auth/oauth2/service.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.auth.principal import Principal' service.py)
# AFTER — insert below `from parrot.auth.principal import Principal` (verified: service.py:26)
from parrot.auth.oauth2.authorization import ConnectionAuthorizer

# occurrences: 1 (verified: grep -c '    def __init__(self, vault_token_sync: Any = None) -> None:' service.py)
# REPLACE the line at service.py:77 with:
    def __init__(self, vault_token_sync: Any = None, *, authorizer: Optional[ConnectionAuthorizer] = None) -> None:
# occurrences: 1 (verified: grep -c '        self._identity_store_instance: Any = None' service.py)
# AFTER — insert below it (verified: service.py:79)
        self._authorizer = authorizer

# occurrences: 1 (verified: grep -c '    async def _check_pbac(' service.py)
# BEFORE — insert above `    async def _check_pbac(` (verified: service.py:471)
    async def _authorize(
        self,
        request: Any,
        principal: Optional[Principal],
        user_id: str,
        action: str,
        provider_id: Optional[str] = None,
        scopes: Optional[List[str]] = None,
    ) -> bool:
        """Web calls use request PBAC; non-web calls require principal + injected authorizer (AC-14)."""
        if request is not None:
            return await self._check_pbac(request, action, provider_id, scopes)
        if principal is None or self._authorizer is None or str(principal.user_id) != str(user_id):
            logger.debug("Denying %s: missing principal/authorizer or principal mismatch", action)
            return False
        try:
            decision = await self._authorizer.authorize(principal, action, provider_id, list(scopes or []))
        except Exception:  # noqa: BLE001 — evaluator errors fail closed
            logger.exception("Connection authorizer failed for action=%s provider=%s — denying", action, provider_id)
            return False
        return decision is True
```
Then edit the call sites (each anchor occurs once — verified with `grep -c`):
- `list_for_principal` signature (:81-85): add `*, principal: Optional[Principal] = None` after `request`;
  :102 → `if not await self._authorize(request, principal, user_id, "integration:list"):`;
  :113 → `if not await self._authorize(request, principal, user_id, "integration:list", provider.provider_id):`.
- `start_connect` :326 → `if not await self._authorize(request, principal, user_id, "integration:connect", provider_id, requested_scopes):`.
- `status` :360 → add `*, principal: Optional[Principal] = None`; :366 → `_authorize(request, principal, user_id, "integration:list", provider_id)`.
- `disconnect` :371-376 → add `*, principal: Optional[Principal] = None`; :391 → `_authorize(request, principal, user_id, "integration:disconnect", provider_id, list(provider.default_scopes))`.
- Update the four docstrings' `Args:` with `principal`.
**Why**: keeps the web path in `_check_pbac` untouched while giving Slack an explicit, injected decision.

### `packages/ai-parrot/tests/auth/test_integrations_service_authorizer.py` (CREATE)
```python
"""IntegrationsService request-independent authorization (FEAT-777 AC-14)."""

from __future__ import annotations

from typing import Any, List, Optional

import pytest

from parrot.auth.oauth2.authorization import ConnectionAuthorizer
from parrot.auth.oauth2.service import IntegrationsService
from parrot.auth.principal import Principal


class RecordingAuthorizer:
    """Authorizer double returning a fixed decision and recording calls."""

    def __init__(self, decision: Any) -> None:
        self.decision = decision
        self.calls: List[tuple] = []

    async def authorize(self, principal: Principal, action: str, provider_id: Optional[str], scopes: List[str]) -> Any:
        self.calls.append((principal.user_id, action, provider_id, list(scopes)))
        return self.decision


@pytest.fixture
def principal() -> Principal:
    return Principal(user_id="1042", channel="slack", channel_user_id="T01:U02")


def test_protocol_runtime_checkable() -> None:
    assert isinstance(RecordingAuthorizer(True), ConnectionAuthorizer)


async def test_no_request_no_authorizer_denies(principal: Principal) -> None:
    assert await IntegrationsService()._authorize(None, principal, "1042", "integration:list") is False


async def test_principal_mismatch_denies(principal: Principal) -> None:
    svc = IntegrationsService(authorizer=RecordingAuthorizer(True))
    assert await svc._authorize(None, principal, "9999", "integration:list") is False


async def test_truthy_non_bool_denies(principal: Principal) -> None:
    # FILL IN: RecordingAuthorizer(object()) → False; RecordingAuthorizer(True) → True — bounded by AC-14 "explicit ALLOW only"
    ...


async def test_authorizer_exception_denies(principal: Principal) -> None:
    # FILL IN: authorizer raising RuntimeError → False, no exception propagates — bounded by AC-14
    ...


async def test_list_for_principal_uses_authorizer(principal: Principal) -> None:
    # FILL IN: register a stub provider in OAuth2ProviderRegistry (see tests/unit/integrations/oauth2/test_service.py
    # for the existing pattern), patch parrot.auth.oauth2.service.list_users_integrations → [];
    # assert list_for_principal("1042", principal=principal) returns one descriptor and the recorded
    # actions include ("integration:list", None) then ("integration:list", "<provider>") — bounded by spec M2
    ...


async def test_start_connect_denied_creates_no_state(principal: Principal) -> None:
    # FILL IN: authorizer False → PermissionError and provider.manager.create_authorization_url not awaited — bounded by AC-14
    ...


async def test_web_path_unchanged() -> None:
    # FILL IN: with a request whose app lacks "abac", _authorize(request, None, "1", ...) is False and the
    # authorizer is never called — bounded by "keep the existing authenticated web PBAC path"
    ...
```

### FILL IN checklist
- [ ] `test_truthy_non_bool_denies` — identity check; AC-14.
- [ ] `test_authorizer_exception_denies` — fail closed; AC-14.
- [ ] `test_list_for_principal_uses_authorizer` — provider stub + action sequence; spec M2.
- [ ] `test_start_connect_denied_creates_no_state` — no OAuth state on deny; AC-14.
- [ ] `test_web_path_unchanged` — authorizer bypassed when a request is present.

---

## Acceptance Criteria

- [ ] `from parrot.auth.oauth2.authorization import ConnectionAuthorizer` works.
- [ ] Non-web calls without principal, with mismatched principal, without authorizer, with a non-`True`
      decision or with an authorizer error are denied; `True` is allowed (AC-14).
- [ ] Existing service and handler tests still pass (web path unchanged).
- [ ] `ruff check` clean on touched files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/auth/test_integrations_service_authorizer.py -q`
- `pytest tests/unit/integrations/oauth2/test_service.py -q`
- `pytest packages/ai-parrot/tests/auth/test_integrations_status.py -q`
- `pytest tests/unit/integrations/oauth2/test_handler.py -q`

---

## Test Specification

See the CREATE block for `test_integrations_service_authorizer.py` above.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug connections-web-slack --feature-id FEAT-777`)
2. **Read the spec** (Module 2, "Request-independent authorization contract")
3. **Check dependencies** in `sdd/tasks/index/connections-web-slack.json`
4. **Verify the Codebase Contract** before writing any code
5. **Update status** → `"in-progress"` and commit only the index
6. **Implement** from the blueprint, completing every `# FILL IN:`
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — only the listed files
9. **Close** with `scripts/sdd/close_task.sh TASK-5038 connections-web-slack verified`
10. **Fill in the Completion Note**, commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker orchestrator; seats codex terra/sol/luna + native sonnet
**Date**: 2026-10-31
**Notes**: Implemented per task; merged and merge-tier validated (only red: 3 failures that also fail on origin/dev: test_o365_refresh x2, slack test_manager_payload_drives_identity_and_dm).

**Deviations from spec**: none | describe if any
