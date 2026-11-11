# TASK-5498: `CredentialsHandler` through `vault_utils` (+ Postgres list/exists)

**Feature**: FEAT-878 — Redis user stores (MongoDB-free local installs)
**Spec**: `sdd/specs/redis-user-stores.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5497
**Assigned-to**: unassigned

---

## Context

Spec §1 Problem Statement, §2 "Vault access is centralised", §3 Module 4, decision
`vault-access-through-vault-utils`. `CredentialsHandler` (`/api/v1/users/credentials[/{name}]`) reads and
writes `user_credentials` in DocumentDB directly, ignoring `VAULT_STORE` (so FEAT-621's Postgres mode splits
credentials across stores), and its POST/PUT use `DocumentDb.save_background` — an INSERT — so every PUT
leaves a duplicate document. Routing all four verbs through `vault_utils` fixes both and makes Redis work.

---

## Scope

- Rewrite `get` / `post` / `put` / `delete` of `CredentialsHandler` to use `retrieve_vault_credential`,
  `list_vault_credentials`, `vault_credential_exists`, `store_vault_credential`, `delete_vault_credential`
  (all awaited — no background write). Remove the `DocumentDb` import.
- Keep every status code, error message and response body as today (AC7); keep the session-vault calls.
- Add `list_credentials` / `exists` to `PgVaultCredentialStore` (the Protocol from TASK-5497 needs them).
- Adapt the two existing handler test modules (their patch targets disappear) and add a dispatch test.

**NOT in scope**: `AgentTalk._restore_user_mcp_servers` (TASK-5499), `vault_utils` itself (TASK-5497).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/credentials.py` | MODIFY | four verbs via `vault_utils`; drop `DocumentDb` |
| `packages/ai-parrot-server/src/parrot/handlers/studio/storage/vault_store.py` | MODIFY | `list_credentials`, `exists` |
| `packages/ai-parrot/tests/handlers/test_credentials_handler.py` | MODIFY | patch `vault_utils` instead of the handler's `DocumentDb`; pin `VAULT_STORE=documentdb` |
| `packages/ai-parrot/tests/handlers/test_credentials_integration.py` | MODIFY | same; fake DB gains `write`/`update_one`; assertions on stored docs instead of `save_background` |
| `packages/ai-parrot-server/tests/unit/test_credentials_store_dispatch.py` | CREATE | four verbs on Redis; double PUT leaves one credential; Pg list/exists |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.security.vault_utils import (            # verified: security/vault_utils.py:57,92,145,184 (+ TASK-5497 additions)
    get_vault_keyring, store_vault_credential, retrieve_vault_credential, delete_vault_credential,
    list_vault_credentials, vault_credential_exists,
)
from parrot.handlers.models.credentials import CredentialDocument, CredentialPayload, CredentialResponse  # verified: credentials.py:30-34
from parrot.security.credentials_utils import credential_context, decrypt_credential, encrypt_credential  # verified: credentials_utils.py:53,108,83
from .repositories import _fetch_all, _fetch_one   # verified: studio/storage/repositories.py:92,98 (overrides_store.py imports both)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/credentials.py
from parrot.interfaces.documentdb import DocumentDb            # line 29 — REMOVE (only used by the four verbs)
from parrot.handlers.credentials_utils import (credential_context, decrypt_credential, encrypt_credential)  # lines 35-39 — remove names that become unused
from parrot.security.vault_utils import get_vault_keyring      # line 40
def _vault_keyring():                                          # line 45 — keep: the 500 "Encryption service unavailable." pre-check
class CredentialsHandler(BaseView):                            # line 59
    COLLECTION: str = "user_credentials"                       # line 71 — keep (compatibility)
    def _get_user_id(self) -> str:                             # line 78 — 401 via web.HTTPUnauthorized
    def _set_session_credential(...)                           # line 110
    def _remove_session_credential(self, name: str) -> None:   # line 121
    async def get(self) -> web.Response:                       # line 152 — single: 404 "Credential '{name}' not found.", 500 "Failed to decrypt credential."; all: {name: CredentialResponse}
    async def post(self) -> web.Response:                      # line 229 — 400 on ValidationError, 409 "Credential '{name}' already exists.", 201 CredentialResponse
    async def put(self) -> web.Response:                       # line 330 — 404 when absent; 200 CredentialResponse
    async def delete(self) -> web.Response:                    # line 436 — 400 no name, 404 absent, removes session copy then store
# Stored payload today: credential_dict = {"driver": payload.driver, "params": payload.params}
#   sealed with credential_context(user_id, name) → identical to store_vault_credential(user_id, name, credential_dict)

