# TASK-4940: AbstractOAuth2Manager: CredentialStore, principal keys/binding, durable-first persistence

**Feature**: FEAT-773 — Delegated Auth Connections — S-1 Connections Core
**Spec**: `sdd/specs/delegated-auth-connections.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4937, TASK-4938
**Assigned-to**: unassigned

---

## Context

Spec §2 "Engine", §3 Module 2 (G1, G4, S1, S2). This is the first half of M2 (non-delegable — the live O365
path runs through this class). It changes the key layout to the principal, introduces the `CredentialStore`
Protocol that replaces the `vault_writer/reader/deleter` kwargs, binds the principal into the OAuth state and
verifies it at callback (fail closed), and makes persistence **durable first**: the store write must succeed
before Redis is written, otherwise `CredentialPersistenceError`. `connection.completed` is published after a
successful persist. The second half (legacy keys, typed refresh outcomes, revoke) is TASK-4941.

---

## Scope

- Replace the key templates: `_TOKEN_KEY_TEMPLATE = "oauth2:{provider}:{user_id}"`,
  `_LOCK_KEY_TEMPLATE = "lock:oauth2:{provider}:refresh:{user_id}"`; add `_LEGACY_TOKEN_KEY_TEMPLATE` and rename the
  vault template to `_LEGACY_VAULT_NAME_TEMPLATE` (read-only, used by TASK-4941); the principal vault name
  `oauth2_{provider}_{user_id}` is owned by `VaultUtilsCredentialStore`.
- Add `CredentialStore` (Protocol), `VaultUtilsCredentialStore` (default, over `vault_utils`), `CredentialPersistenceError`,
  `InvalidGrantError(PermissionError)`, `RefreshTransientError(RuntimeError)` (the two refresh errors are only
  *defined* here; TASK-4941 uses them).
- Constructor: drop `vault_writer/vault_reader/vault_deleter`; add `credential_store` and `event_publisher`.
- `_token_key(user_id)`, `_lock_key(user_id)` (channel dropped); delete `_vault_name`; add `principal_lock(user_id)`
  (async context manager over the Redis lock — the ONE lock shared by callback persistence, refresh, revoke and
  re-encryption; never nested).
- `create_authorization_url(channel, user_id, extra_state=None, *, principal=None)`: resolve the principal when not
  given (`resolve_principal(channel, user_id)`), `ValueError` when none; write `nav_user_id`, `channel`,
  `channel_user_id`, `canonical_identity`, `tenant_id` into the nonce payload (`user_id` keeps the caller's value).
- `handle_callback`: reject a payload without a numeric `nav_user_id` (`ValueError`, nothing written); exchange →
  identity → `_build_token_set` → `_post_exchange` hook (default identity) → `_persist_token(principal, …, minted=True)`
  under `principal_lock` → publish `connection.completed`.
- `_persist_token(principal, token_set, *, minted, state_payload=None)`: store first, Redis second.
- Read path keyed by principal (`_read_token_from_cache(user_id)`, `_read_token_from_store(user_id)`); keep
  `get_valid_token(channel, user_id)` working with the new keys (legacy read + typed refresh come in TASK-4941).
- Shared test fakes module + tests `test_manager_keys_are_principal_scoped`,
  `test_state_binds_principal_and_callback_verifies`, `test_persist_durable_first_then_redis`.
- Update `tests/auth/test_oauth2_base.py` to the new constructor/keys (it is skipped without `fakeredis`, but must stay correct).

**NOT in scope**: legacy-key migration, refresh error typing, `_revoke_remote`, revoke events, conf keys (TASK-4941); O365 changes (TASK-4942); the Identity Vault store (TASK-4950).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/oauth2_base.py` | MODIFY | store protocol, errors, principal keys/binding, durable-first persist |
| `packages/ai-parrot/tests/unit/auth/_oauth2_fakes.py` | CREATE | MemRedis, FakeCredentialStore, FakePrincipalResolver, FakeManager |
| `packages/ai-parrot/tests/unit/auth/test_oauth2_principal_keys.py` | CREATE | unit tests |
| `tests/auth/test_oauth2_base.py` | MODIFY | adapt to new constructor and keys |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` @ `a848d5a73e` (2026-10-30) while writing this task.
> Use these exact imports and signatures. Anything not listed: VERIFY it exists before using it.

### Verified Imports
```python
from parrot.auth.principal import Principal, resolve_principal                     # created by TASK-4937
from parrot.auth.oauth2.events import ConnectionEvent, ConnectionEventPublisher    # created by TASK-4938
from parrot.security.vault_utils import (store_vault_credential, retrieve_vault_credential,
                                         delete_vault_credential)                  # verified: vault_utils.py:92, :145, :184
