---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: O365 Auth Homologation — retire legacy interactive-auth + `device_code` broker kind

**Feature ID**: FEAT-266
**Date**: 2026-07-01
**Author**: Jesus Lara
**Status**: draft
**Target version**: 0.x

> Input: `sdd/proposals/o365-auth-homologation.brainstorm.md` (Recommended Option A).
> All brainstorm resolutions are carried forward; see §8 for the decision trail.

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot carries **three generations** of Office 365 authentication that have drifted apart:

- **Gen 1 — LEGACY (orphaned).** `RemoteAuthManager` + `RemoteAuthSession`
  (`packages/ai-parrot-server/src/parrot/services/o365_remote_auth.py:52`) and the aiohttp
  handlers `O365InteractiveAuthSessions` / `O365InteractiveAuthSessionDetail`
  (`packages/ai-parrot-server/src/parrot/handlers/o365_auth.py:20,62`) ran interactive
  device-code login through an in-memory session dict exposed over a REST polling API. All
  `app.py` wiring is commented out; there are **no external consumers**. Dead code, no
  persisted state.

- **Gen 2/3 — ACTIVE.** OAuth2 3LO (`O365OAuthManager`, PKCE) + `Office365Toolkit` +
  `O365OAuth2Provider`, all fronted by the FEAT-264 `CredentialBroker` (auth kinds
  `obo|oauth2|static_key|mcp`, ContextVar seam in `tools/abstract.py`, `audit_ledger`,
  `CanonicalIdentityMapper`).

Two problems result: (1) a dead Gen 1 surface inflates security/audit surface and confuses
contributors about the canonical path; (2) the one useful Gen 1 capability — **device-code /
headless login** (no browser) — has **no equivalent** in the broker (the factory only knows
`obo|oauth2|static_key|mcp`).

A third finding raises the stakes: there are **three unsynchronized Entra token stores**, and
**nobody currently writes the canonical flat `o365:*` keys** that `WorkIQOBOCredentialResolver`
reads — the 3LO flow persists to `vault_utils`, and there is a `post_auth_jira` bridge but no
`post_auth_o365`. This feature's device-code resolver becomes the **first writer** of the
canonical keys and fixes the contract.

### Goals

- Delete Gen 1 entirely (no shim, no migration).
- Add a `device_code` broker auth kind with an O365-specific resolver that wraps the existing
  `O365Client.interactive_login()` device-code engine.
- Extend `NeedsAuth` + `CredentialRequired` with optional `user_code` / `verification_uri` /
  `expires_in` (additive, backward-compatible) so device-code can be surfaced now and chat can
  adopt it later without re-touching the model.
- Establish `VaultTokenSync` flat `o365:*` as the canonical per-user Entra token store, with a
  fixed field contract, written by device-code.
- Provide silent refresh by reusing a single Entra refresh code path (promoted public primitive
  on `O365OAuthManager`).
- CLI surface only: inline blocking poll, canonical identity from an explicit env principal.

### Non-Goals (explicitly out of scope)

- **Chat surfaces** (A2A/Copilot/MSAgentSDK) for device-code — model is extended for the future,
  but no durable poller / suspend-resume / card renderer is built. Rejected in brainstorm
  (Option A); see `proposals/o365-auth-homologation.brainstorm.md`.
- **Generic Entra device-flow resolver** — O365-specific only (brainstorm Option C rejected, YAGNI).
- **`post_auth_o365` bridge** (making the 3LO browser flow also write `o365:*`) — a separate
  follow-up feature; tracked in §8.
- Modifying `O365OAuthManager.get_valid_token()`'s own internal refresh/store (left untouched).

---

## 2. Architectural Design

### Overview

Add `"device_code"` to `AuthKind` and a `_build_device_code()` branch in
`CredentialResolverFactory`. A new `O365DeviceCodeCredentialResolver` (in
`packages/ai-parrot/src/parrot/auth/oauth2/`) implements the `CredentialResolver` contract:

- `resolve(channel, user_id)`:
  1. Read the user's `o365:*` token set from `VaultTokenSync`. If present and not near expiry,
     return `access_token`.
  2. If present but expired and a `refresh_token` exists, call the promoted public refresh
     primitive on `O365OAuthManager`, re-persist to `VaultTokenSync`, return.
  3. If absent (or refresh rejected with `PermissionError`), run the device-code flow inline via
     `O365Client.interactive_login(open_browser=False, device_flow_callback=…)`. The callback
     surfaces `verification_uri` + `user_code` (printed by the CLI). Block until success or
     Microsoft's `expires_in`. On success, persist the token set to `VaultTokenSync` under
     prefix `o365` and return.
