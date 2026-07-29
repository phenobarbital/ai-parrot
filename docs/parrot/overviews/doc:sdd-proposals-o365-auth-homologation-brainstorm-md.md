---
type: Wiki Overview
title: 'Brainstorm: O365 Auth Homologation — retire legacy interactive-auth + add
  `device_code` broker kind'
id: doc:sdd-proposals-o365-auth-homologation-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: AI-Parrot carries **three generations** of Office 365 authentication code
  that
relates_to:
- concept: mod:parrot.auth.broker
  rel: mentions
- concept: mod:parrot.auth.credentials
  rel: mentions
- concept: mod:parrot.auth.identity
  rel: mentions
- concept: mod:parrot.interfaces.o365
  rel: mentions
- concept: mod:parrot.services.vault_token_sync
  rel: mentions
- concept: mod:parrot.tools.abstract
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: O365 Auth Homologation — retire legacy interactive-auth + add `device_code` broker kind

**Date**: 2026-07-01
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

AI-Parrot carries **three generations** of Office 365 authentication code that
have drifted apart:

- **Gen 1 — LEGACY (orphaned).** `RemoteAuthManager` + `RemoteAuthSession`
  (`packages/ai-parrot-server/src/parrot/services/o365_remote_auth.py:52`) and the
  aiohttp handlers `O365InteractiveAuthSessions` / `O365InteractiveAuthSessionDetail`
  (`packages/ai-parrot-server/src/parrot/handlers/o365_auth.py:20,62`). These ran
  interactive **device-code** login through an in-memory session dict exposed over a
  REST polling API (`POST/GET/DELETE /api/v1/o365/auth/sessions[/{id}]`). All wiring
  in `app.py` is **commented out** (`app.py:31-37,166-181`); the only live reference
  is the handler importing the manager. There are **no external consumers**
  (confirmed by the user). It is dead code with no persisted state to migrate
  (sessions were in-memory only).

- **Gen 2/3 — ACTIVE and already homologated to each other.** OAuth2 3LO via
  `O365OAuthManager` (`packages/ai-parrot/src/parrot/auth/o365_oauth.py`, PKCE) +
  `Office365Toolkit` + `O365OAuth2Provider`
  (`packages/ai-parrot/src/parrot/auth/oauth2/o365_provider.py:32`), all fronted by
  the **unified credential broker** (FEAT-264, `packages/ai-parrot/src/parrot/auth/broker.py`)
  with declarative auth kinds `obo|oauth2|static_key|mcp`, a ContextVar injection
  seam in `tools/abstract.py`, the KMS-signed `audit_ledger`, and
  `CanonicalIdentityMapper`.

The drift causes two concrete problems:

1. **Dead-code liability.** Gen 1 still ships an MSAL/Graph auth path and a REST
   surface that nobody calls, increasing audit/security surface and confusing
   contributors about which auth path is canonical.

2. **Capability gap.** The one genuinely useful thing Gen 1 did — **device-code /
   headless login** (no browser, e.g. CLI / server-side / containers) — has **no
   equivalent** in the broker. The factory only knows `obo|oauth2|static_key|mcp`
   (`broker.py:114-129`). A developer running an agent from the CLI against an
   O365-credentialed tool cannot authenticate without a browser-based 3LO flow.

**Who is affected:** developers/operators running AI-Parrot agents from a CLI or
headless context that need delegated O365 access; maintainers carrying the dead
Gen 1 surface.

## Constraints & Requirements

- **Delete Gen 1 entirely** — no compatibility shim, no data migration (no
  persisted state existed). Remove `o365_remote_auth.py`, `o365_auth.py`, and the
  commented blocks in `app.py`. Verify nothing else imports them.
- **Reuse the existing device-code engine** — `O365Interface.interactive_login()`
  (`packages/ai-parrot/src/parrot/interfaces/o365.py:763`) already implements
  `initiate_device_flow` + `acquire_token_by_device_flow` with `open_browser=False`
  and a `device_flow_callback`. Do NOT reimplement MSAL/Graph.
- **CLI surface only (for now).** Chat surfaces (A2A/Copilot/MSAgentSDK) are
  explicitly **out of scope**. The CLI may block-and-poll inline.
