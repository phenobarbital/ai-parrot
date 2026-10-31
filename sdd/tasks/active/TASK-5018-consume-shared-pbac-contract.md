# TASK-5018: Verify and consume FEAT-775's request-less PBAC contract (gate)

**Feature**: FEAT-776 — Connections on Telegram
**Spec**: `sdd/specs/connections-telegram.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none *(cross-feature gate: FEAT-775 M3/M7 merged on `origin/dev`)*
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3, §8 Q1, AC-7. Telegram commands have no aiohttp request, and today
`IntegrationsService._check_pbac` returns `False` when `request is None` (service.py:494-496). FEAT-775 M3/M7 is
the **sole owner** of the fix: a `permission_context: Optional[PermissionContext]` keyword on
`start_connect`/`disconnect`/`status`/`list_for_principal`/`_check_pbac`, an injected `permission_evaluator`
(constructor keyword), channel-aware `disconnect` (`channel`, `principal` → `manager.revoke`), and shared
production-adapter parity evidence. FEAT-776 adds **no** service code.

**State at decomposition (2026-10-31, dev @ d4e4978cd2):** FEAT-775 has a spec but no task index, and
`service.py` has none of these parameters. This task is therefore a **hard gate**: every downstream task that
calls the service with `permission_context` (TASK-5021 onward) waits on it.

**If FEAT-775's API is not on `origin/dev` when you start: STOP.** Do not implement it here (spec: "No duplicate
implementation if Telegram is scheduled first"). Leave this task `pending` (revert any `in-progress` stamp),
report "blocked on FEAT-775 M3/M7" to the user, and do not start dependants.

---

## Scope

- Verify on `origin/dev` that FEAT-775 merged the interface skeleton of spec §3 M3 (signatures below), including
  the §8 Q1 production-adapter parity tests (real allow/deny fixtures, not a mocked `is_allowed`).
- Write Telegram consumer contract tests: `test_channel_pbac_fails_closed`,
  `test_channel_pbac_uses_navigator_principal`, `test_service_request_less_pbac_branch`.
- Record the verified signatures (with line numbers) in this task's Completion Note; dependants copy them.

**NOT in scope**: editing `service.py`, server factories, a `channel_pbac.py`, a `permission_app`, or a
`check_integration_access` API (all forbidden by the spec).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/tests/integrations/telegram/test_connection_pbac_contract.py` | CREATE | consumer contract tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.oauth2.service import IntegrationsService                       # verified: service.py:65
from parrot.auth.permission import PermissionContext, UserSession                # verified: permission.py:81, :21
from parrot.auth.principal import Principal                                      # verified: principal.py:18
from parrot.auth.oauth2.registry import OAuth2Provider, OAuth2ProviderRegistry   # verified: registry.py:20, :69
```

### Existing Signatures to Use (current, BEFORE FEAT-775)
```python
# packages/ai-parrot/src/parrot/auth/oauth2/service.py
def __init__(self, vault_token_sync: Any = None) -> None                         # :77
async def list_for_principal(self, user_id: str, request: Any = None) -> List[IntegrationDescriptor]   # :81
async def start_connect(self, user_id, provider_id, return_origin=None, *, channel=_WEB_CHANNEL,
                        principal=None, scopes=None, request=None, extra_state=None) -> ConnectInitResponse  # :288
async def status(self, user_id: str, provider_id: str, request: Any = None) -> IntegrationDescriptor     # :360
async def disconnect(self, user_id: str, provider_id: str, request: Any = None) -> DisconnectResponse    # :371
#   :393 await provider.manager.revoke(channel=_WEB_CHANNEL, user_id=user_id)
async def _check_pbac(self, request, action, provider_id=None, scopes=None) -> bool                      # :471
#   :494 if request is None: return False ; :509 result = await abac.is_allowed(request, ctx)

