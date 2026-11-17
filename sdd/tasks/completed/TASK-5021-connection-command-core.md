# TASK-5021: Channel-neutral connection command core (`ConnectionCommandService`)

**Feature**: FEAT-776 — Connections on Telegram
**Spec**: `sdd/specs/connections-telegram.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5018
**Assigned-to**: unassigned

---

## Context

Spec §2 "Command core", §3 Module 5, AC-4. A channel-neutral layer between chat commands and
`IntegrationsService`: it filters the provider registry to connectable providers, applies the allowlist, chooses
server-owned scopes, maps service outcomes to typed values, and never sends messages. Telegram uses it now;
FEAT-775 may adopt it later (§8 Q2 of FEAT-775). It calls the FEAT-775 `permission_context` API verified by
TASK-5018 — that is the only reason for the dependency.

---

## Scope

- Create `integrations/core/auth/connections.py`: `ConnectableProvider`, `OutcomeKind`, `ConnectOutcome`,
  `ConnectionStatusLine`, `ConnectionCommandService`.
- Export the five names from `integrations/core/auth/__init__.py`.
- Tests `test_connectable_providers_filter`, `test_connect_outcomes`, `test_scopes_never_from_user`.

**NOT in scope**: Telegram rendering/handlers (TASK-5024), device-code instructions (rendered only by TASK-5026;
`start_connect` returns `ConnectInitResponse`, never a device-code challenge), any service change.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/core/auth/connections.py` | CREATE | command core |
| `packages/ai-parrot-integrations/src/parrot/integrations/core/auth/__init__.py` | MODIFY | exports |
| `packages/ai-parrot-integrations/tests/integrations/core/test_connection_command_service.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.oauth2.registry import OAuth2Provider, OAuth2ProviderRegistry   # verified: registry.py:20, :69 (all() :117, get() :106, _reset() :92)
from parrot.auth.oauth2.models import ConnectInitResponse, IntegrationDescriptor # verified: oauth2/models.py:80, :21
from parrot.auth.permission import PermissionContext                             # verified: permission.py:81
from parrot.auth.principal import Principal                                      # verified: principal.py:18
# TYPE_CHECKING only:
from parrot.auth.oauth2.service import IntegrationsService                       # verified: service.py:65
```

### Existing Signatures to Use
```python
# registry.py — OAuth2Provider class attrs
provider_id: str; display_name: str; icon: Optional[str] = None
default_scopes: ClassVar[List[str]] = []          # :39
@property def manager(self) -> Any                 # :44  (None ⇒ not connectable)

# oauth2/models.py
class IntegrationDescriptor: provider; display_name; connected: bool; status: Optional["connected"|"disconnected"|"needs_reconnect"];
    display_account_name: Optional[str]; scopes_granted: List[str]          # :21
class ConnectInitResponse: auth_url: str; state: str; scopes: List[str]; expires_in: int = 600   # :80

# IntegrationsService AFTER FEAT-775 — copy the exact signatures from TASK-5018's Completion Note. Expected:
#   start_connect(user_id, provider_id, return_origin=None, *, channel, principal, scopes, request, extra_state, permission_context)
#   disconnect(user_id, provider_id, request=None, *, channel, principal, permission_context)
#   status(user_id, provider_id, request=None, *, principal, permission_context)
#   list_for_principal(user_id, request=None, *, principal, permission_context)
#   denial → PermissionError (status/connect/disconnect), [] (list); unknown provider → ValueError
```