from contextlib import asynccontextmanager
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

# packages/ai-parrot/src/parrot/security/vault_utils.py
async def store_vault_credential(user_id: str, vault_name: str, secret_params: Dict[str, Any]) -> None   # :92
async def retrieve_vault_credential(user_id: str, vault_name: str) -> Dict[str, Any]                    # :145 (KeyError when absent)
async def delete_vault_credential(user_id: str, vault_name: str) -> None                                # :184
def oauth2_vault_name(provider_id, channel, user_id) -> str                                              # :205 legacy name helper
```

### Does NOT Exist
- ~~`AbstractOAuth2Manager.credential_store` / `event_publisher` kwargs~~ — added by this task (today: vault_* kwargs).
- ~~`PermissionContext.nav_user_id`~~ — the Navigator id travels as `nav_user_id` in the OAuth **state** only.
- ~~`fakeredis`~~ — NOT installed; `tests/auth/test_oauth2_base.py` is `importorskip`ped. New tests use the
  `_oauth2_fakes.MemRedis` double created here (get/set(ex=)/delete/lock(name, timeout=, blocking_timeout=)/scan_iter).
- ~~`AbstractOAuth2Manager` provider-side revoke~~ — `_revoke_remote` arrives in TASK-4941.

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
      "path": "packages/ai-parrot/tests/unit/auth/_oauth2_fakes.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/unit/auth/test_oauth2_principal_keys.py",
      "action": "CREATE"
    },
    {
      "path": "tests/auth/test_oauth2_base.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/oauth2_base.py#AbstractOAuth2Manager",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2_base.py#AbstractOAuth2Manager.create_authorization_url",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2_base.py#AbstractOAuth2Manager.handle_callback",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2_base.py#AbstractOAuth2Manager._persist_token",
    "sym:packages/ai-parrot/src/parrot/security/vault_utils.py#store_vault_credential"
  ]
}
```

---

## Implementation Notes

- **Blast radius**: `O365OAuthManager` (o365_oauth.py:55) is the only subclass and passes `**kwargs` through, so
  removing the vault kwargs is safe for it; `workiq_provider.py:210` and `credentials.py:201` call
  `create_authorization_url(channel, user_id)` without `principal` — they now resolve through `resolve_principal`
  (web works with the default resolver; other channels need the server resolver, TASK-4952/4957).
- `nav_user_id` must be numeric (`str.isdigit()`); never reuse `state["user_id"]` as the Navigator id (spec §7).
- Error messages never contain token values or raw token responses.
- `principal_lock`: `self.redis.lock(self._lock_key(user_id), timeout=_REFRESH_LOCK_TIMEOUT,
  blocking_timeout=_REFRESH_LOCK_BLOCKING_TIMEOUT)`; failing to acquire raises `TimeoutError`.

---

## Implementation Blueprint

> Executor-ready starting point. Write each block to its declared path, then complete every
> `# FILL IN:` marker. Business branches, edge cases and test bodies are stubs by design.
> Never change a signature, class name or file path the blueprint fixes.

