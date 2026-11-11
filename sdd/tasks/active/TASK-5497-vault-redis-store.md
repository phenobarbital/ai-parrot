# TASK-5497: Vault credentials — Redis store and `vault_utils` dispatch

**Feature**: FEAT-878 — Redis user stores (MongoDB-free local installs)
**Spec**: `sdd/specs/redis-user-stores.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5496
**Assigned-to**: unassigned

---

## Context

Spec §2 "Vault access is centralised", §3 Module 3. `vault_utils` is the one door to
`user_credentials`. Today it checks only a registered Postgres store and otherwise talks to DocumentDB —
even when `VAULT_STORE=postgres` and nothing is registered (silent fail-open). This task adds a Redis
store, makes the dispatch honour the resolved switch (fail closed for unregistered `postgres`) and adds
`list_vault_credentials` / `vault_credential_exists`, which `CredentialsHandler` needs (TASK-5498).

---

## Scope

- Create `RedisVaultCredentialStore` (store / retrieve / delete / list_credentials / exists).
- In `vault_utils`: add `VaultCredentialStore` Protocol, `get_vault_credential_store()`, route the three
  existing CRUD functions through it, add `list_vault_credentials()` and `vault_credential_exists()` with a
  DocumentDB inline path for `documentdb`.
- Export the two new helpers from `parrot.security`.
- Tests for Redis round-trip, fail-closed postgres, and unchanged DocumentDB path.

**NOT in scope**: `CredentialsHandler` and `PgVaultCredentialStore.list_credentials/exists` (TASK-5498),
`AgentTalk` MCP restore (TASK-5499), rotation targets (TASK-5510).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/security/vault_store_redis.py` | CREATE | `RedisVaultCredentialStore` |
| `packages/ai-parrot/src/parrot/security/vault_utils.py` | MODIFY | Protocol, dispatch, two new helpers |
| `packages/ai-parrot/src/parrot/security/__init__.py` | MODIFY | export the new helpers |
| `packages/ai-parrot/tests/security/test_vault_store_redis.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.security.credentials_utils import credential_context, decrypt_credential, encrypt_credential  # verified: credentials_utils.py:53,108,83
from parrot.interfaces.documentdb import DocumentDb            # verified: interfaces/documentdb.py:65 (already imported in vault_utils.py:30)
from parrot.userstore import RedisDocumentStore, resolve_store_backend   # TASK-5495/5496
from parrot.userstore.collections import USER_CREDENTIALS                # TASK-5496
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/security/vault_utils.py
VAULT_CRED_COLLECTION: str = "user_credentials"                     # line 41
_PG_VAULT_STORE: Any = None                                         # line 43
def set_vault_credential_store(store: Any) -> None:                 # line 46 — keep; server registers Postgres here
def get_vault_keyring() -> Any:                                     # line 57
async def store_vault_credential(user_id: str, vault_name: str, secret_params: Dict[str, Any]) -> None:  # line 92
    #   line 113: `if _PG_VAULT_STORE is not None:` → return await _PG_VAULT_STORE.store(...)
    #   DocumentDB path: read_one → write (insert) or update_one $set {credential, updated_at}
async def retrieve_vault_credential(user_id: str, vault_name: str) -> Dict[str, Any]:  # line 145; KeyError message:
    #   f"Vault credential '{vault_name}' not found for user '{user_id}'"; line 164 PG check
async def delete_vault_credential(user_id: str, vault_name: str) -> None:              # line 184; line 191 PG check

# packages/ai-parrot/src/parrot/security/credentials_utils.py
def encrypt_credential(credential: dict, context: VaultContext, keyring: KeyRing, *, key_id: Optional[int] = None) -> str:  # line 83
def decrypt_credential(...)                                          # line 108 — (ciphertext, context, keyring) -> dict
def credential_context(...)                                          # line 53 — (user_id, name)

# packages/ai-parrot/src/parrot/security/__init__.py:21-29 — `from .vault_utils import (... VAULT_CRED_COLLECTION,)`
#   anchor `    VAULT_CRED_COLLECTION,` occurs 1× (line 29); __all__ entry `'VAULT_CRED_COLLECTION',` 1× (line 77)

# DocumentDB `user_credentials` document shape (vault_utils.py:126-133):
#   {user_id, name, credential, created_at, updated_at}  — ISO strings for the timestamps
```

