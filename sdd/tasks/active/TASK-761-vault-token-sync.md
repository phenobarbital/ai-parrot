# TASK-761: Vault Token Sync

**Feature**: FEAT-108 — Jira OAuth2 3LO Authentication from Telegram WebApp
**Spec**: `sdd/specs/FEAT-108-jiratoolkit-auth-telegram.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-756
**Assigned-to**: unassigned

---

## Context

This task creates a service to store and retrieve OAuth tokens as flat keys in
the user's navigator-auth Vault. The Vault provides encrypted persistence
(AES-GCM via navigator-session) backed by Redis. This supplements the existing
Redis-only storage in `JiraOAuthManager` with an encrypted, user-scoped store.

Implements Spec Module 6.

---

## Scope

- Create `parrot/services/vault_token_sync.py`.
- Implement `VaultTokenSync` class with:
  - `__init__(db_pool, redis)` — accepts DB pool and Redis client
  - `async store_tokens(nav_user_id, provider, tokens: Dict[str, str])` —
    stores each key-value pair as `{provider}:{key}` in the user's vault
    (e.g., `jira:access_token`, `jira:refresh_token`, etc.)
  - `async read_tokens(nav_user_id, provider) -> Optional[Dict[str, str]]` —
    reads all `{provider}:*` keys from the vault
  - `async delete_tokens(nav_user_id, provider)` — removes all provider keys
- Follow the vault access pattern from the user-provided `_get_vault` code.
- Use flat key scheme: `jira:access_token`, `jira:refresh_token`,
  `jira:cloud_id`, `jira:site_url`, `jira:account_id`.
- Write unit tests with mocked vault/session.

**NOT in scope**: HTTP endpoints for vault access, identity mapping (TASK-760),
or integration with the wrapper (TASK-763).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/services/__init__.py` | CREATE (if missing) | Package init |
| `packages/ai-parrot/src/parrot/services/vault_token_sync.py` | CREATE | VaultTokenSync service |
| `packages/ai-parrot/tests/unit/test_vault_token_sync.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# navigator-session vault access (external, verified via credentials.py:40-44):
from navigator_session.vault.config import get_active_key_id, load_master_keys
from navigator_session.vault.crypto import encrypt_for_db, decrypt_for_db

# Credentials handler pattern (reference):
from parrot.handlers.credentials import CredentialsHandler  # credentials.py:71
# CredentialsHandler.SESSION_PREFIX = "_credentials:"
# CredentialsHandler._session_key(name) returns f"_credentials:{name}"
```

### Existing Signatures to Use
```python
# User-provided vault access pattern (from navigator-auth VaultView):
# load_vault_for_session(session, user_id=user_id, db_pool=db_pool, redis=redis)
# Returns a vault dict-like object that supports get/set with string keys
# VAULT_SESSION_KEY is the session dict key where vault is cached

# packages/ai-parrot/src/parrot/handlers/credentials.py
class CredentialsHandler(BaseView):                                 # line 71
    SESSION_PREFIX: str = "_credentials:"                           # used for key prefix
    async def _set_session_credential(self, name, credential_dict): ...  # line 122
    async def _get_all_session_credentials(self) -> dict: ...       # line 143

# packages/ai-parrot/src/parrot/handlers/credentials_utils.py
def encrypt_credential(credential: dict, key_id: int, master_key: bytes) -> str: ...  # line 19
def decrypt_credential(encrypted: str, master_keys: dict[int, bytes]) -> dict: ...    # line 52
```

### Does NOT Exist
- ~~`parrot.services.vault_token_sync`~~ — does not exist yet (this task creates it)
- ~~`VaultTokenSync`~~ — does not exist yet (this task creates it)
- ~~`load_vault_for_session` in parrot~~ — function is in navigator-session, not parrot
- ~~`VAULT_SESSION_KEY` in parrot~~ — constant is in navigator-auth, not parrot

---

## Implementation Notes

