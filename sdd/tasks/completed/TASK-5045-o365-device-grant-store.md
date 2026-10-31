# TASK-5045: O365 device-code grants on the shared principal store (`store_device_grant`, legacy conversion)

**Feature**: FEAT-777 — Connections — Web + Slack
**Spec**: `sdd/specs/connections-web-slack.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5035
**Assigned-to**: unassigned

---

## Context

Spec §2 "O365 consolidation (M3, D3)", §3 Module 3 and the "Legacy conversion and ordering (M3)" block;
AC-8, AC-15. O365 3LO already persists through S-1's durable-first `_persist_token` on
`O365OAuthManager(AbstractOAuth2Manager)`. The device-code resolver still owns a second store
(`VaultTokenSync` `o365:*`). This task gives the manager the two public entry points the resolver
(TASK-5046) will call instead:

- `store_device_grant(principal, payload, *, channel)` — a fresh MSAL / token-endpoint response
  (relative `expires_in`) becomes one principal-keyed `O365TokenSet(grant_origin="device_code")`.
- `migrate_legacy_device_grant(principal, legacy, *, channel)` — a stored legacy `o365:*` dict
  (absolute `expires_at`) is converted without ever pretending it is a fresh response.

It also makes `grant_origin` survive the Identity Vault round trip: the S-1 store only keeps
whitelisted metadata keys (`identity_credential_sink.py:18`), so without the change below
`grant_origin` is silently dropped on every reload.

---

## Scope

- When `store_device_grant` / `migrate_legacy_device_grant` upsert the `users_integrations` row, set
  `grant_origin="device_code"` on it (field added by TASK-5035 to `UsersIntegrationRow`); the 3LO callback path leaves it
  `"authorization_code"` via the token set — *why*: the panel and T27's e2e test read it from `GET /api/v1/connections`.
- Add `grant_origin: Literal["authorization_code", "device_code"] = "authorization_code"` to `O365TokenSet`.
- Add `O365OAuthManager.store_device_grant(...)`: discover identity, build the token set, durable-first
  `_persist_token(..., minted=True)` under `principal_lock`, upsert the `users_integrations` row via
  `IntegrationsService().persist_credential(...)`, publish `connection.completed` once.
- Add `O365OAuthManager.migrate_legacy_device_grant(...)` implementing every rule of spec §3 M3
  "Legacy conversion and ordering".
- Add a revoke tombstone so a disconnected principal's legacy grant can never be re-imported:
  override `revoke(...)` to set `oauth2:o365:legacy_revoked:{user_id}` and expose
  `legacy_migration_allowed(user_id) -> bool`.
- Add `"grant_origin"` (and `"tenant_id"`, `"user_principal_name"`) to `_METADATA_KEYS` in
  `identity_credential_sink.py` so the fields round-trip.
- Create `packages/ai-parrot/tests/auth/test_o365_device_grant.py` with the M3 manager tests (NOT in `tests/auth/test_o365_oauth.py`: its module-level
  `pytest.importorskip("fakeredis")` (:17) skips the whole module locally, so appended tests would never run).

**NOT in scope**: the device-code resolver and broker factory (TASK-5046); O365 provider registration and
WorkIQ (TASK-5047); a `grant_origin` column on `UsersIntegrationRow`/`IntegrationDescriptor` (owned by the
models task — see Completion Note instruction below); any change to `AbstractOAuth2Manager` (S-1 base).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/o365_oauth.py` | MODIFY | `grant_origin`, `store_device_grant`, `migrate_legacy_device_grant`, revoke tombstone |
| `packages/ai-parrot-server/src/parrot/services/identity_credential_sink.py` | MODIFY | keep `grant_origin`, `tenant_id`, `user_principal_name` in `auth_data` |
| `packages/ai-parrot/tests/auth/test_o365_device_grant.py` | CREATE | M3 manager tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.oauth2_base import (                     # verified: o365_oauth.py:23-28 (already imported)
    AbstractOAuth2Manager, AbstractOAuth2TokenSet, InvalidGrantError, RefreshTransientError,
)
from parrot.auth.oauth2_base import CredentialPersistenceError   # verified: oauth2_base.py:100
from parrot.auth.principal import Principal                      # verified: principal.py:18
from parrot.auth.o365_oauth import O365OAuthManager, O365TokenSet # verified: o365_oauth.py:60, :49
from parrot.auth.oauth2.service import IntegrationsService       # verified: service.py (persist_credential :403) — import lazily inside the method (service imports the registry; avoid a cycle)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/o365_oauth.py
class O365TokenSet(AbstractOAuth2TokenSet):                     # :49
    tenant_id: str = ""; user_principal_name: str = ""; id_token: Optional[str] = None   # :55-57
