---
type: Wiki Overview
title: 'TASK-984: Jira OAuth2 Provider and DocumentDB Persistence'
id: doc:sdd-tasks-completed-task-984-jira-provider-and-persistence-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements the first concrete OAuth2 provider (`JiraOAuth2Provider`) and
  the
relates_to:
- concept: mod:parrot.auth.credentials
  rel: mentions
- concept: mod:parrot.auth.jira_oauth
  rel: mentions
- concept: mod:parrot.integrations
  rel: mentions
- concept: mod:parrot.interfaces.documentdb
  rel: mentions
- concept: mod:parrot_tools.jiratoolkit
  rel: mentions
---

# TASK-984: Jira OAuth2 Provider and DocumentDB Persistence

**Feature**: FEAT-144 — Cross-Repository JiraToolkit OAuth2 3LO (Web AgentChat)
**Spec**: `sdd/specs/cross-repository-jiratoolkit-oauth2-3lo.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-983
**Assigned-to**: unassigned

---

## Context

Implements the first concrete OAuth2 provider (`JiraOAuth2Provider`) and the
DocumentDB persistence layer for the two new collections (`users_integrations`,
`user_agent_toolkits`). The provider thin-wraps the existing `JiraOAuthManager`
and `JiraToolkit`. The persistence layer follows the established
`MCPPersistenceService` pattern.

Implements spec Modules 3 and 4.

---

## Scope

- Create `jira_provider.py` with `JiraOAuth2Provider` that:
  - Returns `JiraOAuthManager` via its `manager` property.
  - Returns a `JiraToolkit(auth_type="oauth2_3lo", credential_resolver=...)` via
    `toolkit_factory()`.
- Create `persistence.py` with async repository functions for:
  - `upsert_users_integration(row: UsersIntegrationRow)` — upsert by `(user_id, provider)`.
  - `get_users_integration(user_id, provider)` — fetch single row.
  - `delete_users_integration(user_id, provider)` — hard delete.
  - `upsert_user_agent_toolkit(row: UserAgentToolkitRow)` — upsert by `(user_id, agent_id, toolkit_id)`.
  - `list_user_agent_toolkits(user_id, agent_id)` — fetch all for a user+agent.
  - `delete_user_agent_toolkits_by_provider(user_id, provider)` — cascade delete all enablements for a user+provider.
- Write unit tests for both modules.

**NOT in scope**: IntegrationsService (TASK-985), handler (TASK-986), callback
changes (TASK-987).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/integrations/oauth2/jira_provider.py` | CREATE | `JiraOAuth2Provider` implementation |
| `packages/ai-parrot/src/parrot/integrations/oauth2/persistence.py` | CREATE | DocumentDB repository for two collections |
| `packages/ai-parrot/src/parrot/integrations/oauth2/__init__.py` | MODIFY | Add re-exports for new modules |
| `tests/unit/integrations/oauth2/test_jira_provider.py` | CREATE | Provider tests |
| `tests/unit/integrations/oauth2/test_persistence.py` | CREATE | Persistence tests (mocked DocumentDB) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# From TASK-983 (must be completed first):
from parrot.integrations.oauth2.models import (
    UsersIntegrationRow, UserAgentToolkitRow,
)
from parrot.integrations.oauth2.registry import OAuth2Provider

# Existing — verified:
from parrot.auth.jira_oauth import JiraOAuthManager  # parrot/auth/jira_oauth.py:86
from parrot.auth.credentials import OAuthCredentialResolver  # parrot/auth/credentials.py:49
from parrot_tools.jiratoolkit import JiraToolkit  # jiratoolkit.py:630

# DocumentDB access pattern — verified from mcp_persistence.py:
from parrot.interfaces.documentdb import DocumentDb  # mcp_persistence.py:26
# Usage:
#   async with DocumentDb() as db:
#       await db.update_one(COLLECTION, query, update_data, upsert=True)
#       docs = await db.read(COLLECTION, query)

