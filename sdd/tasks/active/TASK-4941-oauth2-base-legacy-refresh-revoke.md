# TASK-4941: AbstractOAuth2Manager: legacy-key migration, typed refresh outcomes, revoke + events

**Feature**: FEAT-773 — Delegated Auth Connections — S-1 Connections Core
**Spec**: `sdd/specs/delegated-auth-connections.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4940
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (second half), S7, AC-10, AC-12, AC-13, AC-20. With keys now principal-scoped (TASK-4940), the
manager must (a) migrate legacy channel-scoped keys on first use — read once, rewrite under the principal, delete —
and stop reading them after `OAUTH2_LEGACY_KEYS_UNTIL`; (b) classify refresh failures: `InvalidGrantError` →
delete the grant + `connection.refresh_failed`, `RefreshTransientError` → keep the grant, no event; (c) revoke
with a best-effort `_revoke_remote` hook then local delete then `connection.revoked`. Refresh, revoke and the
cold-cache fill must never resurrect a grant that was replaced or deleted concurrently.

---

## Scope

- conf.py: `OAUTH2_LEGACY_KEYS_UNTIL` (ISO date/datetime string or empty → window open) and `OAUTH2_PROVIDERS_FILE`.
- `get_valid_token(channel, user_id, *, channel_user_id=None)`: cache → store (re-fill cache under the lock with a
  re-read) → `_read_legacy_token(channel, channel_user_id or user_id, user_id)` (only before the cutover) → expiry →
  refresh. Signature stays compatible (new kw-only arg).
- `_read_legacy_token`: read `oauth2:{p}:{channel}:{channel_user_id}` and the legacy vault name; rewrite with
  `_persist_token(..., minted=False)` under `principal_lock`; delete both legacy copies; at most once.
- `_refresh_tokens`: single flight on `principal_lock`; re-read store + cache after acquiring; abort (return
  `None`) if the grant was deleted or the `account_id` changed meanwhile; map `aiohttp.ClientError` →
  `RefreshTransientError`; on `InvalidGrantError` delete grant (store + cache, no nested lock) and publish
  `connection.refresh_failed` (reason = error class name), then re-raise; any `refresh_token` in the response replaces
  the stored one (AC-20).
- `revoke(channel, user_id, *, channel_user_id=None)` under `principal_lock`: `_revoke_remote(token)` best effort →
  store.delete → cache delete → legacy deletes → publish `connection.revoked` after the lock.
- `_revoke_remote(token_set)` default no-op hook.
- Tests: `test_legacy_key_read_rewrite_delete`, `test_refresh_invalid_grant_revokes_and_emits`,
  `test_refresh_transient_keeps_grant`, `test_concurrent_refresh_single_flight`, `test_revoke_calls_remote_then_local_then_event`.

**NOT in scope**: O365 error parsing (TASK-4942); descriptor-driven revoke URL (TASK-4943); Jira legacy prefix `jira:oauth:*` (TASK-4954).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/oauth2_base.py` | MODIFY | legacy migration, typed refresh, revoke hook/events |
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | OAUTH2_LEGACY_KEYS_UNTIL, OAUTH2_PROVIDERS_FILE |
| `packages/ai-parrot/tests/unit/auth/test_oauth2_refresh_legacy.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` @ `a848d5a73e` (2026-10-30) while writing this task.
> Use these exact imports and signatures. Anything not listed: VERIFY it exists before using it.