class O365OAuthManager(AbstractOAuth2Manager):                  # :60
    provider_id = "o365" (:70); token_set_cls = O365TokenSet (:72)
    def __init__(self, client_id, client_secret, redirect_uri, *, tenant_id="common", **kwargs)  # :78
    async def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]   # :184 — raises InvalidGrantError / RefreshTransientError / RuntimeError
    async def _discover_identity(self, access_token: str) -> Dict[str, Any]       # :207 — GET Graph /me; raises ValueError on non-200
    def _build_token_set(self, token_response, identity) -> O365TokenSet          # :223-244 (LAST method of the file); uses expires_in, default 3600

# packages/ai-parrot/src/parrot/auth/oauth2_base.py
class AbstractOAuth2TokenSet(BaseModel):                        # :165
    access_token; refresh_token=""; expires_at: float = 0.0; scopes; granted_at; last_refreshed_at; account_id; display_name; email
    _EXPIRY_LEEWAY_SECONDS: ClassVar[int] = 60                   # :183
    @property is_expired -> bool                                 # :186 (expires_at falsy → False!)
class AbstractOAuth2Manager:
    self.redis (set in __init__ :259 / _on_startup); self._store (:267); self._events (:268); self.logger
    async def principal_lock(self, user_id: str)   # :351 asynccontextmanager — NEVER nest
    async def _publish(self, kind, principal, token_set, *, reason=None, state_payload=None)  # :551
    async def _persist_token(self, principal, token_set, *, minted: bool, state_payload=None)  # :581 — durable save then Redis; raises CredentialPersistenceError
    async def _read_token_from_cache(self, user_id)  # :614
    async def _read_token_from_store(self, user_id)  # :626
    async def revoke(self, channel: str, user_id: str, *, channel_user_id: Optional[str] = None) -> None  # :743 — takes principal_lock itself
    handle_callback(...)  # :465 — pattern: persist under principal_lock (:521-522), then _publish("connection.completed", ...) (:524)

# packages/ai-parrot/src/parrot/auth/oauth2/service.py
async def persist_credential(self, user_id, provider_id, token_set, *, channel: str, canonical_identity=None) -> UsersIntegrationRow  # :403
#   (the 3LO callback calls it after handle_callback: auth/oauth2_routes.py:175, :307)