- `get_auth_url(channel, user_id)`: returns the device-login verification URI (used to populate
  the extended `NeedsAuth`/`CredentialRequired` fields on failure/timeout and for future chat).

The signal models gain optional `user_code` / `verification_uri` / `expires_in` (default `None`).
On the CLI happy path the resolver returns a token (no `CredentialRequired` raised); the
exception is reserved for failure/timeout and the future chat surface.

The broker is built in `AbstractBot.configure()` from `self._credentials`
(`bots/abstract.py:1401`) and handed to `ToolManager.set_broker()`. At execute time
`ToolManager` injects `_broker` + `_cred_channel`/`_cred_user_id` (read from
`permission_context.channel`/`.user_id`, `manager.py:1305-1316`). The CLI entry point therefore
supplies a permission context with `channel="cli"` and `user_id=<canonical principal>` (read from
env `O365_PRINCIPAL`, normalized by `CanonicalIdentityMapper`), and declares the o365
`device_code` provider in the agent's credentials config.

### Component Diagram
```
CLI bootstrap (env O365_PRINCIPAL → CanonicalIdentityMapper)
   │  permission_context(channel="cli", user_id=<canonical>)
   ▼
AbstractBot.configure() ── CredentialBroker.from_config(_credentials)
   │                              │ register("o365", auth="device_code")
   ▼                              ▼
ToolManager.execute() ──► AbstractTool seam (_broker.resolve) ──► O365DeviceCodeCredentialResolver
                                                                     │ read/refresh/device-flow
                                                                     ├─► VaultTokenSync (o365:* canonical store)
                                                                     ├─► O365Client.interactive_login (device engine)
                                                                     └─► O365OAuthManager.refresh_access_token (refresh primitive)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.auth.credentials` (`AuthKind`, `NeedsAuth`, `CredentialRequired`) | modifies | add `"device_code"`; add optional device-code fields |
| `parrot.auth.broker.CredentialResolverFactory` | extends | `_build_device_code()` + dispatch in `build()` |
| `parrot.interfaces.o365.O365Client` (`O365Interface`) | uses | `interactive_login(open_browser=False, device_flow_callback=…)` |
| `parrot.auth.o365_oauth.O365OAuthManager` | extends | promote `_refresh_request` → public `refresh_access_token` |
| `parrot.services.vault_token_sync.VaultTokenSync` | uses | `store_tokens`/`read_tokens` under prefix `o365` (canonical store) |
| `parrot.auth.identity.CanonicalIdentityMapper` | uses | `to_canonical()` for the CLI principal |
| `parrot.tools.manager.ToolManager` / `tools.abstract` seam | depends on | existing `_broker`/`_cred_channel`/`_cred_user_id` propagation |
| Gen 1 files + `app.py` commented blocks | removes | dead code |

### Data Models
```python
# parrot/auth/credentials.py — EXTENDED (additive, backward-compatible)
AuthKind = Literal["obo", "oauth2", "static_key", "mcp", "device_code"]  # + "device_code"

class NeedsAuth(BaseModel):
    provider: str
    auth_url: str
    auth_kind: AuthKind
    user_code: Optional[str] = None          # NEW
    verification_uri: Optional[str] = None   # NEW
    expires_in: Optional[int] = None         # NEW

# Canonical VaultTokenSync field contract under prefix "o365":
#   access_token: str
#   refresh_token: str
#   expires_at: int        # epoch seconds
#   scope: str             # space-delimited granted scopes
#   id_token: str          # optional
#   tenant_id: str
```

### New Public Interfaces
```python
# parrot/auth/oauth2/o365_devicecode_provider.py  (NEW)
class O365DeviceCodeCredentialResolver(CredentialResolver):
    def __init__(self, o365_client, o365_oauth_manager, vault_token_sync,
                 scopes: list[str], prompt_callback=None) -> None: ...
    async def resolve(self, channel: str, user_id: str) -> Optional[str]: ...
    async def get_auth_url(self, channel: str, user_id: str) -> str: ...

# parrot/auth/o365_oauth.py  (PROMOTED from _refresh_request)
class O365OAuthManager(AbstractOAuth2Manager):
    async def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]: ...
```

---

## 3. Module Breakdown

