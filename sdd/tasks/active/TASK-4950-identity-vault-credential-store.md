# TASK-4950: IdentityVaultCredentialStore: transactional single-account load/save/delete for any provider

**Feature**: FEAT-773 — Delegated Auth Connections — S-1 Connections Core
**Spec**: `sdd/specs/delegated-auth-connections.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4940
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 and the **M8 transaction contract (AC-12)**, G4, S2, S3. The Identity Vault (`auth.user_identities`)
becomes the durable owner for every 3LO provider. navigator-auth's `IdentityStore` cannot do what v1 needs:
`save_linked_identity` upserts per `(user_id, provider, provider_user_id)` (so a reconnect with a different external
account keeps the old one) and every method commits on its own connection. This task generalizes
`IdentityVaultCredentialSink` into `IdentityVaultCredentialStore` (the `CredentialStore` Protocol) with a
**server-side transaction helper**: under the M2 principal lock (held by the caller), a minted save atomically
inserts/updates the new account row and deletes superseded rows for the same principal/provider; failure rolls back
and keeps the previous grant. Delete removes every credential row for the principal/provider. Refresh updates only
the still-selected row after re-reading it.

---

## Scope

- Replace `IdentityVaultCredentialSink` with `IdentityVaultCredentialStore(db_pool, cipher=None)`:
  `load(user_id, provider)` → newest enabled row → decrypt → token payload dict (`AbstractOAuth2TokenSet` shape, extras
  from `auth_data`); `save(..., minted=True)` → `_replace_account_tx`; `save(..., minted=False)` → re-read selected row,
  skip (log) if its `provider_user_id` differs from `payload["account_id"]`, else update sealed token columns in one
  statement; `delete(user_id, provider)` → one transaction deleting all rows of that principal/provider.
- Transaction helper over `_raw_connection(conn)` + `async with raw.transaction()`; seal with `IdentityCipher.encrypt`
  (same context fields as IdentityStore: user_id, auth_provider, provider_user_id, field) and stamp `key_version`.
- Never write channel identity rows (provider = `telegram`/`slack`/`msteams` rows belong to `IdentityMappingService`).
- Update `test_identity_credential_sink.py`; add a real-DB integration test file gated on DB reachability.

**NOT in scope**: the metadata-preserving re-seal helper (TASK-4951); wiring the store into managers (TASK-4954/4955/4957).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/services/identity_credential_sink.py` | MODIFY | IdentityVaultCredentialStore + transaction helper |
| `packages/ai-parrot-server/tests/unit/test_identity_credential_sink.py` | MODIFY | store unit tests |
| `packages/ai-parrot-server/tests/integration/test_identity_vault_store_db.py` | CREATE | real-DB AC-12 gates |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` @ `a848d5a73e` (2026-10-30) while writing this task.
> Use these exact imports and signatures. Anything not listed: VERIFY it exists before using it.

### Verified Imports
```python
from navigator_auth.identity.store import IdentityStore, IdentityCredentialError     # verified: store.py:151, :44
from navigator_auth.identity.crypto import IdentityCipher                          # verified: crypto.py:95
from navigator_auth.identity.types import TokenResponse                            # verified (spec §6)
from parrot.services.identity_mapping import _raw_connection                       # verified: identity_mapping.py:101
from parrot.auth.oauth2_base import CredentialStore                                # TASK-4940 (Protocol, structural)
from parrot.auth.principal import Principal                                        # TASK-4937
```

### Existing Signatures to Use
```python
# navigator_auth 0.28.9 (installed; pyproject floor >=0.28.8) — navigator_auth/identity/store.py
class IdentityStore:                                                     # :151
    def __init__(self, db_pool, cipher: Optional[IdentityCipher] = None)  # self._pool, self._cipher
    # every method does `async with await self._pool.acquire() as conn:` and commits on its own — NO shared transaction API
    async def save_linked_identity(user_id, provider, token: TokenResponse, userinfo=None) -> UserIdentity   # :214 upsert by
                                                                         #   (user_id, provider, provider_user_id); enables row; rewrites auth_data
    async def get_by_provider(user_id, provider) -> Optional[UserIdentity]          # :322 newest enabled row
    async def delete(user_id, identity_id) -> bool                                  # :396
    async def update_tokens(identity, token: TokenResponse) -> UserIdentity          # :408 re-seals access/refresh(/id) only
    def decrypt_credential(identity: UserIdentity) -> TokenResponse                  # :444
    async def find_user_by_provider_account(provider, provider_user_id) -> Optional[Any]   # :497 enabled rows only
# navigator_auth/identity/crypto.py
class IdentityCipher:                                                    # :95  (public)
    def __init__(self, master_keys: Optional[dict] = None, *, keyring: Optional[KeyRing] = None)
    key_id -> int (active key, property :138) ; keyring -> KeyRing (:143)
    def encrypt(self, value, *, user_id, auth_provider, provider_user_id, field) -> bytes        # :147
    def decrypt(self, ciphertext, *, user_id, auth_provider, provider_user_id, field) -> Any     # :165 raises VaultCryptoError