### Verified Imports
```python
from parrot.auth.oauth2_base import (CredentialPersistenceError, InvalidGrantError, RefreshTransientError,
                                     _LEGACY_TOKEN_KEY_TEMPLATE, _LEGACY_VAULT_NAME_TEMPLATE)   # created by TASK-4940
from parrot.security.vault_utils import retrieve_vault_credential, delete_vault_credential     # verified: :145, :184
from navconfig import config                                                                   # verified: conf.py:6
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/oauth2_base.py (verified @ a848d5a73e)
_TOKEN_KEY_TEMPLATE = "oauth2:{provider}:{channel}:{user_id}"                 # :39
_NONCE_KEY_TEMPLATE = "oauth2:{provider}:nonce:{nonce}"                       # :40
_LOCK_KEY_TEMPLATE = "lock:oauth2:{provider}:refresh:{channel}:{user_id}"     # :41
_VAULT_NAME_TEMPLATE = "oauth2_{provider}_{channel}_{user_id}"                # :44
_TOKEN_TTL_SECONDS (:47) _NONCE_TTL_SECONDS (:48) _REFRESH_LOCK_TIMEOUT = 10 (:49) _REFRESH_LOCK_BLOCKING_TIMEOUT = 5 (:50)
VaultWriter / VaultReader / VaultDeleter type aliases                        # :56-58
class AbstractOAuth2TokenSet(BaseModel)  # :61 access_token, refresh_token="", expires_at=0.0, scopes, granted_at,
                                          #     last_refreshed_at, account_id="", display_name="", email; is_expired (:82)
class AbstractOAuth2Manager(ABC):                                             # :89
    provider_id / authorization_url / token_url / default_scopes / token_set_cls (ClassVar) ; use_pkce (:116) ; require_client_secret
    def __init__(self, client_id, redirect_uri, *, client_secret=None, app=None, redis_url=None, redis_client=None,
                 scopes=None, http_session=None, vault_writer=None, vault_reader=None, vault_deleter=None,
                 callback_path=None)                                          # :120-134 ; vault defaults :172-182
    def setup(self) -> None                                                   # :186
    def _token_key(self, channel, user_id) -> str                             # :251
    def _nonce_key(self, nonce) -> str                                        # :256
    def _lock_key(self, channel, user_id) -> str                              # :259
    def _vault_name(self, channel, user_id) -> str                            # :264
    async def _get_session(self) -> aiohttp.ClientSession                     # :271
    async def create_authorization_url(self, channel, user_id, extra_state=None) -> Tuple[str, str]   # :298
    def authorization_url_extra_params(self) -> Dict[str, str]              # :345
    async def handle_callback(self, code, state) -> Tuple[AbstractOAuth2TokenSet, Dict[str, Any]]    # :354
    async def _persist_token(self, channel, user_id, token_set) -> None       # :409 (vault failure swallowed :415-420)
    async def _read_token_from_cache(self, channel, user_id)                  # :429
    async def _read_token_from_vault(self, channel, user_id)                  # :443
    async def get_valid_token(self, channel, user_id)                         # :461
    async def is_connected(self, channel, user_id) -> bool                    # :493
    async def revoke(self, channel: str, user_id: str) -> None                # :497
    async def _refresh_tokens(self, channel, user_id, token_set)              # :507 (lock :519; except PermissionError → revoke;
                                                                              #       except aiohttp.ClientError as exc: at :550)
    @abstractmethod _exchange_code (:578) / _refresh_request (:594) / _discover_identity (:603) / _build_token_set (:612)

# After TASK-4940 (same file): principal_lock(user_id) (async CM), _persist_token(principal, token_set, *, minted,
#   state_payload=None), _read_token_from_cache(user_id), _read_token_from_store(user_id), _publish(kind, principal,
#   token_set, *, reason=None), self._store: CredentialStore, self._events
# packages/ai-parrot/src/parrot/conf.py
JIRA_REDIRECT_URI = config.get("JIRA_REDIRECT_URI")                         # :746 (anchor)
```

### Does NOT Exist
- ~~`parrot.conf.OAUTH2_LEGACY_KEYS_UNTIL`~~, ~~`OAUTH2_PROVIDERS_FILE`~~ — added by this task.
- ~~`AbstractOAuth2Manager._revoke_remote`~~ — added by this task.
- ~~`fakeredis`~~ — not installed; use `_oauth2_fakes.MemRedis`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/auth/oauth2_base.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/conf.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/auth/test_oauth2_refresh_legacy.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/oauth2_base.py#AbstractOAuth2Manager.get_valid_token",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2_base.py#AbstractOAuth2Manager.revoke",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2_base.py#AbstractOAuth2Manager._refresh_tokens"
  ]
}
```

---

## Implementation Notes

- Read `OAUTH2_LEGACY_KEYS_UNTIL` through a small helper `_legacy_window_open(now=None) -> bool` so tests can
  patch it; parse with `datetime.fromisoformat`; unset/empty → open; unparsable → log error once, treat as closed.
- Legacy resurrection guard (AC-12/13): `revoke` deletes legacy keys for `channel_user_id` and `user_id`, and the
  legacy read happens only inside `principal_lock` after re-checking the principal key is still absent.
- O365's legacy keys were already `oauth2:o365:web:{nav_user_id}` → with `channel_user_id == user_id` the rewrite is a rename.
- Never log or raise with token values; `reason` on `refresh_failed` is an error class name only.

---

## Implementation Blueprint

> Executor-ready starting point. Write each block to its declared path, then complete every
> `# FILL IN:` marker. Business branches, edge cases and test bodies are stubs by design.
> Never change a signature, class name or file path the blueprint fixes.