### Module 1: Broker signal-model extension
- **Path**: `packages/ai-parrot/src/parrot/auth/credentials.py`
- **Responsibility**: add `"device_code"` to `AuthKind`; add optional `user_code` /
  `verification_uri` / `expires_in` to `NeedsAuth` and matching attrs/kwargs to
  `CredentialRequired` (all default `None`, backward-compatible).
- **Depends on**: none (foundational).

### Module 2: O365 refresh primitive
- **Path**: `packages/ai-parrot/src/parrot/auth/o365_oauth.py`
- **Responsibility**: promote `_refresh_request(refresh_token)` to a documented public
  `refresh_access_token(refresh_token) -> Dict[str, Any]` (keep `_refresh_request` as a thin
  alias if internal callers exist). Preserve the `PermissionError` on 400/401 (dead refresh token).
- **Depends on**: none.

### Module 3: Device-code credential resolver
- **Path**: `packages/ai-parrot/src/parrot/auth/oauth2/o365_devicecode_provider.py` (new)
- **Responsibility**: `O365DeviceCodeCredentialResolver` — vault read → refresh → inline device
  flow; persist canonical `o365:*` token set; surface `verification_uri`+`user_code` via the
  device-flow callback; respect `expires_in`; clean cancellation.
- **Depends on**: Module 1 (model), Module 2 (refresh), `O365Client`, `VaultTokenSync`.

### Module 4: Factory wiring
- **Path**: `packages/ai-parrot/src/parrot/auth/broker.py`
- **Responsibility**: `_build_device_code(cfg, opts)` constructing Module 3 from deps
  (`o365_interface`/`o365_client`, `o365_oauth_manager`, `vault`) + dispatch branch in `build()`.
- **Depends on**: Module 3.

### Module 5: CLI bootstrap / identity wiring
- **Path**: CLI agent run path (exact entry to be confirmed — see §8) + agent credentials config.
- **Responsibility**: read `O365_PRINCIPAL` from env, normalize via `CanonicalIdentityMapper`,
  supply a permission context with `channel="cli"` + `user_id=<canonical>`; ensure the agent's
  `_credentials` declares the o365 `device_code` provider so `configure()` builds the broker.
- **Depends on**: Modules 1–4.

### Module 6: Gen 1 removal
- **Path**: delete `packages/ai-parrot-server/src/parrot/services/o365_remote_auth.py` and
  `packages/ai-parrot-server/src/parrot/handlers/o365_auth.py`; remove the commented Gen 1
  blocks in `app.py` (lines ~31-37, 166-181) — touch ONLY those blocks, not the unrelated
  uncommitted logging refactor.
- **Depends on**: none (independent; verify no other importer first).

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_authkind_includes_device_code` | M1 | `"device_code"` is a valid `AuthKind`; `ProviderCredentialConfig(auth="device_code")` validates |
| `test_needsauth_optional_devicecode_fields` | M1 | `NeedsAuth`/`CredentialRequired` accept and default `user_code`/`verification_uri`/`expires_in` to `None`; existing call sites unaffected |
| `test_refresh_access_token_public` | M2 | `refresh_access_token` returns token dict; raises `PermissionError` on simulated 400 invalid_grant |
| `test_resolver_cache_hit` | M3 | valid `o365:*` in vault → returns `access_token`, no device flow |
| `test_resolver_refresh_on_expiry` | M3 | expired token + refresh_token → calls `refresh_access_token`, re-persists, returns new token |
| `test_resolver_device_flow_on_miss` | M3 | empty vault → invokes `interactive_login` (mocked), surfaces user_code via callback, persists canonical fields |
| `test_resolver_expiry_no_partial_write` | M3 | device flow times out → raises/returns cleanly, vault untouched |
| `test_resolver_fail_closed_no_identity` | M3 | absent `user_id` → fail closed (no anonymous vault key) |
| `test_factory_builds_device_code` | M4 | `CredentialResolverFactory.build(auth="device_code")` returns `O365DeviceCodeCredentialResolver`; missing dep → `KeyError` |
| `test_gen1_modules_removed` | M6 | importing `parrot.services.o365_remote_auth` / `parrot.handlers.o365_auth` raises `ImportError`; no live references remain |

### Integration Tests
| Test | Description |
|---|---|
| `test_cli_device_code_end_to_end` | With a mocked Entra device endpoint: broker built from `device_code` config; tool with `credential_provider="o365"` resolves via inline flow; token lands in `VaultTokenSync` `o365:*`; second resolve is a cache hit |
| `test_devicecode_token_consumable_by_workiq_obo` | After device-code persists `o365:access_token`, `WorkIQOBOCredentialResolver.resolve` finds the Entra token and performs OBO (mocked) — proves the canonical-store homologation |

### Test Data / Fixtures
```python
@pytest.fixture
def fake_device_flow():
    return {"verification_uri": "https://microsoft.com/devicelogin",
            "user_code": "A1B2-C3D4", "expires_in": 900, "message": "..."}