# navigator_auth.identity.store: IdentityCredentialError(provider, field, reason) (:44); _IDENTITY_TABLE = "<schema>.user_identities"
# navigator_auth.models.UserIdentity fields: identity_id (UUID), user_id, auth_provider, auth_data (dict), provider_user_id, scopes,
#   access_token/refresh_token/id_token (bytes), token_type, expires_at, refreshed_at, enabled, key_version, created_at, email, display_name
# navigator_auth.identity.types.TokenResponse: credential, access_token, refresh_token, id_token, expires_at, expires_in,
#   provider_user_id, token_type, scopes, raw; classmethods from_credential, from_oauth_response(payload, scopes)
# Transaction path (verified, used by IdentityMappingService):
#   packages/ai-parrot-server/src/parrot/services/identity_mapping.py:101  def _raw_connection(conn) -> asyncpg connection
#   (asyncdb conn.engine()); asyncpg connections support `async with raw.transaction():` and raise on SQL errors

# packages/ai-parrot-server/src/parrot/services/identity_credential_sink.py (today)
class IdentityVaultCredentialSink:                                       # :24 anchor
    def __init__(self, db_pool: Any, provider: str = "jira") (:34); _store() (:39); _as_token_response(token) (:45-63)
    async def persist_minted(channel, user_id, token, state_payload) (:64) ; async def persist(channel, user_id, token) (:123)
```

### Does NOT Exist
- ~~`IdentityStore` transaction / replace-account / metadata-only write API~~ — none in 0.28.9; build the helper here.
- ~~`IdentityVaultCredentialSink`~~ — replaced (hard cut; its only caller is `integrations/manager.py`, switched by TASK-4954).
- ~~an upstream navigator-auth method~~ — do not invent one, do not add a dependency (spec §3 M8).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/services/identity_credential_sink.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/unit/test_identity_credential_sink.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/integration/test_identity_vault_store_db.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/services/identity_credential_sink.py#IdentityVaultCredentialSink",
    "sym:packages/ai-parrot-server/src/parrot/services/identity_mapping.py#_raw_connection"
  ]
}
```

---

## Implementation Notes

- SQL on `navigator_auth.identity.store._IDENTITY_TABLE` (import the constant; do not hard-code the schema).
- Minted save in ONE transaction: `SELECT … FOR UPDATE` rows of (user_id, provider) → upsert the row for the new
  `provider_user_id` (UPDATE if present else INSERT with a new UUID) → `DELETE` the other rows. Exceptions propagate
  (the manager turns them into `CredentialPersistenceError`).
- `auth_data` keeps non-secret metadata (account_id, display_name, email, cloud_id, site_url, scopes_granted);
  never put tokens in `auth_data` (`_SECRET_KEYS`, identity_mapping.py:98).
- `user_id` is a bigint column: pass `int(user_id)` (mirror `_user_id_param`, store.py:86).
- O365 payloads (no cloud_id) must be accepted — the store is provider-agnostic.
- Real-DB tests: skip when the auth DB is unreachable (pattern: FEAT-644 conftest, real Postgres; no fakeredis/fake DB).

---

## Implementation Blueprint

> Executor-ready starting point. Write each block to its declared path, then complete every
> `# FILL IN:` marker. Business branches, edge cases and test bodies are stubs by design.
> Never change a signature, class name or file path the blueprint fixes.

### Steps (in order)
1. Rename/reshape the class and implement load (block A) — *why*: cold-cache hydration from the durable owner (G4).
2. Implement the minted transaction + refresh update + delete (block B) — *why*: AC-12 contract.
3. Unit tests with a fake asyncpg connection; real-DB tests for rollback, A→B replacement, disconnect, cold load.

### `packages/ai-parrot-server/src/parrot/services/identity_credential_sink.py` (MODIFY)

Block A — class shell + load:
```python
# occurrences: 1 (verified: grep -c 'class IdentityVaultCredentialSink:' identity_credential_sink.py → :24)
# REPLACE the class (and module docstring wording "sink" → "store") WITH:
class IdentityVaultCredentialStore:
    """``CredentialStore`` over navigator-auth's Identity Vault for any 3LO provider (FEAT-773 M8).

    Single account per (principal, provider) in v1 (S3): a minted save atomically replaces superseded accounts.
    The caller (AbstractOAuth2Manager) holds the per-principal lock; this class never takes it.
    """

    def __init__(self, db_pool: Any, cipher: Optional[Any] = None) -> None:
        self._db_pool = db_pool
        self._cipher = cipher
        self.logger = logging.getLogger(__name__)

    def _store(self) -> Any:
        from navigator_auth.identity.store import IdentityStore
        return IdentityStore(self._db_pool, cipher=self._cipher)

    def _identity_cipher(self) -> Any:
        from navigator_auth.identity.crypto import IdentityCipher
        return self._cipher or IdentityCipher()

    async def load(self, user_id: str, provider: str) -> Optional[Dict[str, Any]]:
        """Newest enabled row → decrypted token payload (AbstractOAuth2TokenSet shape), else None."""
        # FILL IN: row = await self._store().get_by_provider(int(user_id), provider); None → None;
        #          tr = store.decrypt_credential(row); map to {"access_token", "refresh_token", "expires_at" (epoch float),
        #          "scopes", "account_id": row.provider_user_id, **non-secret auth_data extras}; IdentityCredentialError
        #          → log (no token) and return None
        raise NotImplementedError
```