### Steps (in order)
1. Replace the key templates and add the store protocol/errors/default store (block A) — *why*: AC-1 and the S-4 rule that `CredentialStore` lives in core.
2. Rework the constructor and key helpers, add `principal_lock` (block B) — *why*: one lock for persist/refresh/revoke/re-encrypt (spec §3 M2).
3. Rework `create_authorization_url` and `handle_callback` (block C) — *why*: S1 principal binding, fail closed.
4. Rework `_persist_token` and the read helpers (block D) — *why*: S2 durable first.
5. Write `_oauth2_fakes.py`, the new tests, and fix `tests/auth/test_oauth2_base.py` — *why*: later M2/M3 tasks reuse the fakes.

### `packages/ai-parrot/src/parrot/auth/oauth2_base.py` (MODIFY)

Block A — templates, store protocol, errors:
```python
# occurrences: 1 (verified: grep -c '_TOKEN_KEY_TEMPLATE = "oauth2:{provider}:{channel}:{user_id}"' oauth2_base.py)
# REPLACE lines :39-44 (`_TOKEN_KEY_TEMPLATE` … `_VAULT_NAME_TEMPLATE`, verified: oauth2_base.py:39, :44) WITH:
_TOKEN_KEY_TEMPLATE = "oauth2:{provider}:{user_id}"
_NONCE_KEY_TEMPLATE = "oauth2:{provider}:nonce:{nonce}"
_LOCK_KEY_TEMPLATE = "lock:oauth2:{provider}:refresh:{user_id}"
# Legacy channel-scoped layout — READ-ONLY during the migration window (TASK-4941).
_LEGACY_TOKEN_KEY_TEMPLATE = "oauth2:{provider}:{channel}:{user_id}"
_LEGACY_VAULT_NAME_TEMPLATE = "oauth2_{provider}_{channel}_{user_id}"
_VAULT_NAME_TEMPLATE = "oauth2_{provider}_{user_id}"

# AFTER the VaultDeleter alias (:58) — delete the three Vault* aliases and add:
class CredentialPersistenceError(RuntimeError):
    """The durable credential write failed; the callback/refresh must not report success."""


class InvalidGrantError(PermissionError):
    """Provider rejected the refresh token (invalid_grant); the grant is revoked locally."""


class RefreshTransientError(RuntimeError):
    """Network / 429 / 5xx during refresh; the grant is kept."""


@runtime_checkable
class CredentialStore(Protocol):
    """Durable owner of an OAuth2 grant (server injects the Identity Vault store)."""

    async def load(self, user_id: str, provider: str) -> Optional[Dict[str, Any]]: ...
    async def save(self, user_id: str, provider: str, payload: Dict[str, Any], *, minted: bool,
                   principal: Optional["Principal"], state_payload: Optional[Dict[str, Any]]) -> None: ...
    async def delete(self, user_id: str, provider: str) -> None: ...


class VaultUtilsCredentialStore:
    """Default store over navigator-session vault_utils; name ``oauth2_{provider}_{user_id}``."""

    async def load(self, user_id: str, provider: str) -> Optional[Dict[str, Any]]:
        # FILL IN: retrieve_vault_credential(user_id, _VAULT_NAME_TEMPLATE.format(...)); KeyError → None
        raise NotImplementedError

    async def save(self, user_id, provider, payload, *, minted, principal, state_payload) -> None:
        # FILL IN: store_vault_credential(user_id, name, payload) — let exceptions propagate (caller wraps them)
        raise NotImplementedError

    async def delete(self, user_id: str, provider: str) -> None:
        # FILL IN: delete_vault_credential(user_id, name)
        raise NotImplementedError
```