# packages/ai-parrot-server/src/parrot/services/identity_credential_sink.py
_METADATA_KEYS = frozenset({"account_id", "display_name", "email", "cloud_id", "site_url", "scopes_granted"})  # :18
def _metadata(payload) -> Dict[str, Any]   # :39 — only _METADATA_KEYS survive into auth_data
IdentityVaultCredentialStore.load (:79-100) merges _metadata(auth_data) back into the payload
```

### Does NOT Exist
- ~~`O365TokenSet.grant_origin`~~, ~~`store_device_grant`~~, ~~`migrate_legacy_device_grant`~~, ~~`legacy_migration_allowed`~~ — created here.
- ~~A "generation" counter / generation check on `AbstractOAuth2Manager`~~ — S-1 shipped only `principal_lock` (`oauth2_base.py:351`). Spec §3 M3 says "S-1's ... generation checks": implement the guarantee with `principal_lock` + "a current record wins" + the revoke tombstone instead.
- ~~An `upsert_users_integration` call inside `AbstractOAuth2Manager`~~ — the row is written by `IntegrationsService.persist_credential` (the 3LO routes call it after the callback).
- ~~`O365OAuthManager.revoke`~~ — not overridden today; the base implementation is used.
- ~~`fakeredis` in the venv~~ — `tests/auth/test_o365_oauth.py:17` uses `pytest.importorskip("fakeredis")`, so this module is SKIPPED locally. New tests must not depend on fakeredis: use an in-memory async Redis double (get/set/delete/lock) in the test file.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/auth/o365_oauth.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/src/parrot/services/identity_credential_sink.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/auth/test_o365_device_grant.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/o365_oauth.py#O365TokenSet",
    "sym:packages/ai-parrot/src/parrot/auth/o365_oauth.py#O365OAuthManager",
    "sym:packages/ai-parrot/src/parrot/auth/o365_oauth.py#O365OAuthManager._build_token_set",
    "sym:packages/ai-parrot/src/parrot/auth/o365_oauth.py#O365OAuthManager.refresh_access_token",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2_base.py#AbstractOAuth2Manager._persist_token",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2_base.py#AbstractOAuth2Manager.principal_lock",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2_base.py#AbstractOAuth2Manager.revoke",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/service.py#IntegrationsService.persist_credential",
    "sym:packages/ai-parrot-server/src/parrot/services/identity_credential_sink.py#_metadata"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Durable first: every write goes through `_persist_token` (store → Redis). A store failure raises
  `CredentialPersistenceError` and leaves no Redis key (AC-15, `test_o365_store_device_grant_durable_first`).
- Hold `principal_lock(principal.user_id)` around read-current → persist. Never call `revoke()` or
  `get_valid_token()` while holding it (both take the same lock; the lock is not re-entrant).
- Publish `connection.completed` exactly once per successful persist, after releasing the lock
  (same order as `handle_callback`). Migration of an already-current record publishes nothing.
- No token material in logs or exceptions (S-1 S7).

### References in Codebase
- `oauth2_base.py:465-537` `handle_callback` — persist-under-lock then publish.
- `oauth2_base.py:819-876` `_refresh_tokens` — how a refresh keeps the old refresh token when the provider omits one.

---

## Implementation Blueprint

### Steps (in order)
1. Add `grant_origin` to `O365TokenSet` — *why*: AC-8 requires one record type for both grants, distinguishable for display/audit.
2. Add the module constant `_LEGACY_REVOKED_KEY` and the three new methods after `_build_token_set` — *why*: TASK-5046 calls them by these exact names.
3. Override `revoke` — *why*: after a disconnect, a still-present legacy `o365:*` entry must not resurrect the account (AC-15).
4. Extend `_METADATA_KEYS` — *why*: otherwise `IdentityVaultCredentialStore.load` drops `grant_origin` and every reload reports `authorization_code`.
5. Write the tests with an in-memory Redis/store double and run them.

### `packages/ai-parrot/src/parrot/auth/o365_oauth.py` (MODIFY — token set)
```python
# occurrences: 1 (verified: grep -c 'class O365TokenSet(AbstractOAuth2TokenSet):' packages/ai-parrot/src/parrot/auth/o365_oauth.py)
# AFTER — insert below `    id_token: Optional[str] = None` inside `class O365TokenSet(AbstractOAuth2TokenSet):` (verified: o365_oauth.py:57)
    grant_origin: Literal["authorization_code", "device_code"] = "authorization_code"

# imports: extend `from typing import Any, ClassVar, Dict, List, Optional` (:18) with `Literal`;
# add below the oauth2_base import block (:23-28):
from parrot.auth.oauth2_base import CredentialPersistenceError  # noqa: F401  (re-raised, documented)
from parrot.auth.principal import Principal

