# TASK-4952: IdentityPrincipalResolver over auth.user_identities

**Feature**: FEAT-773 — Delegated Auth Connections — S-1 Connections Core
**Spec**: `sdd/specs/delegated-auth-connections.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4937
**Assigned-to**: unassigned

---

## Context

Spec §2 "Principal", §3 Module 8 (G1, U1, U3). The server's resolver maps `(channel, channel_user_id)` to the
Navigator principal: web ids pass through; other channels look up the channel identity row in
`auth.user_identities` via `IdentityStore.find_user_by_provider_account(channel, channel_user_id)`. A miss is `None`
(the caller fails closed — unlinked Telegram users must `/login`). `canonical_identity` comes from the row's e-mail
or, for `msteams`, the Entra OID.

---

## Scope

- New `services/identity_principal.py`: `IdentityPrincipalResolver(db_pool)`; `resolve(channel, channel_user_id)`.
- `a2a` ids that look like e-mails: resolve via the identity row with matching e-mail is NOT available in
  `IdentityStore` — FILL IN bounded: return `None` unless a verified lookup exists (record in the Completion Note).
- Test `test_identity_principal_resolver`.

**NOT in scope**: registering it (TASK-4957); Slack composite id normalization beyond passing it through.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/services/identity_principal.py` | CREATE | resolver |
| `packages/ai-parrot-server/tests/unit/test_identity_principal_resolver.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` @ `a848d5a73e` (2026-10-30) while writing this task.
> Use these exact imports and signatures. Anything not listed: VERIFY it exists before using it.

### Verified Imports
```python
from parrot.auth.principal import Principal          # TASK-4937
from navigator_auth.identity.store import IdentityStore   # verified: store.py:151
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

# packages/ai-parrot-server/src/parrot/services/identity_mapping.py
class IdentityMappingService: get_identity(...) (:270) / get_all_identities(nav_user_id) (:291) — channel rows' auth_data
```

### Does NOT Exist
- ~~`IdentityStore.find_user_by_email`~~ — does not exist; only `find_user_by_provider_account`.
- ~~`CanonicalIdentityMapper` → Navigator id~~ — returns OID/e-mail only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/services/identity_principal.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/unit/test_identity_principal_resolver.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/services/identity_mapping.py#IdentityMappingService"
  ]
}
```

---

## Implementation Notes

- `find_user_by_provider_account` returns only the `user_id`; for `canonical_identity` read the row with
  `IdentityStore.get_by_provider(user_id, channel)` (`email` column, or `provider_user_id` for msteams). Failure to
  read the secondary identity is not fatal (`canonical_identity=None`).
- DB errors → log + `None` (fail closed), never raise into a channel handler.

---

## Implementation Blueprint

> Executor-ready starting point. Write each block to its declared path, then complete every
> `# FILL IN:` marker. Business branches, edge cases and test bodies are stubs by design.
> Never change a signature, class name or file path the blueprint fixes.

### Steps (in order)
1. Write the resolver (block) — *why*: U1 principal resolution on the server.
2. Tests with a stubbed `IdentityStore`.

### `packages/ai-parrot-server/src/parrot/services/identity_principal.py` (CREATE)
```python
"""IdentityPrincipalResolver — (channel, channel_user_id) → Navigator principal (FEAT-773 M8)."""
from __future__ import annotations

import logging
from typing import Any, Optional

from parrot.auth.principal import Principal


class IdentityPrincipalResolver:
    """web → passthrough; other channels → auth.user_identities channel row; miss → None (fail closed)."""

    def __init__(self, db_pool: Any) -> None:
        self._db_pool = db_pool
        self.logger = logging.getLogger(__name__)

    def _store(self) -> Any:
        from navigator_auth.identity.store import IdentityStore
        return IdentityStore(self._db_pool)

    async def resolve(self, channel: str, channel_user_id: str) -> Optional[Principal]:
        """Return the bound principal or None."""
        if not channel or not channel_user_id:
            return None
        if channel == "web":
            return Principal(user_id=str(channel_user_id), channel="web", channel_user_id=str(channel_user_id))
        # FILL IN: nav = await store.find_user_by_provider_account(channel, channel_user_id); None → None;
        #          canonical = row.email.lower() or (row.provider_user_id for msteams) via get_by_provider (best effort);
        #          return Principal(user_id=str(nav), canonical_identity=canonical, channel=channel,
        #          channel_user_id=str(channel_user_id)); any exception → logger.warning + None
        raise NotImplementedError
```

### FILL IN checklist
- [ ] non-web branch; bounded by U3 (fail closed)
- [ ] `test_identity_principal_resolver`

---

## Acceptance Criteria

- [ ] Web ids pass through; a linked telegram id resolves to its Navigator id; an unlinked one returns `None`
- [ ] DB errors return `None` (logged), never raise

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/unit/test_identity_principal_resolver.py -q`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/unit/test_identity_principal_resolver.py
@pytest.mark.asyncio
async def test_identity_principal_resolver(monkeypatch): ...   # stub IdentityStore: telegram 88123 → 1042; unknown → None; web passthrough
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