Block B — constructor + key helpers + lock:
```python
# occurrences: 1 (verified: grep -c '        vault_writer: Optional[VaultWriter] = None,' oauth2_base.py)
# REPLACE the three vault_* parameters (:131-133) WITH:
        credential_store: Optional[CredentialStore] = None,
        event_publisher: Optional["ConnectionEventPublisher"] = None,
# REPLACE the vault default block (:172-182, `if vault_writer is None or …` … `self._vault_deleter = vault_deleter`) WITH:
        self._store: CredentialStore = credential_store or VaultUtilsCredentialStore()
        self._events: Optional["ConnectionEventPublisher"] = event_publisher

# REPLACE _token_key / _lock_key / _vault_name (:251-268) WITH:
    def _token_key(self, user_id: str) -> str:
        return _TOKEN_KEY_TEMPLATE.format(provider=self.provider_id, user_id=user_id)

    def _lock_key(self, user_id: str) -> str:
        return _LOCK_KEY_TEMPLATE.format(provider=self.provider_id, user_id=user_id)

    @asynccontextmanager
    async def principal_lock(self, user_id: str) -> AsyncIterator[None]:
        """The single per-(provider, principal) lock for persist/refresh/revoke/re-encrypt. Never nest it."""
        lock = self.redis.lock(self._lock_key(user_id), timeout=_REFRESH_LOCK_TIMEOUT,
                               blocking_timeout=_REFRESH_LOCK_BLOCKING_TIMEOUT)
        # FILL IN: acquire (False → raise TimeoutError naming provider only); yield; release in finally,
        #          swallowing an already-released lock — bounded by spec §3 M2 "acquire it once per operation"
        raise NotImplementedError
```

Block C — authorize + callback:
```python
# occurrences: 1 each (verified: '    async def create_authorization_url(' :298, '    async def handle_callback(' :354)
    async def create_authorization_url(self, channel: str, user_id: str,
                                       extra_state: Optional[Dict[str, Any]] = None, *,
                                       principal: Optional["Principal"] = None) -> Tuple[str, str]:
        """Bind the principal into the nonce payload (S1). ValueError when no principal resolves."""
        if principal is None:
            principal = await resolve_principal(channel, user_id)
        if principal is None:
            raise ValueError(f"No platform principal bound to this {channel} user; link the account first.")
        nonce = secrets.token_urlsafe(32)
        state_payload: Dict[str, Any] = {
            "channel": channel, "user_id": user_id, "extra": extra_state or {},
            "nav_user_id": principal.user_id, "channel_user_id": principal.channel_user_id,
            "canonical_identity": principal.canonical_identity, "tenant_id": principal.tenant_id,
        }
        # KEEP the existing params/PKCE/extra_params/redis.set/url code unchanged (:322-343).

    async def handle_callback(self, code: str, state: str) -> Tuple[AbstractOAuth2TokenSet, Dict[str, Any]]:
        # KEEP nonce consume + JSON decode (:368-380).
        # FILL IN: nav_user_id = state_payload.get("nav_user_id"); missing or not str(nav).isdigit() → ValueError
        #          BEFORE any exchange (AC-2: render error, write nothing); build Principal(user_id=nav, channel=…,
        #          channel_user_id=state_payload.get("channel_user_id") or state_payload["user_id"], canonical_identity=…,
        #          tenant_id=…)
        # KEEP exchange → _discover_identity → _build_token_set.
        # FILL IN: token_set = await self._post_exchange(token_response, token_set)
        #          async with self.principal_lock(principal.user_id):
        #              await self._persist_token(principal, token_set, minted=True, state_payload=state_payload)
        #          await self._publish("connection.completed", principal, token_set,
        #                              state_payload={**state_payload, "connection_meta": self._public_metadata(token_set)})
        #          — publish AFTER the lock; connection_meta lets notifier adapters render e.g. Jira site_url
        raise NotImplementedError

    def _public_metadata(self, token_set: AbstractOAuth2TokenSet) -> Dict[str, Any]:
        """Non-secret token attributes handed to notifiers (default none; Jira returns site_url/cloud_id)."""
        return {}

    async def _post_exchange(self, token_response: Dict[str, Any],
                             token_set: AbstractOAuth2TokenSet) -> AbstractOAuth2TokenSet:
        """Provider hook after the exchange (StandardOAuth2Manager wires the descriptor hook). Default: identity."""
        return token_set

    async def _publish(self, kind: str, principal: "Principal", token_set: Optional[AbstractOAuth2TokenSet],
                       *, reason: Optional[str] = None, state_payload: Optional[Dict[str, Any]] = None) -> None:
        """Publish a ConnectionEvent when a publisher is attached (never raises)."""
        # FILL IN: no publisher → return; build ConnectionEvent(kind=…, user_id=principal.user_id,
        #          canonical_identity=…, tenant_id=…, provider=self.provider_id, account_id/display_name from token_set,
        #          channel=principal.channel, occurred_at=time.time(), reason=reason);
        #          await self._events.publish(event, state_payload or {})
        raise NotImplementedError
```