# packages/ai-parrot/src/parrot/auth/permission.py
class UserSession: user_id: str; tenant_id: str; roles: frozenset[str]; metadata: dict     # :21 (fields :46-49)
class PermissionContext: session; request_id; channel; ...; extra                          # :81
```

### Expected Signatures AFTER FEAT-775 (verify; spec §3 M3 skeleton)
```python
def __init__(self, vault_token_sync: Any = None, *, permission_evaluator: Any = None) -> None
async def start_connect(..., extra_state=None, permission_context: Optional[PermissionContext] = None) -> ConnectInitResponse
async def disconnect(self, user_id, provider_id, request=None, *, channel="web", principal=None, permission_context=None)
async def status(self, user_id, provider_id, request=None, *, principal=None, permission_context=None)
async def list_for_principal(self, user_id, request=None, *, principal=None, permission_context=None)
async def _check_pbac(self, request, action, provider_id=None, scopes=None, *, principal=None, permission_context=None) -> bool
# denial: list → [], status/connect/disconnect → PermissionError; unknown provider → ValueError; no HTTP fallback.
```

### Does NOT Exist (at decomposition time)
- ~~`permission_context` parameter on any `IntegrationsService` method~~ — FEAT-775 adds it.
- ~~`IntegrationsService(permission_evaluator=...)`~~ — FEAT-775 adds it.
- ~~`parrot.auth.oauth2.channel_pbac`~~ / ~~`check_integration_access`~~ / ~~`permission_app`~~ — never created.
- ~~`ResourceType.INTEGRATION`~~ — not in navigator-auth 0.28.7.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/tests/integrations/telegram/test_connection_pbac_contract.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/service.py#IntegrationsService._check_pbac",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/service.py#IntegrationsService.start_connect",
    "sym:packages/ai-parrot/src/parrot/auth/permission.py#PermissionContext"
  ]
}
```

---

## Implementation Notes

- Context identity is the Navigator principal (`principal.user_id`); never the Telegram id.
- Roles/groups come only from validated session claims; a persisted-link-only principal has empty roles.
- Do not treat a mocked `abac.is_allowed` as parity evidence (§8 Q1 gate) — cite FEAT-775's parity test path.

---

## Implementation Blueprint

### Steps (in order)
1. `git fetch origin && git grep -n "permission_context" origin/dev -- packages/ai-parrot/src/parrot/auth/oauth2/service.py` — *why*: gate.
2. If absent → stop and report (see Context). If present → diff the real signatures against "Expected" above;
   any difference is recorded in the Completion Note and the dependants' contracts are corrected before they start.
3. Write the three consumer tests using an injected fake evaluator.

### `packages/ai-parrot-integrations/tests/integrations/telegram/test_connection_pbac_contract.py` (CREATE)
```python
"""FEAT-776 M3: Telegram consumes FEAT-775's request-less PBAC contract."""
import pytest

from parrot.auth.oauth2.service import IntegrationsService
from parrot.auth.permission import PermissionContext, UserSession
from parrot.auth.principal import Principal


def _ctx(user_id: str = "1042", channel: str = "telegram") -> PermissionContext:
    return PermissionContext(session=UserSession(user_id=user_id, tenant_id="default", roles=frozenset()), channel=channel)


@pytest.mark.asyncio
async def test_channel_pbac_fails_closed() -> None:
    # FILL IN: missing evaluator, missing context, principal/context user mismatch, evaluator raising → _check_pbac False
    ...


@pytest.mark.asyncio
async def test_channel_pbac_uses_navigator_principal() -> None:
    # FILL IN: capturing evaluator; assert the evaluated identity == principal.user_id ("1042"), never "88123"
    ...


@pytest.mark.asyncio
async def test_service_request_less_pbac_branch() -> None:
    # FILL IN: request=None + permission_context + principal → evaluator consulted; without them → denied
    ...
```

### FILL IN checklist
- [ ] Gate result and verified signatures recorded in the Completion Note
- [ ] Three test bodies against the real FEAT-775 API (registry fixture: `OAuth2ProviderRegistry._reset()` + a dummy provider)

---

## Acceptance Criteria

- [ ] FEAT-775 M3/M7 API confirmed on `origin/dev`, parity evidence path cited (else task stays blocked)
- [ ] Consumer tests pass; no service/factory file modified by this task

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/integrations/telegram/test_connection_pbac_contract.py -q`
- `pytest tests/unit/integrations/oauth2/test_service.py -q`

---

## Test Specification

Blueprint test file; names fixed by spec §4 (M3 rows).

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug connections-telegram --feature-id FEAT-776`)
2. Run the gate first; never implement FEAT-775's API here
3. Validate with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src`
4. Commit only the listed file; close with `scripts/sdd/close_task.sh TASK-5018 connections-telegram verified`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**: (gate result + verified FEAT-775 signatures with line numbers)

**Deviations from spec**: none