### Does NOT Exist
- ~~`vault_utils.list_vault_credentials` / `vault_credential_exists` / `get_vault_credential_store` / `VaultCredentialStore`~~ — added by this task.
- ~~`PgVaultCredentialStore.list_credentials` / `.exists`~~ — added by TASK-5498; do not call them from tests here.
- ~~`RedisDocumentStore.find_one`~~ — use `get(key)`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/security/vault_store_redis.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/security/vault_utils.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/security/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/security/test_vault_store_redis.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/security/vault_utils.py#store_vault_credential",
    "sym:packages/ai-parrot/src/parrot/security/vault_utils.py#retrieve_vault_credential",
    "sym:packages/ai-parrot/src/parrot/security/vault_utils.py#delete_vault_credential",
    "sym:packages/ai-parrot/src/parrot/security/vault_utils.py#set_vault_credential_store",
    "sym:packages/ai-parrot/src/parrot/security/credentials_utils.py#encrypt_credential",
    "sym:packages/ai-parrot/src/parrot/security/credentials_utils.py#decrypt_credential"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Dispatch order (spec §2): registered store (`_PG_VAULT_STORE`) → `resolve_store_backend("VAULT_STORE")`:
  `redis` → module-level `RedisVaultCredentialStore` (lazy), `documentdb` → `None` (existing inline code),
  `postgres` with nothing registered → `RuntimeError("VAULT_STORE=postgres but no Postgres vault store is registered")`.
- Import `parrot.userstore` lazily inside `get_vault_credential_store()` — `parrot.security` is imported
  very early by many modules; keep its import graph unchanged.
- Never log a credential value or ciphertext; log only `vault_name` and the exception class.
- Redis documents mirror the DocumentDB shape exactly (spec "Document shape rule").

---

## Implementation Blueprint

### Steps (in order)
1. Create `vault_store_redis.py` — *why*: the Redis twin of `PgVaultCredentialStore` with the same signatures.
2. Add the Protocol + `get_vault_credential_store()` to `vault_utils.py` below `set_vault_credential_store` — *why*: one dispatch point.
3. Replace each `if _PG_VAULT_STORE is not None:` block (3×) with the dispatch — *why*: the switch must be honoured, postgres fails closed.
4. Append `list_vault_credentials` / `vault_credential_exists` — *why*: TASK-5498 removes CredentialsHandler's direct DocumentDB reads.
5. Export from `parrot.security`; write tests.

### `packages/ai-parrot/src/parrot/security/vault_store_redis.py` (CREATE)
```python
"""Vault credentials in Redis (FEAT-878). Same AAD contexts as DocumentDB/Postgres: ciphertexts copy verbatim."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from parrot.security.credentials_utils import credential_context, decrypt_credential, encrypt_credential
from parrot.userstore import RedisDocumentStore
from parrot.userstore.collections import USER_CREDENTIALS

logger = logging.getLogger("parrot.security.vault")


class RedisVaultCredentialStore:
    """``user_credentials`` in Redis; documents {user_id, name, credential, created_at, updated_at}."""

    def __init__(self, documents: RedisDocumentStore | None = None) -> None:
        self._docs = documents or RedisDocumentStore(USER_CREDENTIALS)

    async def store(self, user_id: Any, vault_name: str, secret_params: dict[str, Any]) -> None:
        """Seal with credential_context(user_id, vault_name); created_at kept on rewrite."""
        from parrot.security.vault_utils import get_vault_keyring  # lazy: vault_utils imports this module lazily

        sealed = encrypt_credential(secret_params, credential_context(user_id, vault_name), get_vault_keyring())
        now = datetime.now(timezone.utc).isoformat()
        await self._docs.upsert(
            {"user_id": user_id, "name": vault_name},
            {"credential": sealed, "updated_at": now},
            on_insert={"created_at": now},
        )

    async def retrieve(self, user_id: Any, vault_name: str) -> dict[str, Any]:
        """Open the credential. KeyError when absent (same message as the DocumentDB path)."""
        # FILL IN: get(); KeyError(f"Vault credential '{vault_name}' not found for user '{user_id}'") when None;
        #   decrypt_credential(doc["credential"], credential_context(user_id, vault_name), get_vault_keyring())
        raise NotImplementedError

    async def delete(self, user_id: Any, vault_name: str) -> None:
        await self._docs.delete({"user_id": user_id, "name": vault_name})

    async def list_credentials(self, user_id: Any) -> dict[str, dict[str, Any]]:
        """{name: decrypted dict}; undecryptable entries skipped with a warning (no value logged)."""
        # FILL IN: find({"user_id": user_id}); decrypt each with its own name's context; on failure
        #   logger.warning("Skipping undecryptable credential '%s': %s", name, type(exc).__name__)
        raise NotImplementedError

    async def exists(self, user_id: Any, vault_name: str) -> bool:
        return await self._docs.exists({"user_id": user_id, "name": vault_name})
```
**Why this shape**: signatures match `PgVaultCredentialStore` (vault_store.py:23) plus the two new
operations, so `vault_utils` can treat both alike.