@pytest.fixture
def fake_token_response():
    return {"access_token": "eyJ...", "refresh_token": "0.AR...",
            "expires_in": 3600, "scope": "User.Read offline_access", "id_token": "eyJ..."}
```

---

## 5. Acceptance Criteria

- [ ] `AuthKind` includes `"device_code"`; `ProviderCredentialConfig(auth="device_code")` validates.
- [ ] `NeedsAuth` and `CredentialRequired` carry optional `user_code`/`verification_uri`/`expires_in`
      (default `None`); the existing `obo|oauth2|static_key|mcp` paths and all current call sites are
      unaffected (no breaking change).
- [ ] `O365OAuthManager.refresh_access_token(refresh_token)` is public and reused by the resolver;
      `PermissionError` is raised on dead refresh tokens.
- [ ] `O365DeviceCodeCredentialResolver` persists the canonical `o365:*` field set via
      `VaultTokenSync` and reads it back on subsequent resolves (cache hit, no re-prompt).
- [ ] On a vault miss, the resolver runs `interactive_login(open_browser=False, …)` inline, surfaces
      `verification_uri`+`user_code`, and blocks up to Microsoft's `expires_in`; on the happy path it
      returns a token WITHOUT raising `CredentialRequired`.
- [ ] Device-flow expiry / cancellation leaves no partial vault write.
- [ ] Absent CLI identity fails closed (no anonymous vault key).
- [ ] A device-code-obtained `o365:access_token` is consumable by `WorkIQOBOCredentialResolver` (proves
      the canonical-store standard).
- [ ] Gen 1 modules are deleted and the commented `app.py` blocks removed; nothing imports them; the
      unrelated uncommitted `app.py` logging change is untouched.
- [ ] All unit tests pass (`pytest packages/ai-parrot/tests/ -v` for the touched areas).
- [ ] No `device_code` secret ever appears in logs/audit (only `key_fingerprint`); audit entry appended
      on success.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Re-verified 2026-07-01.

### Verified Imports
```python
from parrot.auth.credentials import (
    AuthKind, ProviderCredentialConfig, NeedsAuth, CredentialRequired,
    ResolvedCredential, CredentialResolver, OAuthCredentialResolver,
)                                            # packages/ai-parrot/src/parrot/auth/credentials.py
from parrot.auth.broker import (
    CredentialBroker, CredentialResolverFactory, CredentialBrokerConfigError,
)                                            # broker.py:42 __all__
from parrot.interfaces.o365 import O365Client          # interfaces/o365.py:115 (alias O365Interface — used by workiq_provider)
from parrot.services.vault_token_sync import VaultTokenSync   # ai-parrot-server (services/vault_token_sync.py:55)
from parrot.auth.identity import CanonicalIdentityMapper      # identity.py:57 (__all__:14)
from parrot.auth.o365_oauth import O365OAuthManager           # auth/o365_oauth.py:55
from parrot.tools.abstract import current_credential          # tools/abstract.py:36
```

### Existing Class Signatures
```python
# parrot/auth/credentials.py
AuthKind = Literal["obo", "oauth2", "static_key", "mcp"]                  # line 43  → add "device_code"
class NeedsAuth(BaseModel):                                              # line 82
    provider: str; auth_url: str; auth_kind: AuthKind                    #          → add 3 optional fields
class CredentialRequired(Exception):                                     # line 97
    def __init__(self, provider: str, auth_url: str, auth_kind: str): ...# line 113
class CredentialResolver(ABC):                                          # line 128
    async def resolve(self, channel: str, user_id: str) -> Optional[Any]: ...  # line 132
    async def get_auth_url(self, channel: str, user_id: str) -> str: ...       # line 141
    async def is_connected(self, channel: str, user_id: str) -> bool: ...      # line 145

# parrot/auth/broker.py
class CredentialResolverFactory:                                        # line 66
    def build(self, cfg: ProviderCredentialConfig) -> CredentialResolver: ...  # line 101 (dispatch 114-129)
    def _build_obo / _build_oauth2 / _build_static_key / _build_mcp(self, cfg, opts): ...  # 135/165/184/210