Block D — durable-first persistence and reads:
```python
# occurrences: 1 (verified: '    async def _persist_token(' :409)
    async def _persist_token(self, principal: "Principal", token_set: AbstractOAuth2TokenSet, *, minted: bool,
                             state_payload: Optional[Dict[str, Any]] = None) -> None:
        """CredentialStore.save FIRST (CredentialPersistenceError on failure), then Redis. Caller holds principal_lock."""
        payload = token_set.model_dump(mode="json")
        try:
            await self._store.save(principal.user_id, self.provider_id, payload, minted=minted,
                                   principal=principal, state_payload=state_payload)
        except Exception as exc:  # noqa: BLE001 - any durable failure is fatal (S2)
            self.logger.error("Durable %s credential write failed for principal %s: %s",
                              self.provider_id, principal.user_id, type(exc).__name__)
            raise CredentialPersistenceError(f"{self.provider_id} credential could not be persisted") from None
        await self.redis.set(self._token_key(principal.user_id), json.dumps(payload), ex=_TOKEN_TTL_SECONDS)

    # REPLACE _read_token_from_cache / _read_token_from_vault (:429-459) with user_id-only versions:
    async def _read_token_from_cache(self, user_id: str) -> Optional[AbstractOAuth2TokenSet]: ...   # FILL IN: same body, new key
    async def _read_token_from_store(self, user_id: str) -> Optional[AbstractOAuth2TokenSet]: ...   # FILL IN: self._store.load → model_validate; errors logged → None
    # FILL IN: adapt get_valid_token / is_connected / revoke / _refresh_tokens bodies to the user_id-only keys and
    #          to `_persist_token(Principal(user_id=user_id, channel=channel, channel_user_id=user_id), …, minted=False)`
    #          — minimal mechanical change only; TASK-4941 rewrites them.
```
**Why this shape**: the signatures are the spec §3 M2 skeleton. `_post_exchange` and `_publish` are the two
internal seams TASK-4943 (descriptor hook) and TASK-4941 (revoke/refresh events) build on; publishing happens
outside the lock so a slow notifier never extends it.

### `packages/ai-parrot/tests/unit/auth/_oauth2_fakes.py` (CREATE)
```python
"""Shared fakes for FEAT-773 OAuth2 tests (no fakeredis — it is not installed)."""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional, Tuple

from parrot.auth.oauth2_base import AbstractOAuth2Manager, AbstractOAuth2TokenSet
from parrot.auth.principal import Principal


class MemRedis:
    """get/set(ex=)/delete/scan_iter/lock — enough for the manager (TTL ignored)."""
    # FILL IN: dict storage; delete(*keys) returns count; scan_iter(match=) async generator using fnmatch;
    #          lock(name, timeout=None, blocking_timeout=None) → object with async acquire()/release() backed by
    #          one asyncio.Lock per name (acquire honours blocking_timeout via asyncio.wait_for → False on timeout)


class FakeCredentialStore:
    """In-memory CredentialStore; `fail_next_save=True` raises once; records calls."""
    # FILL IN: rows Dict[Tuple[user_id, provider], payload]; calls list; load/save/delete per the Protocol


class FakePrincipalResolver:
    """{(channel, channel_user_id): Principal}; unknown → None."""
    # FILL IN


class FakeManager(AbstractOAuth2Manager):
    """Concrete manager with scripted hooks: set .exchange_payload / .refresh_result / .identity."""
    provider_id = "fake"
    authorization_url = "https://idp.example/authorize"
    token_url = "https://idp.example/token"
    default_scopes = ["read"]
    # FILL IN: _exchange_code/_refresh_request/_discover_identity/_build_token_set returning scripted values;
    #          refresh_result may be an Exception instance to raise
```

