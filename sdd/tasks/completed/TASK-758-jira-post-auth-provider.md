# TASK-758: JiraPostAuthProvider Implementation

**Feature**: FEAT-108 — Jira OAuth2 3LO Authentication from Telegram WebApp
**Spec**: `sdd/specs/FEAT-108-jiratoolkit-auth-telegram.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-757, TASK-760, TASK-761
**Assigned-to**: unassigned

---

## Context

This task implements the Jira-specific `PostAuthProvider` that wraps
`JiraOAuthManager` to participate in the combined auth chain. It builds
Jira authorization URLs, processes Jira OAuth callback results, stores
tokens in both Redis (existing) and the user's Vault (new), and creates
`UserIdentity` records for the Telegram and Jira identities.

Implements Spec Module 3.

---

## Scope

- Create `parrot/integrations/telegram/post_auth_jira.py`.
- Implement `JiraPostAuthProvider` satisfying the `PostAuthProvider` protocol:
  - `provider_name = "jira"`
  - `build_auth_url()`: uses `JiraOAuthManager.create_authorization_url()` with
    `channel="telegram"`, `user_id=str(session.telegram_id)`, and `extra_state`
    containing the BasicAuth data to stash in the Redis nonce.
  - `handle_result()`: calls `JiraOAuthManager.handle_callback()`, then:
    - Stores tokens in the user's Vault via `VaultTokenSync` (TASK-761).
    - Creates/updates `UserIdentity` records via `IdentityMappingService` (TASK-760).
    - Returns True on success, False on failure.
- Write unit tests with mocked `JiraOAuthManager`, `VaultTokenSync`, and
  `IdentityMappingService`.

**NOT in scope**: The combined callback endpoint (TASK-759), login page JS (TASK-762),
or wrapper orchestration (TASK-763).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/integrations/telegram/post_auth_jira.py` | CREATE | Jira PostAuthProvider |
| `packages/ai-parrot/tests/unit/test_post_auth_jira.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.jira_oauth import JiraOAuthManager, JiraTokenSet  # jira_oauth.py:85, 58
from parrot.auth.jira_oauth import _TELEGRAM_CHANNEL  # NOT HERE — it's in jira_commands.py:33
from parrot.integrations.telegram.jira_commands import _TELEGRAM_CHANNEL  # jira_commands.py:33 (= "telegram")
from parrot.integrations.telegram.auth import TelegramUserSession  # auth.py:36
from parrot.integrations.telegram.models import TelegramAgentConfig  # models.py:13
from parrot.integrations.telegram.post_auth import PostAuthProvider  # CREATED BY TASK-757
from parrot.services.identity_mapping import IdentityMappingService  # CREATED BY TASK-760
from parrot.services.vault_token_sync import VaultTokenSync  # CREATED BY TASK-761
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/jira_oauth.py
class JiraOAuthManager:                                             # line 85
    async def create_authorization_url(
        self, channel: str, user_id: str,
        extra_state: Optional[Dict[str, Any]] = None
    ) -> Tuple[str, str]: ...                                       # line 157
    async def handle_callback(
        self, code: str, state: str
    ) -> Tuple[JiraTokenSet, Dict[str, Any]]: ...                   # line 203

class JiraTokenSet(BaseModel):  # frozen=True                      # line 58
    access_token: str; refresh_token: str; expires_at: float
    cloud_id: str; site_url: str; account_id: str
    display_name: str; email: Optional[str]

# packages/ai-parrot/src/parrot/integrations/telegram/auth.py
class TelegramUserSession:  # @dataclass                            # line 36
    telegram_id: int                                                # line 39
    telegram_username: Optional[str]                                # line 40
    nav_user_id: Optional[str]                                      # line 44
    nav_email: Optional[str]                                        # line 47
```

### Does NOT Exist
- ~~`JiraOAuthManager.store_in_vault()`~~ — no vault method exists on the manager
- ~~`JiraOAuthManager.create_identity()`~~ — no identity method exists
- ~~`parrot.integrations.telegram.post_auth_jira`~~ — module does not exist yet (this task creates it)
- ~~`_TELEGRAM_CHANNEL` in jira_oauth.py~~ — it's in `jira_commands.py:33`, NOT in jira_oauth.py

---

## Implementation Notes

### Pattern to Follow
```python
class JiraPostAuthProvider:
    provider_name = "jira"

    def __init__(
        self,
        oauth_manager: JiraOAuthManager,
        identity_service: IdentityMappingService,
        vault_sync: VaultTokenSync,
    ) -> None:
        self._oauth = oauth_manager
        self._identity = identity_service
        self._vault = vault_sync
        self.logger = logging.getLogger(__name__)

    async def build_auth_url(self, session, config, callback_base_url) -> str:
        url, _nonce = await self._oauth.create_authorization_url(
            channel="telegram",
            user_id=str(session.telegram_id),
            extra_state={...},  # Include BasicAuth data + chat context
        )
        return url

    async def handle_result(self, data, session, primary_auth_data) -> bool:
        code = data.get("code")
        state = data.get("state")
        token_set, state_payload = await self._oauth.handle_callback(code, state)
        # Store in Vault
        await self._vault.store_tokens(...)
        # Create identity mappings
        await self._identity.upsert_identity(...)
        return True
```