class CredentialBroker:                                                 # line 280
    def register(self, provider, resolver, auth_kind="oauth2") -> None: ...     # line 329
    @classmethod def from_config(cls, configs, strict=True, **deps): ...        # line 355
    async def resolve(self, provider, channel, user_id, **ctx) -> "ResolvedCredential | NeedsAuth": ... # line 405

# parrot/interfaces/o365.py
class O365Client(CredentialsInterface):                                 # line 115
    async def interactive_login(self, scopes=None, redirect_uri="http://localhost",
        open_browser=True, login_callback=None, device_flow_callback=None) -> Dict[str, Any]: ...  # line 763
        # internals: public_app.initiate_device_flow(scopes) (~832); acquire_token_by_device_flow(flow) (~854)
    def acquire_token_on_behalf_of(self, user_assertion, scopes=None) -> Dict[str, Any]: ...  # line 621

# parrot/auth/o365_oauth.py
class O365OAuthManager(AbstractOAuth2Manager):                          # line 55
    async def _refresh_request(self, refresh_token: str) -> Dict[str, Any]: ...  # line 140 → promote to public
        # raises PermissionError on HTTP 400/401 (dead refresh token)
DEFAULT_O365_SCOPES includes "offline_access"                          # line 30-33 (enables refresh token)

# parrot/services/vault_token_sync.py  (flat {provider}:{field} scheme)
class VaultTokenSync:                                                   # line 55
    async def store_tokens(self, nav_user_id: str, provider: str, tokens: Dict[str, Any]) -> None: ...  # line 106
    async def read_tokens(self, nav_user_id: str, provider: str) -> Optional[Dict[str, Any]]: ...       # line 141
    async def delete_tokens(self, nav_user_id: str, provider: str) -> None: ...                          # line 176

# parrot/auth/identity.py
class CanonicalIdentityMapper:                                          # line 57
    @staticmethod def to_canonical(raw_identity: Dict[str, Any]) -> Optional[str]: ...  # line 75 (OID → email → None)

# parrot/tools/abstract.py
def current_credential() -> Optional[Any]: ...                         # line 36 (reads _CREDENTIAL_VAR, line 31)
class AbstractTool(...): credential_provider: Optional[str] = None     # line 123 / 147
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `O365DeviceCodeCredentialResolver` | `O365Client.interactive_login` | method call (device flow) | `interfaces/o365.py:763` |
| `O365DeviceCodeCredentialResolver` | `O365OAuthManager.refresh_access_token` | method call (refresh) | `o365_oauth.py:140` (promote) |
| `O365DeviceCodeCredentialResolver` | `VaultTokenSync.store_tokens/read_tokens` | method call (persist `o365:*`) | `vault_token_sync.py:106,141` |
| `_build_device_code` | factory dispatch | `build()` branch | `broker.py:114-129` |
| CLI bootstrap | `_cred_channel`/`_cred_user_id` | `permission_context.channel/.user_id` | `manager.py:1305-1316` |
| Agent credentials | broker build | `CredentialBroker.from_config(self._credentials)` | `bots/abstract.py:1389-1402` |

