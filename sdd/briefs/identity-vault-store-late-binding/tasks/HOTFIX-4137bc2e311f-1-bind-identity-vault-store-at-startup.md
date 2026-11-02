# HOTFIX-4137bc2e311f-1: Bind IdentityVaultCredentialStore onto OAuth2 managers at startup

**Feature**: issue:4137bc2e311f — Identity Vault credential store is never bound
**Spec**: `sdd/briefs/identity-vault-store-late-binding.brief.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context
OAuth2 managers freeze their durable `CredentialStore` at construction
(`packages/ai-parrot/src/parrot/auth/oauth2_base.py:267`), before navigator-auth publishes
`app["authdb"]` in `on_startup`. Every server-wired manager therefore falls back to
`VaultUtilsCredentialStore`. The startup hook `BotManager._register_oauth2_providers`
(`packages/ai-parrot-server/src/parrot/manager/manager.py:2950`) sees `authdb` but never binds a store.

## Scope
1. `oauth2_base.py`:
   - In `__init__`, set `self._store_is_default: bool = credential_store is None` next to line 267.
   - Add public `bind_credential_store(self, store: CredentialStore, *, force: bool = False) -> bool`:
     replaces `self._store` only when `force` or `self._store_is_default`; on replace sets
     `_store_is_default = False`, logs at INFO (provider_id + store class), returns `True`; else `False`.
     Google-style docstring explaining it exists for late binding after app startup.
2. `manager.py` `_register_oauth2_providers`: inside the existing `if authdb is not None:` block,
   build ONE `IdentityVaultCredentialStore(authdb)` and call `bind_credential_store()` on
   `app.get("jira_oauth_manager")` and on every value whose key starts with `"oauth2_manager_"`
   (dedupe by `id()`; skip objects lacking `bind_credential_store`). Do this BEFORE
   `self._register_descriptor_oauth2_providers(app)`. When `authdb is None`, log INFO that the
   Identity Vault is unavailable and managers keep the default store.
3. Tests (new files):
   - `packages/ai-parrot/tests/auth/test_oauth2_store_binding.py`: default store → bind returns True and
     swaps; explicit store → bind returns False and keeps; `force=True` swaps an explicit store.
     Use a minimal concrete `AbstractOAuth2Manager` subclass or an existing one (e.g. `JiraOAuthManager`)
     constructed without an app.
   - `packages/ai-parrot-server/tests/manager/test_oauth2_identity_store_binding.py`: an
     `web.Application` with `app["authdb"] = object()`, a default-store Jira manager in
     `app["jira_oauth_manager"]`, an O365-like manager in `app["oauth2_manager_o365"]`, and one manager
     with an explicit store; `await BotManager._register_oauth2_providers(bm, app)` (build `bm` via
     `BotManager.__new__` + a `logger`) → first two are `IdentityVaultCredentialStore`, explicit one
     unchanged; with no `authdb` → stores unchanged. Patch `register_oauth2_provider` /
     `set_principal_resolver` if they need real backends.
4. `docs/auth/connections.md` § "Durable owner": one sentence that the store is bound at app startup
   once navigator-auth's `authdb` exists, and pre-existing generic-vault grants are not migrated.

**NOT in scope**: changing root `app.py` (it benefits automatically via `app["jira_oauth_manager"]`);
lazy resolution inside core; migrating existing vault tokens; descriptor provider wiring (already correct).

## Files to Create / Modify
| File | Action |
|---|---|
| `packages/ai-parrot/src/parrot/auth/oauth2_base.py` | modify |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | modify |
| `packages/ai-parrot/tests/auth/test_oauth2_store_binding.py` | create |
| `packages/ai-parrot-server/tests/manager/test_oauth2_identity_store_binding.py` | create |
| `docs/auth/connections.md` | modify |

## Codebase Contract
### Verified Imports
- `from parrot.services.identity_credential_sink import IdentityVaultCredentialStore` (manager.py:2928)
### Existing Signatures
- `AbstractOAuth2Manager.__init__(..., credential_store: Optional[CredentialStore] = None, ...)` — oauth2_base.py:235; store assigned at :267
- `IdentityVaultCredentialStore.__init__(self, db_pool: Any, cipher: Optional[Any] = None)` — identity_credential_sink.py:74
- `async def BotManager._register_oauth2_providers(self, app: web.Application) -> None` — manager.py:2950; `authdb` block at :2980-2985
### Does NOT Exist
- `AbstractOAuth2Manager.bind_credential_store` / `_store_is_default` (this task adds them)
- Any lazy `app["authdb"]` lookup in core `parrot.auth`

## Acceptance Criteria
- After startup with `app["authdb"]` set, default-store managers use `IdentityVaultCredentialStore`.
- Explicitly supplied stores are never replaced (unless `force=True`).
- Without `authdb`, behavior is unchanged.
- Both new test files pass; `ruff check` clean on touched files.

## Validation Commands
```bash
PYTHONPATH=$PWD/packages/ai-parrot/src:$PWD/packages/ai-parrot-server/src pytest packages/ai-parrot/tests/auth/test_oauth2_store_binding.py -q
PYTHONPATH=$PWD/packages/ai-parrot/src:$PWD/packages/ai-parrot-server/src pytest packages/ai-parrot-server/tests/manager/test_oauth2_identity_store_binding.py -q
ruff check packages/ai-parrot/src/parrot/auth/oauth2_base.py packages/ai-parrot-server/src/parrot/manager/manager.py
```

## Completion Note
Implemented `bind_credential_store()` + `_store_is_default` in oauth2_base.py; `_register_oauth2_providers` binds one `IdentityVaultCredentialStore(authdb)` onto jira/oauth2_manager_* default-store managers (INFO log when authdb absent). 5 new tests pass; ruff clean. Implemented directly (no coder seats).
