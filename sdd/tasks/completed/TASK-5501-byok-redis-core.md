# TASK-5501: BYOK `user_llm_keys` in Redis — core store and resolver

**Feature**: FEAT-878 — Redis user stores (MongoDB-free local installs)
**Spec**: `sdd/specs/redis-user-stores.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5496
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 (core half). Studio "bring your own key" LLM keys live in DocumentDB `user_llm_keys`
(or Postgres with `BYOK_STORE=postgres`). This task adds the Redis store in core, makes
`byok_store_setting()` use the FEAT-878 resolver (so it can return `redis`, default `redis`), adds one
accessor `get_user_llm_key_store()` and generalises `_UserLLMKeyResolver` to any non-DocumentDB store.
The Studio handler side is TASK-5502.

---

## Scope

- Create `parrot/auth/broker/byok_redis.py`: `mask_api_key()` and `RedisUserLLMKeyStore` (get / put / delete / list_masked).
- `byok_store_setting()` → `resolve_store_backend("BYOK_STORE")`; add `get_user_llm_key_store()`.
- `_UserLLMKeyResolver.resolve`: `postgres`/`redis` → the accessor's store (fail closed → `None`), `documentdb` → today's code.
- Pin `BYOK_STORE=documentdb` in `test_user_llm_key_resolver.py`; new Redis tests.

**NOT in scope**: `StudioKeysHandler`, `resolve_user_api_key`, `user_byok_providers` (TASK-5502); rotation targets (TASK-5510).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/broker/byok_redis.py` | CREATE | `mask_api_key`, `RedisUserLLMKeyStore` |
| `packages/ai-parrot/src/parrot/auth/broker/__init__.py` | MODIFY | resolver-backed `byok_store_setting`, `get_user_llm_key_store` |
| `packages/ai-parrot/src/parrot/auth/broker/byok.py` | MODIFY | resolver dispatch to any registered/Redis store |
| `packages/ai-parrot/tests/auth/test_byok_store_redis.py` | CREATE | Redis store + resolver tests |
| `packages/ai-parrot/tests/unit/test_user_llm_key_resolver.py` | MODIFY | autouse pin `BYOK_STORE=documentdb` |
| `packages/ai-parrot-server/tests/studio/test_integration.py` | MODIFY | shared wave fix (see TASK-5497): BYOK fixture selects documentdb |
| `packages/ai-parrot-server/tests/studio/test_byok.py` | MODIFY | shared wave fix (see TASK-5497) |
| `packages/ai-parrot-server/tests/studio/storage/test_vault_store.py` | MODIFY | shared wave fix (see TASK-5497) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.security.credentials_utils import decrypt_credential, encrypt_credential, llm_key_context  # verified: credentials_utils.py:108,83,68
from parrot.security.vault_utils import get_vault_keyring                                             # verified: vault_utils.py:57
from parrot.userstore import RedisDocumentStore, resolve_store_backend                                # TASK-5495/5496
from parrot.userstore.collections import USER_LLM_KEYS                                                # TASK-5496
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/broker/__init__.py
from .byok import _UserLLMKeyResolver  # noqa: F401  (re-exported)          # line 31
_PG_STORE: Any = None                                                        # line 41
def set_user_llm_key_store(store: Any) -> None:                              # line 44 — server registers Postgres here
def byok_store_setting() -> str:                                             # line 53 — today: documentdb|postgres, default documentdb

# packages/ai-parrot/src/parrot/auth/broker/byok.py
from parrot.auth import broker as _pkg   # globals read at call time
class _UserLLMKeyResolver(CredentialResolver):
    COLLECTION: str = "user_llm_keys"
    async def resolve(self, channel: str, user_id: str) -> str | None:       # branch at line 49: `if _pkg.byok_store_setting() == "postgres":`
    async def _resolve_postgres(self, channel: str, user_id: str) -> str | None:  # line 98 — fails closed (None) when unregistered or on error

# packages/ai-parrot-server/src/parrot/handlers/studio/storage/byok_store.py — the Postgres twin to mirror
class PgUserLLMKeyStore:
    async def get(self, user_id: Any, provider: str) -> str | None:          # decrypt; raises on keyring/decrypt failure
    async def put(self, user_id: Any, provider: str, api_key: str) -> None:  # seals {"api_key": api_key}; stores key_id=keyring.active_key_id, masked
    async def delete(self, user_id: Any, provider: str) -> bool:
    async def list_masked(self, user_id: Any) -> list[dict[str, Any]]:       # line 61 — [{provider, masked, created_at}] sorted by provider

# packages/ai-parrot-server/src/parrot/handlers/studio/byok.py:47 — mask rule to move into core
def _mask(api_key: str) -> str:
    if len(api_key) <= 7:
        return "*" * len(api_key)
    return f"{api_key[:3]}…{api_key[-4:]}"