from navconfig.logging import logging  # mcp_persistence.py:24
```

### Existing Signatures to Use
```python
# parrot/auth/jira_oauth.py:86
class JiraOAuthManager:
    async def create_authorization_url(  # line 258
        self, channel: str, user_id: str,
        extra_state: Optional[Dict[str, Any]] = None,
    ) -> Tuple[str, str]: ...  # returns (url, nonce)
    async def handle_callback(self, code: str, state: str) -> Tuple[JiraTokenSet, Dict[str, Any]]: ...  # line 304
    async def get_valid_token(self, channel: str, user_id: str) -> Optional[JiraTokenSet]: ...  # line 384

# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py:630
class JiraToolkit(AbstractToolkit):
    def __init__(self, ..., credential_resolver: Any = None, ...): ...  # line 688-700

# parrot/handlers/mcp_persistence.py — DocumentDB pattern:
# line 84-85: async with DocumentDb() as db: await db.update_one(COLLECTION, query, update, upsert=True)
# line 117-118: async with DocumentDb() as db: docs = await db.read(COLLECTION, query)
```

### Does NOT Exist
- ~~`parrot.integrations.oauth2.jira_provider`~~ — does not exist yet; this task creates it.
- ~~`parrot.integrations.oauth2.persistence`~~ — does not exist yet; this task creates it.
- ~~`DocumentDb.delete_one`~~ — verify this method exists before using it; `mcp_persistence.py` uses soft-delete (`update_one` with `active=False`). If `delete_one` doesn't exist, use `update_one` to hard-delete or find the correct deletion method.
- ~~`users_integrations` collection~~ — does not exist; created implicitly on first write.
- ~~`user_agent_toolkits` collection~~ — does not exist; created implicitly on first write.
- ~~`JiraToolkit(auth_type="oauth2_3lo")`~~ — verify the exact kwarg name. The spec says `auth_type`; grep `jiratoolkit.py` for the `__init__` parameter name.

---

## Implementation Notes

### Pattern to Follow — JiraOAuth2Provider
```python
class JiraOAuth2Provider(OAuth2Provider):
    provider_id = "jira"
    display_name = "Jira"
    icon = "mdi:jira"
    default_scopes = [
        "read:jira-user", "read:jira-work", "write:jira-work", "offline_access",
    ]
    pbac_action_namespace = "integration"

    @property
    def manager(self) -> JiraOAuthManager:
        # Return a singleton or lazily-initialised instance
        ...

    def toolkit_factory(self, credential_resolver) -> JiraToolkit:
        return JiraToolkit(
            auth_type="oauth2_3lo",
            credential_resolver=credential_resolver,
        )
```

### Pattern to Follow — Persistence (mirror MCPPersistenceService)
```python
USERS_INTEGRATIONS_COLLECTION = "users_integrations"
USER_AGENT_TOOLKITS_COLLECTION = "user_agent_toolkits"

async def upsert_users_integration(row: UsersIntegrationRow) -> None:
    query = {"user_id": row.user_id, "provider": row.provider}
    update_data = {
        "$set": row.model_dump(exclude={"user_id", "provider"}),
        "$setOnInsert": {"user_id": row.user_id, "provider": row.provider},
    }
    async with DocumentDb() as db:
        await db.update_one(USERS_INTEGRATIONS_COLLECTION, query, update_data, upsert=True)
