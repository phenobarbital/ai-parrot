---
type: Wiki Overview
title: 'TASK-985: IntegrationsService'
id: doc:sdd-tasks-completed-task-985-integrations-service-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The `IntegrationsService` is the orchestration layer that combines the
relates_to:
- concept: mod:parrot.auth.jira_oauth
  rel: mentions
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.integrations
  rel: mentions
---

# TASK-985: IntegrationsService

**Feature**: FEAT-144 — Cross-Repository JiraToolkit OAuth2 3LO (Web AgentChat)
**Spec**: `sdd/specs/cross-repository-jiratoolkit-oauth2-3lo.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-983, TASK-984
**Assigned-to**: unassigned

---

## Context

The `IntegrationsService` is the orchestration layer that combines the
`OAuth2ProviderRegistry`, persistence, and PBAC checks into four cohesive
operations: list, start_connect, confirm_enable, and disconnect. It also
provides `persist_credential()` for the web-channel OAuth callback. The
handler (TASK-986) delegates all real work to this service.

Implements spec Module 5.

---

## Scope

- Create `service.py` with `IntegrationsService` class providing:
  - `list_for_user(user_id, agent_id)` — returns `List[IntegrationDescriptor]`,
    PBAC-filtered.
  - `start_connect(user_id, agent_id, provider_id, return_origin)` — validates
    origin against `WEB_OAUTH_ALLOWED_ORIGINS`, calls
    `provider.manager.create_authorization_url(channel="web", user_id,
    extra_state={"channel": "web", "agent_id": agent_id, "return_origin": origin})`,
    returns `ConnectInitResponse`.
  - `confirm_enable(user_id, agent_id, provider_id)` — verifies a
    `users_integrations` row exists (409 if not), upserts
    `user_agent_toolkits` row, returns `IntegrationDescriptor`.
  - `disconnect(user_id, agent_id, provider_id)` — deletes
    `users_integrations` row, cascade-deletes all `user_agent_toolkits` rows
    for `(user_id, provider)`, returns `DisconnectResponse`.
  - `persist_credential(user_id, provider_id, token_set)` — builds a
    `UsersIntegrationRow` from the token_set and upserts it. Called from the
    web-channel branch of `jira_oauth_callback`.
- Write comprehensive unit tests.

**NOT in scope**: handler/routing (TASK-986), callback modification (TASK-987),
AgentTalk envelope (TASK-988).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/integrations/oauth2/service.py` | CREATE | `IntegrationsService` implementation |
| `packages/ai-parrot/src/parrot/integrations/oauth2/__init__.py` | MODIFY | Add `IntegrationsService` re-export |
| `tests/unit/integrations/oauth2/test_service.py` | CREATE | Service tests with mocked deps |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# From TASK-983:
from parrot.integrations.oauth2 import _WEB_CHANNEL
from parrot.integrations.oauth2.models import (
    IntegrationDescriptor, ConnectInitResponse, DisconnectResponse,
    UsersIntegrationRow, UserAgentToolkitRow,
)
from parrot.integrations.oauth2.registry import OAuth2ProviderRegistry

# From TASK-984:
from parrot.integrations.oauth2.persistence import (
    upsert_users_integration, get_users_integration,
    delete_users_integration, upsert_user_agent_toolkit,
    list_user_agent_toolkits, delete_user_agent_toolkits_by_provider,
)

# Existing — verified:
from parrot.auth.jira_oauth import JiraOAuthManager, JiraTokenSet  # jira_oauth.py:59,86
from parrot.conf import WEB_OAUTH_ALLOWED_ORIGINS  # added by TASK-986 (or add here if needed first)

from navconfig.logging import logging  # standard pattern
```

### Existing Signatures to Use
```python
# parrot/auth/jira_oauth.py:258
class JiraOAuthManager:
    async def create_authorization_url(
        self, channel: str, user_id: str,
        extra_state: Optional[Dict[str, Any]] = None,
    ) -> Tuple[str, str]: ...  # returns (url, nonce)

# parrot/auth/jira_oauth.py:59
class JiraTokenSet(BaseModel):
    access_token: str
    refresh_token: str
    expires_at: float
    cloud_id: str
    site_url: str
    account_id: str
    display_name: str
    email: Optional[str]
    scopes: List[str]
    granted_at: float
    last_refreshed_at: float
    available_sites: List[Dict[str, Any]]