Block B — writes:
```python
    async def save(self, user_id: str, provider: str, payload: Dict[str, Any], *, minted: bool,
                   principal: Optional["Principal"], state_payload: Optional[Dict[str, Any]]) -> None:
        """minted → _replace_account_tx; refresh → _update_selected_tx. Raises on any failure (S2)."""
        if minted:
            await self._replace_account_tx(int(user_id), provider, payload)
        else:
            await self._update_selected_tx(int(user_id), provider, payload)

    async def delete(self, user_id: str, provider: str) -> None:
        """Delete EVERY credential row of (principal, provider) in one transaction (AC-12)."""
        # FILL IN: acquire → raw = _raw_connection(conn) → async with raw.transaction(): DELETE FROM _IDENTITY_TABLE
        #          WHERE user_id = $1 AND auth_provider = $2
        raise NotImplementedError

    async def _replace_account_tx(self, user_id: int, provider: str, payload: Dict[str, Any]) -> None:
        """One transaction: lock rows → upsert the new account row → delete superseded rows."""
        # FILL IN: per Implementation Notes; seal each present token column with
        #          self._identity_cipher().encrypt(value, user_id=user_id, auth_provider=provider,
        #          provider_user_id=account_id, field=<column>); key_version = cipher.key_id; enabled = TRUE;
        #          auth_data = non-secret metadata only — bounded by AC-12 (rollback keeps A)
        raise NotImplementedError

    async def _update_selected_tx(self, user_id: int, provider: str, payload: Dict[str, Any]) -> None:
        """Refresh: re-read the selected row FOR UPDATE; only update it if it still is payload['account_id']."""
        # FILL IN: row missing or provider_user_id != payload["account_id"] → log + return (replaced/deleted meanwhile);
        #          else UPDATE access_token/refresh_token (only when present)/expires_at/refreshed_at/key_version
        raise NotImplementedError
```
**Why this shape**: navigator-auth exposes no shared transaction, so the store owns it over the same asyncpg path
`IdentityMappingService` already uses, and seals with the public `IdentityCipher` so ciphertext stays readable by
`IdentityStore.decrypt_credential`.

### FILL IN checklist
- [ ] `load` mapping + IdentityCredentialError handling
- [ ] `delete` single transaction
- [ ] `_replace_account_tx` — lock/upsert/delete in one transaction; bounded by AC-12
- [ ] `_update_selected_tx` — re-read guard; bounded by AC-12 (no resurrection)
- [ ] unit tests (fake raw connection) + real-DB tests (skip when unreachable)

---

## Acceptance Criteria

- [ ] AC-12: minted save of account B for a principal holding A leaves only B; a failure inside the transaction leaves A intact
- [ ] Disconnect removes every credential row of the principal/provider; a cold `load` afterwards returns `None`
- [ ] Refresh updates only the still-selected account; a refresh for a replaced account is a logged no-op
- [ ] O365 payloads are accepted (provider-agnostic); no token value in `auth_data` or logs

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/unit/test_identity_credential_sink.py -q`
- `pytest packages/ai-parrot-server/tests/integration/test_identity_vault_store_db.py -q`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/unit/test_identity_credential_sink.py
@pytest.mark.asyncio
async def test_identity_vault_store_roundtrip_any_provider(): ...   # save(minted) → load decrypts; o365 payload accepted
@pytest.mark.asyncio
async def test_refresh_updates_selected_row_only(): ...

# packages/ai-parrot-server/tests/integration/test_identity_vault_store_db.py  (skip if auth DB unreachable)
@pytest.mark.asyncio
async def test_replace_a_with_b_then_cold_load_returns_b(): ...
@pytest.mark.asyncio
async def test_failure_inside_replacement_keeps_a(): ...           # force an error after the upsert → rollback
@pytest.mark.asyncio
async def test_disconnect_then_cold_load_returns_none(): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug delegated-auth-connections --feature-id FEAT-773`)
2. **Read the spec** (`sdd/specs/delegated-auth-connections.spec.md`) — at least §2, the module section named in Context, §5 and §7
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/delegated-auth-connections.json`
4. **Verify the Codebase Contract** before writing ANY code (re-grep each anchor; line numbers drift). If an entry is stale, fix the contract in this file first
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a signature or path the blueprint fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH` set to every touched `packages/<dist>/src` (the shared `.venv` imports the main checkout otherwise)
8. **Commit the code** — stage only the files listed above (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <TASK-ID> delegated-auth-connections verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