### `packages/ai-parrot/src/parrot/security/vault_utils.py` (MODIFY — dispatch)
```python
# occurrences: 1 (verified: grep -c 'def set_vault_credential_store(store: Any) -> None:' packages/ai-parrot/src/parrot/security/vault_utils.py)
# AFTER the body of `def set_vault_credential_store(store: Any) -> None:` (verified: vault_utils.py:46), insert:
class VaultCredentialStore(Protocol):
    """store / retrieve / delete / list_credentials / exists — implemented by the Redis and Postgres stores."""

    async def store(self, user_id: Any, vault_name: str, secret_params: Dict[str, Any]) -> None: ...
    async def retrieve(self, user_id: Any, vault_name: str) -> Dict[str, Any]: ...
    async def delete(self, user_id: Any, vault_name: str) -> None: ...
    async def list_credentials(self, user_id: Any) -> Dict[str, Dict[str, Any]]: ...
    async def exists(self, user_id: Any, vault_name: str) -> bool: ...


_REDIS_VAULT_STORE: Any = None


def get_vault_credential_store() -> "VaultCredentialStore | None":
    """Registered store → it; VAULT_STORE=redis → module-level Redis store; documentdb → None;
    postgres with nothing registered → RuntimeError (fail closed)."""
    # FILL IN: lazy `from parrot.userstore import resolve_store_backend`; build _REDIS_VAULT_STORE once
    #   with a lazy `from parrot.security.vault_store_redis import RedisVaultCredentialStore` — bounded by spec §2 / AC4.
    raise NotImplementedError
# Also add `Protocol` to the `from typing import ...` line (vault_utils.py:23: `from typing import Any, Dict`).
```

### `packages/ai-parrot/src/parrot/security/vault_utils.py` (MODIFY — the three CRUD functions)
```python
# occurrences: 3 (verified: grep -c 'if _PG_VAULT_STORE is not None:' packages/ai-parrot/src/parrot/security/vault_utils.py)
# FILL IN: disambiguate by function — replace, inside store_vault_credential (line 113), retrieve_vault_credential
#   (line 164) and delete_vault_credential (line 191), the two lines
#       if _PG_VAULT_STORE is not None:
#           return await _PG_VAULT_STORE.<op>(user_id, vault_name[, secret_params])
#   with
#       store = get_vault_credential_store()
#       if store is not None:
#           return await store.<op>(user_id, vault_name[, secret_params])
#   Leave the DocumentDB code below each check untouched.
```