```

### Does NOT Exist
- ~~`parrot.integrations.oauth2.service`~~ — does not exist yet; this task creates it.
- ~~`WEB_OAUTH_ALLOWED_ORIGINS`~~ — does not exist in `parrot/conf.py` yet. Either
  TASK-986 adds it first, or this task reads it directly from navconfig. Check
  whether TASK-986 is complete; if not, read directly:
  `from navconfig import config; origins = config.get("WEB_OAUTH_ALLOWED_ORIGINS", fallback=[])`.
- ~~`request.app['abac']`~~ — may or may not exist at runtime. Convention: fail-open
  when absent (see AgentTalk._check_pbac_agent_access pattern at agent.py:83).
- ~~`OAuth2ProviderRegistry.get_all()`~~ — the method is `all()`, not `get_all()`.

---

## Implementation Notes

### PBAC Convention
```python
# Follow AgentTalk's fail-open pattern when no PDP is configured:
async def _check_pbac(self, request, action: str, provider_id: str) -> bool:
    abac = request.app.get('abac') if request else None
    if abac is None:
        return True  # fail-open (current convention)
    # ... evaluate policy ...
```

Note: open question Q-B says fail-closed for integrations. Check with spec owner.
The spec resolved Q-B as "fail-closed" — implement accordingly unless overridden.

### Origin Validation
```python
async def start_connect(self, user_id, agent_id, provider_id, return_origin):
    # WEB_OAUTH_ALLOWED_ORIGINS is a list of strings
    if return_origin not in WEB_OAUTH_ALLOWED_ORIGINS:
        raise ValueError(f"Origin {return_origin!r} not in allowed origins")
    provider = OAuth2ProviderRegistry().get(provider_id)
    if provider is None:
        raise ValueError(f"Unknown provider: {provider_id}")
    url, nonce = await provider.manager.create_authorization_url(
        channel=_WEB_CHANNEL,
        user_id=user_id,
        extra_state={"channel": "web", "agent_id": agent_id, "return_origin": return_origin},
    )
    return ConnectInitResponse(
        auth_url=url, state=nonce,
        scopes=provider.default_scopes, expires_in=600,
    )
```

### Idempotency
- `confirm_enable` upserts — calling twice is a no-op.
- `disconnect` deletes — calling twice is a no-op (second call finds no rows).

---

## Acceptance Criteria

- [ ] `list_for_user` returns descriptors with accurate `connected` and `enabled_on_agent` flags.
- [ ] `start_connect` validates origin and raises `ValueError` for disallowed origins.
- [ ] `start_connect` passes `extra_state` with `channel`, `agent_id`, `return_origin`.
- [ ] `confirm_enable` raises (409-equivalent) when no `users_integrations` row exists.
- [ ] `confirm_enable` is idempotent — second call is a no-op.
- [ ] `disconnect` cascade-deletes both `users_integrations` and all `user_agent_toolkits` for `(user, provider)`.
- [ ] `disconnect` is idempotent — second call is a no-op.
- [ ] `persist_credential` builds `UsersIntegrationRow` from `JiraTokenSet` fields.
- [ ] All tests pass: `pytest tests/unit/integrations/oauth2/test_service.py -v`
- [ ] No lint errors.

---

## Test Specification

```python
# tests/unit/integrations/oauth2/test_service.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from parrot.integrations.oauth2.service import IntegrationsService


class TestListForUser:
    @pytest.mark.asyncio
    async def test_returns_descriptors_with_connected_flag(self):
        # Mock registry with one provider, persistence with one row
        ...

    @pytest.mark.asyncio
    async def test_pbac_filters_providers(self):
        # When PBAC denies integration:list, provider excluded
        ...


class TestStartConnect:
    @pytest.mark.asyncio
    async def test_validates_origin(self):
        svc = IntegrationsService()
        with pytest.raises(ValueError, match="not in allowed origins"):
            await svc.start_connect("u1", "agent1", "jira", "https://evil.com")

    @pytest.mark.asyncio
    async def test_returns_connect_init_response(self):
        ...


class TestConfirmEnable:
    @pytest.mark.asyncio
    async def test_409_when_no_credential(self):
        # No users_integrations row → raise
        ...

    @pytest.mark.asyncio
    async def test_idempotent(self):
        # Second call is a no-op
        ...


class TestDisconnect:
    @pytest.mark.asyncio
    async def test_cascade_deletes(self):
        # Verify both users_integrations and user_agent_toolkits are deleted
        ...

    @pytest.mark.asyncio
    async def test_idempotent(self):
        ...


class TestPersistCredential:
    @pytest.mark.asyncio
    async def test_builds_row_from_token_set(self):
        # Verify UsersIntegrationRow fields are populated from JiraTokenSet
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/cross-repository-jiratoolkit-oauth2-3lo.spec.md` §2-3 (Module 5)
2. **Check dependencies** — verify TASK-983 and TASK-984 are in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm persistence function signatures from TASK-984
4. **Check Q-B resolution**: spec says fail-closed for integrations PBAC. Implement accordingly.
5. **Update status** in `tasks/.index.json` → `"in-progress"`
6. **Implement** the service and tests
7. **Verify** all acceptance criteria
8. **Move this file** to `tasks/completed/`
9. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