# module constant, below `logger = logging.getLogger(__name__)` (:30):
_LEGACY_REVOKED_KEY = "oauth2:o365:legacy_revoked:{user_id}"
_LEGACY_REVOKED_TTL_SECONDS = 400 * 24 * 60 * 60   # outlives any OAUTH2_LEGACY_KEYS_UNTIL window
```
**Why**: the default keeps every existing 3LO record valid without migration.

### `packages/ai-parrot/src/parrot/auth/o365_oauth.py` (MODIFY — new methods)
```python
# occurrences: 1 (verified: grep -c '    def _build_token_set(' packages/ai-parrot/src/parrot/auth/o365_oauth.py)
# AFTER — append below the end of `_build_token_set` (the last method; file ends at :244)

    # ------------------------------------------------------------------ device code (FEAT-777 M3)

    async def store_device_grant(
        self, principal: Principal, payload: Dict[str, Any], *, channel: str,
    ) -> O365TokenSet:
        """Persist a freshly minted device-code token response as the principal's single O365 record.

        Raises:
            CredentialPersistenceError: durable write failed (no Redis key is written).
            ValueError: identity discovery failed or ``payload`` has no access token.
        """
        if not payload.get("access_token"):
            raise ValueError("Device-code payload carries no access_token")
        identity = await self._discover_identity(payload["access_token"])
        token_set = self._build_token_set(payload, identity).model_copy(update={"grant_origin": "device_code"})
        async with self.principal_lock(principal.user_id):
            await self._persist_token(principal, token_set, minted=True)
        await self._upsert_row(principal, token_set, channel=channel)
        await self._publish("connection.completed", principal, token_set)
        self.logger.info("Stored o365 device-code grant for principal %s", principal.user_id)
        return token_set

    async def migrate_legacy_device_grant(
        self, principal: Principal, legacy: Dict[str, Any], *, channel: str,
    ) -> Optional[O365TokenSet]:
        """Convert one legacy ``o365:*`` dict (absolute ``expires_at``); ``None`` when a current record already wins.

        Raises:
            InvalidGrantError: legacy refresh token is dead (caller falls back to the device flow; legacy kept).
            RefreshTransientError: transient refresh/discovery failure (retryable; legacy kept).
            CredentialPersistenceError: durable write failed (legacy kept).
        """
        # FILL IN: parse legacy["expires_at"] as an absolute epoch (float); never synthesize a lifetime — bounded by spec §3 M3 legacy rules, AC-15
        # FILL IN: usable token = access_token present AND expires_at valid AND expires_at > now + O365TokenSet._EXPIRY_LEEWAY_SECONDS → keep expires_at EXACTLY
        # FILL IN: otherwise refresh with legacy["refresh_token"] via self.refresh_access_token BEFORE _discover_identity;
        #          new expires_at = now + expires_in from the refresh response; keep the old refresh token only when the response omits one;
        #          no refresh token → raise InvalidGrantError (needs-auth); RefreshTransientError propagates unchanged
        # FILL IN: _discover_identity(usable access token); wrap aiohttp/ValueError into RefreshTransientError (retryable, legacy preserved)
        # FILL IN: build O365TokenSet(grant_origin="device_code", scopes from legacy["scope"].split(), id_token, tenant_id from legacy or self.tenant_id)
        async with self.principal_lock(principal.user_id):
            current = await self._read_token_from_cache(principal.user_id) or await self._read_token_from_store(principal.user_id)
            if current is not None or not await self.legacy_migration_allowed(principal.user_id):
                return None  # a newer grant or a disconnect wins; never overwrite / resurrect
            await self._persist_token(principal, token_set, minted=True)  # noqa: F821 — token_set built in the FILL IN above
        await self._upsert_row(principal, token_set, channel=channel)
        await self._publish("connection.completed", principal, token_set)
        return token_set

    async def legacy_migration_allowed(self, user_id: str) -> bool:
        """``False`` once the principal disconnected o365: its legacy grant must never be re-imported."""
        return not await self.redis.get(_LEGACY_REVOKED_KEY.format(user_id=user_id))

    async def revoke(self, channel: str, user_id: str, *, channel_user_id: Optional[str] = None) -> None:
        """Revoke as the base class does, then tombstone legacy migration for this principal."""
        await super().revoke(channel, user_id, channel_user_id=channel_user_id)
        await self.redis.set(_LEGACY_REVOKED_KEY.format(user_id=user_id), "1", ex=_LEGACY_REVOKED_TTL_SECONDS)

    async def _upsert_row(self, principal: Principal, token_set: O365TokenSet, *, channel: str) -> None:
        """Write the ``users_integrations`` row the 3LO routes write after ``handle_callback``."""
        from parrot.auth.oauth2.service import IntegrationsService  # lazy: service imports the registry

        await IntegrationsService().persist_credential(
            principal.user_id, self.provider_id, token_set,
            channel=channel, canonical_identity=principal.canonical_identity,
        )