- **Extend the broker signal models** (`NeedsAuth` + `CredentialRequired`,
  `credentials.py:82-120`) with optional `user_code` / `verification_uri` /
  `expires_in` so device-code can be surfaced now and chat can adopt it later
  **without re-touching the model**. New fields must be optional / backward-compatible.
- **Canonical identity required.** CLI must supply an explicit Entra principal
  (email/OID) via env/config; normalize with `CanonicalIdentityMapper` so the vault
  key matches other surfaces (cross-surface reuse). Fail-closed if absent.
- **Silent refresh.** After the first device-code login, persist the refresh token
  and use silent acquisition on subsequent resolves — only re-prompt when refresh
  fails. Reuse the existing O365 token-cache/refresh machinery.
- **Respect Microsoft's `expires_in`** for the poll deadline (~15 min); clean
  cancellation on Ctrl-C with no half-written vault state.
- **Audit parity.** Device-code resolutions append to `audit_ledger` like every
  other kind (fingerprint only, never the token).
- **`device_code` added to the `AuthKind` Literal** and to the factory dispatch.
- Async-first, type hints, Google-style docstrings, `uv` + venv (project rules).

---

## Options Explored

### Option A: `device_code` auth kind — O365-specific resolver, inline blocking poll (Recommended)

Add `"device_code"` to `AuthKind` and a `_build_device_code()` branch in
`CredentialResolverFactory`. The new `O365DeviceCodeCredentialResolver`
(in `parrot/auth/oauth2/`, next to `workiq_provider.py`/`o365_provider.py`) wraps the
existing `O365Interface.interactive_login(open_browser=False, device_flow_callback=…)`.
On a vault miss its `resolve()` starts the device flow, surfaces
`verification_uri` + `user_code` (via the extended signal / printed by the CLI
surface), and **awaits** `acquire_token_by_device_flow` inline until success or
Microsoft's `expires_in`. On success it persists the token set to `VaultTokenSync`
keyed by the canonical identity and returns it. Subsequent resolves read the vault
and silently refresh through the existing O365 cache/refresh path. The signal models
gain optional `user_code` / `verification_uri` / `expires_in` fields (default
`None`) so the abstraction is future-proof for chat.

✅ **Pros:**
- Smallest blast radius that still homologates: reuses the device-code engine,
  the broker seam, `VaultTokenSync`, `CanonicalIdentityMapper`, and `audit_ledger`
  verbatim.
- Inline blocking poll sidesteps suspend-store / resume / card renderers entirely
  — those only matter for async chat surfaces, which are out of scope.
- Model extension is additive and optional → zero breakage for `obo/oauth2/static_key/mcp`.
- Leaves a clean seam for a future chat surface (just render the new fields + add a
  durable poller) without re-touching the model.

❌ **Cons:**
- The inline poll holds the calling coroutine for up to ~15 min — acceptable for an
  interactive CLI, but a non-interactive script must rely on the `expires_in`
  deadline / Ctrl-C to bail.
- Device-code background polling is inherently single-process (not multi-server
  safe), but that's fine because the scope is CLI/headless single-process.
- O365-specific (not a generic Entra device-flow resolver) — see Option C.

📊 **Effort:** Low (S, ~0.5–1 day): resolver + factory branch + model fields +
Gen 1 deletion. Gen 1 removal is trivial.

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `msal` | Device flow (`initiate_device_flow`, `acquire_token_by_device_flow`) | Already a dep; invoked inside `interactive_login()` — not called directly here |
| `azure-identity` / `msgraph` | Graph client + token credential | Already used by `O365Interface` |
| `pydantic>=2` | Optional fields on `NeedsAuth`/`CredentialRequired` | Core dep |

🔗 **Existing Code to Reuse:**
- `parrot/interfaces/o365.py:763` — `interactive_login(open_browser, device_flow_callback)` device-code engine.
- `parrot/auth/broker.py:66` — `CredentialResolverFactory.build()` dispatch + `_build_*` pattern.
- `parrot/auth/credentials.py:128` — `CredentialResolver` ABC (`resolve`/`get_auth_url`).
- `parrot/services/vault_token_sync.py:55` — `VaultTokenSync.store_tokens/read_tokens/delete_tokens`.
- `parrot/auth/identity.py` — `CanonicalIdentityMapper.to_canonical()`.
- `parrot/auth/oauth2/workiq_provider.py` — reference for an O365-backed resolver shape.