### Does NOT Exist
- ~~`ConnectionCommandService`, `ConnectOutcome`, `ConnectionStatusLine`, `ConnectableProvider`~~ — created here.
- ~~`ConnectionChannel` protocol~~ — not created by this spec.
- ~~A device-code field on `ConnectInitResponse`~~ — none.
- ~~User-supplied scopes~~ — no command argument may reach `scopes`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/core/auth/connections.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/core/auth/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/integrations/core/test_connection_command_service.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/registry.py#OAuth2ProviderRegistry",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/registry.py#OAuth2Provider",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/models.py#IntegrationDescriptor",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/models.py#ConnectInitResponse"
  ]
}
```

---

## Implementation Notes

- Connectable = `provider.manager is not None` and `not provider_id.startswith("mcp:")` and (allowlist is None or id in it).
  Re-check the manager at call time (`unavailable` when it disappeared).
- `resolve_provider`: alias `{"office365": "o365"}` first, then case-insensitive match on connectable ids only.
- Scopes: explicit commands → `provider.default_scopes`; automatic offers (TASK-5026) pass the sorted union of trusted
  payload scopes (defaults when the union is empty). `already_connected` only when the active grant
  (`status == "connected"` and `set(scopes_granted) ⊇ requested`) covers every requested scope.
- Messages are plain text, no Markdown (Telegram sends with `parse_mode=None`).

---

## Implementation Blueprint

### Steps (in order)
1. Write models + service skeleton below — *why*: §2 Data Models are fixed.
2. Fill the outcome mapping — *why*: AC-4, AC-7 (denial → `denied`).
3. Export from `__init__.py`; write tests with a fake service (spec §4 fixture `fake_integrations_service`).

### `packages/ai-parrot-integrations/src/parrot/integrations/core/auth/connections.py` (CREATE)
```python
"""Channel-neutral connection commands over IntegrationsService (FEAT-776 M5)."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Mapping, Optional, Sequence

from pydantic import BaseModel

from parrot.auth.oauth2.registry import OAuth2Provider, OAuth2ProviderRegistry
from parrot.auth.permission import PermissionContext
from parrot.auth.principal import Principal

if TYPE_CHECKING:  # pragma: no cover
    from parrot.auth.oauth2.service import IntegrationsService

_PROVIDER_ALIASES = {"office365": "o365"}

OutcomeKind = Literal["needs_login", "denied", "unknown_provider", "unavailable",
                      "already_connected", "auth_url", "disconnected"]


class ConnectableProvider(BaseModel):
    """A provider a channel user may connect."""

    provider_id: str
    display_name: str
    icon: Optional[str] = None


class ConnectOutcome(BaseModel):
    """Result of a connect/disconnect command (never sent by this module)."""

    kind: OutcomeKind
    provider_id: str
    display_name: str = ""
    auth_url: Optional[str] = None
    account_display_name: str = ""
    message: str = ""


class ConnectionStatusLine(BaseModel):
    """One provider's connection status for a principal."""

    provider_id: str
    display_name: str
    status: Literal["connected", "disconnected", "needs_reconnect"]
    account_display_name: str = ""


class ConnectionCommandService:
    """Filter providers, choose server-owned scopes, and map service results to outcomes."""

    def __init__(self, *, service: "IntegrationsService", app: Mapping[str, Any], channel: str,
                 allowlist: Optional[Sequence[str]] = None,
                 registry: Optional[OAuth2ProviderRegistry] = None) -> None:
        self._service = service
        self._app = app
        self.channel = channel
        self._allowlist = set(allowlist) if allowlist is not None else None
        self._registry = registry or OAuth2ProviderRegistry()
        self.logger = logging.getLogger(__name__)

    def _connectable(self, provider: OAuth2Provider) -> bool:
        # FILL IN: manager present, not mcp:*, allowlist — bounded by AC-4
        raise NotImplementedError

    def connectable_providers(self) -> List[ConnectableProvider]:
        """registry.all() filtered by ``_connectable``, sorted by provider_id."""
        # FILL IN
        raise NotImplementedError

    def resolve_provider(self, name: str) -> Optional[ConnectableProvider]:
        """Case-insensitive match on connectable provider ids; aliases applied first."""
        # FILL IN
        raise NotImplementedError

    async def connect(self, principal: Optional[Principal], provider_id: str, *,
                      extra_state: Dict[str, Any], permission_context: PermissionContext,
                      scopes: Optional[List[str]] = None) -> ConnectOutcome:
        """needs_login → unknown_provider → unavailable → already_connected → auth_url; PermissionError → denied."""
        # FILL IN: requested = sorted(set(scopes)) if scopes else list(provider.default_scopes);
        # status(...) check; start_connect(principal.user_id, provider_id, channel=self.channel, principal=principal,
        # extra_state=extra_state, scopes=requested, permission_context=permission_context)
        raise NotImplementedError

    async def disconnect(self, principal: Optional[Principal], provider_id: str, *,
                         permission_context: PermissionContext) -> ConnectOutcome:
        """service.disconnect(..., channel=self.channel, principal=principal, permission_context=...) → disconnected."""
        # FILL IN
        raise NotImplementedError

    async def statuses(self, principal: Optional[Principal], *,
                       permission_context: PermissionContext) -> List[ConnectionStatusLine]:
        """list_for_principal filtered to connectable providers; denial → []."""
        # FILL IN
        raise NotImplementedError