# DocumentDB `user_llm_keys` document shape (studio/byok.py:225-231): {user_id, provider, api_key (sealed), created_at, updated_at}
```

### Does NOT Exist
- ~~`get_user_llm_key_store`, `mask_api_key`, `RedisUserLLMKeyStore`~~ — created by this task.
- ~~A quarantine marker in Redis~~ — Redis quarantine moves documents to `user_llm_keys_quarantine` (TASK-5510); the Postgres `QUARANTINE_MARK` (server `studio/storage/vault_targets.py:30`) does not apply and must not be imported into core.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/auth/broker/byok_redis.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/auth/broker/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/auth/broker/byok.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/auth/test_byok_store_redis.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/unit/test_user_llm_key_resolver.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/broker/__init__.py#byok_store_setting",
    "sym:packages/ai-parrot/src/parrot/auth/broker/__init__.py#set_user_llm_key_store",
    "sym:packages/ai-parrot/src/parrot/auth/broker/byok.py#_UserLLMKeyResolver",
    "sym:packages/ai-parrot/src/parrot/security/credentials_utils.py#llm_key_context"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `byok_store_setting()` keeps its name and its callers (`studio/byok.py`, `key_source.py`); it may now raise
  `UserStoreMisconfigured` — `_UserLLMKeyResolver.resolve` catches it and returns `None` (fail closed, as today).
- `get_user_llm_key_store()`: `postgres` → `_PG_STORE` (may be `None`), `redis` → module-level `RedisUserLLMKeyStore`, `documentdb` → `None`.
- Never log the key, ciphertext or masked preview.

---

## Implementation Blueprint

### Steps (in order)
1. Create `byok_redis.py` — *why*: Redis twin of `PgUserLLMKeyStore` with the same four methods.
2. Rewrite `byok_store_setting()` and add `get_user_llm_key_store()` in `__init__.py` — *why*: one accessor replaces four `== "postgres"` branches (TASK-5502 uses it).
3. Generalise the resolver branch — *why*: `redis` must work without touching DocumentDB.
4. Pin the legacy resolver test; write Redis tests.

### `packages/ai-parrot/src/parrot/auth/broker/byok_redis.py` (CREATE)
```python
"""BYOK LLM keys in Redis (FEAT-878). Same AAD (llm_key_context) as DocumentDB/Postgres."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from parrot.security.credentials_utils import decrypt_credential, encrypt_credential, llm_key_context
from parrot.userstore import RedisDocumentStore
from parrot.userstore.collections import USER_LLM_KEYS

logger = logging.getLogger("parrot.auth.broker")


def mask_api_key(api_key: str) -> str:
    """First 3 + last 4 chars; all '*' when len <= 7 (never expose more — Studio spec §7)."""
    if len(api_key) <= 7:
        return "*" * len(api_key)
    return f"{api_key[:3]}…{api_key[-4:]}"


class RedisUserLLMKeyStore:
    """Documents {user_id, provider, api_key (sealed), key_id, masked, created_at, updated_at}."""

    def __init__(self, documents: RedisDocumentStore | None = None) -> None:
        self._docs = documents or RedisDocumentStore(USER_LLM_KEYS)

    async def get(self, user_id: Any, provider: str) -> str | None:
        """Decrypted key or None when absent. Raises on keyring/decrypt failure (like the Postgres twin)."""
        from parrot.security.vault_utils import get_vault_keyring

        doc = await self._docs.get({"user_id": user_id, "provider": provider})
        if doc is None:
            return None
        return decrypt_credential(doc["api_key"], llm_key_context(user_id, provider), get_vault_keyring()).get("api_key")

    async def put(self, user_id: Any, provider: str, api_key: str) -> None:
        """Seal and upsert; created_at kept on rotation."""
        # FILL IN: keyring = get_vault_keyring(); sealed = encrypt_credential({"api_key": api_key}, llm_key_context(...), keyring);
        #   upsert({user_id, provider}, {api_key: sealed, key_id: keyring.active_key_id, masked: mask_api_key(api_key),
        #   updated_at: now}, on_insert={created_at: now}) — bounded by PgUserLLMKeyStore.put parity.
        raise NotImplementedError

    async def delete(self, user_id: Any, provider: str) -> bool:
        return await self._docs.delete({"user_id": user_id, "provider": provider})

    async def list_masked(self, user_id: Any) -> list[dict[str, Any]]:
        """[{provider, masked, created_at}] sorted by provider; decrypt-and-mask only when ``masked`` is missing
        (documents copied from DocumentDB). An undecryptable copied key shows "****"."""
        # FILL IN: find({"user_id": user_id}); build items; sort by provider — bounded by spec §3 M6.
        raise NotImplementedError
```

### `packages/ai-parrot/src/parrot/auth/broker/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def byok_store_setting() -> str:' packages/ai-parrot/src/parrot/auth/broker/__init__.py)
# REPLACE the whole `def byok_store_setting() -> str:` function (line 53 to end of file) with:
def byok_store_setting() -> str:
    """The ``BYOK_STORE`` backend via the FEAT-878 resolver: redis (default) | documentdb | postgres.

    Raises:
        UserStoreMisconfigured: invalid BYOK_STORE / PARROT_USER_STORE value.
    """
    from parrot.userstore import resolve_store_backend

    return resolve_store_backend("BYOK_STORE")


_REDIS_STORE: Any = None


def get_user_llm_key_store() -> Any | None:
    """Registered Postgres store when postgres (may be None); Redis store when redis; None for documentdb."""
    # FILL IN: branch on byok_store_setting(); build _REDIS_STORE lazily from parrot.auth.broker.byok_redis — bounded by spec §3 M6.
    raise NotImplementedError
```

### `packages/ai-parrot/src/parrot/auth/broker/byok.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'if _pkg.byok_store_setting() == "postgres":' packages/ai-parrot/src/parrot/auth/broker/byok.py)
# REPLACE `if _pkg.byok_store_setting() == "postgres":` + its return (byok.py:49-50) with:
        try:
            setting = _pkg.byok_store_setting()
        except Exception as exc:  # pylint: disable=broad-except — misconfiguration must not break agent creation
            logger.warning("_UserLLMKeyResolver: invalid BYOK store setting: %s", type(exc).__name__)
            return None
        if setting in ("postgres", "redis"):
            return await self._resolve_store(channel, user_id)
# occurrences: 1 (verified: grep -c 'async def _resolve_postgres(self, channel: str, user_id: str) -> str | None:' .../byok.py)
# RENAME `_resolve_postgres` (line 98) to `_resolve_store`; read `_pkg.get_user_llm_key_store()` instead of `_pkg._PG_STORE`;
#   keep the fail-closed warnings (None when no store, None on any read error); never log the key.
```

### `packages/ai-parrot/tests/unit/test_user_llm_key_resolver.py` (MODIFY)
```python
# Add near the top-level fixtures:
@pytest.fixture(autouse=True)
def _pin_documentdb(monkeypatch):
    """These tests fake DocumentDB; FEAT-878 made Redis the default."""
    monkeypatch.setenv("BYOK_STORE", "documentdb")
```

### FILL IN checklist
- [ ] `RedisUserLLMKeyStore.put` / `list_masked`
- [ ] `get_user_llm_key_store`
- [ ] `_resolve_store` rename + accessor

---

## Acceptance Criteria

- [ ] `BYOK_STORE` unset → keys stored/listed/resolved in Redis; masked previews never expose more than 3+4 chars
- [ ] `BYOK_STORE=postgres` behaviour unchanged (existing studio storage tests pass)
- [ ] Invalid `BYOK_STORE` → resolver returns `None` (fail closed), no exception escapes
- [ ] `ruff check` clean

---

## Validation Commands
- `pytest packages/ai-parrot/tests/auth/test_byok_store_redis.py -q`
- `pytest packages/ai-parrot/tests/unit/test_user_llm_key_resolver.py -q`
- `pytest packages/ai-parrot-server/tests/studio/storage/test_byok_store.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/auth/test_byok_store_redis.py
import pytest

from parrot.auth import broker
from parrot.auth.broker import _UserLLMKeyResolver
from parrot.auth.broker.byok_redis import RedisUserLLMKeyStore, mask_api_key
from parrot.userstore.testing import redis_test_settings


@pytest.fixture
async def redis_byok(monkeypatch):
    # FILL IN: test keyring (VAULT_MASTER_KEY_v1 / VAULT_ACTIVE_KEY_ID + reset_vault_keyring), BYOK_STORE unset,
    #   monkeypatch.setattr(broker, "_REDIS_STORE", None); then `async with redis_test_settings(monkeypatch): yield`
    ...


async def test_byok_redis_store(redis_byok):
    store = RedisUserLLMKeyStore()
    await store.put("35", "anthropic", "sk-ant-1234567890")
    assert await store.get("35", "anthropic") == "sk-ant-1234567890"
    assert (await store.list_masked("35"))[0]["masked"] == mask_api_key("sk-ant-1234567890")
    assert await store.delete("35", "anthropic") is True


async def test_byok_resolver_redis(redis_byok): ...          # resolver returns the key; None for another user
async def test_list_masked_fallback_for_copied_docs(redis_byok): ...  # doc without "masked" → decrypt+mask
async def test_invalid_setting_fails_closed(monkeypatch): ...  # BYOK_STORE=bogus → resolver returns None
```

---

## Agent Instructions

1. **Work in the feature worktree** — `parrot sdd worktree ensure --slug redis-user-stores --feature-id FEAT-878`
2. **Read the spec** (§3 M6)
3. **Check dependencies** — TASK-5496 must be `done`
4. **Verify the Codebase Contract** (re-run each `grep -c`)
5. **Update status** → `"in-progress"`, commit only the index file
6. **Implement** from the blueprint, complete every `# FILL IN:`
7. **Verify** — Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`
8. **Commit the code** — only the files listed above
9. **Close the task** — `parrot sdd task close TASK-5501 redis-user-stores verified`
10. **Fill in the Completion Note**, commit the staged SDD state

---

## Completion Note


- Task: TASK-5501
- Feature: redis-user-stores
- Implementation SHA: 4499e5d7141c96a0145660c68962efd625dcf331
- Closed at (UTC): 2026-11-11T01:37:06+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-luna · Backend: codex · Model: gpt-5.6-luna · Attempts: 2 · Duration: 223s · Tokens: n/a |