---

### Option B: Pure deletion — retire Gen 1, no device-code replacement

Just delete Gen 1 and accept that O365 from the CLI requires the existing
browser-based OAuth2 3LO (Gen 2/3). No new auth kind, no model change.

✅ **Pros:**
- Trivial; removes dead code immediately with near-zero risk.
- No new surface to test/maintain.

❌ **Cons:**
- Leaves the **headless/CLI capability gap** unaddressed — the user explicitly wants
  device-code for CLI. 3LO needs a browser + callback, which a headless box may not
  have.
- The user already decided to extend the model and add device-code, so this
  under-delivers.

📊 **Effort:** Low (trivial).

📦 **Libraries / Tools:** none.

🔗 **Existing Code to Reuse:** n/a (deletion only).

---

### Option C: Generic Entra/MSAL `device_code` resolver (provider-agnostic)

Same as A, but the resolver is a generic Entra device-flow strategy reusable by any
future Entra-backed provider (not just O365), parameterized by client_id/tenant/scopes.

✅ **Pros:**
- Future providers needing device-code (e.g. another MS service) reuse it for free.
- Cleaner separation between "device-flow mechanics" and "O365 specifics".

❌ **Cons:**
- Wider surface and more test matrix now, for a generalization nobody has asked for
  (YAGNI). The only concrete device-code need today is O365.
- Higher chance of leaking MSAL details into the broker core vs. delegating to the
  already-encapsulated `O365Interface`.

📊 **Effort:** Medium — generalization + broader tests.

📦 **Libraries / Tools:** same as A.

🔗 **Existing Code to Reuse:** same as A, minus the O365-specific delegation.

---

## Recommendation

**Option A** is recommended. It delivers exactly the decided scope (delete Gen 1 +
CLI-only `device_code` + extended model) at the lowest effort while reusing every
existing seam (`interactive_login`, broker factory, `VaultTokenSync`,
`CanonicalIdentityMapper`, `audit_ledger`). The inline blocking poll is the right
trade for a synchronous CLI and lets us avoid the durable-poller / suspend-resume /
card-renderer machinery that only async chat surfaces need — which is precisely why
Gen 1 grew its own session manager. By making the model fields **optional and
additive**, we leave a clean upgrade path to chat (render the fields + add a durable
poller) without re-opening the model. Option B under-delivers (ignores the CLI gap);
Option C over-builds a generalization nobody needs yet (YAGNI). If a second Entra
device-code consumer appears later, A's resolver can be promoted to C's generic form
with a focused refactor.

---

## Feature Description

### User-Facing Behavior

A developer/operator declares the O365 provider with `auth: device_code` on the
agent/manifest and supplies their Entra principal (email/OID) via env/config. When a
CLI-run tool with `credential_provider="o365"` needs access and no valid vault token
exists, the CLI prints a clear prompt:

```
To sign in, open https://microsoft.com/devicelogin and enter code: A1B2-C3D4
(waiting up to 15 minutes…)
```

The user completes login in any browser (even on another device). Once done, the
agent continues automatically — no code re-typing, no extra command. On subsequent
runs the token is silently refreshed from the vault; the user is not prompted again
until the refresh token itself expires or is revoked.

### Internal Behavior

1. **Config → broker.** `CredentialBroker.from_config()` sees
   `ProviderCredentialConfig(provider="o365", auth="device_code", options={...})`,
   and `CredentialResolverFactory._build_device_code()` constructs an
   `O365DeviceCodeCredentialResolver(o365_interface, vault, scope/options)`.
2. **Identity.** The CLI principal is normalized via
   `CanonicalIdentityMapper.to_canonical()`; absent identity → fail closed.
3. **Resolve (hit).** `resolve(channel, user_id)` reads `VaultTokenSync`; if a valid
   token exists, return it. If expired, attempt silent refresh through the existing
   O365 cache/refresh path; on success persist + return.