# packages/ai-parrot-server/src/parrot/handlers/studio/storage/vault_store.py
from .repositories import _fetch_one                           # line 10
_GET_SQL = "SELECT credential FROM navigator.ai_user_credentials WHERE user_id = $1 AND name = $2"
class PgVaultCredentialStore:                                  # line 23
    async def retrieve(self, user_id: Any, vault_name: str) -> dict[str, Any]:
    async def delete(self, user_id: Any, vault_name: str) -> None:  # line 43
```

### Does NOT Exist
- ~~`DocumentDb` in `parrot.handlers.credentials` after this task~~ — tests must not patch it.
- ~~`PgVaultCredentialStore.list` / `.list_names`~~ — the methods are `list_credentials` and `exists`.
- ~~`vault_utils.update_vault_credential`~~ — `store_vault_credential` is the upsert.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/handlers/credentials.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/src/parrot/handlers/studio/storage/vault_store.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/handlers/test_credentials_handler.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/handlers/test_credentials_integration.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/unit/test_credentials_store_dispatch.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/credentials.py#CredentialsHandler",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/storage/vault_store.py#PgVaultCredentialStore",
    "sym:packages/ai-parrot/src/parrot/security/vault_utils.py#store_vault_credential",
    "sym:packages/ai-parrot/src/parrot/security/vault_utils.py#retrieve_vault_credential"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Same HTTP contract (AC7): status codes, messages, bodies. Only change: POST/PUT await the durable write.
- `user_id` passes through exactly as `_get_user_id()` returns it (string) — do not cast.
- A decrypt failure on single GET stays 500 "Failed to decrypt credential."; `retrieve_vault_credential`
  raises `KeyError` for absent → 404, anything else → 500.
- Existing tests: change patch targets to `parrot.security.vault_utils.DocumentDb` and
  `parrot.security.vault_utils.get_vault_keyring`, add an autouse `monkeypatch.setenv("VAULT_STORE", "documentdb")`,
  keep every status/body assertion; replace `save_background` assertions with assertions on the stored document.

---

## Implementation Blueprint

### Steps (in order)
1. Add `list_credentials` / `exists` to `PgVaultCredentialStore` — *why*: `vault_utils` dispatches these to a registered Postgres store.
2. Rewrite the four verbs — *why*: removes the VAULT_STORE bypass and the duplicate-insert bug (AC5, AC6).
3. Drop now-unused imports (`DocumentDb`, `encrypt_credential`, possibly `decrypt_credential`/`credential_context`) — *why*: ruff F401.
4. Adapt the two test modules; create the dispatch test; run validation.

### `packages/ai-parrot-server/src/parrot/handlers/studio/storage/vault_store.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from .repositories import _fetch_one' .../studio/storage/vault_store.py)
# REPLACE `from .repositories import _fetch_one` (line 10) with:
from .repositories import _fetch_all, _fetch_one
# occurrences: 1 (verified: grep -c 'async def delete(self, user_id: Any, vault_name: str) -> None:' .../vault_store.py)
# AFTER the body of `async def delete(self, user_id: Any, vault_name: str) -> None:` (verified: vault_store.py:43) add:
    async def list_credentials(self, user_id: Any) -> dict[str, dict[str, Any]]:
        """{name: decrypted dict} for one user; undecryptable rows skipped with a warning."""
        async with self._pool.acquire() as conn:
            rows = await _fetch_all(conn, _LIST_SQL, str(user_id))
        # FILL IN: decrypt each row["credential"] with credential_context(user_id, row["name"]); on failure
        #   logger.warning naming only the credential and the exception class.
        raise NotImplementedError

    async def exists(self, user_id: Any, vault_name: str) -> bool:
        async with self._pool.acquire() as conn:
            return await _fetch_one(conn, _GET_SQL, str(user_id), vault_name) is not None
# and next to _GET_SQL add:
_LIST_SQL = "SELECT name, credential FROM navigator.ai_user_credentials WHERE user_id = $1 ORDER BY name"
```

### `packages/ai-parrot-server/src/parrot/handlers/credentials.py` (MODIFY — GET)
```python
# occurrences: 1 (verified: grep -c 'async def get(self) -> web.Response:' .../handlers/credentials.py)
# REPLACE the `async with DocumentDb() as db:` block inside get() (from line ~179 to the end of the method) with:
        if name:
            try:
                cred_dict = await retrieve_vault_credential(user_id, name)
            except KeyError:
                return self.error(f"Credential '{name}' not found.", status=404)
            except Exception as exc:  # pylint: disable=broad-except
                self.logger.error("Failed to decrypt credential '%s' for user %s: %s", name, user_id, type(exc).__name__)
                return self.error("Failed to decrypt credential.", status=500)
            return self.json_response(CredentialResponse(name=name, **cred_dict).model_dump())
        result: dict[str, Any] = {}
        for cname, cred_dict in (await list_vault_credentials(user_id)).items():
            # FILL IN: build CredentialResponse(name=cname, **cred_dict); skip (warn) entries that fail validation — matches today's "Skipping undecryptable credential" behaviour
            raise NotImplementedError
        return self.json_response(result)