```
**Why this shape**: signatures are fixed by spec §3 M3 (the spec's `-> O365TokenSet` for the migration is
widened to `Optional[...]` so "a current record already exists, it wins" is expressible without an exception —
record this in the Completion Note). The tombstone replaces the non-existent S-1 "generation check".
A 3LO reconnect after a disconnect must clear the tombstone? No — a fresh grant is a current record, which already
wins; the tombstone only blocks *legacy* import, so it is never cleared.

### `packages/ai-parrot-server/src/parrot/services/identity_credential_sink.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '_METADATA_KEYS = frozenset({"account_id", "display_name", "email", "cloud_id", "site_url", "scopes_granted"})' packages/ai-parrot-server/src/parrot/services/identity_credential_sink.py)
# REPLACE the line (verified: identity_credential_sink.py:18) with:
_METADATA_KEYS = frozenset(
    {
        "account_id", "display_name", "email", "cloud_id", "site_url", "scopes_granted",
        "grant_origin", "tenant_id", "user_principal_name",   # FEAT-777 M3: O365 fields must round-trip
    }
)
```
**Why**: non-secret identity metadata only; tokens stay in the encrypted columns.

### `packages/ai-parrot/tests/auth/test_o365_device_grant.py` (CREATE)
```python
"""FEAT-777 M3: O365 device-code grants on the principal store (no fakeredis)."""
import time
from unittest.mock import AsyncMock

import pytest

from parrot.auth.o365_oauth import O365OAuthManager, O365TokenSet
from parrot.auth.oauth2_base import CredentialPersistenceError, InvalidGrantError, RefreshTransientError
from parrot.auth.principal import Principal

# Build the manager with redis_client=_MemRedis() and credential_store=_MemStore().

class _MemRedis:
    """Async Redis double: get/set/delete + a no-op lock."""
    # FILL IN: get/set(ex=)/delete over a dict; lock(...) returning an object with async acquire()->True / release()


class _MemStore:
    """CredentialStore double recording saves; ``fail=True`` raises on save."""
    # FILL IN: load/save(user_id, provider, payload, *, minted, principal, state_payload)/delete


@pytest.mark.asyncio
async def test_o365_store_device_grant_durable_first(monkeypatch):
    """Store failure → CredentialPersistenceError and no Redis key; success → grant_origin == 'device_code'."""
    # FILL IN: monkeypatch _discover_identity and IntegrationsService.persist_credential (AsyncMock)


@pytest.mark.asyncio
async def test_devicecode_legacy_expiry_preserved(monkeypatch):
    """Usable legacy token keeps expires_at exactly; no default-hour extension; missing/invalid/near/expired refresh first."""