### Key Constraints
- `handle_callback` on `JiraOAuthManager` already stores the token in Redis — don't duplicate
- Vault storage is additive (store after Redis succeeds)
- Identity mapping creates TWO records: telegram identity + jira identity
- Must handle exceptions gracefully — a vault or identity failure should log but not block the auth
- The `extra_state` in `create_authorization_url` is stored in Redis with 10-min TTL (nonce mechanism)

### References in Codebase
- `packages/ai-parrot/src/parrot/auth/jira_oauth.py:157-199` — `create_authorization_url()` implementation
- `packages/ai-parrot/src/parrot/auth/jira_oauth.py:203-279` — `handle_callback()` implementation
- `packages/ai-parrot/src/parrot/integrations/telegram/jira_commands.py:44-68` — existing `connect_jira_handler` as reference

---

## Acceptance Criteria

- [ ] `JiraPostAuthProvider` implements `PostAuthProvider` protocol
- [ ] `build_auth_url()` returns valid Atlassian authorization URL
- [ ] `handle_result()` exchanges code, stores tokens in Vault, creates identities
- [ ] Vault storage failures are logged but don't block the auth flow
- [ ] Identity mapping creates records for both "telegram" and "jira" providers
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/test_post_auth_jira.py -v`
- [ ] Importable: `from parrot.integrations.telegram.post_auth_jira import JiraPostAuthProvider`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/test_post_auth_jira.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.integrations.telegram.post_auth_jira import JiraPostAuthProvider


@pytest.fixture
def mock_oauth_manager():
    m = AsyncMock()
    m.create_authorization_url.return_value = ("https://auth.atlassian.com/authorize?...", "nonce123")
    m.handle_callback.return_value = (MagicMock(
        access_token="at", refresh_token="rt", cloud_id="cloud",
        site_url="https://site.atlassian.net", account_id="acc123",
        display_name="Jira User", email="jira@example.com",
    ), {"channel": "telegram", "user_id": "123"})
    return m


@pytest.fixture
def mock_vault_sync():
    return AsyncMock()


@pytest.fixture
def mock_identity_service():
    return AsyncMock()


@pytest.fixture
def provider(mock_oauth_manager, mock_identity_service, mock_vault_sync):
    return JiraPostAuthProvider(mock_oauth_manager, mock_identity_service, mock_vault_sync)


class TestJiraPostAuthProvider:
    async def test_build_auth_url(self, provider):
        session = MagicMock(telegram_id=123456)
        config = MagicMock()
        url = await provider.build_auth_url(session, config, "https://example.com")
        assert "atlassian" in url

    async def test_handle_result_success(self, provider, mock_vault_sync, mock_identity_service):
        session = MagicMock(telegram_id=123456, nav_user_id="nav-user-1")
        data = {"code": "auth-code", "state": "nonce123"}
        result = await provider.handle_result(data, session, {"user_id": "nav-user-1"})
        assert result is True
        mock_vault_sync.store_tokens.assert_called_once()
        assert mock_identity_service.upsert_identity.call_count == 2  # telegram + jira

    async def test_handle_result_failure(self, provider, mock_oauth_manager):
        mock_oauth_manager.handle_callback.side_effect = ValueError("Invalid state")
        session = MagicMock(telegram_id=123456)
        data = {"code": "bad-code", "state": "bad-state"}
        result = await provider.handle_result(data, session, {})
        assert result is False
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/FEAT-108-jiratoolkit-auth-telegram.spec.md`
2. **Check dependencies** — verify TASK-757, TASK-760, TASK-761 are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm `JiraOAuthManager` signatures still match
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
5. **Implement** the Jira provider
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

**Completed by**: sdd-worker (Claude Opus 4.7)
**Date**: 2026-04-19
**Notes**:

- Created
  `packages/ai-parrot/src/parrot/integrations/telegram/post_auth_jira.py`
  with `JiraPostAuthProvider` implementing `PostAuthProvider`.
- `build_auth_url` uses `JiraOAuthManager.create_authorization_url` with
  `channel="telegram"` (via `_TELEGRAM_CHANNEL`), `user_id=str(telegram_id)`,
  and an `extra_state` dict containing the primary-auth context
  (`nav_user_id`, `nav_display_name`, `nav_email`, `telegram_id`,
  `telegram_username`, `callback_base_url`, `flow="combined"`).
- `handle_result` exchanges the code via `handle_callback`, resolves
  `nav_user_id` with a three-level fallback (primary_auth_data →
  extra_state → session), then calls `VaultTokenSync.store_tokens` and
  two `IdentityMappingService.upsert_identity` calls (telegram + jira).
- Vault and identity failures are caught and logged — `handle_result`
  still returns True because the primary OAuth exchange (Redis write)
  succeeded.
- Missing code/state in the payload, or a raised OAuth exchange
  exception, returns False (no side effects).
- Created `packages/ai-parrot/tests/unit/test_post_auth_jira.py` with
  14 tests covering build URL, success path (flat-key Vault, two
  identity rows, user_id fallback), and five failure modes. All pass.

**Deviations from spec**: none