```

### Key Constraints
- `JiraOAuthManager` is instantiated at app startup; the provider should receive
  or lazily resolve it (check how the existing `jira_oauth_callback` accesses it —
  likely via `request.app["jira_oauth_manager"]`).
- `toolkit_factory` must pass `auth_type="oauth2_3lo"` — `JiraToolkit.__init__`
  raises if `auth_type == "oauth2_3lo"` and no resolver is given (jiratoolkit.py:766-770).
- Cascade rule: `delete_user_agent_toolkits_by_provider(user_id, provider)` removes
  ALL `user_agent_toolkits` rows matching `(user_id, provider)` regardless of `agent_id`.
- Collections are created implicitly on first write (same as `user_mcp_configs`).

---

## Acceptance Criteria

- [ ] `JiraOAuth2Provider.toolkit_factory(resolver)` returns a `JiraToolkit` with
      `auth_type="oauth2_3lo"` and the supplied resolver.
- [ ] `JiraOAuth2Provider.provider_id == "jira"` and `display_name == "Jira"`.
- [ ] `upsert_users_integration` is idempotent — two upserts with same `(user_id, provider)` result in one row.
- [ ] `delete_users_integration` removes the row.
- [ ] `delete_user_agent_toolkits_by_provider(user_id, "jira")` removes all enablement rows for that user+provider.
- [ ] All tests pass: `pytest tests/unit/integrations/oauth2/test_jira_provider.py tests/unit/integrations/oauth2/test_persistence.py -v`
- [ ] No lint errors: `ruff check packages/ai-parrot/src/parrot/integrations/oauth2/`

---

## Test Specification

```python
# tests/unit/integrations/oauth2/test_jira_provider.py
import pytest
from unittest.mock import MagicMock
from parrot.integrations.oauth2.jira_provider import JiraOAuth2Provider


class TestJiraOAuth2Provider:
    def test_provider_id(self):
        p = JiraOAuth2Provider()
        assert p.provider_id == "jira"

    def test_display_name(self):
        p = JiraOAuth2Provider()
        assert p.display_name == "Jira"

    def test_toolkit_factory_returns_jira_toolkit(self):
        p = JiraOAuth2Provider()
        resolver = MagicMock()
        toolkit = p.toolkit_factory(resolver)
        from parrot_tools.jiratoolkit import JiraToolkit
        assert isinstance(toolkit, JiraToolkit)


# tests/unit/integrations/oauth2/test_persistence.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from parrot.integrations.oauth2.persistence import (
    upsert_users_integration,
    get_users_integration,
    delete_users_integration,
    upsert_user_agent_toolkit,
    list_user_agent_toolkits,
    delete_user_agent_toolkits_by_provider,
)
from parrot.integrations.oauth2.models import (
    UsersIntegrationRow, UserAgentToolkitRow,
)
from datetime import datetime


class TestUsersIntegrationPersistence:
    @pytest.fixture
    def sample_row(self):
        return UsersIntegrationRow(
            user_id="u1", provider="jira", account_id="a1",
            display_name="Test User", scopes=["read:jira-work"],
            connected_at=datetime.now(),
        )

    @pytest.mark.asyncio
    async def test_upsert_calls_update_one(self, sample_row):
        with patch("parrot.integrations.oauth2.persistence.DocumentDb") as mock_db_cls:
            mock_db = AsyncMock()
            mock_db_cls.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            await upsert_users_integration(sample_row)
            mock_db.update_one.assert_called_once()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/cross-repository-jiratoolkit-oauth2-3lo.spec.md` §2-3 (Modules 3-4)
2. **Check dependencies** — verify TASK-983 is in `tasks/completed/`
3. **Verify the Codebase Contract** — especially:
   - Grep `jiratoolkit.py` for the `auth_type` parameter name in `__init__`
   - Confirm `DocumentDb` has a `delete_one` or `delete_many` method
   - Check how `JiraOAuthManager` is instantiated (singleton? per-request?)
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** provider and persistence
6. **Verify** all acceptance criteria
7. **Move this file** to `tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker agent
**Date**: 2026-05-04
**Notes**: Implemented jira_provider.py (JiraOAuth2Provider wrapping JiraOAuthManager, toolkit_factory returning JiraToolkit with auth_type=oauth2_3lo) and persistence.py (6 async repository functions for users_integrations and user_agent_toolkits collections using DocumentDb context manager pattern). All 18 unit tests pass. JiraOAuth2Provider takes manager as constructor arg for testability.

**Deviations from spec**: JiraOAuth2Provider takes manager as __init__ arg instead of singleton resolution, for better testability.