4. **Resolve (miss).** Start `interactive_login(open_browser=False,
   device_flow_callback=…)`; the callback yields `{verification_uri, user_code,
   expires_in, …}`, surfaced via the extended `NeedsAuth`/`CredentialRequired`
   fields (and printed by the CLI surface). `await` the device-flow completion
   inline up to `expires_in`.
5. **Persist + audit.** On success, store the token set in `VaultTokenSync` keyed by
   canonical identity; the broker appends an `audit_ledger` entry (fingerprint only).
   The ContextVar seam in `AbstractTool.execute()` injects the token; the tool reads
   it via `current_credential()`.

### Edge Cases & Error Handling

- **No identity supplied** → fail closed (`ValueError`-style), explicit message to
  set the principal env/config. Never key the vault anonymously.
- **Device flow expires** (`expires_in` elapsed) → clean error instructing retry; no
  partial vault write.
- **Ctrl-C during poll** → cancel the poll task, surface a cancellation, leave vault
  untouched.
- **Silent refresh fails** (revoked/expired refresh token) → fall back to a fresh
  device-code prompt.
- **Non-interactive context** (no TTY) → relies on `expires_in` deadline; document
  that device-code is for interactive/headless-with-operator use, not unattended CI.
- **Concurrent resolves for same user** → second caller should observe the first's
  result via vault once written (best-effort; single-process scope).

---

## Capabilities

### New Capabilities
- `o365-device-code-broker`: a `device_code` broker auth kind with an O365-specific
  resolver wrapping `interactive_login()`, CLI inline-poll, vault persistence,
  silent refresh, and audit.

### Modified Capabilities
- `unified-credential-broker` (FEAT-264): extend `AuthKind`, `NeedsAuth`,
  `CredentialRequired`, and `CredentialResolverFactory` with the device-code kind
  and optional surfacing fields.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/auth/credentials.py` | modifies | `AuthKind` += `"device_code"`; optional `user_code`/`verification_uri`/`expires_in` on `NeedsAuth` & `CredentialRequired` (backward-compatible) |
| `parrot/auth/broker.py` | extends | `_build_device_code()` branch + dispatch in `build()` |
| `parrot/auth/oauth2/o365_devicecode_provider.py` (new) | adds | `O365DeviceCodeCredentialResolver` |
| `parrot/interfaces/o365.py` | depends on | reuses `interactive_login()` / refresh; ideally no change |
| `parrot/services/vault_token_sync.py` | depends on | `store_tokens`/`read_tokens` for persistence |
| `parrot/auth/identity.py` | depends on | `CanonicalIdentityMapper.to_canonical()` |
| CLI run path / surface | extends | print `verification_uri`+`user_code` from the extended signal |
| `parrot/services/o365_remote_auth.py` | **removes** | Gen 1 manager (dead) |
| `parrot/handlers/o365_auth.py` | **removes** | Gen 1 handlers (dead) |
| `app.py` | modifies | delete commented Gen 1 wiring blocks |

---

## Code Context

### User-Provided Code
_None — scope provided as prose; all references below verified against the codebase._

### Verified Codebase References

#### Classes & Signatures
```python
# From parrot/auth/credentials.py:43
AuthKind = Literal["obo", "oauth2", "static_key", "mcp"]   # → add "device_code"

# From parrot/auth/credentials.py:82
class NeedsAuth(BaseModel):
    provider: str
    auth_url: str           # "Consent URL — NEVER a secret"
    auth_kind: AuthKind
    # → ADD (optional, default None): user_code, verification_uri, expires_in

# From parrot/auth/credentials.py:97
class CredentialRequired(Exception):
    def __init__(self, provider: str, auth_url: str, auth_kind: str) -> None: ...
    # attrs: .provider .auth_url .auth_kind
    # → ADD optional device-code attrs mirroring NeedsAuth

# From parrot/auth/credentials.py:128
class CredentialResolver(ABC):
    async def resolve(self, channel: str, user_id: str) -> Optional[Any]: ...   # line 132
    async def get_auth_url(self, channel: str, user_id: str) -> str: ...        # line 141
    async def is_connected(self, channel: str, user_id: str) -> bool: ...       # line 145

# From parrot/auth/credentials.py:46
class ProviderCredentialConfig(BaseModel):
    provider: str
    auth: AuthKind
    options: Dict[str, Any]