### Pattern to Follow
The vault access pattern depends on whether we're in an HTTP request context
(where `session` is available) or in the Telegram wrapper context (where
we need to access the vault directly). Since the Telegram wrapper runs via
aiogram polling, we need a direct vault access approach:

```python
class VaultTokenSync:
    def __init__(self, db_pool, redis) -> None:
        self._pool = db_pool
        self._redis = redis
        self.logger = logging.getLogger(__name__)

    async def store_tokens(
        self,
        nav_user_id: str,
        provider: str,
        tokens: Dict[str, str],
    ) -> None:
        """Store token key-value pairs in the user's vault."""
        # Option A: Use load_vault_for_session directly
        # Option B: Use the credentials table pattern from CredentialsHandler
        # Option C: Store directly in Redis with vault encryption
        #
        # Recommended: Use load_vault_for_session pattern
        # The exact approach depends on what load_vault_for_session returns
        # and whether it can be used without an HTTP session
        for key, value in tokens.items():
            vault_key = f"{provider}:{key}"
            # Store encrypted in vault
            ...
```

### Key Constraints
- Flat key scheme: each token field is a separate vault key (e.g., `jira:access_token`)
- All vault operations must be async
- Encryption/decryption uses `navigator_session.vault.crypto` (AES-GCM)
- Must handle the case where vault is not available (log warning, don't crash)
- The `db_pool` is the `authdb` pool from `app.get("authdb")`
- The `redis` client is from `app.get("redis")`

### References in Codebase
- `packages/ai-parrot/src/parrot/handlers/credentials.py:40-66` — vault key loading
- `packages/ai-parrot/src/parrot/handlers/credentials_utils.py:19-81` — encrypt/decrypt
- User-provided `_get_vault` pattern (see spec Section 6)

---

## Acceptance Criteria

- [ ] `VaultTokenSync` with `store_tokens`, `read_tokens`, `delete_tokens` methods
- [ ] Flat key scheme: `{provider}:{key}` (e.g., `jira:access_token`)
- [ ] Tokens encrypted when stored
- [ ] Failures logged but don't raise (graceful degradation)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/test_vault_token_sync.py -v`
- [ ] Importable: `from parrot.services.vault_token_sync import VaultTokenSync`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/test_vault_token_sync.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.services.vault_token_sync import VaultTokenSync


@pytest.fixture
def mock_db_pool():
    return AsyncMock()


@pytest.fixture
def mock_redis():
    return AsyncMock()


@pytest.fixture
def sync(mock_db_pool, mock_redis):
    return VaultTokenSync(mock_db_pool, mock_redis)


class TestVaultTokenSync:
    async def test_store_tokens(self, sync):
        tokens = {
            "access_token": "at-123",
            "refresh_token": "rt-456",
            "cloud_id": "cloud-abc",
            "site_url": "https://site.atlassian.net",
            "account_id": "acc-789",
        }
        # Should not raise
        await sync.store_tokens("user-123", "jira", tokens)

    async def test_read_tokens(self, sync):
        result = await sync.read_tokens("user-123", "jira")
        # Implementation-dependent: could be None or dict

    async def test_read_tokens_missing_user(self, sync):
        result = await sync.read_tokens("nonexistent-user", "jira")
        assert result is None

    async def test_delete_tokens(self, sync):
        await sync.delete_tokens("user-123", "jira")
        # Should not raise

    async def test_store_tokens_failure_handled(self, sync, mock_db_pool):
        mock_db_pool.acquire.side_effect = Exception("DB unavailable")
        # Should log warning, not raise
        await sync.store_tokens("user-123", "jira", {"access_token": "at"})
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** for full context — especially the user-provided vault pattern
2. **Check dependencies** — verify TASK-756 is completed
3. **Investigate navigator-session vault API** — check if `load_vault_for_session`
   can be used without an HTTP session context
4. **Check if `parrot/services/` package exists** — create `__init__.py` if needed
5. **Implement** the vault sync service
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any