### Does NOT Exist (Anti-Hallucination)
- ~~`AuthKind` value `"device_code"`~~ — not present yet (only `obo|oauth2|static_key|mcp`, credentials.py:43). This feature adds it.
- ~~`NeedsAuth.user_code` / `.verification_uri` / `.expires_in`~~ — do not exist yet; added here.
- ~~`CredentialResolverFactory._build_device_code`~~ — does not exist; added here.
- ~~`O365OAuthManager.refresh_access_token` (public)~~ — only the private `_refresh_request` exists today.
- ~~Any writer of flat `o365:*` keys via `VaultTokenSync` in the O365 path~~ — NONE today (grep-verified); 3LO writes `vault_utils`; no `post_auth_o365`. Device-code becomes the first writer.
- ~~A generic `parrot/auth/device_flow.py` resolver~~ — does not exist (Option C; not chosen).
- ~~`VaultTokenSync` arbitrary key/value `get`/`set` API~~ — it is token-set based (`store_tokens`/`read_tokens`/`delete_tokens`), flat `{provider}:{field}` internally.
- ~~Any live consumer of `/api/v1/o365/auth/sessions`~~ — none in-repo; `app.py` wiring fully commented.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Async-first; Google-style docstrings; strict type hints; Pydantic for models; `self.logger` (no print — the device prompt goes through the resolver's `prompt_callback`/stdout deliberately, not the logger secret path).
- Mirror the existing resolver shape in `parrot/auth/oauth2/workiq_provider.py` (vault read → exchange → cache → return; `get_auth_url` for the link).
- Model changes must be purely additive — default new fields to `None`, do not reorder, keep `CredentialRequired.__init__` backward-compatible (new args keyword-only with defaults).
- `device_code` registers with `auth_kind="device_code"` so `NeedsAuth.auth_kind` reflects it on misses.

### Known Risks / Gotchas
- **Three token stores.** Canonical = `VaultTokenSync` `o365:*`. Do NOT also write the MSAL Redis
  cache or `vault_utils` as a second source of truth. `interactive_login` will populate its own
  internal MSAL cache as a side effect — that is engine-internal and not read by the resolver.
- **`VaultTokenSync` Telegram assumptions.** `_synth_session_uuid` uses a `telegram-persistent:`
  prefix and `_coerce_user_id` tries `int()` with a non-numeric fallback. Verify a canonical
  email/OID `user_id` round-trips correctly in a non-Telegram CLI context before relying on it
  (§8). If it does not, generalize the session-uuid scheme rather than work around it.
- **Inline blocking poll** holds the coroutine up to ~15 min — acceptable for interactive CLI;
  rely on `expires_in` + clean Ctrl-C for non-interactive. Document that device-code is not for
  unattended CI.
- **Single-process only** — device-code background polling is not multi-server safe; fine for the
  CLI/headless scope.
- **Gen 1 deletion** — confirm no importer beyond the handler↔manager pair; the `app.py` working
  tree currently has an unrelated uncommitted logging refactor — edit ONLY the commented Gen 1
  blocks.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `msal` | existing | device flow inside `interactive_login` (not called directly here) |
| `azure-identity` / `msgraph` | existing | Graph client / token credential (via `O365Client`) |
| `aiohttp` | existing | Entra token endpoint calls in `refresh_access_token` |
| `pydantic` | `>=2` | optional model fields |

---

## 8. Open Questions

- [x] Flow type / base branch — *Resolved in brainstorm*: `feature` on `dev`.
- [x] CLI canonical identity source — *Resolved in brainstorm*: explicit Entra principal via env (`O365_PRINCIPAL`), normalized by `CanonicalIdentityMapper`; fail-closed if absent.
- [x] Resolver scope — *Resolved in brainstorm*: O365-specific (Option A); generalize later if a second consumer appears.
- [x] CLI resolution semantics — *Resolved in brainstorm*: inline blocking poll; extend the model anyway for future chat.
- [x] Refresh behavior — *Resolved in brainstorm*: silent refresh reusing the O365 engine via a promoted public `refresh_access_token`; re-prompt only on refresh failure.
- [x] Expiry/cancel — *Resolved in brainstorm*: respect Microsoft `expires_in`; clean Ctrl-C, no partial vault write.
- [x] CLI entry point — *Resolved in brainstorm*: no new command; resolver fires inline from the existing agent/tool run path via the broker seam.
- [x] Canonical token store — *Resolved in brainstorm*: `VaultTokenSync` prefix `o365` with the fixed field contract; user_id = canonical identity.
- [ ] Exact CLI run path / entry where the `permission_context(channel="cli", user_id=<canonical>)` is constructed and the o365 `device_code` config is attached to the agent — *Owner: implementer*: confirm during implementation (seam verified at `manager.py:1305-1316`).
- [ ] `VaultTokenSync._coerce_user_id` / `_synth_session_uuid` (`telegram-persistent:` prefix) behavior for a canonical email/OID `user_id` in a non-Telegram CLI context — *Owner: implementer*.
- [ ] **Follow-up feature (out of scope):** add a `post_auth_o365` bridge so the 3LO browser flow also writes canonical `o365:*` keys (so 3LO-authenticated users can use WorkIQ OBO) — *Owner: triage*.

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — all tasks run sequentially in one worktree.
- **Rationale**: Effort is Low (S). Modules 1–4 share the model extension and touch the
  FEAT-264 broker core (`credentials.py`, `broker.py`); doing them sequentially in one worktree
  keeps the homologation atomic. Gen 1 deletion (Module 6) is independent but trivial and best
  bundled so the "retire + replace" lands as one reviewable change.
- **Cross-feature dependencies**: touches FEAT-264 broker files — coordinate with any in-flight
  broker work to avoid conflicts on `credentials.py` / `broker.py`. No spec must merge first.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-01 | Jesus Lara | Initial draft from brainstorm (Option A); token-store standard carried forward |