### FILL IN checklist
- [ ] `oauth2_base.py::VaultUtilsCredentialStore.load/save/delete` — over vault_utils; bounded by spec §3 M2 skeleton
- [ ] `oauth2_base.py::AbstractOAuth2Manager.principal_lock` — acquire/raise/release; bounded by "never nest"
- [ ] `oauth2_base.py::AbstractOAuth2Manager.handle_callback` — nav_user_id check, hook, locked persist, publish; bounded by AC-2/AC-5
- [ ] `oauth2_base.py::AbstractOAuth2Manager._publish` — event build; bounded by §2 ConnectionEvent (no tokens)
- [ ] `oauth2_base.py` read helpers + mechanical adaptation of get_valid_token/revoke/_refresh_tokens
- [ ] `_oauth2_fakes.py` — MemRedis, FakeCredentialStore, FakePrincipalResolver, FakeManager
- [ ] `tests/auth/test_oauth2_base.py` — constructor (`credential_store=`) and `_token_key(user_id)` call sites

---

## Acceptance Criteria

- [ ] AC-1: no key produced by the manager contains the channel; only `_LEGACY_*` templates contain `{channel}`
- [ ] AC-2: nonce payload carries nav_user_id/channel/channel_user_id(/canonical_identity); a callback without a numeric nav_user_id raises ValueError before any exchange and writes nothing
- [ ] AC-5: store failure → `CredentialPersistenceError`, no Redis write, no event
- [ ] `connection.completed` published once after a successful callback (when a publisher is attached)
- [ ] `ruff check` clean on touched files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/auth/test_oauth2_principal_keys.py -q`
- `pytest tests/auth/test_oauth2_base.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/auth/test_oauth2_principal_keys.py
import json
import pytest
from parrot.auth.oauth2_base import CredentialPersistenceError
from parrot.auth.principal import Principal, set_principal_resolver
from ._oauth2_fakes import FakeCredentialStore, FakeManager, FakePrincipalResolver, MemRedis  # unit/auth is a package (has __init__.py)


@pytest.fixture
def principal():
    return Principal(user_id="1042", canonical_identity="jlara@example.com", channel="telegram", channel_user_id="88123")


@pytest.mark.asyncio
async def test_manager_keys_are_principal_scoped(principal):
    m = FakeManager("cid", "https://cb", client_secret="s", redis_client=MemRedis(), credential_store=FakeCredentialStore())
    assert m._token_key("1042") == "oauth2:fake:1042" and "telegram" not in m._lock_key("1042")


@pytest.mark.asyncio
async def test_state_binds_principal_and_callback_verifies(principal):
    redis = MemRedis(); m = FakeManager("cid", "https://cb", client_secret="s", redis_client=redis,
                                        credential_store=FakeCredentialStore())
    url, nonce = await m.create_authorization_url("telegram", "88123", principal=principal)
    state = json.loads(await redis.get(m._nonce_key(nonce)))
    assert state["nav_user_id"] == "1042" and state["channel_user_id"] == "88123"
    # FILL IN: tamper a second nonce payload without nav_user_id → handle_callback raises ValueError, store untouched


@pytest.mark.asyncio
async def test_persist_durable_first_then_redis(principal):
    store = FakeCredentialStore(); store.fail_next_save = True
    redis = MemRedis(); m = FakeManager("cid", "https://cb", client_secret="s", redis_client=redis, credential_store=store)
    _, nonce = await m.create_authorization_url("telegram", "88123", principal=principal)
    with pytest.raises(CredentialPersistenceError):
        await m.handle_callback("code", nonce)
    assert await redis.get(m._token_key("1042")) is None
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

**Completed by**: sdd-worker orchestrator; seat gpt-5.6-sol (codex), attempt 3; engine task-tier selector reported no tests collected, direct run 5 passed, merged manually
**Date**: 2026-10-30
**Notes**: Implemented per task; merged, engine lint clean. Merge-tier validation: only red is pre-existing test_oauth_callback_routes::test_invalid_state_returns_400 (ledger issue:e7b7e5906b6e).