```
**Why**: same responses as today; decryption now happens in `vault_utils`, the keyring pre-check
(`_vault_keyring()`) stays so a missing keyring still answers 500 "Encryption service unavailable.".

### `packages/ai-parrot-server/src/parrot/handlers/credentials.py` (MODIFY — POST / PUT / DELETE)
```python
# occurrences: 1 each (verified: grep -c for 'async def post(self) -> web.Response:', 'async def put(self) -> web.Response:',
#   'async def delete(self) -> web.Response:' in .../handlers/credentials.py → lines 229, 330, 436)
# POST — replace the `db = DocumentDb()` try-block with:
        try:
            if await vault_credential_exists(user_id, payload.name):
                return self.error(f"Credential '{payload.name}' already exists.", status=409)
            credential_dict = {"driver": payload.driver, "params": payload.params}
            self._set_session_credential(payload.name, credential_dict)
            await store_vault_credential(user_id, payload.name, credential_dict)
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.error("POST credential failed: %s", type(exc).__name__)
            return self.error("Failed to create credential.", status=500)
# PUT — same shape: `if not await vault_credential_exists(user_id, name): return 404 "Credential '{name}' not found."`,
#   then session update + `await store_vault_credential(user_id, name, credential_dict)`; keep today's 500 message for failures.
# DELETE — `if not await vault_credential_exists(user_id, name): return 404`; `self._remove_session_credential(name)`;
#   `await delete_vault_credential(user_id, name)`; keep today's success body and error logging.
# FILL IN: copy each verb's existing success response and failure message verbatim from the current code — bounded by AC7.
```
**Why**: `store_vault_credential` upserts in every backend, so a second PUT replaces instead of inserting (AC6).

### FILL IN checklist
- [ ] `PgVaultCredentialStore.list_credentials` decrypt loop
- [ ] GET all-credentials loop
- [ ] POST/PUT/DELETE success bodies and error messages copied verbatim (AC7)
- [ ] test modules: new patch targets + `VAULT_STORE=documentdb` pin + fake DB `write`/`update_one`

---

## Acceptance Criteria

- [ ] `credentials.py` no longer imports or uses `DocumentDb` (AC5)
- [ ] Two PUTs leave exactly one stored credential holding the second value, on Redis and on DocumentDB (AC6)
- [ ] Existing handler tests pass (pinned to `documentdb`) with unchanged status/body assertions; the same cases pass on Redis (AC7)
- [ ] `PgVaultCredentialStore.list_credentials` / `exists` work with a mocked pool
- [ ] `ruff check` clean on touched files

---

## Validation Commands
- `pytest packages/ai-parrot-server/tests/unit/test_credentials_store_dispatch.py -q`
- `pytest packages/ai-parrot/tests/handlers/test_credentials_handler.py -q`
- `pytest packages/ai-parrot/tests/handlers/test_credentials_integration.py -q`
- `pytest packages/ai-parrot/tests/handlers/test_credential_routes.py -q`
- `pytest packages/ai-parrot-server/tests/studio/storage/test_vault_store.py -q`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/unit/test_credentials_store_dispatch.py
import pytest

from parrot.userstore.testing import redis_test_settings


@pytest.fixture
async def redis_vault(monkeypatch):
    # FILL IN: test keyring (as in tests/security/test_vault_store_redis.py), VAULT_STORE unset, reset
    #   vault_utils._PG_VAULT_STORE/_REDIS_VAULT_STORE, then `async with redis_test_settings(monkeypatch): yield`
    ...


async def test_credentials_handler_uses_vault_utils(redis_vault): ...   # GET 404 → POST 201 → POST 409 → GET 200 → DELETE → GET 404
async def test_credentials_put_no_duplicate(redis_vault): ...           # PUT twice → list has one entry with the 2nd value
async def test_pg_vault_list_and_exists(): ...                          # mocked pool rows, as in studio/storage/test_vault_store.py
```

---

## Agent Instructions

1. **Work in the feature worktree** — `parrot sdd worktree ensure --slug redis-user-stores --feature-id FEAT-878`
2. **Read the spec** (§2 Vault access is centralised, §3 M4, AC5–AC7)
3. **Check dependencies** — TASK-5497 must be `done`
4. **Verify the Codebase Contract** (re-run each `grep -c`)
5. **Update status** → `"in-progress"`, commit only the index file
6. **Implement** from the blueprint, complete every `# FILL IN:`
7. **Verify** — Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`
8. **Commit the code** — only the files listed above
9. **Close the task** — `parrot sdd task close TASK-5498 redis-user-stores verified`
10. **Fill in the Completion Note**, commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