__all__ = ["ConnectableProvider", "ConnectOutcome", "ConnectionStatusLine", "ConnectionCommandService", "OutcomeKind"]
```
**Why this shape**: models and method signatures are the spec skeleton verbatim; only bodies are open.

### `integrations/core/auth/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.integrations.core.auth.post_auth import PostAuthProvider, PostAuthRegistry' .../core/auth/__init__.py)
# AFTER that import:
from parrot.integrations.core.auth.connections import (
    ConnectableProvider,
    ConnectionCommandService,
    ConnectionStatusLine,
    ConnectOutcome,
)
# and append the four names to __all__
```

### `tests/integrations/core/test_connection_command_service.py` (CREATE)
```python
"""FEAT-776 M5 unit tests."""
import pytest

# FILL IN: provider_registry fixture (OAuth2ProviderRegistry._reset(); jira + dummy + "mcp:x" + manager None)
# and fake_integrations_service per spec §4 "Test Data / Fixtures"

def test_connectable_providers_filter() -> None: ...
@pytest.mark.asyncio
async def test_connect_outcomes() -> None: ...          # needs_login / unknown_provider / already_connected / auth_url / denied
@pytest.mark.asyncio
async def test_scopes_never_from_user() -> None: ...    # defaults for explicit, union for automatic, insufficient grant → auth_url
```

### FILL IN checklist
- [ ] All `raise NotImplementedError` bodies replaced
- [ ] `statuses` maps descriptor `status` + `display_account_name`
- [ ] Three test bodies; registry reset in teardown

---

## Acceptance Criteria

- [ ] AC-4 filter and scope rules hold; PBAC denial maps to `denied`; no message is sent by this module
- [ ] `from parrot.integrations.core.auth import ConnectionCommandService` works; `ruff check` clean

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/integrations/core/test_connection_command_service.py -q`

---

## Test Specification

Blueprint test file; names fixed by spec §4 (M5 rows).

---

## Agent Instructions

1. Work in the feature worktree; confirm TASK-5018 is `done` and copy its verified service signatures into this contract
2. Implement from the blueprint; validate with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src`
3. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-5021 connections-telegram verified`

---

## Completion Note

**Completed by**: sdd-worker; coded by gpt-5.6-terra (codex), attempt 1, reviewed by the worker
**Date**: 2026-11-01
**Notes**:
- `ConnectionCommandService`, `ConnectableProvider`, `ConnectOutcome`, `ConnectionStatusLine` in `core/auth/connections.py`; exported from `core/auth/__init__.py`.
- Filter: manager present, not `mcp:*`, allowlist when set. A configured provider whose manager is missing at call time returns `unavailable`. `office365` aliases to `o365`.
- Scopes: explicit commands use the provider's `default_scopes`; the `scopes` argument is only for trusted needs-auth payloads (TASK-5026). Nothing user-typed reaches it.
- Denials: `PermissionError` from `status`/`start_connect`/`disconnect` -> `denied`; `list_for_principal` denial -> `[]`.
- Tests: 3 in `tests/integrations/core/test_connection_command_service.py`, all pass (run by hand with absolute PYTHONPATH; merge-tier engine validation not used because of the 12 baseline reds on `dev`). Review `0 corrections`.

**Deviations from spec**: none