### `packages/ai-parrot/src/parrot/security/vault_utils.py` (MODIFY — new helpers)
```python
# occurrences: 1 (verified: grep -c 'def oauth2_vault_name(provider_id: str, channel: str, user_id: str) -> str:' ...vault_utils.py)
# BEFORE the "# OAuth2 helpers" banner that precedes `def oauth2_vault_name(` (verified: vault_utils.py:205), insert:
async def list_vault_credentials(user_id: str) -> Dict[str, Dict[str, Any]]:
    """All of a user's credentials, decrypted; undecryptable ones skipped with a warning."""
    store = get_vault_credential_store()
    if store is not None:
        return await store.list_credentials(user_id)
    # FILL IN: DocumentDB path — read(VAULT_CRED_COLLECTION, {"user_id": user_id}); decrypt each doc with
    #   credential_context(user_id, doc["name"]); skip failures with a warning naming only the credential.
    raise NotImplementedError


async def vault_credential_exists(user_id: str, vault_name: str) -> bool:
    """True when ``(user_id, vault_name)`` is stored (no decryption)."""
    store = get_vault_credential_store()
    if store is not None:
        return await store.exists(user_id, vault_name)
    async with DocumentDb() as db:
        return await db.read_one(VAULT_CRED_COLLECTION, {"user_id": user_id, "name": vault_name}) is not None
```

### `packages/ai-parrot/src/parrot/security/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    VAULT_CRED_COLLECTION,' packages/ai-parrot/src/parrot/security/__init__.py)
# AFTER `    VAULT_CRED_COLLECTION,` (verified: security/__init__.py:29) add:
    list_vault_credentials,
    vault_credential_exists,
# occurrences: 1 (verified: grep -c "'VAULT_CRED_COLLECTION'," packages/ai-parrot/src/parrot/security/__init__.py)
# AFTER `    'VAULT_CRED_COLLECTION',` (verified: security/__init__.py:77) add:
    'list_vault_credentials',
    'vault_credential_exists',
```

### FILL IN checklist
- [ ] `RedisVaultCredentialStore.retrieve` / `list_credentials`
- [ ] `get_vault_credential_store` — dispatch + fail closed; AC4
- [ ] three CRUD dispatch replacements
- [ ] `list_vault_credentials` DocumentDB path

---

## Acceptance Criteria

- [ ] With `VAULT_STORE` unset and no global, credentials round-trip through Redis (store → retrieve → list → exists → delete); `created_at` survives a rewrite
- [ ] `VAULT_STORE=postgres` with nothing registered raises `RuntimeError` and never touches DocumentDB (AC4)
- [ ] `VAULT_STORE=documentdb` uses the unchanged inline code (mocked `DocumentDb`)
- [ ] A registered store still wins (existing `test_vault_store.py` passes)
- [ ] `ruff check` clean

---

## Validation Commands
- `pytest packages/ai-parrot/tests/security/test_vault_store_redis.py -q`
- `pytest packages/ai-parrot-server/tests/studio/storage/test_vault_store.py -q`
- `pytest packages/ai-parrot-server/tests/studio/storage/test_overrides_store.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/security/test_vault_store_redis.py
import pytest

from parrot.security import vault_utils
from parrot.userstore.testing import redis_test_settings


@pytest.fixture
def keyring(monkeypatch):
    """Test keyring: VAULT_MASTER_KEY_v1 + VAULT_ACTIVE_KEY_ID; reset the cached ring around the test."""
    # FILL IN: copy the keyring setup used by packages/ai-parrot-server/tests/studio/storage/test_vault_store.py
    vault_utils.reset_vault_keyring()
    yield
    vault_utils.reset_vault_keyring()


@pytest.fixture
async def redis_vault(monkeypatch, keyring):
    monkeypatch.delenv("VAULT_STORE", raising=False)
    monkeypatch.delenv("PARROT_USER_STORE", raising=False)
    monkeypatch.setattr(vault_utils, "_PG_VAULT_STORE", None)
    monkeypatch.setattr(vault_utils, "_REDIS_VAULT_STORE", None)
    async with redis_test_settings(monkeypatch):
        yield


async def test_vault_redis_roundtrip(redis_vault):
    await vault_utils.store_vault_credential("35", "db1", {"driver": "pg", "params": {"pw": "x"}})
    assert (await vault_utils.retrieve_vault_credential("35", "db1"))["driver"] == "pg"
    assert "db1" in await vault_utils.list_vault_credentials("35")
    assert await vault_utils.vault_credential_exists("35", "db1")
    await vault_utils.delete_vault_credential("35", "db1")
    with pytest.raises(KeyError):
        await vault_utils.retrieve_vault_credential("35", "db1")


async def test_vault_postgres_unregistered_fails_closed(monkeypatch): ...  # VAULT_STORE=postgres → RuntimeError; DocumentDb forbidden
async def test_vault_documentdb_path_unchanged(monkeypatch): ...          # VAULT_STORE=documentdb; fake DocumentDb records calls
async def test_list_skips_undecryptable(redis_vault): ...                 # write a garbage ciphertext doc directly → skipped
```

---

## Agent Instructions

1. **Work in the feature worktree** — `parrot sdd worktree ensure --slug redis-user-stores --feature-id FEAT-878`
2. **Read the spec** (§2 Vault access is centralised, §3 M3)
3. **Check dependencies** — TASK-5496 must be `done`
4. **Verify the Codebase Contract** (re-run each `grep -c`)
5. **Update status** → `"in-progress"`, commit only the index file
6. **Implement** from the blueprint, complete every `# FILL IN:`
7. **Verify** — Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`
8. **Commit the code** — only the files listed above
9. **Close the task** — `parrot sdd task close TASK-5497 redis-user-stores verified`
10. **Fill in the Completion Note**, commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