@pytest.mark.asyncio
async def test_devicecode_legacy_refresh_and_failure(monkeypatch):
    """Refresh rotates/keeps refresh token; transient/probe/persistence failure raises and persists nothing; invalid grant raises."""


@pytest.mark.asyncio
async def test_legacy_migration_current_record_and_revoke_win(monkeypatch):
    """Existing current record → None, nothing written, no event; after revoke() legacy_migration_allowed is False."""
```

### FILL IN checklist
- [ ] `migrate_legacy_device_grant` expiry parse + usable/refresh decision — bounded by spec §3 M3 legacy rules, AC-15
- [ ] refresh-before-probe and refresh-token retention — bounded by AC-15 ("rotated refresh token retained")
- [ ] error mapping (terminal vs transient) without token material — bounded by spec §3 M3, S-1 S7
- [ ] `_MemRedis` / `_MemStore` doubles — bounded by "no fakeredis" (Does NOT Exist)
- [ ] four tests — bounded by spec §4 rows `test_o365_store_device_grant_durable_first`, `test_devicecode_legacy_expiry_preserved`, `test_devicecode_legacy_refresh_and_failure`

---

## Acceptance Criteria

- [ ] `O365TokenSet().grant_origin == "authorization_code"`; device grants persist `"device_code"` and it survives `IdentityVaultCredentialStore.load` (AC-8).
- [ ] `store_device_grant` is durable-first, writes the `users_integrations` row with `channels=[channel]`, publishes one `connection.completed`.
- [ ] Legacy conversion follows every rule in spec §3 M3 "Legacy conversion and ordering" (AC-15).
- [ ] After `revoke()`, `legacy_migration_allowed(user_id)` is `False`.
- [ ] `ruff check packages/ai-parrot/src/parrot/auth/o365_oauth.py packages/ai-parrot-server/src/parrot/services/identity_credential_sink.py` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/auth/test_o365_device_grant.py -q`
- `pytest tests/auth/test_o365_oauth.py -q`
- `pytest packages/ai-parrot/tests/auth/test_o365_refresh.py -q`

---

## Test Specification

See the `packages/ai-parrot/tests/auth/test_o365_device_grant.py` block above. Cases per test:

| Test | Must assert |
|---|---|
| `test_o365_store_device_grant_durable_first` | `_MemStore(fail=True)` → `CredentialPersistenceError`, Redis key `oauth2:o365:<uid>` absent, no publish; success → store payload `grant_origin == "device_code"`, one `connection.completed` |
| `test_devicecode_legacy_expiry_preserved` | `expires_at = now+3600` → identical value persisted, `refresh_access_token` not called; `None` / `"abc"` / `now+30` / `now-10` → refresh called before `_discover_identity` |
| `test_devicecode_legacy_refresh_and_failure` | refresh response with new refresh token → stored; without → old kept; `RefreshTransientError` / `_discover_identity` failure / store failure → raises, nothing persisted; `InvalidGrantError` propagates |
| `test_legacy_migration_current_record_and_revoke_win` | pre-seeded current record → returns `None`, no save, no event; `revoke()` then `legacy_migration_allowed` → `False` |

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug connections-web-slack --feature-id FEAT-777`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/connections-web-slack.json`
4. **Verify the Codebase Contract** before writing ANY code; if anything changed, update the contract FIRST
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a fixed signature or path
7. **Verify** acceptance criteria — run the Validation Commands (with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`)
8. **Commit the code** — stage only the files listed above
9. **Close the task** with `scripts/sdd/close_task.sh TASK-5045 connections-web-slack verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker orchestrator; seats codex terra/sol/luna + native sonnet
**Date**: 2026-10-31
**Notes**: Implemented per task; merged and merge-tier validated (only red: 3 failures that also fail on origin/dev: test_o365_refresh x2, slack test_manager_payload_drives_identity_and_dm).

**Deviations from spec**: none | describe if any