### Steps (in order)
1. Add the two conf keys after the anchor — *why*: AC-13 window + TASK-4943/4957 descriptor file.
2. Rewrite `get_valid_token` + add `_read_legacy_token` (block A) — *why*: AC-13 read-once/rewrite/delete.
3. Rewrite `_refresh_tokens` (block B) — *why*: S7 typed outcomes + AC-12 no resurrection.
4. Rewrite `revoke` + add `_revoke_remote` (block C) — *why*: spec §3 M2 order remote → local → event.
5. Tests — *why*: spec §4 M2 rows.

### `packages/ai-parrot/src/parrot/conf.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'JIRA_REDIRECT_URI = config.get("JIRA_REDIRECT_URI")' conf.py)
# AFTER — insert below `JIRA_REDIRECT_URI = config.get("JIRA_REDIRECT_URI")` (verified: conf.py:746)
# FEAT-773: legacy channel-scoped OAuth2 keys are read (and migrated) only until this ISO date/datetime.
# Ops sets it to the S-1 prod deploy + 30 days; empty = window open.
OAUTH2_LEGACY_KEYS_UNTIL = config.get("OAUTH2_LEGACY_KEYS_UNTIL", fallback="")
# FEAT-773: YAML file of OAuth2ProviderDescriptor entries (client secrets come from OAUTH2_<PROVIDER>_*).
OAUTH2_PROVIDERS_FILE = config.get("OAUTH2_PROVIDERS_FILE", fallback="")
```

### `packages/ai-parrot/src/parrot/auth/oauth2_base.py` (MODIFY)

Block A — read path + legacy:
```python
# occurrences: 1 (verified: '    async def get_valid_token(' — line moves after TASK-4940; re-grep)
    async def get_valid_token(self, channel: str, user_id: str, *,
                              channel_user_id: Optional[str] = None) -> Optional[AbstractOAuth2TokenSet]:
        """``user_id`` is the principal. cache → store → legacy (window only) → refresh."""
        # FILL IN: token = cache; miss → async with principal_lock: re-read cache, else store → refill cache;
        #          still None and _legacy_window_open() → _read_legacy_token(channel, channel_user_id or user_id, user_id)
        #          None → return None; not expired → return; no refresh_token → revoke(...) and return None;
        #          else return await self._refresh_tokens(channel, user_id, token) — bounded by AC-12/AC-13
        raise NotImplementedError

    async def _read_legacy_token(self, channel: str, channel_user_id: str,
                                 user_id: str) -> Optional[AbstractOAuth2TokenSet]:
        """Read oauth2:{p}:{channel}:{channel_user_id} + legacy vault name, rewrite under user_id, delete legacy."""
        # FILL IN: no-op (return None) after the window; read Redis legacy key then retrieve_vault_credential(
        #          channel_user_id, _LEGACY_VAULT_NAME_TEMPLATE.format(...)) (KeyError → None); validate with
        #          token_set_cls; _persist_token(Principal(user_id=user_id, channel=channel,
        #          channel_user_id=channel_user_id), token, minted=False); then delete both legacy copies
        #          (delete failures logged). Caller holds principal_lock. — bounded by AC-13
        raise NotImplementedError
```

Block B — refresh:
```python
# occurrences: 1 (verified: '            except aiohttp.ClientError as exc:' oauth2_base.py:550 inside _refresh_tokens)
    async def _refresh_tokens(self, channel: str, user_id: str,
                              token_set: AbstractOAuth2TokenSet) -> Optional[AbstractOAuth2TokenSet]:
        """Single-flight refresh. InvalidGrantError → delete + refresh_failed; RefreshTransientError → keep."""
        principal = Principal(user_id=user_id, channel=channel, channel_user_id=user_id)
        try:
            async with self.principal_lock(user_id):
                current = await self._read_token_from_cache(user_id) or await self._read_token_from_store(user_id)
                # FILL IN: current None (deleted meanwhile) → return None; current.account_id != token_set.account_id
                #          → return current if not expired else None (replaced meanwhile); current not expired → return it
                try:
                    payload = await self._refresh_request(current.refresh_token)
                except aiohttp.ClientError as exc:
                    raise RefreshTransientError(f"{self.provider_id} refresh network error") from exc
                except InvalidGrantError:
                    # FILL IN: await self._store.delete(user_id, self.provider_id) (errors logged) +
                    #          await self.redis.delete(self._token_key(user_id)); set a flag to publish after the lock
                    raise
                # FILL IN: build `refreshed` like today (:554-566) but ALWAYS take payload["refresh_token"] when present
                #          (AC-20); await self._persist_token(principal, refreshed, minted=False); return refreshed
        except InvalidGrantError:
            await self._publish("connection.refresh_failed", principal, token_set, reason="InvalidGrantError")
            raise