# From parrot/auth/broker.py:66
class CredentialResolverFactory:
    def __init__(self, deps: Optional[Dict[str, Any]] = None) -> None: ...      # line 98
    def build(self, cfg: ProviderCredentialConfig) -> CredentialResolver: ...   # line 101 (dispatch 114-129)
    def _build_obo(self, cfg, opts) -> CredentialResolver: ...                  # line 135
    def _build_oauth2(self, cfg, opts) -> CredentialResolver: ...               # line 165
    def _build_static_key(self, cfg, opts) -> CredentialResolver: ...           # line 184
    def _build_mcp(self, cfg, opts) -> CredentialResolver: ...                  # line 210
    # → ADD _build_device_code(self, cfg, opts)

# From parrot/auth/broker.py:316 (CredentialBroker)
def register(self, provider: str, resolver: CredentialResolver, auth_kind: str = "oauth2") -> None: ...   # line 329
def from_config(cls, configs: List[ProviderCredentialConfig], strict: bool = True, **deps) -> "CredentialBroker": ...  # line 355
async def resolve(self, provider: str, channel: str, user_id: str, **ctx) -> "ResolvedCredential | NeedsAuth": ...     # line 405

# From parrot/interfaces/o365.py:763
async def interactive_login(
    self,
    scopes: Optional[List[str]] = None,
    redirect_uri: str = "http://localhost",
    open_browser: bool = True,
    login_callback: Optional[Callable[[str], Optional[bool]]] = None,
    device_flow_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]: ...
# Internals: public_app.initiate_device_flow(scopes) (≈832) →
#            public_app.acquire_token_by_device_flow(flow) (≈854)

# From parrot/interfaces/o365.py:621
def acquire_token_on_behalf_of(self, user_assertion: str, scopes: Optional[List[str]] = None) -> Dict[str, Any]: ...

# From parrot/services/vault_token_sync.py:55
class VaultTokenSync:
    async def store_tokens(self, ...) -> ...: ...    # line 106
    async def read_tokens(self, ...) -> ...: ...     # line 141
    async def delete_tokens(self, ...) -> ...: ...   # line 176

