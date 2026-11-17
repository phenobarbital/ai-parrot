# TASK-4951: Metadata-preserving re-seal transaction helper for Identity Vault rows

**Feature**: FEAT-773 — Delegated Auth Connections — S-1 Connections Core
**Spec**: `sdd/specs/delegated-auth-connections.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4950
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 10 (re-encryption) delegates the write to M8: "M8 owns a transaction helper in
`identity_credential_sink.py` for this metadata-preserving write". `IdentityStore.update_tokens` stamps the active
`key_version` but never re-seals `id_token`, so a row can claim the active key while holding old-key ciphertext.
This helper decrypts every present token column with the full key ring and re-seals all of them under the active
key in one write, preserving identity id, account binding, enabled status, profile/auth_data, scopes and expiry.

---

## Scope

- Add `reseal_identity_row(db_pool, row, *, cipher=None) -> None`: one transaction; `SELECT … FOR UPDATE` by
  `identity_id`; decrypt `access_token`, `refresh_token`, `id_token` (those present) with the full ring; re-encrypt each
  under the active key; `UPDATE` only those columns + `key_version`; nothing else changes.
- Add `verify_active_only(row, *, active_cipher) -> bool`: every present token column decrypts with a cipher whose ring
  holds ONLY the active key.
- Add `list_credential_rows(db_pool, providers) -> List[row]`: all credential-bearing rows (disabled included) for the
  given providers (empty = all providers).
- Undecryptable column → raise `IdentityCredentialError` (caller counts it as failed) and leave the row untouched.
- Tests including the mixed-key row and disabled-row preservation.

**NOT in scope**: the CLI/job orchestration, counts and retirement gate (TASK-4963); taking the principal lock (the job does).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/services/identity_credential_sink.py` | MODIFY | reseal/verify/list helpers |
| `packages/ai-parrot-server/tests/unit/test_identity_reseal.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` @ `a848d5a73e` (2026-10-30) while writing this task.
> Use these exact imports and signatures. Anything not listed: VERIFY it exists before using it.

### Verified Imports
```python
from navigator_auth.identity.crypto import IdentityCipher                 # verified: crypto.py:95 (keyring= kwarg)
from navigator_auth.identity.store import IdentityCredentialError         # verified: store.py:44
from parrot.services.identity_mapping import _raw_connection              # verified: identity_mapping.py:101
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

# After TASK-4950 (same file): IdentityVaultCredentialStore with _identity_cipher(); transaction pattern
#   `async with await pool.acquire() as conn: raw = _raw_connection(conn); async with raw.transaction(): ...`
# navigator_session KeyRing: IdentityCipher(keyring=KeyRing(...)) — build an active-only ring for verify_active_only
#   FILL IN: verify the KeyRing constructor in navigator_session.vault before use (crypto.py:126 shows how IdentityCipher builds one)
```

### Does NOT Exist
- ~~re-sealing via `save_linked_identity`~~ — forbidden: it enables rows and rewrites profile fields (spec M10).
- ~~filtering rows by `key_version`~~ — forbidden: the row-level version lies for mixed-key rows.

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
      "path": "packages/ai-parrot-server/tests/unit/test_identity_reseal.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/services/identity_mapping.py#_raw_connection"
  ]
}
```

---

## Implementation Notes

- Decrypt context per column = (user_id, auth_provider, provider_user_id, field) — exactly IdentityStore._open's.
- Never log decrypted values; log `identity_id`, provider and the error class only.

---

## Implementation Blueprint

> Executor-ready starting point. Write each block to its declared path, then complete every
> `# FILL IN:` marker. Business branches, edge cases and test bodies are stubs by design.
> Never change a signature, class name or file path the blueprint fixes.

### Steps (in order)
1. Add the three helpers (block) — *why*: AC-18 needs a metadata-preserving re-seal and an active-only check.
2. Tests: two keys in the ring, v2 active; mixed-key row (id_token v1) → reseal → verify_active_only with v2 only is True; disabled row stays disabled.

### `packages/ai-parrot-server/src/parrot/services/identity_credential_sink.py` (MODIFY — append at module end)
```python
_TOKEN_COLUMNS = ("access_token", "refresh_token", "id_token")


async def list_credential_rows(db_pool: Any, providers: Sequence[str]) -> List[Any]:
    """Every credential-bearing identity row (disabled included) for ``providers`` (empty → all)."""
    # FILL IN: SELECT identity_id, user_id, auth_provider, provider_user_id, access_token, refresh_token, id_token,
    #          enabled, key_version FROM _IDENTITY_TABLE WHERE (access_token IS NOT NULL OR refresh_token IS NOT NULL
    #          OR id_token IS NOT NULL) [AND auth_provider = ANY($1)]
    raise NotImplementedError


async def reseal_identity_row(db_pool: Any, row: Any, *, cipher: Optional[Any] = None) -> None:
    """Re-seal every present token column of one row under the active key; preserve all metadata."""
    # FILL IN: one transaction; re-read FOR UPDATE by identity_id (row gone → return); decrypt each present column with
    #          the full ring (IdentityCredentialError on failure → raise, nothing written); encrypt under active key;
    #          UPDATE only those columns + key_version WHERE identity_id = $n — bounded by AC-18 (metadata preserved)
    raise NotImplementedError


def verify_active_only(row: Any, *, active_cipher: Any) -> bool:
    """True iff every present token column decrypts with a ring holding ONLY the active key."""
    # FILL IN: try active_cipher.decrypt(...) per present column; any exception → False
    raise NotImplementedError
```

### FILL IN checklist
- [ ] `list_credential_rows` SQL
- [ ] `reseal_identity_row` transaction; bounded by AC-18
- [ ] `verify_active_only`
- [ ] imports (`Sequence`, `List`)
- [ ] tests: `test_reencrypt_reseals_all_columns`, `test_reencrypt_mixed_key_row` (helper level), `test_reencrypt_preserves_disabled_metadata`

---

## Acceptance Criteria

- [ ] AC-18 (helper): access, refresh AND id_token are re-sealed under the active key; identity id, enabled, auth_data, scopes, expiry unchanged
- [ ] An undecryptable row raises `IdentityCredentialError` and is not modified
- [ ] `verify_active_only` is False for a row whose id_token is still under the old key

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/unit/test_identity_reseal.py -q`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/unit/test_identity_reseal.py
@pytest.mark.asyncio
async def test_reencrypt_preserves_disabled_metadata(): ...
@pytest.mark.asyncio
async def test_reseal_mixed_key_row_then_active_only_verifies(): ...
@pytest.mark.asyncio
async def test_undecryptable_row_untouched(): ...
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

**Completed by**: sdd-worker orchestrator; seat sonnet (native)
**Date**: 2026-10-30
**Notes**: Implemented per task; merged, engine lint clean. Merge-tier validation: only red is pre-existing test_invalid_state_returns_400 (issue:e7b7e5906b6e).