```

Block C — revoke:
```python
# occurrences: 1 (verified: '    async def revoke(self, channel: str, user_id: str) -> None:' oauth2_base.py:497)
    async def revoke(self, channel: str, user_id: str, *, channel_user_id: Optional[str] = None) -> None:
        """_revoke_remote (best effort) → store.delete → cache delete → legacy deletes → connection.revoked."""
        # FILL IN: async with principal_lock: token = cache or store; if token: try await self._revoke_remote(token)
        #          except Exception → logger.warning (type name only); await self._store.delete(...) (raise
        #          CredentialPersistenceError on failure — disconnect must not silently leave a grant);
        #          redis.delete(principal key, legacy key(s) for channel_user_id and user_id); legacy vault delete
        #          best effort. After the lock: publish connection.revoked when a token existed — bounded by AC-12
        raise NotImplementedError

    async def _revoke_remote(self, token_set: AbstractOAuth2TokenSet) -> None:
        """Provider-side revocation hook. Default no-op; descriptor managers POST revoke_url."""
        return None
```
**Why this shape**: the spec skeleton fixes the names; the added `channel_user_id` keyword is the only way the
legacy key (keyed by the raw channel id) can be located once `user_id` is the principal. Publishing outside the
lock and never nesting the lock are the spec §3 M2 concurrency rules.

### FILL IN checklist
- [ ] `conf.py` — two keys (done in block)
- [ ] `oauth2_base.py::_legacy_window_open` helper — parse/patchable; bounded by AC-13
- [ ] `oauth2_base.py::get_valid_token` — locked cold fill + legacy + refresh; bounded by AC-12/13
- [ ] `oauth2_base.py::_read_legacy_token` — read/rewrite/delete once; bounded by AC-13
- [ ] `oauth2_base.py::_refresh_tokens` — re-read guards, typed errors, refresh-token replacement; bounded by AC-10/12/20
- [ ] `oauth2_base.py::revoke` — order + legacy delete + event; bounded by AC-12
- [ ] `test_oauth2_refresh_legacy.py` — five test bodies

---

## Acceptance Criteria

- [ ] AC-13: a legacy key is read once, rewritten under the principal and deleted; no legacy read after `OAUTH2_LEGACY_KEYS_UNTIL`
- [ ] AC-10: `InvalidGrantError` deletes the grant and publishes `connection.refresh_failed`; `RefreshTransientError` keeps the grant and publishes nothing
- [ ] Two concurrent refreshers make one token-endpoint call; the rotated refresh token is persisted once
- [ ] AC-12: a refresh racing a revoke/replacement never restores the previous grant
- [ ] AC-20: a `refresh_token` in a refresh response always replaces the stored one
- [ ] `revoke` calls `_revoke_remote`, deletes locally (store, cache, legacy) then publishes `connection.revoked`

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/auth/test_oauth2_refresh_legacy.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/auth/test_oauth2_refresh_legacy.py  (fakes: ._oauth2_fakes from TASK-4940)
import asyncio, json, time
import pytest
from parrot.auth.oauth2_base import InvalidGrantError, RefreshTransientError

@pytest.mark.asyncio
async def test_legacy_key_read_rewrite_delete(): ...          # FILL IN: seed oauth2:fake:telegram:88123 → get_valid_token(
                                                              #   "telegram","1042", channel_user_id="88123") returns it, principal
                                                              #   key exists, legacy key gone; patch window closed → None
@pytest.mark.asyncio
async def test_refresh_invalid_grant_revokes_and_emits(): ... # FILL IN: refresh_result=InvalidGrantError() → raises; store+cache empty;
                                                              #   publisher saw connection.refresh_failed
@pytest.mark.asyncio
async def test_refresh_transient_keeps_grant(): ...           # FILL IN: refresh_result=RefreshTransientError() → raises; grant kept; no event
@pytest.mark.asyncio
async def test_concurrent_refresh_single_flight(): ...        # FILL IN: asyncio.gather two get_valid_token on an expired token;
                                                              #   FakeManager counts _refresh_request calls == 1
@pytest.mark.asyncio
async def test_revoke_calls_remote_then_local_then_event(): ... # FILL IN: record order remote → store.delete → event
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