# From parrot/tools/abstract.py:36
def current_credential() -> Optional[Any]: ...       # reads _CREDENTIAL_VAR (line 31)
# class AbstractTool (line 123): credential_provider: Optional[str] = None  (line 147)
```

#### Verified Imports
```python
from parrot.auth.credentials import (
    AuthKind, ProviderCredentialConfig, NeedsAuth, CredentialRequired,
    ResolvedCredential, CredentialResolver,
)                                                    # parrot/auth/credentials.py
from parrot.auth.broker import CredentialBroker, CredentialResolverFactory  # parrot/auth/broker.py
from parrot.interfaces.o365 import O365Client        # parrot/interfaces/o365.py (a.k.a. O365Interface)
from parrot.services.vault_token_sync import VaultTokenSync  # ai-parrot-server
from parrot.auth.identity import CanonicalIdentityMapper      # parrot/auth/identity.py
from parrot.tools.abstract import current_credential          # parrot/tools/abstract.py
```

#### Key Attributes & Constants
- `AbstractTool.credential_provider` → `Optional[str]` (parrot/tools/abstract.py:147)
- `O365OAuth2Provider.provider_id` → `"o365"` (parrot/auth/oauth2/o365_provider.py:43)
- `O365OAuth2Provider.default_scopes` includes `offline_access` (enables refresh) (o365_provider.py:46-57)

### Does NOT Exist (Anti-Hallucination)
- ~~`AuthKind` value `"device_code"`~~ — NOT present yet (only `obo|oauth2|static_key|mcp`, credentials.py:43). This feature adds it.
- ~~`NeedsAuth.user_code` / `NeedsAuth.verification_uri` / `NeedsAuth.expires_in`~~ — do NOT exist yet; this feature adds them (optional).
- ~~`CredentialResolverFactory._build_device_code`~~ — does NOT exist; to be added.
- ~~A generic `parrot/auth/device_flow.py` resolver~~ — does NOT exist (Option C would create one; not chosen).
- ~~`VaultTokenSync` arbitrary key-value API (`get(key)`/`set(key)`)~~ — NOT how it works; it is token-set based (`store_tokens`/`read_tokens`/`delete_tokens` keyed by user). Inline `_VaultStaticKeyResolver` in broker.py uses a different `vault` shape — confirm the exact persistence contract during spec.
- ~~Any live consumer of `/api/v1/o365/auth/sessions`~~ — none in-repo; `app.py` wiring is fully commented.

---

## Token-Store Standard (resolved 2026-07-01)

Investigation found **three unsynchronized Entra token stores** in the codebase:

1. **MSAL `SerializableTokenCache` in Redis** — internal to
   `O365Client.interactive_login()` (the device-code engine); per-app, not
   per-canonical-user. Engine-internal only.
2. **`O365OAuthManager` via `vault_utils`** (`oauth2_base.py`) — the OAuth2 3LO
   path. Persists a JSON token-set blob under `o365:{channel}:{user_id}` + a Redis
   cache; full transparent refresh with distributed lock in `get_valid_token()`
   (`oauth2_base.py:461`).
3. **`VaultTokenSync` flat `{provider}:{field}` keys** (`o365:access_token`, …) —
   what `WorkIQOBOCredentialResolver` **reads** (`workiq_provider.py:140`).

**Critical gap found:** grep for writers of the flat `o365:*` keys returns **none**
in the O365 path — the 3LO flow (#2) writes to `vault_utils`, never to
`VaultTokenSync`. There is a `telegram/post_auth_jira.py` bridge for Jira but **no
`post_auth_o365` equivalent**. So WorkIQ OBO's source token (`o365:access_token`) is
currently unwritten by any live path. This feature's device-code resolver becomes the
**first writer** of the canonical keys and **fixes the contract**.

**Standard (decided):**
- **Canonical per-user Entra store = `VaultTokenSync`, prefix `o365`**, fixed field
  contract: `access_token`, `refresh_token`, `expires_at` (epoch int), `scope`,
  `id_token` (optional), `tenant_id`. `user_id` = canonical identity
  (`CanonicalIdentityMapper`). This is exactly what WorkIQ OBO consumes → device-code
  ⇄ OBO interoperate for free.
- **Refresh = a stateless public primitive on `O365OAuthManager`** (promote
  `_refresh_request`, `o365_oauth.py:140`, to e.g. `async def
  refresh_access_token(refresh_token) -> dict`); the device-code resolver calls it and
  re-persists to `VaultTokenSync`. One Entra refresh code path, one store. The 3LO
  `get_valid_token()` keeps its own internal refresh untouched.
- **CLI surface = inline blocking poll**: `resolve()` does NOT raise
  `CredentialRequired` on the happy path — it blocks, prints `verification_uri` +
  `user_code` via `device_flow_callback`, persists, and returns the token.
  `CredentialRequired` (with the extended `user_code`/`verification_uri`/`expires_in`
  fields) is reserved for failure/timeout and for the future chat surface. Entry
  point: a CLI bootstrap reads the Entra principal from env (`O365_PRINCIPAL`),
  normalizes it, and threads `_cred_channel="cli"` + `_cred_user_id=<canonical>` +
  `_broker` into the agent run.

**Follow-up (out of scope here):** add a `post_auth_o365` bridge so the 3LO flow ALSO
writes the canonical `o365:*` keys — completing the homologation so a user who
authenticated via 3LO (browser) can also use WorkIQ OBO. Tracked as an open question.

---

## Parallelism Assessment

- **Internal parallelism**: Two largely independent strands —
  (1) **Gen 1 deletion** (`o365_remote_auth.py`, `o365_auth.py`, `app.py` blocks),
  and (2) **device-code build** (model extension + factory branch + resolver + CLI
  surfacing). The model extension is a small shared prerequisite for the resolver.
- **Cross-feature independence**: Touches FEAT-264 broker core files
  (`credentials.py`, `broker.py`). Coordinate with any in-flight broker work to avoid
  conflicts on those two files. Gen 1 files are isolated (server package) and conflict
  with nothing.
- **Recommended isolation**: `per-spec` (single worktree, sequential tasks).
- **Rationale**: Effort is Low (S) and the device-code tasks share the model
  extension; the deletion is trivial and best done in the same worktree to keep the

…(truncated)…
