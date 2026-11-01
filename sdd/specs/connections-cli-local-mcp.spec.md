---
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-tools, ai-parrot-integrations, ai-parrot-server, docs]
tags: [oauth2, connections, cli, mcp-local, stdio, agentd, device-code, principal]
reuse_feature_id: FEAT-774   # reserved by /sdd-proposal for this slug (connections-cli-local-mcp); intentional reuse, not a second reservation
depends_on: [FEAT-773]
---

# Feature Specification: Connections for CLI agents and local MCP toolkits (S-4 of FEAT-773)

**Feature ID**: FEAT-774
**Date**: 2026-10-30
**Author**: Jesus Lara (with Claude Fable 5.1)
**Status**: approved
**Target version**: 1.4.0

> **Source**: proposal `sdd/proposals/connections-cli-local-mcp.proposal.md` (FEAT-774, status `accepted`,
> research state `sdd/state/FEAT-774/`), the S-4 sub-spec declared by the FEAT-773 spec rev 0.2
> (`sdd/specs/delegated-auth-connections.spec.md` §1 Non-Goals). Decisions U1–U5 were taken by the user in the
> proposal's Q&A and are carried forward verbatim in §8; they are not re-opened here.
>
> **Dependency**: every `Principal` / `PrincipalResolver` / `CredentialStore` / `AuthRequiredPayload` /
> `ConnectionsHandler` symbol below is defined by FEAT-773 (S-1) and does not exist on `dev` yet. Contract
> entries for them cite the S-1 spec line (`verified: delegated-auth-connections.spec.md:NN`) and are marked
> **planned**; `/sdd-task` for FEAT-774 runs only after FEAT-773 has merged and MUST re-anchor them to code.

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-773 gives every connection a Navigator-keyed principal and a channel-neutral API, but only for surfaces that
live inside the aiohttp server. Three CLI-side surfaces are left out and today carry no platform identity at all:

- **`parrot agent` standalone** sends `--user <string>` or the literal `cli-user` as the user id, and builds a
  `PermissionContext` only for O365 device-code bots, keyed by an Entra id read from the `O365_PRINCIPAL`
  environment variable (`cli/agent_repl.py:218-247`, `cli/identity.py:76`). In `--server` mode identity is a
  bearer the user pastes by hand (`--token` / `PARROT_SERVER_TOKEN`). There is no `parrot login`.
- **`parrot mcp-local` stdio toolkit servers** that Claude Code and Codex launch carry no principal, broker or
  vault: `MCPToolAdapter.execute` calls the tool's private `_execute` directly (`mcp/adapter.py:79`), so the
  FEAT-264 credential gate never runs, and the only secret channel is `ToolkitSection.env`
  (`mcp/toolkit_config.py:57`). FEAT-485 forbids these processes from importing server code.
- **agentd** binds an OS-username principal per Unix-socket connection (`agentd/server.py:355`) with a
  service-identity fallback; neither is a Navigator user.

The only CLI 3LO precedent, FEAT-696 `parrot jiratoolkit auth`, works end to end (manual paste of the redirected
URL, CSRF state check, 0600 token file) but is single-user (`local:cli`), Jira-only and stores refresh tokens on
the laptop outside the Identity Vault. Research also found that navigator-auth 0.28.7 already ships an OAuth 2.1
authorization server with the RFC 8628 device grant, which removes the need to invent a CLI login protocol.

### Goals

- **G1 — One CLI login.** `parrot login` obtains a navigator-auth bearer through the RFC 8628 device grant
  (public client `parrot-cli`, PKCE S256) or the browser flow and stores it in a 0600 login file under
  `~/.parrot/`; `parrot logout` revokes and wipes it (U1).
- **G2 — Navigator principal on every CLI surface.** A `CliPrincipalResolver` (S-1 `PrincipalResolver`) turns the
  login into `Principal(channel="cli" | "agentd")` with the Navigator `user_id`, tenant and server-issued roles;
  `parrot agent` standalone, `parrot mcp-local` and agentd all carry it; `--server` mode stays bearer-owned (S12).
- **G3 — Connections usable out of process without the vault.** An aiohttp-client-only `RemoteConnectionResolver`
  pulls **access tokens only** from the server into an encrypted local cache; refresh never leaves the server
  (U2 + S5); the Identity Vault remains the durable owner.
- **G4 — The credential gate is real in stdio servers.** `MCPToolAdapter` routes calls through
  `AbstractTool.execute` with a process-scoped `ToolExecutionContext`, so `credential_provider` tools resolve
  through the broker and a missing connection becomes one structured MCP auth-required result (S1, S2).
- **G5 — Connect from the CLI.** `parrot connect <provider>` and the `/connect` slash command start the S-1
  connect flow for `channel="cli"`, open or print the authorize URL, complete by polling or by pasting the
  redirected URL, and pull the token into the cache (U3).
- **G6 — Generic device code.** A typed RFC 8628 client engine (`DeviceAuthorization`, polling state machine) is
  used both by `parrot login` and, through a `device_authorization_url` descriptor field and two server endpoints,
  for providers that support the grant (U4, S8).
- **G7 — agentd resolves the Navigator principal** from the connecting OS user's own login file, with ownership,
  mode and symlink checks, only against an operator-pinned Navigator server (off until
  `AGENTD_LOGIN_FILE_SERVER_URL` is set) and read-only, falling back to today's behaviour (U5, S11).
- **G8 — Jira converges.** `JiraToolkit` drops the fixed `local:cli` identity; `parrot jiratoolkit auth` becomes an
  alias of `parrot connect jira`; the Jira-only local token file is removed.

### Non-Goals (explicitly out of scope)

- MCP **client-side** OAuth (parrot calling remote MCP servers): `parrot.mcp.oauth` token stores,
  `VaultMCPTokenStorage`, `MCPOAuth2Config`, `MCPOAuth2Provider` and the `mcp:oauth:*` key family are untouched.
- The HTTP MCP server principal guard, PBAC guard, session store and transports (FEAT-477); the `OAUTH2_EXTERNAL`
  introspection path is not the CLI login path (S6).
- The agentd UDS transport and SO_PEERCRED binding themselves; only the login-file step is added (M9).
- FEAT-485 rules: stdio servers never import ai-parrot-server, aiohttp-server or navconfig; stdout stays a pure
  JSON-RPC channel; the host's permission prompt remains the human gate for tool confirmation.
- S-1 internals (`AbstractOAuth2Manager`, `IntegrationsService` core, `ConnectionsHandler` base routes): consumed
  over HTTP and extended only by the endpoints in M3 and the additive descriptor field / event kind in M8 / M3.
- O365 store consolidation (`VaultTokenSync o365:*`) and the WorkIQ OBO path — S-3a. S-4 only makes the O365
  device-code prompt stdio-safe and routes the CLI through the generic engine (M8).
- A local full 3LO (client secret on the laptop) — rejected in the proposal's U2 follow-up; the server completes
  every exchange.
- Telegram, Slack, Teams and web consumers — S-2 / S-3a / S-3b.
- OS-keyring-backed cache keys and the agentd privilege model — decided in §8 (Q2, Q3), not assumed here.

---

## 2. Architectural Design

### Overview

**Login (M1).** `parrot login --server <url>` discovers `/.well-known/oauth-authorization-server`
(navigator-auth `metadata.py:42-54`), posts to `device_authorization_endpoint` as the public client `parrot-cli`
with a PKCE S256 challenge (required for public clients, `backend.py:2528-2540`), prints `verification_uri` +
`user_code` (and opens the browser unless `--no-browser`), then polls `token_endpoint` with
`grant_type=urn:ietf:params:oauth:grant-type:device_code` honouring `authorization_pending` / `slow_down` /
`expired_token` / `access_denied` (`devicecode.py:poll_decision`). The resulting access JWT (1 h by default,
`OAUTH_ACCESS_TOKEN_TTL`) and rotating refresh token (30 d, `OAUTH_REFRESH_TOKEN_TTL`, `OAUTH_REFRESH_ROTATION`)
are written to `~/.parrot/login.json` (0600, lock file, atomic write — the `LocalJiraTokenStore` pattern) together
with the identity read from `/oauth2/userinfo` (`sub`, optional `email`) and a random 32-byte `cache_key`.
`parrot logout` posts to `/oauth2/revoke`, deletes the login file and the connection cache. The server side needs
the navigator-auth `Oauth2Provider` backend enabled and a static public client `parrot-cli` with
`allowed_grant_types` ⊇ {device_code, refresh_token}; both are deployment prerequisites recorded in §7/§8, and
`parrot login` fails loudly (exit 2, message naming the missing endpoint or client) when they are absent.

**Principal (M2).** `CliPrincipalResolver` implements S-1's `PrincipalResolver`. For `channel in {"cli", "agentd"}`
it loads the login record, refreshes the access token when expired (single-flight), calls
`GET /api/v1/connections/me` (M3) and returns `Principal(user_id, canonical_identity=email, tenant_id, channel,
channel_user_id=<login user_id | OS username>)` plus the server-issued `roles`/`scopes`. `build_cli_permission_context(principal, roles)`
wraps S-1's `build_principal_context` with the real tenant and the roles frozenset (S7). Without a login record it
returns `None` and callers fall back exactly as today (`cli-user`, no gate). The `O365_PRINCIPAL` Entra bootstrap
is removed (hard cut, no shim).

**Server endpoints (M3).** Four additions to S-1's `ConnectionsHandler`, all behind navigator-auth
(`@is_authenticated`, so a `parrot-cli` bearer is accepted by `Oauth2Provider.authenticate`, `backend.py:2833-2881`):
`GET /api/v1/connections/me` (whoami: `user_id` via `resolve_user_id`, tenant, email, roles, scopes);
`POST /api/v1/connections/{provider}/token` (access token + `expires_at` + `scopes` + `account_id`; PBAC
`integration:use`; audit event `connection.token_pulled`; refresh server-side when needed; 409 `not_connected`
with the S-1 `AuthRequiredPayload` body when no active connection exists);
`POST /api/v1/connections/{provider}/complete` (paste fallback: `{code, state}` → S-1 `manager.handle_callback`
→ `persist_credential`; the nonce check is S-1's); and the device pair
`POST /api/v1/connections/{provider}/device/start` / `POST .../device/poll` (M8).

**Cache and remote resolver (M4).** `ConnectionCache` is an AES-GCM-encrypted JSON file
(`~/.parrot/connections.cache`, 0600) keyed by the login's `cache_key`; every read/write runs in
`asyncio.to_thread`, with a per-provider `asyncio.Lock` for single-flight refresh (S9). `RemoteConnectionResolver`
(a `CredentialResolver`) answers `resolve(channel, user_id)` from the cache when `expires_at − skew > now`,
otherwise pulls through `ServerConnectionsClient.pull_token`; `not_connected` → `None`, so the broker yields
`NeedsAuth` whose `auth_url` comes from `get_auth_url` → `start_connect(channel)`. `build_cli_broker(login,
providers)` registers one resolver per `credential_provider` the loaded tools declare.

**Stdio binding (M5).** `MCPServerBase` and `MCPToolAdapter` accept an optional `ToolExecutionContext`
(permission context + broker). `MCPToolAdapter.execute` calls `AbstractTool.execute(**arguments,
_permission_context=…, _broker=…, _cred_channel="cli", _cred_user_id=…)` instead of `_execute` (S1), so the
FEAT-264 gate, lifecycle hooks and `ToolkitTool._pre_execute` run. `AuthorizationRequired` and
`CredentialRequired` are caught and rendered as one envelope: `isError: true`, one text item, and
`structuredContent = AuthRequiredPayload.model_dump()` (S2). `create_toolkit_mcp_server` resolves the principal and
broker at process start from the login file (default path or `PARROT_LOGIN_FILE`), under the existing stderr
redirect; without a login the server behaves exactly as today.

**Connect from the CLI (M6).** `parrot connect <provider>` records `started_at`, calls `start_connect(channel="cli")`
(auth URL + `state`), opens/prints the URL, then polls `GET /api/v1/connections/{provider}` every 2 s until
`status == "active"` and `connected_at >= started_at`, or until the nonce TTL (600 s) lapses; `--paste` or the
timeout prompt accepts the redirected URL, verifies `state` with `hmac.compare_digest` and posts `{code, state}` to
`/complete` (S10). On success it pulls the token into the cache. `/connect`, `/connections` and `/disconnect` are
REPL built-ins using `CommandContext.suspend()` for the prompt.

**REPL identity (M7).** In standalone mode `_run` resolves the principal through M2 when a login exists, sets
`REPLConfig.user_id` to the Navigator id, builds the permission context and a CLI broker for the bot's declared
providers; `--user` together with a login is refused (identity comes from the login). In `--server` mode the login's
access token is the default bearer and nothing local is built (S12).

**Generic device code (M8).** `parrot/auth/oauth2/device_code.py` holds the pure client engine; S-1's
`OAuth2ProviderDescriptor` gains `device_authorization_url: Optional[str]`; `StandardOAuth2Manager` gains
`start_device_authorization` / `complete_device_authorization`; the server keeps the provider `device_code` under a
short-lived Redis handle and polls the provider once per CLI poll. `O365DeviceCodeCredentialResolver`'s default
prompt moves to stderr; the CLI path for O365 becomes `parrot connect o365 --device`.

**agentd (M9).** `_resolve_identity` adds a step between peercred and the fallback: read the peer user's
`~/.parrot/login.json` (owner == uid, mode 0600, `O_NOFOLLOW`, via `asyncio.to_thread`) and resolve the Navigator
principal with `channel="agentd"`; `identity_source` becomes `"login_file"`. The file is user-writable, so only its
bearer is trusted: the step is off until the operator pins a server with `AGENTD_LOGIN_FILE_SERVER_URL`, a record
naming another server is ignored, the principal is always requested from the pinned URL, and the store is opened
read-only (no refresh, lock, temp file or rewrite in the peer's directory). Any failure keeps today's behaviour.

**Jira (M10).** `oauth2_local` and `FileTokenCredentialResolver` are removed; `JiraToolkit._pre_execute` requires a
`PermissionContext` for every 3LO call; `parrot jiratoolkit auth|status|logout` delegate to `parrot connect jira`,
`parrot connections`, `parrot disconnect jira`; `parse_pasted_redirect` moves to core.

### Component Diagram

```
 ~/.parrot/login.json ──LoginStore (M1)──┐                      navigator-auth Oauth2Provider
   access/refresh/cache_key/identity     │  device grant / refresh / revoke ───►  /oauth2/device_authorization
                                         │                                        /oauth2/token  /oauth2/userinfo
                                         ▼
                          CliPrincipalResolver (M2) ──GET /api/v1/connections/me──►  ai-parrot-server
                                         │                                           ConnectionsHandler (S-1 + M3)
                 ┌───────────────────────┼─────────────────────────┐                  /token  /complete  /device/*
                 ▼                       ▼                         ▼                  IntegrationsService (S-1)
   parrot agent --standalone      parrot mcp-local            agentd _resolve_identity         │
   _run → REPLConfig (M7)         create_toolkit_mcp_server   (peer uid → login file, M9)      │ CredentialStore
                 │                 ToolExecutionContext (M5)        │                           ▼
                 └────────────┬────────────┘                        │                   Identity Vault (owner)
                              ▼                                     ▼
                     CredentialBroker ── RemoteConnectionResolver (M4) ── ConnectionCache (AES-GCM, 0600)
                              │                 │ pull access token only  (POST .../{provider}/token)
                              ▼                 ▼
                   AbstractTool.execute   NeedsAuth → CredentialRequired → AuthRequiredPayload
                                                         │
                     parrot connect / /connect (M6) ◄────┘  start_connect(channel=cli) → poll | paste → /complete
                     parrot login (M1) ◄── device_code.py engine (M8) ──► provider device grant via server
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| navigator-auth `Oauth2Provider` (`backends/oauth2/backend.py:258`) | uses (HTTP client) | `parrot login` = RFC 8628 client of its device endpoint (`:292`, `:364-372`), token endpoint (`:333`, `_handle_device_code :2105`), userinfo (`:2194`), revoke (`:347`); its `authenticate` (`:2833`) validates the CLI bearer on API routes |
| S-1 `Principal`, `PrincipalResolver`, `build_principal_context` | implements / uses | `CliPrincipalResolver`; `channel in {cli, agentd}` (S3) |
| S-1 `IntegrationsService.start_connect(channel=…)`, `status`, `persist_credential`, `disconnect` | extends | M3 adds `pull_access_token`, `complete_connect`, `whoami`; device start/poll |
| S-1 `ConnectionsHandler` (`handlers/connections.py`) + `manager.py` route block | extends | 5 new routes under `/api/v1/connections` |
| S-1 `AuthRequiredPayload` + `to_payload()` on both exceptions | uses | the MCP envelope and the `not_connected` 409 body |
| S-1 `OAuth2ProviderDescriptor`, `StandardOAuth2Manager` | extends (additive) | `device_authorization_url`; device start/complete methods |
| S-1 `ConnectionEventKind` / `ConnectionEventPublisher` | extends (additive) | new kind `connection.token_pulled` |
| `CredentialBroker.register(provider, resolver, auth_kind)` (`broker/core.py:81`) | uses | `build_cli_broker` |
| `CredentialResolver` ABC (`credentials.py:162`) | implements | `RemoteConnectionResolver`, `DeviceCodeCredentialResolver` |
| `AbstractTool.execute` kwargs `_permission_context`, `_broker`, `_cred_channel`, `_cred_user_id` (`tools/abstract.py:939, 950-952`) | uses | fed by `ToolExecutionContext.exec_kwargs()` |
| `MCPToolAdapter`, `MCPServerBase.register_tool` (`mcp/adapter.py:19/59`, `server_base.py:68-78`) | modifies | execution context plumbing + auth envelope |
| `create_toolkit_mcp_server`, `mcp_local` (`toolkit_server.py:137`, `local_cli.py:167`) | modifies | principal/broker at process start; `--login-file` |
| `toolkit_mcp_json_entry` / `toolkit_mcp_block` (`claude_code/assets.py:159`, `codex/assets.py:63`) | modifies | pass `PARROT_LOGIN_FILE` through when set at install time |
| `cli._lazy_commands` (`cli/__init__.py:109-141`) | modifies | `login`, `logout`, `whoami`, `connect`, `connections`, `disconnect` |
| `agent_repl._run`, `REPLConfig`, `TurnRunner._identity_kwargs` | modifies / unchanged | M7; `_identity_kwargs` keeps its shape |
| `SlashCommandDispatcher._register_builtins` (`commands.py:187-211`) | modifies | `/connect`, `/connections`, `/disconnect` |
| `JsonRpcUnixServer._resolve_identity`, `ServiceIdentityConfig` (`agentd/server.py:323`, `config.py:131`) | modifies | login-file step; `login_file_lookup` flag |
| `JiraToolkit` (`jiratoolkit.py:927, 1338-1350`), `jira_cli.py`, `jira_local_auth.py` | modifies / deletes | M10 |
| `O365DeviceCodeCredentialResolver._default_prompt_callback` (`o365_devicecode_provider.py:57`) | modifies | stderr, never stdout |
| `parrot.security.vault_utils` AES-GCM helpers (used by `mcp/oauth.py:81-95` `VaultTokenStore`) | uses | cache encryption primitives (core, no server import) |

### Data Models

```python
# packages/ai-parrot/src/parrot/cli/login.py  (new, M1)
class LoginRecord(BaseModel):
    """Contents of ~/.parrot/login.json (0600). Never logged."""
    server_url: str
    client_id: str = "parrot-cli"
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "Bearer"
    expires_at: float                      # epoch seconds (access token)
    scopes: List[str] = []
    user_id: str                           # navigator-auth userinfo `sub` (Navigator user_id as str)
    email: Optional[str] = None
    tenant_id: Optional[str] = None
    roles: List[str] = []                  # server-issued (GET /api/v1/connections/me)
    cache_key: str                         # base64url 32 random bytes; key for ConnectionCache (S4)
    issued_at: float

# packages/ai-parrot/src/parrot/auth/oauth2/device_code.py  (new, M8)
class DeviceAuthorization(BaseModel):
    """RFC 8628 §3.2 response."""
    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: Optional[str] = None
    expires_in: int
    interval: int = 5

class DeviceCodeError(RuntimeError):
    """Terminal RFC 8628 outcome: `code` in {expired_token, access_denied, invalid_grant, timeout}."""
    code: str

# packages/ai-parrot/src/parrot/auth/oauth2/local_cache.py  (new, M4)
class CachedConnection(BaseModel):
    provider: str
    access_token: str
    expires_at: float
    scopes: List[str] = []
    account_id: str = ""
    pulled_at: float

# packages/ai-parrot/src/parrot/auth/oauth2/remote_client.py  (new, M4)
class WhoAmI(BaseModel):                   # GET /api/v1/connections/me
    user_id: str
    tenant_id: Optional[str] = None
    canonical_identity: Optional[str] = None
    email: Optional[str] = None
    roles: List[str] = []
    scopes: List[str] = []

class PulledToken(BaseModel):              # POST /api/v1/connections/{provider}/token
    provider: str
    access_token: str                      # NEVER a refresh token (S5)
    expires_at: float
    scopes: List[str] = []
    account_id: str = ""

class ConnectAttempt(BaseModel):           # CLI-side correlation (S10); never stored server-side
    provider: str
    state: str
    auth_url: str
    started_at: float
    expires_in: int = 600

# packages/ai-parrot/src/parrot/mcp/adapter.py  (M5)
@dataclass(frozen=True)
class ToolExecutionContext:
    """Process-scoped identity for stdio servers; None keeps today's behaviour."""
    permission_context: Optional[Any] = None      # parrot.auth.permission.PermissionContext
    broker: Optional[Any] = None                  # parrot.auth.broker.CredentialBroker
    channel: str = "cli"
    def exec_kwargs(self) -> Dict[str, Any]: ...  # {_permission_context, _broker, _cred_channel, _cred_user_id}

# MCP auth-required envelope (M5, S2) — returned by MCPToolAdapter.execute
# {
#   "isError": true,
#   "content": [{"type": "text", "text": "<provider> authorization required — run `parrot connect <provider>` or open <auth_url>"}],
#   "structuredContent": AuthRequiredPayload.model_dump(exclude_none=True)   # S-1 M5 model, all fields preserved
# }

# S-1 additive changes (M3, M8)
ConnectionEventKind = Literal["connection.completed", "connection.revoked", "connection.refresh_failed",
                              "connection.token_pulled"]          # + token_pulled (audit of every pull)
class OAuth2ProviderDescriptor(BaseModel):
    device_authorization_url: Optional[str] = None                 # RFC 8628 §3.1 endpoint; None = grant unsupported
```

### New Public Interfaces

```python
# parrot/cli/login.py (M1)
class LoginStore:
    def __init__(self, path: Optional[Path] = None) -> None: ...        # default ~/.parrot/login.json, env PARROT_LOGIN_FILE
    @classmethod
    def for_uid(cls, uid: int) -> "LoginStore": ...                      # pwd.getpwuid(uid).pw_dir / .parrot/login.json (M9)
    def load_optional(self) -> Optional[LoginRecord]: ...                 # None when absent; raises LoginFileError on bad mode/owner
    def save(self, record: LoginRecord) -> None: ...                      # atomic, 0600, lock file
    def delete(self) -> bool: ...
async def refresh_login(record: LoginRecord, session: aiohttp.ClientSession) -> LoginRecord: ...
# click commands exposed as module attributes: login, logout, whoami

# parrot/cli/principal.py (M2)
class CliPrincipalResolver:                                                # S-1 PrincipalResolver
    def __init__(self, store: LoginStore, client: "ServerConnectionsClient") -> None: ...
    async def resolve(self, channel: str, channel_user_id: str) -> Optional[Principal]: ...
    async def resolve_with_roles(self, channel: str, channel_user_id: str) -> Optional[Tuple[Principal, frozenset[str]]]: ...
def build_cli_permission_context(principal: Principal, *, roles: frozenset[str] = frozenset()) -> PermissionContext: ...

# parrot/auth/oauth2/remote_client.py (M4)
class ServerConnectionsClient:
    def __init__(self, store: LoginStore, *, session: Optional[aiohttp.ClientSession] = None) -> None: ...
    async def me(self) -> WhoAmI: ...
    async def list(self) -> List[Dict[str, Any]]: ...
    async def status(self, provider: str) -> Dict[str, Any]: ...
    async def start_connect(self, provider: str, *, channel: str = "cli", scopes: Optional[List[str]] = None) -> ConnectAttempt: ...
    async def complete(self, provider: str, *, code: str, state: str) -> Dict[str, Any]: ...
    async def pull_token(self, provider: str) -> PulledToken: ...         # raises NotConnected(payload: AuthRequiredPayload)
    async def disconnect(self, provider: str) -> None: ...
    async def device_start(self, provider: str) -> Dict[str, Any]: ...
    async def device_poll(self, provider: str, handle: str) -> Dict[str, Any]: ...

# parrot/auth/oauth2/local_cache.py (M4)
class ConnectionCache:
    def __init__(self, path: Path, key: bytes) -> None: ...
    async def get(self, provider: str) -> Optional[CachedConnection]: ...
    async def put(self, entry: CachedConnection) -> None: ...
    async def delete(self, provider: Optional[str] = None) -> None: ...
class RemoteConnectionResolver(CredentialResolver):
    def __init__(self, provider: str, *, cache: ConnectionCache, client: ServerConnectionsClient, skew_s: int = 60) -> None: ...
    async def resolve(self, channel: str, user_id: str) -> Optional[str]: ...
    async def get_auth_url(self, channel: str, user_id: str) -> str: ...
def build_cli_broker(store: LoginStore, providers: Iterable[str], *, client: Optional[ServerConnectionsClient] = None) -> CredentialBroker: ...

# parrot/auth/oauth2/device_code.py (M8)
async def discover_authorization_server(session, issuer: str) -> Dict[str, Any]: ...        # /.well-known/oauth-authorization-server
async def request_device_authorization(session, url: str, *, client_id: str, scopes: Sequence[str],
                                       code_challenge: Optional[str] = None) -> DeviceAuthorization: ...
async def poll_device_token(session, token_url: str, *, client_id: str, authorization: DeviceAuthorization,
                            code_verifier: Optional[str] = None, timeout_s: Optional[int] = None,
                            on_wait: Optional[Callable[[int], None]] = None) -> Dict[str, Any]: ...
def make_pkce_pair() -> Tuple[str, str]: ...                                                 # (verifier, S256 challenge)

# parrot/mcp/adapter.py (M5)
class MCPToolAdapter:
    def __init__(self, tool: AbstractTool, *, execution_context: Optional[ToolExecutionContext] = None) -> None: ...
def auth_required_result(payload: AuthRequiredPayload) -> Dict[str, Any]: ...

# ai-parrot-server handlers/connections.py (M3) — routes added to S-1's ConnectionsHandler
#   GET  /api/v1/connections/me
#   POST /api/v1/connections/{provider}/token
#   POST /api/v1/connections/{provider}/complete          body: {code, state}
#   POST /api/v1/connections/{provider}/device/start
#   POST /api/v1/connections/{provider}/device/poll       body: {handle}
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: `parrot login` / `LoginStore` | no | — | token handling + device-grant UX against a live IdP; thinking model owns error paths and the file format |
| M2: `CliPrincipalResolver` | yes | S-1 `PrincipalResolver` Protocol; `build_principal_context` with explicit tenant + roles; `None` without login | — |
| M3: server endpoints | no | — | security endpoints (token vending, paste completion); PBAC + audit decisions |
| M4: cache + remote resolver + broker builder | no | — | AES-GCM key handling, single-flight, fail-closed semantics |
| M5: stdio execution context + auth envelope | yes | `ToolExecutionContext.exec_kwargs()` fixed; `AbstractTool.execute` route; envelope shape fixed in §2 | — |
| M6: `parrot connect` + slash commands | yes | poll/paste algorithm fixed in §2; `parse_pasted_redirect` moved verbatim | — |
| M7: REPL identity regimes | no | — | three identity regimes interact (login, `--user`, `--server`); thinking model owns the refusal matrix |
| M8: generic device-code engine + descriptor field + device endpoints | no | — | protocol state machine; server-side device handle lifecycle |
| M9: agentd login-file step | no | — | privilege and filesystem checks (S11) |
| M10: Jira convergence | yes | remove `oauth2_local`; alias commands; tests listed | — |
| M11: docs + validation | yes | doc outline fixed below | — |

### Module 1: `parrot login` / `parrot logout` / `parrot whoami` and `LoginStore`
- **Path**: `packages/ai-parrot/src/parrot/cli/login.py` (new); `packages/ai-parrot/src/parrot/cli/__init__.py` (modify `_lazy_commands`)
- **Responsibility**: device-grant login against navigator-auth (G1); login file lifecycle; token refresh helper
  used by M2/M4; `whoami` prints the identity from `GET /api/v1/connections/me`.
- **Depends on**: M8 (`discover_authorization_server`, `request_device_authorization`, `poll_device_token`,
  `make_pkce_pair`); M4 `ServerConnectionsClient.me` (for `whoami` and to fill `roles`).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/cli/login.py  (new)
  DEFAULT_LOGIN_PATH = Path("~/.parrot/login.json")          # env PARROT_LOGIN_FILE overrides (pattern: jira_local_auth.py:24)
  DEFAULT_CLIENT_ID = "parrot-cli"                          # env PARROT_CLI_CLIENT_ID
  class LoginFileError(RuntimeError):
      """Login file unreadable, wrong owner/mode, or a symlink (fail closed)."""
  class LoginStore:
      def __init__(self, path: Optional[Path] = None) -> None: ...
      @classmethod
      def for_uid(cls, uid: int) -> "LoginStore":
          """pwd.getpwuid(uid).pw_dir / '.parrot/login.json'; used by agentd (M9)."""
      def load_optional(self, *, expected_uid: Optional[int] = None) -> Optional[LoginRecord]:
          """None when the file is absent. Opens with O_NOFOLLOW; requires mode 0600 and owner == expected_uid (when given)."""
      def save(self, record: LoginRecord) -> None:
          """Atomic write under a 0600 lock file (pattern: jira_local_auth.py:49-62, 95-106)."""
      def delete(self) -> bool: ...
  async def refresh_login(record: LoginRecord, session: aiohttp.ClientSession) -> LoginRecord:
      """grant_type=refresh_token at the discovered token_endpoint; rotation keeps the new refresh token; raises LoginExpired on invalid_grant."""
  @click.command("login")
  @click.option("--server", envvar="PARROT_SERVER_URL", required=True)
  @click.option("--client-id", envvar="PARROT_CLI_CLIENT_ID", default=DEFAULT_CLIENT_ID)
  @click.option("--scopes", default=None)
  @click.option("--no-browser", is_flag=True, default=False)
  def login(server: str, client_id: str, scopes: Optional[str], no_browser: bool) -> None:
      """Discover the AS, run the device grant (PKCE S256), print verification_uri + user_code, poll, call userinfo + /me, save."""
  @click.command("logout")
  def logout() -> None:
      """POST /oauth2/revoke (best effort), delete login file and ConnectionCache."""
  @click.command("whoami")
  def whoami() -> None: ...
  ```
  `cli/__init__.py` `_lazy_commands` gains `"login"`, `"logout"`, `"whoami"` → `"parrot.cli.login"` and `"connect"`,
  `"connections"`, `"disconnect"` → `"parrot.cli.connect"` (M6), inserted after the `"mcp-serve"` entry
  (`# verified: cli/__init__.py:140`; `get_command` maps names to attributes, `:99-100`).

### Module 2: `CliPrincipalResolver`
- **Path**: `packages/ai-parrot/src/parrot/cli/principal.py` (new); `packages/ai-parrot/src/parrot/cli/identity.py` (modify)
- **Responsibility**: S-1 `PrincipalResolver` for `channel in {"cli", "agentd"}` backed by the login file + `/me`;
  `build_cli_permission_context(principal, roles)`; remove the `O365_PRINCIPAL` bootstrap.
- **Depends on**: M1 (`LoginStore`, `refresh_login`), M4 (`ServerConnectionsClient.me`), S-1 `Principal` /
  `PrincipalResolver` (planned, `delegated-auth-connections.spec.md:230-236, 322-326`), `build_principal_context`
  (`permission.py:166`).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/cli/principal.py  (new)
  CLI_CHANNELS = frozenset({"cli", "agentd"})
  class CliPrincipalResolver:                                           # satisfies S-1 PrincipalResolver (spec:322-326)
      def __init__(self, store: LoginStore, client: ServerConnectionsClient) -> None: ...
      async def resolve(self, channel: str, channel_user_id: str) -> Optional[Principal]:
          """channel not in CLI_CHANNELS → None. No login → None. Else /me → Principal(user_id, canonical_identity=email,
          tenant_id, channel, channel_user_id). Refreshes the login when the access token is expired (single-flight)."""
      async def resolve_with_roles(self, channel: str, channel_user_id: str) -> Optional[Tuple[Principal, frozenset[str]]]:
          """Same, plus the server-issued roles ∪ scopes (S7)."""
  def build_cli_permission_context(principal: Principal, *, roles: frozenset[str] = frozenset()) -> PermissionContext:
      """build_principal_context(principal.user_id, channel=principal.channel, tenant_id=principal.tenant_id, roles=roles)  # verified: permission.py:166-172"""

  # packages/ai-parrot/src/parrot/cli/identity.py  (modifies — hard cut)
  CLI_CHANNEL: str = "cli"                                              # kept  # verified: identity.py:27
  # REMOVED: O365_PRINCIPAL_ENV_VAR (:22), O365_TENANT_ID_ENV_VAR (:33), UNSET_CLI_TENANT (:40),
  #          resolve_cli_o365_principal (:45), build_cli_permission_context(user_id) (:76), bot_declares_o365_device_code (:108)
  # identity.py re-exports build_cli_permission_context from parrot.cli.principal for the single caller agent_repl.py:23
  ```

### Module 3: Server endpoints — whoami, token pull, paste completion, device start/poll
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/connections.py` (S-1 file, modify); `packages/ai-parrot/src/parrot/auth/oauth2/service.py` (modify); `packages/ai-parrot/src/parrot/auth/oauth2/events.py` (S-1 file, modify `ConnectionEventKind`); `packages/ai-parrot-server/src/parrot/manager/manager.py` (modify route block)
- **Responsibility**: the five routes in §2 behind navigator-auth; PBAC `integration:use` on `/token`; audit
  `connection.token_pulled`; `not_connected` → 409 with `AuthRequiredPayload`; paste completion reuses S-1's
  `handle_callback` + `persist_credential`; device handle lifecycle (M8 server half).
- **Depends on**: S-1 M6 (`IntegrationsService.status/start_connect/persist_credential`, spec:582-597;
  `_check_pbac`, `service.py:490`), S-1 M2 (`AbstractOAuth2Manager.handle_callback`, `get_valid_token`), M8.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/auth/oauth2/service.py  (modifies; after start_connect, service.py:291)
  class IntegrationsService:
      async def whoami(self, user_id: str, request: Any = None) -> WhoAmI:
          """user_id via resolve_user_id (session_identity.py:90); tenant/email/roles from the session; scopes from token claims when present."""
      async def pull_access_token(self, user_id: str, provider_id: str, request: Any = None) -> PulledToken:
          """PBAC integration:use (ctx provider) fail-closed (pattern service.py:117-119); manager.get_valid_token refreshes server-side;
          no active connection → raise NotConnected(AuthRequiredPayload); publishes connection.token_pulled (audit only, never token material)."""
      async def complete_connect(self, user_id: str, provider_id: str, *, code: str, state: str, channel: str) -> IntegrationDescriptor:
          """manager.handle_callback(code, state) (nonce check is S-1's) → persist_credential(..., channel) → status(...)."""
      async def device_start(self, user_id: str, provider_id: str, *, principal: Principal, request: Any = None) -> Dict[str, Any]: ...
      async def device_poll(self, user_id: str, provider_id: str, *, handle: str, request: Any = None) -> Dict[str, Any]:
          """{status: pending|completed|failed|expired, interval}; one provider poll per call, honouring slow_down."""

  # packages/ai-parrot-server/src/parrot/handlers/connections.py  (S-1 file; modifies — route dispatch by URL suffix, pattern integrations.py:34-41)
  class ConnectionsHandler(BaseView):                                   # planned: spec:605
      async def get(self) -> web.Response: ...     # + GET /api/v1/connections/me
      async def post(self) -> web.Response: ...    # + /{provider}/token | /{provider}/complete | /{provider}/device/start | /{provider}/device/poll
  # packages/ai-parrot-server/src/parrot/manager/manager.py  (modifies the FEAT-144 route block, manager.py:2457-2472)
  #   + router.add_view("/api/v1/connections/me", ConnectionsHandler)  (registered BEFORE "/api/v1/connections/{provider}")
  #   + router.add_view("/api/v1/connections/{provider}/token" | "/complete" | "/device/start" | "/device/poll", ConnectionsHandler)
  # packages/ai-parrot/src/parrot/auth/oauth2/events.py  (S-1 file; modifies spec:268 Literal) + "connection.token_pulled"
  ```

### Module 4: Encrypted connection cache, remote resolver, CLI broker builder
- **Path**: `packages/ai-parrot/src/parrot/auth/oauth2/remote_client.py` (new), `packages/ai-parrot/src/parrot/auth/oauth2/local_cache.py` (new); `packages/ai-parrot/src/parrot/auth/oauth2/__init__.py` (export)
- **Responsibility**: aiohttp-client-only access to the M3 endpoints with bearer + auto-refresh (M1); AES-GCM
  cache keyed by `LoginRecord.cache_key`; `RemoteConnectionResolver`; `build_cli_broker`.
- **Depends on**: M1, S-1 `AuthRequiredPayload` (planned, spec:283-293), `CredentialResolver` (`credentials.py:162`),
  `CredentialBroker.register` (`broker/core.py:81`), `parrot.security.vault_utils` AES-GCM helpers.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/auth/oauth2/remote_client.py  (new)
  class NotConnected(Exception):
      payload: AuthRequiredPayload                                       # from the 409 body
  class ServerConnectionsClient:                                         # signatures in §2 New Public Interfaces
      """Bearer = LoginRecord.access_token; on 401 once: refresh_login then retry; never logs tokens."""

  # packages/ai-parrot/src/parrot/auth/oauth2/local_cache.py  (new)
  class ConnectionCache:
      def __init__(self, path: Path, key: bytes) -> None: ...             # default ~/.parrot/connections.cache (0600)
      async def get(self, provider: str) -> Optional[CachedConnection]: ...   # asyncio.to_thread; corrupt/undecryptable file → treated as empty + warning
      async def put(self, entry: CachedConnection) -> None: ...
      async def delete(self, provider: Optional[str] = None) -> None: ...
  class RemoteConnectionResolver(CredentialResolver):                    # verified: credentials.py:162 (ABC: resolve, get_auth_url)
      def __init__(self, provider: str, *, cache: ConnectionCache, client: ServerConnectionsClient, skew_s: int = 60) -> None: ...
      async def resolve(self, channel: str, user_id: str) -> Optional[str]:
          """cache hit (expires_at - skew > now) → access_token; else single-flight pull_token → cache.put → token; NotConnected → None."""
      async def get_auth_url(self, channel: str, user_id: str) -> str:
          """client.start_connect(provider, channel=channel).auth_url (so NeedsAuth.auth_url is actionable)."""
  def build_cli_broker(store: LoginStore, providers: Iterable[str], *, client: Optional[ServerConnectionsClient] = None) -> CredentialBroker:
      """CredentialBroker(); broker.register(p, RemoteConnectionResolver(p, ...), auth_kind="oauth2") for each p  # verified: core.py:68, :81"""
  ```

### Module 5: Stdio execution context and MCP auth-required envelope
- **Path**: `packages/ai-parrot/src/parrot/mcp/adapter.py`, `packages/ai-parrot/src/parrot/mcp/server_base.py`, `packages/ai-parrot/src/parrot/mcp/toolkit_server.py`, `packages/ai-parrot/src/parrot/mcp/local_cli.py` (modify); `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py`, `packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py` (modify)
- **Responsibility**: S1 + S2; process-start binding from the login file; `--login-file`; host entries pass
  `PARROT_LOGIN_FILE` through when set at install time.
- **Depends on**: M2, M4, S-1 M5 (`to_payload()` on both exceptions, planned spec:550/561).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/mcp/adapter.py  (modifies)
  @dataclass(frozen=True)
  class ToolExecutionContext: ...                                       # §2 Data Models
  class MCPToolAdapter:
      def __init__(self, tool: AbstractTool, *, execution_context: Optional[ToolExecutionContext] = None) -> None: ...   # verified: adapter.py:19
      async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:                                                # verified: adapter.py:59
          """result = await self.tool.execute(**arguments, **(ctx.exec_kwargs() if ctx else {}))   # REPLACES tool._execute(**arguments) (adapter.py:79)
          except (AuthorizationRequired, CredentialRequired) as exc: return auth_required_result(exc.to_payload(tool_name=self.tool.name))"""
  def auth_required_result(payload: AuthRequiredPayload) -> dict[str, Any]:
      """{'isError': True, 'content': [text], 'structuredContent': payload.model_dump(exclude_none=True)} — no stdout writes."""

  # packages/ai-parrot/src/parrot/mcp/server_base.py  (modifies)
  class MCPServerBase(ABC):
      def __init__(self, config: LocalServerConfig, *, execution_context: Optional[ToolExecutionContext] = None): ...   # verified: server_base.py:60
      def register_tool(self, tool: AbstractTool):   # adapter = MCPToolAdapter(tool, execution_context=self.execution_context)   # verified: :68-72

  # packages/ai-parrot/src/parrot/mcp/toolkit_server.py  (modifies)
  def create_toolkit_mcp_server(name: str, root: Path = Path.cwd(), *, login_file: Optional[Path] = None, **overrides: Any) -> StdioMCPServer:   # verified: toolkit_server.py:137-141
      """Inside the existing redirect_stdout(sys.stderr) block (:186): store = LoginStore(login_file); if a login exists →
      principal, roles = await-free resolve via asyncio.run? NO — resolution is async: the factory stays sync and defers to
      _ToolkitStdioMCPServer.start() (:62), which resolves principal + broker once before serving (build_cli_broker over the
      toolkit's credential_provider, toolkit.py:331). No login → execution_context None (today's behaviour)."""

  # packages/ai-parrot/src/parrot/mcp/local_cli.py  (modifies)
  # + @click.option("--login-file", "login_file", default=None, type=click.Path(path_type=Path), envvar="PARROT_LOGIN_FILE")   # after "--list" (:160-166)
  # knowledge/wiki/claude_code/assets.py:181 and codex/assets.py:89-91: when os.environ.get("PARROT_LOGIN_FILE") is set at install
  # time, copy it into the entry env (never the token itself).
  ```

### Module 6: `parrot connect` / `connections` / `disconnect` and REPL slash commands
- **Path**: `packages/ai-parrot/src/parrot/cli/connect.py` (new); `packages/ai-parrot/src/parrot/auth/oauth2/paste.py` (new, `parse_pasted_redirect` moved from `parrot_tools/jira_cli.py:42`); `packages/ai-parrot/src/parrot/cli/commands.py` (modify)
- **Responsibility**: G5; poll + paste completion (S10); device variant (`--device`, M8); slash commands via
  `CommandContext.suspend()` for prompts.
- **Depends on**: M1, M4, M8.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/auth/oauth2/paste.py  (new; moved verbatim from jira_cli.py:42-67)
  def parse_pasted_redirect(text: str) -> Tuple[str, Optional[str]]: ...

  # packages/ai-parrot/src/parrot/cli/connect.py  (new)
  async def run_connect(client: ServerConnectionsClient, cache: ConnectionCache, provider: str, *, scopes: Optional[List[str]],
                        open_browser: bool, paste: bool, device: bool, prompt: Callable[[str], str], echo: Callable[[str], None],
                        poll_interval_s: float = 2.0) -> Dict[str, Any]:
      """start_connect → echo/open auth_url → poll status until active and connected_at >= started_at (≤ expires_in) |
      paste: parse_pasted_redirect → hmac.compare_digest(state) → complete(code, state) | device: device_start → show code → device_poll.
      Then pull_token → cache.put. Raises ConnectFailed with a one-line reason."""
  @click.command("connect") ... def connect(provider, scopes, no_browser, paste, device) -> None: ...
  @click.command("connections") def connections() -> None: ...          # table: provider, status, account, scopes, expires
  @click.command("disconnect") def disconnect(provider) -> None: ...   # client.disconnect + cache.delete(provider)

  # packages/ai-parrot/src/parrot/cli/commands.py  (modifies _register_builtins, commands.py:189-209)
  async def _cmd_connect(ctx: "CommandContext", args: str) -> None: ...        # with ctx.suspend(): run_connect(..., prompt=click.prompt)
  async def _cmd_connections(ctx: "CommandContext", args: str) -> None: ...
  async def _cmd_disconnect(ctx: "CommandContext", args: str) -> None: ...
  #   SlashCommand("connect", "Connect a provider for this login. Usage: /connect <provider> [--paste|--device]", _cmd_connect), ... inserted before "help" (:207)
  ```

### Module 7: REPL identity regimes
- **Path**: `packages/ai-parrot/src/parrot/cli/agent_repl.py`, `packages/ai-parrot/src/parrot/cli/repl.py` (modify); `packages/ai-parrot/src/parrot/cli/session.py` (unchanged shape)
- **Responsibility**: standalone + login → Navigator principal, permission context and CLI broker; `--user` with a
  login refused; `--server` → bearer defaults to the login access token, no local principal (S12).
- **Depends on**: M2, M4.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/cli/agent_repl.py  (modifies _run, agent_repl.py:134-252)
  #   login = LoginStore().load_optional()                                                    # after loader selection (:161-164)
  #   if server: loader = ServerAgentProxy(server, token=token or (login.access_token if login else None), login_store=store if login else None)   # replaces :162 (Q5: auto-refresh on 401)
  #   if not server and login and user_id: error "--user is not allowed when logged in; identity comes from `parrot login`" (exit 2)  # mirrors :186-191
  #   permission_context = None                                                              # :218 — replaces the O365-only block (:215-224)
  #   if not server and login:
  #       principal, roles = await CliPrincipalResolver(store, client).resolve_with_roles("cli", login.user_id)
  #       permission_context = build_cli_permission_context(principal, roles=roles)
  #       bot.tool_manager.set_broker(build_cli_broker(store, _declared_providers(bot)))     # ToolManager.set_broker verified: tools/manager.py:517
  #   user_id=None if server else (user_id or (login.user_id if login else "cli-user"))       # replaces :247
  def _declared_providers(bot: Any) -> set[str]:
      """{tool.credential_provider for tool in bot.tool_manager tools if tool.credential_provider}  # attribute verified: tools/abstract.py:306"""
  # packages/ai-parrot/src/parrot/cli/repl.py  (modifies REPLConfig, repl.py:60-69)
  #   + login_user_id: Optional[str] = None      # shown by /info; appended after history_enabled (:69)
  ```

### Module 8: Generic RFC 8628 engine, descriptor field, server device grant
- **Path**: `packages/ai-parrot/src/parrot/auth/oauth2/device_code.py` (new); `packages/ai-parrot/src/parrot/auth/oauth2/descriptor.py` (S-1 file, modify); `packages/ai-parrot/src/parrot/auth/oauth2/o365_devicecode_provider.py` (modify `_default_prompt_callback`)
- **Responsibility**: pure client engine (S8) used by M1 and by the server for provider device grants;
  `device_authorization_url` on the descriptor; `StandardOAuth2Manager.start_device_authorization` /
  `complete_device_authorization`; O365 prompt off stdout.
- **Depends on**: S-1 M3 (`OAuth2ProviderDescriptor`, `StandardOAuth2Manager`, planned spec:250-265, 483-493).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/auth/oauth2/device_code.py  (new) — signatures in §2 New Public Interfaces
  class DeviceAuthorization(BaseModel): ...
  class DeviceCodeError(RuntimeError): ...
  async def discover_authorization_server(session, issuer) -> Dict[str, Any]: ...
  def make_pkce_pair() -> Tuple[str, str]: ...
  async def request_device_authorization(...) -> DeviceAuthorization: ...
  async def poll_device_token(...) -> Dict[str, Any]:
      """authorization_pending → wait interval; slow_down → interval += 5 (OAUTH_DEVICE_SLOW_DOWN_INCREMENT default); expired_token /
      access_denied → DeviceCodeError; timeout_s or expires_in elapsed → DeviceCodeError('timeout'); CancelledError propagates."""

  # packages/ai-parrot/src/parrot/auth/oauth2/descriptor.py  (S-1 file; modifies spec:250-265)
  class OAuth2ProviderDescriptor(BaseModel):
      device_authorization_url: Optional[str] = None                     # additive
  class StandardOAuth2Manager(AbstractOAuth2Manager):                    # planned: spec:483
      async def start_device_authorization(self, principal: Principal, *, scopes: Optional[List[str]] = None) -> Tuple[str, DeviceAuthorization]:
          """(handle, authorization); stores {device_code, principal, provider, code_verifier} under oauth2:{provider}:device:{handle} with TTL expires_in;
          raises ValueError when descriptor.device_authorization_url is None."""
      async def complete_device_authorization(self, handle: str) -> Dict[str, Any]:
          """One token-endpoint poll; pending/slow_down → {status: pending, interval}; success → _persist_token(minted=True) + publish → {status: completed}."""

  # packages/ai-parrot/src/parrot/auth/oauth2/o365_devicecode_provider.py  (modifies :57-70)
  def _default_prompt_callback(flow: Dict[str, Any]) -> None:
      """print(message, file=sys.stderr) — stdout is reserved for stdio JSON-RPC (FEAT-485)."""
  ```

### Module 9: agentd login-file principal
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/agentd/server.py`, `packages/ai-parrot-integrations/src/parrot/integrations/agentd/config.py` (modify)
- **Responsibility**: U5 with the S11 constraints; `identity_source = "login_file"`; `login_file_lookup` flag;
  trusted-server pin `login_file_server_url` (the step runs only when both are set — `login_file_enabled`);
  read-only peer store.
- **Depends on**: M1 (`LoginStore.for_uid`), M2, M4 (`ServerConnectionsClient`).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-integrations/src/parrot/integrations/agentd/server.py  (modifies _resolve_identity, server.py:323-361)
  #   username = await asyncio.to_thread(_uid_to_username, uid)                                   # :354 unchanged
  #   if self.service_identity.login_file_enabled:                       # lookup flag AND a pinned trusted server
  #       store = LoginStore.for_uid(uid, read_only=True)                   # never refreshes, locks, writes temp files
  #       login = await asyncio.to_thread(store.load_optional, expected_uid=uid)   # O_NOFOLLOW, owner == uid, 0600 — on every load; else None
  #       if login and normalize(login.server_url) == normalize(login_file_server_url):   # other server → ignored
  #           async with ServerConnectionsClient(store, server_url=login_file_server_url) as client:   # always the pinned URL
  #               resolved = await CliPrincipalResolver(store, client).resolve_with_roles("agentd", username)   # 401 → None
  #           if resolved: principal, roles = resolved; return build_cli_permission_context(principal, roles=roles), "login_file"
  #   return build_principal_context(username, channel="agentd"), "peercred"                       # :355 unchanged
  # packages/ai-parrot-integrations/src/parrot/integrations/agentd/config.py  (modifies ServiceIdentityConfig, config.py:131-166)
  #   + login_file_lookup: bool = True      # env AGENTD_LOGIN_FILE_LOOKUP; appended after roles (:166)
  #   + login_file_server_url: Optional[str] = None   # env AGENTD_LOGIN_FILE_SERVER_URL; step is OFF while unset
  #   + login_file_enabled -> bool          # property: login_file_lookup and bool(login_file_server_url)
  ```

### Module 10: Jira convergence
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`, `packages/ai-parrot-tools/src/parrot_tools/jira_cli.py` (modify); `packages/ai-parrot-tools/src/parrot_tools/jira_local_auth.py` (delete)
- **Responsibility**: G8; remove `oauth2_local` / `_local_single_user` / `FileTokenCredentialResolver`;
  `_pre_execute` requires a `PermissionContext` for every 3LO call (the existing `else` branch, `jiratoolkit.py:1351+`);
  `parrot jiratoolkit auth|status|logout` delegate to M6 commands; `sync-kb` keeps using the broker-resolved token.
- **Depends on**: M4, M6; S-1 M7 (`JiraToolkit.credential_provider = "jira"`, planned spec M7).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py  (modifies)
  #   REMOVED: `if self.auth_type == "oauth2_local":` block (:927-933) and `if self._local_single_user:` branch (:1338-1350);
  #            `from .jira_local_auth import FileTokenCredentialResolver` (:67)
  # packages/ai-parrot-tools/src/parrot_tools/jira_cli.py  (modifies)
  @cli.command()
  def auth(...) -> None:
      """Deprecated alias: invokes parrot.cli.connect.run_connect(provider="jira", paste=True by default) and prints the new command."""   # replaces :283-351
  #   status → parrot.cli.connect connections (filtered to jira); logout → disconnect("jira"); imports of build_authorization_url/exchange_code removed (:23-30)
  # packages/ai-parrot-tools/src/parrot_tools/jira_local_auth.py — DELETED (LocalJiraTokenStore, FileTokenCredentialResolver); tests test_jira_local_auth.py, test_oauth2_local_wiring.py removed
  ```

### Module 11: Docs and validation
- **Path**: `docs/cli/parrot-login-and-connections.md` (new), `docs/mcp-local-toolkits.md` (modify: "Credentials and identity" section), `docs/auth/connections.md` (S-1 doc, modify: CLI consumers), `docs/cli/parrot-agent.md` (modify)
- **Responsibility**: deployment prerequisites (navigator-auth `Oauth2Provider` backend, static `parrot-cli` public
  client with device_code + refresh_token grants, `OAUTH_DEVICE_*` settings), login/connect walkthrough, stdio
  binding and the auth-required envelope, agentd login-file rules, migration from `parrot jiratoolkit auth`.
- **Depends on**: M1–M10.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_login_store_roundtrip_0600_and_lock` | M1 | save/load atomic, mode 0600, lock file, `O_NOFOLLOW` rejects symlink, wrong owner → `LoginFileError` |
| `test_login_device_grant_happy_path` | M1 | fake AS: discovery → device_authorization (PKCE challenge present) → pending ×2 → slow_down → token; userinfo `sub` → `LoginRecord.user_id` |
| `test_login_fails_loudly_without_device_endpoint` | M1 | discovery lacks `device_authorization_endpoint` → exit 2, message names it |
| `test_refresh_login_rotation_and_invalid_grant` | M1 | new refresh token stored; `invalid_grant` → `LoginExpired` |
| `test_logout_revokes_and_wipes` | M1 | revoke called best-effort; login file and cache deleted |
| `test_cli_principal_resolver_channels` | M2 | `cli`/`agentd` → Principal with Navigator id, tenant, email; other channel → None; no login → None |
| `test_cli_principal_roles_from_server` | M2 | `build_cli_permission_context` carries roles ∪ scopes and the real tenant (never the principal as tenant) |
| `test_identity_o365_bootstrap_removed` | M2 | `resolve_cli_o365_principal` / `bot_declares_o365_device_code` absent; `O365_PRINCIPAL` ignored |
| `test_pull_access_token_never_returns_refresh` | M3 | response keys ⊆ {provider, access_token, expires_at, scopes, account_id}; audit event `connection.token_pulled` published without token material |
| `test_pull_token_not_connected_409_payload` | M3 | body validates as `AuthRequiredPayload` with `auth_url` |
| `test_pull_token_pbac_denied_403` | M3 | `integration:use` denied → 403, no event |
| `test_complete_connect_state_mismatch_rejected` | M3 | bad/expired nonce → 400; good → row persisted with `channels` ∋ cli |
| `test_whoami_route_ordering` | M3 | `/connections/me` resolves before `/{provider}` |
| `test_connection_cache_encrypt_roundtrip_and_tamper` | M4 | AES-GCM; tampered file → treated as empty with warning; wrong key → empty |
| `test_cache_io_off_event_loop_and_single_flight` | M4 | concurrent resolves for one provider → one pull; loop never blocks (`to_thread` spy) |
| `test_remote_resolver_hit_miss_not_connected` | M4 | hit → token; expired → pull; `NotConnected` → None; `get_auth_url` returns `start_connect.auth_url` |
| `test_build_cli_broker_registers_declared_providers` | M4 | one resolver per provider, `auth_kind == "oauth2"` |
| `test_adapter_routes_through_abstract_tool_execute` | M5 | `_execute` not called directly; `_permission_context`/`_broker`/`_cred_*` reach the tool |
| `test_adapter_auth_required_envelope_fields_survive` | M5 | every `AuthRequiredPayload` field present in `structuredContent`; `isError` true; nothing on stdout |
| `test_toolkit_server_without_login_unchanged` | M5 | no login → `execution_context is None`; existing behaviour (`tests/mcp/test_toolkit_server.py`) still green |
| `test_toolkit_server_binds_principal_from_login_file` | M5 | login present → broker with the toolkit's `credential_provider`; `--login-file` honoured |
| `test_host_entries_pass_login_file_env` | M5 | `PARROT_LOGIN_FILE` set at install → in `.mcp.json` env and Codex `env =`; never a token |
| `test_connect_poll_completes_only_new_connection` | M6 | pre-existing active row with `connected_at < started_at` does not complete; new row does |
| `test_connect_paste_fallback_state_check` | M6 | state mismatch aborts; match → `/complete` called; token pulled into cache |
| `test_slash_connect_uses_suspend` | M6 | `/connect` enters `ctx.suspend()` around the prompt |
| `test_repl_identity_matrix` | M7 | (login, --user, --server) × outcomes: Navigator id; refusal; bearer default; no local principal in server mode |
| `test_device_code_engine_state_machine` | M8 | pending → slow_down (interval +5) → approved; expired/denied raise; timeout; cancellation |
| `test_descriptor_device_url_optional` | M8 | default None; manager raises when starting a device grant without it |
| `test_server_device_start_poll` | M8 | handle stored with TTL; poll pending → completed persists via `CredentialStore` and publishes |
| `test_o365_prompt_goes_to_stderr` | M8 | `capsys.readouterr().out == ""` |
| `test_agentd_login_file_principal` | M9 | owner/mode/symlink checks; valid → `identity_source == "login_file"` and Navigator id; invalid → `peercred` |
| `test_agentd_login_lookup_disabled` | M9 | `login_file_lookup=False` → today's behaviour |
| `test_no_trusted_server_keeps_peercred` | M9 | `AGENTD_LOGIN_FILE_SERVER_URL` unset → step off, `peercred` |
| `test_login_file_naming_untrusted_server_is_ignored` | M9 | record names another server → ignored, `peercred` |
| `test_read_only_store_never_refreshes_on_401` | M9 | read-only peer store: no refresh, lock, temp file or rewrite; 401 → `peercred` |
| `test_jiratoolkit_local_mode_removed` | M10 | `auth_type="oauth2_local"` rejected; `_pre_execute` without `PermissionContext` raises `AuthorizationRequired` |
| `test_jira_cli_auth_aliases_connect` | M10 | `parrot jiratoolkit auth` invokes `run_connect("jira", paste=True)`; `parse_pasted_redirect` importable from core |

### Integration Tests
| Test | Description |
|---|---|
| `test_e2e_cli_login_connect_tool_call` | fake navigator-auth AS + fake parrot server: `parrot login` → `parrot connect fake` (poll path) → standalone agent runs a `credential_provider="fake"` tool → broker resolves from cache → server `/token` called once; second call is a cache hit |
| `test_e2e_stdio_toolkit_auth_required` | `parrot mcp-local` process with login but no connection: `tools/call` returns the auth-required envelope over stdio; stdout contains only JSON-RPC |
| `test_e2e_agentd_login_file` | daemon with a peer whose home has a valid login file → `agent.info` reports the Navigator id and `identity_source == "login_file"` |
| `test_e2e_cli_devicecode_e2e` (rewrite of `packages/ai-parrot/tests/integration/test_cli_devicecode_e2e.py`) | O365 device grant via `parrot connect o365 --device` against a fake provider; token persisted server-side; WorkIQ OBO interop assertion moves to the S-3a backlog (see §7) |

### Validation Contract

runners:
- kind: pytest
  tests:
  - packages/ai-parrot/tests/cli/test_identity.py
  - packages/ai-parrot/tests/cli/test_agent_command.py
  - packages/ai-parrot/tests/cli/test_session.py
  - packages/ai-parrot/tests/cli/test_commands_context.py
  - packages/ai-parrot/tests/cli/test_loaders_server.py
  - packages/ai-parrot/tests/mcp/test_adapter.py
  - packages/ai-parrot/tests/mcp/test_adapter_confirm.py
  - packages/ai-parrot/tests/mcp/test_server_base.py
  - packages/ai-parrot/tests/mcp/test_local_server.py
  - packages/ai-parrot/tests/mcp/test_hosts.py
  - packages/ai-parrot/tests/mcp/test_toolkit_install.py
  - tests/mcp/test_toolkit_server.py
  - tests/mcp/test_local_cli.py
  - tests/mcp/test_toolkit_config.py
  - packages/ai-parrot/tests/unit/test_tool_credential_seam.py
  - packages/ai-parrot/tests/unit/test_credential_broker.py
  - packages/ai-parrot/tests/unit/test_credential_resolver.py
  - packages/ai-parrot/tests/auth/test_broker_devicecode.py
  - packages/ai-parrot/tests/auth/test_credentials_devicecode.py
  - packages/ai-parrot/tests/unit/test_permission_context_channel.py
  - packages/ai-parrot/tests/integration/test_cli_devicecode_e2e.py
  - packages/ai-parrot-integrations/tests/agentd/test_caller_identity.py
  - packages/ai-parrot-integrations/tests/agentd/test_server.py
  - packages/ai-parrot-integrations/tests/agentd/test_mcp_proxy.py
  - packages/ai-parrot-tools/tests/unit/test_jira_cli.py
  - packages/ai-parrot-tools/tests/unit/test_jiratoolkit_oauth.py
  - packages/ai-parrot-server/tests/unit/test_identity_credential_sink.py
  - packages/ai-parrot-server/tests/mcp/test_principal_resolution.py
  - tests/unit/integrations/oauth2/test_service.py
  - tests/unit/integrations/oauth2/test_handler.py
  - packages/ai-parrot-server/tests/unit/test_connections_handler.py
  - packages/ai-parrot/tests/unit/auth/test_oauth2_descriptor.py
  - packages/ai-parrot/tests/unit/auth/test_connection_events.py
  - packages/ai-parrot/tests/auth/test_device_code_engine.py
  - packages/ai-parrot/tests/unit/auth/test_oauth2_descriptor_device.py
  - packages/ai-parrot/tests/auth/test_o365_prompt_stderr.py
  - packages/ai-parrot/tests/cli/test_login.py
  - packages/ai-parrot/tests/unit/auth/test_service_cli_endpoints.py
  - packages/ai-parrot-server/tests/unit/test_connections_cli_routes.py
  - packages/ai-parrot/tests/unit/auth/test_service_device_endpoints.py
  - packages/ai-parrot/tests/auth/test_remote_client.py
  - packages/ai-parrot/tests/auth/test_connection_cache.py
  - packages/ai-parrot/tests/cli/test_cli_principal.py
  - packages/ai-parrot/tests/mcp/test_adapter_execution_context.py
  - tests/mcp/test_toolkit_server_login.py
  - packages/ai-parrot/tests/cli/test_connect.py
  - packages/ai-parrot/tests/cli/test_repl_identity_matrix.py
  - packages/ai-parrot-integrations/tests/agentd/test_login_file_identity.py
  - packages/ai-parrot-tools/tests/unit/test_jira_connect_convergence.py
  - packages/ai-parrot/tests/integration/test_cli_connections_e2e.py
  - tests/mcp/test_stdio_auth_required_e2e.py
  - packages/ai-parrot/tests/docs/test_cli_connections_docs.py
  markers: none

> `packages/ai-parrot-tools/tests/unit/test_jira_local_auth.py` and `test_oauth2_local_wiring.py` are deleted by M10
> and intentionally absent from the contract. S-1's contract files were added by `/sdd-task` on 2026-10-31 after
> FEAT-773 merged (rev 0.3).

### Test Data / Fixtures
```python
@pytest.fixture
def login_record(tmp_path) -> LoginRecord:
    return LoginRecord(server_url="http://parrot.test", access_token="at", refresh_token="rt", expires_at=time.time() + 3600,
                       user_id="1042", email="jlara@example.com", tenant_id="troc", roles=["agents:use"], cache_key=_b64(os.urandom(32)), issued_at=time.time())

@pytest.fixture
def login_store(tmp_path, login_record) -> LoginStore:   # file created 0600 under tmp_path / ".parrot/login.json"
    ...

@pytest.fixture
def fake_authorization_server():   # aiohttp test app: /.well-known/oauth-authorization-server, /oauth2/device_authorization,
    ...                            # /oauth2/token (scripted pending/slow_down/approved), /oauth2/userinfo, /oauth2/revoke

@pytest.fixture
def fake_parrot_server():          # aiohttp test app with the five M3 routes + S-1 GET /api/v1/connections/{provider}; records pulls
    ...

@pytest.fixture
def connection_cache(tmp_path, login_record) -> ConnectionCache: ...

@pytest.fixture
def credentialed_stub_toolkit():   # AbstractToolkit with credential_provider="fake" and one tool returning current_credential()
    ...

@pytest.fixture
def peer_home(tmp_path):           # home dir + .parrot/login.json with controllable owner/mode/symlink (uses os.chown only when root; otherwise monkeypatches os.stat)
    ...
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] **AC-1 (G1)** `parrot login --server <url>` completes the RFC 8628 device grant against navigator-auth as public client `parrot-cli` with PKCE S256, honours `authorization_pending` / `slow_down` / `expired_token` / `access_denied`, and writes `~/.parrot/login.json` with mode 0600; `parrot logout` revokes, deletes the file and the cache.
- [ ] **AC-2 (G1)** With the device endpoint or the `parrot-cli` client missing, `parrot login` exits 2 and names the missing prerequisite; it never falls back to `--user`-style identities.
- [ ] **AC-3 (G2, S12)** `parrot agent` standalone with a login runs every turn with `user_id == <Navigator id>` and a `PermissionContext(channel="cli")` carrying the server-issued roles and tenant; `--user` together with a login is refused (exit 2); in `--server` mode no local principal is built and the login's access token is the default bearer.
- [ ] **AC-4 (G2)** Without a login, every surface behaves exactly as before S-4 (`cli-user`, no broker, no gate) — the existing CLI, local-MCP and agentd tests stay green.
- [ ] **AC-5 (G3, S5)** `POST /api/v1/connections/{provider}/token` returns only an access token, `expires_at`, `scopes`, `account_id`; it enforces PBAC `integration:use` (403 fail-closed) and publishes `connection.token_pulled` without token material; a missing connection yields 409 with an `AuthRequiredPayload` body.
- [ ] **AC-6 (G3, S4, S9)** The local cache is AES-GCM encrypted with the login's `cache_key`, mode 0600, read and written off the event loop, with single-flight refresh per provider; a tampered or undecryptable cache is treated as empty; `parrot logout` wipes it.
- [ ] **AC-7 (G4, S1)** In a `parrot mcp-local` server started with a login, a tool with `credential_provider` executes through `AbstractTool.execute` with `_permission_context`, `_broker`, `_cred_channel="cli"`, `_cred_user_id`, and receives the token via `current_credential()`.
- [ ] **AC-8 (G4, S2)** When no connection exists, the stdio `tools/call` response is `isError: true` with `structuredContent` equal to `AuthRequiredPayload.model_dump(exclude_none=True)` (every field preserved) and a text item; stdout carries only JSON-RPC frames.
- [ ] **AC-9 (G5, S10)** `parrot connect <provider>` completes by polling only when `status == "active"` and `connected_at >= started_at`, or by pasting a redirected URL whose `state` matches (`hmac.compare_digest`) and posting it to `/complete`; on success the token is pulled into the cache; `/connect`, `/connections`, `/disconnect` exist in the REPL.
- [ ] **AC-10 (G6, S8)** `parrot/auth/oauth2/device_code.py` implements the RFC 8628 client state machine with timeout and cancellation; `OAuth2ProviderDescriptor.device_authorization_url` defaults to `None`; `parrot connect <provider> --device` works against a provider descriptor that sets it, through the server's `device/start` and `device/poll`.
- [ ] **AC-11 (G7, S11)** agentd resolves a Navigator principal only from a login file at `pwd.getpwuid(uid).pw_dir/.parrot/login.json` that is a regular file (no symlink), owned by the peer uid, mode 0600 (re-checked on every load); `identity_source == "login_file"`. The step is **off** until the operator sets `AGENTD_LOGIN_FILE_SERVER_URL` to a trusted Navigator server: a login record naming any other server is ignored and the principal is always requested from the pinned URL, never from the file's `server_url`. The peer store is read-only — agentd never refreshes an expired login, never rewrites the file and never creates a lock or temporary file in the peer's directory; a 401 falls back. Any failure keeps peercred / service identity; `AGENTD_LOGIN_FILE_LOOKUP=0` disables the step even when a trusted server is set. *(Amended by TASK-5080, `issue:08e55d4b23ca`, to match review fix c252e73ea6.)*
- [ ] **AC-12 (G8)** `auth_type="oauth2_local"` is rejected by `JiraToolkit`; `jira_local_auth.py` no longer exists; `parrot jiratoolkit auth` delegates to the generic connect flow; `parse_pasted_redirect` lives in `parrot.auth.oauth2.paste`.
- [ ] **AC-13** The `O365_PRINCIPAL` / `O365_TENANT_ID` bootstrap is removed from `parrot/cli/identity.py`; the O365 device-code default prompt writes to stderr only.
- [ ] **AC-14** The CLI never persists a provider refresh token and never sends `user_id` in `--server` mode; no test, log line or error message prints token material.
- [ ] **AC-15** `docs/cli/parrot-login-and-connections.md` documents the deployment prerequisites, the login/connect walkthrough, the stdio envelope and the agentd rules; `docs/mcp-local-toolkits.md` gains the credentials section.
- [ ] **AC-16** All tests in the Validation Contract pass; `ruff check` is clean on every touched file.

---

## 6. Codebase Contract

> Verified against `dev` at `370a62d9b` (2026-10-30). Entries marked **planned** are S-1 (FEAT-773) symbols that
> exist only in `sdd/specs/delegated-auth-connections.spec.md`; `/sdd-task` for FEAT-774 MUST re-anchor them to
> code after FEAT-773 merges and MUST re-run every `grep -c` below.

### Verified Imports
```python
# Live on dev
from parrot.auth.credentials import CredentialResolver, CredentialRequired, NeedsAuth, AuthKind, ProviderCredentialConfig   # credentials.py:162, :113, :82, :43, :46
from parrot.auth.broker.core import CredentialBroker                     # broker/core.py:32
from parrot.auth.broker.factory import CredentialResolverFactory         # broker/factory.py:11
from parrot.auth.permission import PermissionContext, UserSession, build_principal_context   # permission.py:81, :21, :166
from parrot.auth.exceptions import AuthorizationRequired                 # exceptions.py:12
from parrot.auth.identity import CanonicalIdentityMapper                 # identity.py:57 (to_canonical takes a dict, :75)
from parrot.auth.session_identity import resolve_user_id                 # session_identity.py:90
from parrot.auth.context import _pctx_var                                # context.py:33
from parrot.tools.abstract import AbstractTool, ToolResult, current_credential   # tools/abstract.py (class), :251, :45
from parrot.tools.toolkit import AbstractToolkit, ToolkitTool            # toolkit.py (class), :37
from parrot.mcp.adapter import MCPToolAdapter                            # mcp/adapter.py:8
from parrot.mcp.server_base import MCPServerBase, LocalServerConfig      # server_base.py:57, :48
from parrot.mcp.local_server import StdioMCPServer                       # local_server.py:54
from parrot.mcp.toolkit_server import create_toolkit_mcp_server          # toolkit_server.py:137
from parrot.mcp.toolkit_config import ToolkitSection, load_toolkits_config   # toolkit_config.py:20, :90
from parrot.mcp.hosts import HostAdapter, HostKind, get_adapter, detect_hosts   # hosts.py:37, :18, :228-245
from parrot.knowledge.wiki.claude_code.assets import toolkit_mcp_json_entry     # claude_code/assets.py:159
from parrot.knowledge.wiki.codex.assets import toolkit_mcp_block                # codex/assets.py:63
from parrot.cli.repl import AgentREPL, REPLConfig                        # repl.py:34 (REPLConfig)
from parrot.cli.session import TurnRunner                                # session.py:70 (__init__)
from parrot.cli.commands import SlashCommand, SlashCommandDispatcher, CommandContext   # commands.py:68, :125, :41
from parrot.cli.loaders import ServerAgentProxy, StandaloneAgentLoader   # loaders.py:466, :90
from parrot.integrations.agentd.server import JsonRpcUnixServer          # agentd/server.py:214
from parrot.integrations.agentd.config import ServiceIdentityConfig      # agentd/config.py:131
from parrot_tools.jiratoolkit import JiraToolkit                         # jiratoolkit.py (class)
from parrot.auth.oauth2.service import IntegrationsService               # oauth2/service.py:74
from parrot.auth.oauth2.models import IntegrationDescriptor, ConnectInitResponse, DisconnectResponse, AuthRequiredEnvelope   # models.py:21, :79, :105, :117
from navigator.views import BaseView                                     # handlers/integrations.py:22 (import site)
from navigator_auth.decorators import is_authenticated, user_session     # handlers/integrations.py:23 (import site); decorators.py:179, :117

# Planned — S-1 (FEAT-773), spec lines in sdd/specs/delegated-auth-connections.spec.md
from parrot.auth.principal import Principal, PrincipalResolver, set_principal_resolver, resolve_principal   # planned: spec:230-236, :322-326, M1 :390-404
from parrot.auth.credentials import AuthRequiredPayload                  # planned: spec:283-293 (M5)
from parrot.auth.oauth2_base import CredentialStore                      # planned: spec:329-336 (M2)
from parrot.auth.oauth2.descriptor import OAuth2ProviderDescriptor, StandardOAuth2Manager   # planned: spec:250-265, :483
from parrot.auth.oauth2.events import ConnectionEvent, ConnectionEventKind, ConnectionEventPublisher   # planned: spec:268-280, :527
from parrot.handlers.connections import ConnectionsHandler               # planned: spec:605 (ai-parrot-server)
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/auth/broker/core.py
class CredentialBroker:                                                   # :32
    def __init__(self, *, audit_ledger: AuditLedger | None = None, identity_mapper: CanonicalIdentityMapper | None = None) -> None:   # :68-73
    def register(self, provider: str, resolver: CredentialResolver, auth_kind: str = "oauth2") -> None:   # :81-86 (no add_resolver)
    @classmethod
    def from_config(cls, configs: list[ProviderCredentialConfig], strict: bool = True, **deps: Any) -> CredentialBroker:   # :106-112
    async def resolve(self, provider: str, channel: str, user_id: str, **ctx: Any) -> ResolvedCredential | NeedsAuth:   # :156-162
    # empty user_id → ValueError (:188); unknown provider → KeyError (:196); miss → NeedsAuth(provider, auth_url, auth_kind) (:211-215)

# packages/ai-parrot/src/parrot/auth/credentials.py
AuthKind = Literal["obo", "oauth2", "static_key", "mcp", "device_code"]  # :43
class NeedsAuth(BaseModel):                                               # :82 — provider, auth_url, auth_kind, user_code, verification_uri, expires_in
class CredentialRequired(Exception):                                      # :113
    def __init__(self, provider: str, auth_url: str, auth_kind: str, *, user_code=None, verification_uri=None, expires_in=None) -> None:   # :135-143
class CredentialResolver(ABC):                                            # :162
    async def resolve(self, channel: str, user_id: str) -> Optional[Any]:     # :166 (abstract)
    async def get_auth_url(self, channel: str, user_id: str) -> str:          # :175 (abstract)
    async def is_connected(self, channel: str, user_id: str) -> bool:         # :179

# packages/ai-parrot/src/parrot/tools/abstract.py
_CREDENTIAL_VAR: ContextVar[Optional[Any]]                                # :42 ; def current_credential() -> Optional[Any]  # :45
class AbstractTool:
    credential_provider: Optional[str] = None                             # :306
    async def _execute(self, **kwargs) -> Any:                            # :604 (abstract)
    async def execute(self, *args, **kwargs) -> ToolResult:               # :916
    #   pops _permission_context (:939), _resolver (:940), _broker/_cred_channel/_cred_user_id (:950-952); gate :1023-1049; re-raises AuthorizationRequired (:1186-1189) and CredentialRequired (:1194-1197)
class ToolResult(BaseModel):                                              # :251 — success, status, result, error, metadata: Dict[str, Any], timestamp, files, images

# packages/ai-parrot/src/parrot/tools/manager.py
class ToolManager:
    def set_broker(self, broker: Any) -> None:                            # :517 (attribute _broker :389)
    # exec_kwargs["_broker"] / _cred_channel / _cred_user_id injection      # :2178-2183

# packages/ai-parrot/src/parrot/auth/permission.py
class UserSession:  user_id: str; tenant_id: str; roles: frozenset[str]; metadata: dict   # :21, fields :46-49
class PermissionContext: session: UserSession; request_id; channel: Optional[str]; trace_context; extra: dict   # :81, fields :122-126
def build_principal_context(principal: str, *, channel: str, tenant_id: Optional[str] = None, roles: Optional[frozenset[str]] = None) -> "PermissionContext":   # :166-172 (tenant defaults to principal :202)

# packages/ai-parrot/src/parrot/auth/exceptions.py
class AuthorizationRequired(Exception):
    def __init__(self, tool_name: str, message: str, auth_url: Optional[str] = None, provider: str = "unknown", scopes: Optional[List[str]] = None) -> None:   # :12, :34-41

# packages/ai-parrot/src/parrot/mcp/adapter.py
class MCPToolAdapter:
    def __init__(self, tool: AbstractTool):                               # :19
    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]: # :59 ; calls `await self.tool._execute(**arguments)` :79 ; errors → isError :75/:105/:147
# packages/ai-parrot/src/parrot/mcp/server_base.py
class MCPServerBase(ABC):
    def __init__(self, config: LocalServerConfig):                        # :60 ; self.tools: dict[str, MCPToolAdapter] :62
    def register_tool(self, tool: AbstractTool):                          # :68 ; adapter = MCPToolAdapter(tool) :71
    def register_tools(self, tools: list[AbstractTool]):                  # :75
    async def handle_tools_call(self, params: dict[str, Any]) -> dict[str, Any]:   # :111-124 ; return await adapter.execute(arguments) :124
# packages/ai-parrot/src/parrot/mcp/local_server.py
class StdioMCPServer(LocalMCPServerBase):                                 # :54 ; __init__(self, config: LocalServerConfig) :63 ; start :70 ; _admit :129 ; _handle_request :208
# packages/ai-parrot/src/parrot/mcp/toolkit_server.py
class _ToolkitStdioMCPServer(StdioMCPServer):                             # :37 ; __init__(self, config: LocalServerConfig, toolkit: AbstractToolkit) :56 ; start :62 ; stop :69
def create_toolkit_mcp_server(name: str, root: Path = Path.cwd(), **overrides: Any) -> StdioMCPServer:   # :137-141 ; redirect block :186 ; toolkit = toolkit_cls(**kwargs) :222 ; server = _ToolkitStdioMCPServer(...) :262 ; register_tools :263
# packages/ai-parrot/src/parrot/mcp/local_cli.py
def mcp_local(name: str | None, config_path: Path | None, include: tuple[str, ...], exclude: tuple[str, ...], list_toolkits: bool) -> None:   # :167-173 ; options :139-166 ; server = create_toolkit_mcp_server(name, root, **overrides) :218
# packages/ai-parrot/src/parrot/mcp/toolkit_config.py
class ToolkitSection(BaseModel): class_path (alias "class"), enabled, kwargs, include, exclude, llm, llm_kwargs, env: dict[str, str]   # :20, fields :50-57
# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py
def toolkit_mcp_json_entry(root: Path, name: str, section: ToolkitSection) -> dict:   # :159 ; "env": dict(section.env) :181
# packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py
def toolkit_mcp_block(root: Path, sections: dict[str, ToolkitSection]) -> str:        # :63 ; if section.env: :89-91

# packages/ai-parrot/src/parrot/cli/__init__.py
class LazyGroup(click.Group):                                             # :19 ; get_command maps "a-b" → attr a_b :99-100
cli._lazy_commands = { ... "mcp-local": "parrot.mcp.local_cli", ... "jiratoolkit": "parrot_tools.jira_cli", ... "mcp-serve": "parrot.integrations.agentd.cli", }   # :109-141
# packages/ai-parrot/src/parrot/cli/agent_repl.py
def agent(name, list_agents, server, no_stream, ui, session, user_id, token, no_history) -> None:   # :97-107 ; --user :78-84 ; --token :85-90
async def _run(name, list_agents, server, no_stream, ui="auto", session=None, user_id=None, token=None, no_history=False) -> None:   # :134-144 ; loader :161-164 ; guard :186-191 ; permission_context :218-224 ; REPLConfig :238-248 ; TurnRunner :252
# packages/ai-parrot/src/parrot/cli/identity.py
CLI_CHANNEL: str = "cli"                                                  # :27
def resolve_cli_o365_principal() -> str:                                  # :45  (REMOVED by M2)
def build_cli_permission_context(user_id: Optional[str] = None) -> PermissionContext:   # :76  (REPLACED by M2)
def bot_declares_o365_device_code(bot: object) -> bool:                   # :108 (REMOVED by M2)
# packages/ai-parrot/src/parrot/cli/repl.py
class REPLConfig(BaseModel): agent_name; streaming; server_url; session_id; user_id: Optional[str] = "cli-user" (:64); permission_context: Optional[Any] = None (:65); ui_mode; resume_session_id; server_token (:68); history_enabled: bool = True (:69)   # :34
# packages/ai-parrot/src/parrot/cli/session.py
class TurnRunner: def __init__(self, bot: Any, config: Any, *, capabilities: Optional[BackendCapabilities] = None) -> None:   # :70 ; _identity_kwargs :105-114
# packages/ai-parrot/src/parrot/cli/commands.py
class CommandContext(Protocol): bot; config; dispatcher; runner; renderer; history; def suspend(self) -> ContextManager[None]   # :41-64
@dataclass class SlashCommand: name: str; description: str; handler: Callable   # :68, :77-79
class SlashCommandDispatcher: def register(self, cmd: SlashCommand) -> None (:131) ; def _register_builtins(self) -> None (:187) ; builtins list :189-209
# packages/ai-parrot/src/parrot/cli/loaders.py
class StandaloneAgentLoader: async def load(self, name: str) -> AbstractBot   # :90, :141
class _ServerBotProxy: async def configure(self, app: Any = None) -> None (no-op :242) ; async def ask(..., user_id: Optional[str] = None, ...) (:249 ; never sends user_id :280)
class ServerAgentProxy: def __init__(self, server_url: str, timeout: int = 30, *, token: Optional[str] = None) -> None   # :466, :477-483 ; Bearer header :506 ; M7 adds login_store: Optional[LoginStore] = None (Q5: auto-refresh on 401)

# packages/ai-parrot-integrations/src/parrot/integrations/agentd/server.py
def _read_peercred(sock: socket.socket) -> tuple[int, int, int]:          # :62
def _uid_to_username(uid: int) -> str:                                    # :77 (pwd.getpwuid(uid).pw_name :89)
class JsonRpcUnixServer:
    def __init__(self, socket_path: Path, dispatch: dict[str, Handler], *, max_line_bytes: int = DEFAULT_MAX_LINE_BYTES, service_identity: ServiceIdentityConfig | None = None) -> None:   # :228-235
    async def _resolve_identity(self, writer: asyncio.StreamWriter) -> tuple[PermissionContext, str]:   # :323-361 ; peercred return :355 ; fallback :361
    async def _handle_connection(self, reader, writer) -> None:          # :363-377
# packages/ai-parrot-integrations/src/parrot/integrations/agentd/config.py
class ServiceIdentityConfig(BaseModel): display_name; user_id: str = "1001"; tenant_id: str = "default"; roles: frozenset[str]   # :131, :163-166
    @classmethod def from_env(cls) -> ServiceIdentityConfig (:179) ; def to_permission_context(self, channel: str = "agentd") -> PermissionContext (:198)

# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py
#   if self.auth_type == "oauth2_local": ... self._local_single_user = True   # :927-933
#   async def _pre_execute(self, tool_name: str, /, **kwargs) -> None       # :1316 ; if self._local_single_user: :1338 ; user_key = "local:cli" :1350
# packages/ai-parrot-tools/src/parrot_tools/jira_cli.py
def parse_pasted_redirect(text: str) -> Tuple[str, Optional[str]]:         # :42
@click.group(name="jiratoolkit") def cli() -> None                        # :261-262
def auth(site, scopes, env_file, client_id, client_secret, redirect_uri, allow_bare_code) -> None   # :283 ; status :356 ; logout :384 ; sync_kb :395
# packages/ai-parrot-tools/src/parrot_tools/jira_local_auth.py  (DELETED by M10)
DEFAULT_SETTINGS_PATH = Path("~/.parrot/jira/settings.local.json")        # :24 ; class LocalJiraTokenStore :35 ; class FileTokenCredentialResolver(CredentialResolver) :155 (allowed_channels default {"cli","local"} :172)

# packages/ai-parrot/src/parrot/auth/oauth2/o365_devicecode_provider.py
def _default_prompt_callback(flow: Dict[str, Any]) -> None:              # :57 (print → stdout today)
class O365DeviceCodeCredentialResolver(CredentialResolver):               # :73 ; __init__(o365_client, o365_oauth_manager, vault_token_sync, scopes=None, prompt_callback=None) :100-107 ; resolve :117 ; _run_device_flow :206
# packages/ai-parrot/src/parrot/auth/broker/factory.py
class CredentialResolverFactory: def __init__(self, deps: dict[str, Any] | None = None) (:43) ; def build(self, cfg) (:46) ; _build_oauth2 (:114) ; _build_device_code (:168, does not forward prompt_callback)

# packages/ai-parrot/src/parrot/auth/oauth2/service.py (live) — S-1 rewrites these signatures (spec:582-597)
class IntegrationsService:                                                # :74 ; list_for_user :90 ; start_connect :291 ; confirm_enable :346 ; disconnect :406 ; persist_credential :440 ; _check_pbac(request, action, provider_id=None) :490
# packages/ai-parrot/src/parrot/auth/oauth2_base.py
_NONCE_KEY_TEMPLATE = "oauth2:{provider}:nonce:{nonce}" (:40) ; _NONCE_TTL_SECONDS = 600 (:48) ; create_authorization_url stores the state record :304-343 ; handle_callback validates the nonce :354+
# packages/ai-parrot/src/parrot/auth/session_identity.py
def resolve_user_id(request: Any, session: Any = None) -> str | None:     # :90-133
# packages/ai-parrot-server/src/parrot/handlers/integrations.py
class IntegrationsHandler(BaseView):                                      # :34 ; async def _get_user_id(self) -> str | None :43 (request["user_id"] → session user_id/id/username)
# packages/ai-parrot-server/src/parrot/manager/manager.py
#   # OAuth2 Integrations routes (FEAT-144)  → router.add_view("/api/v1/agents/integrations/...", IntegrationsHandler) ×4   # :2457-2472
#   async def _register_oauth2_providers(self, app: web.Application) -> None   # :2789 (on_startup :2388)
# packages/ai-parrot-server/src/parrot/mcp/config.py
class AuthMethod(str, Enum): NONE, API_KEY, OAUTH2_INTERNAL, OAUTH2_EXTERNAL, BEARER   # :9-15

# navigator-auth 0.28.7 (.venv/lib/python3.12/site-packages/navigator_auth)
class Oauth2Provider(BaseAuthBackend):                                    # backends/oauth2/backend.py:258
    device_authorization_uri = "/oauth2/device_authorization" (:292) ; device_uri = "/oauth2/device" (:293) ; routes :323-394 (token :333, userinfo :336, revoke :347, introspect :360, device :364-372, jwks :394)
    async def token_request(self, request) (:1694) ; async def _handle_device_code(self, payload, request) (:2105 — device_code, client_id, PKCE :2165) ; async def userinfo(self, request) (:2194 — claims {"sub": str(user_id)} + profile/email by scope)
    async def device_authorization(self, request) (:2500 — client_id, scope, code_challenge S256 required for public clients :2528-2540) ; async def authenticate(self, request) (:2833 — validates Bearer, jti revocation, binds session) ; check_credentials (:2884)
backends/oauth2/devicecode.py: generate_user_code(length, alphabet) ; poll_decision(dc, now) → slow_down | authorization_pending | access_denied | expired_token | approved
backends/oauth2/metadata.py: WELL_KNOWN_AS_PATH = "/.well-known/oauth-authorization-server" (:42) ; DEFAULT_ENDPOINT_PATHS (:46-55) ; grant types incl. device_code (:68-73)
backends/oauth2/models.py: OAuthClient fields client_id (:84), client_type: str = "public" (:89), default_scopes (:95), allowed_grant_types (:96), token_endpoint_auth_method (:99), registration_source (:101)
conf.py: OAUTH_ACCESS_TOKEN_TTL=3600 (:723) ; OAUTH_REFRESH_TOKEN_TTL=2592000 (:729) ; OAUTH_REFRESH_ROTATION=True (:735) ; OAUTH_REQUIRE_PKCE_PUBLIC=True (:738) ; OAUTH_DEVICE_CODE_TTL=600 (:785) ; OAUTH_DEVICE_POLL_INTERVAL=5 (:788) ; OAUTH_DEVICE_SLOW_DOWN_INCREMENT=5 (:791) ; OAUTH_DEVICE_VERIFICATION_URI (:800)
backends/token.py: class TokenAuth(BaseAuthBackend) (:54) — partner JWT via AUTH_TOKEN_SECRET (:104); NOT the CLI path
decorators.py: def user_session() (:117) ; def is_authenticated(content_type="application/json") (:179)
settings/settings.py (this repo): AUTHENTICATION_BACKENDS = ('navigator_auth.backends.BasicAuth',) with TokenAuth commented out (:111-121) — Oauth2Provider must be added for `parrot login` (§7)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `LoginStore` / `parrot login` | navigator-auth `Oauth2Provider` device grant, token, userinfo, revoke | aiohttp client (M8 helpers) | `backend.py:292, 333, 336, 347, 364-372, 2105, 2194, 2500` |
| `CliPrincipalResolver` | `build_principal_context` | call | `permission.py:166-172` |
| `CliPrincipalResolver` | `GET /api/v1/connections/me` (M3) → `resolve_user_id` | HTTP → call | `session_identity.py:90` |
| `ServerConnectionsClient` | S-1 `ConnectionsHandler` + M3 routes | HTTP bearer | planned `spec:356-359, 605-608`; `manager.py:2457-2472` route block |
| `RemoteConnectionResolver` | `CredentialBroker.register` / `resolve` | `build_cli_broker` | `broker/core.py:81, 156` |
| `ToolExecutionContext.exec_kwargs()` | `AbstractTool.execute` kwargs | `MCPToolAdapter.execute` | `tools/abstract.py:939, 950-952, 1023` |
| `auth_required_result` | `AuthorizationRequired.to_payload()` / `CredentialRequired.to_payload()` | except branch | planned `spec:550, 561` |
| `create_toolkit_mcp_server(login_file=…)` | `_ToolkitStdioMCPServer.start()` | resolve principal + broker once before serving | `toolkit_server.py:62, 262` |
| `mcp_local --login-file` | `create_toolkit_mcp_server` | `overrides` / kwarg | `local_cli.py:209-218` |
| host entries | `toolkit_mcp_json_entry` env / `toolkit_mcp_block` env | `PARROT_LOGIN_FILE` passthrough | `claude_code/assets.py:181`, `codex/assets.py:89-91` |
| `run_connect` | S-1 `start_connect(channel="cli")`, `GET /{provider}`, M3 `/complete`, `/token` | HTTP | planned `spec:587-590`; `models.py:79` (`ConnectInitResponse.state`) |
| `/connect` built-ins | `SlashCommandDispatcher._register_builtins`, `CommandContext.suspend` | list insertion, context manager | `commands.py:189-209, 62` |
| `_run` (M7) | `LoginStore`, `CliPrincipalResolver`, `ToolManager.set_broker`, `REPLConfig` | calls | `agent_repl.py:161-164, 218-224, 238-248`; `tools/manager.py:517`; `repl.py:60-69` |
| agentd step (M9) | `LoginStore.for_uid`, `CliPrincipalResolver` | `_resolve_identity` | `agentd/server.py:353-355` |
| `complete_connect` (M3) | S-1 `AbstractOAuth2Manager.handle_callback` + `IntegrationsService.persist_credential` | calls | `oauth2_base.py:354`; planned `spec:596-597` |
| `pull_access_token` (M3) | `IntegrationsService._check_pbac`, S-1 `get_valid_token`, `ConnectionEventPublisher.publish` | calls | `service.py:490`; planned `spec:453-454, 530` |
| device endpoints (M3/M8) | S-1 `StandardOAuth2Manager` + Redis handle `oauth2:{provider}:device:{handle}` | calls | planned `spec:483`; nonce pattern `oauth2_base.py:40-48` |
| `parrot jiratoolkit auth` alias | `parrot.cli.connect.run_connect` | call | `jira_cli.py:283` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot login` / `parrot logout` / `parrot whoami` / `parrot connect` / `parrot connections` / `parrot disconnect`~~ — none registered in `cli/__init__.py:109-141`; M1/M6 create them.
- ~~`parrot.cli.login`, `LoginStore`, `LoginRecord`, `parrot.cli.principal`, `CliPrincipalResolver`~~ — do not exist (grep 0 hits under `parrot/cli`, `parrot/auth`).
- ~~`parrot.auth.oauth2.device_code`, `DeviceAuthorization`, `poll_device_token`~~ — no generic device-code engine; only the O365-bound resolver exists (`o365_devicecode_provider.py:73`).
- ~~`RemoteConnectionResolver`, `ConnectionCache`, `ServerConnectionsClient`, `parrot.auth.oauth2.local_cache`, `remote_client`~~ — do not exist; every `CredentialResolverFactory` kind needs an in-process `oauth_manager` or `vault` (`factory.py:59-74`).
- ~~`CredentialBroker.add_resolver()`~~ — the method is `register()` (`core.py:81`).
- ~~`CredentialRequired.to_payload()` / `AuthorizationRequired.to_payload()` on dev~~ — added by S-1 M5 (planned); not present at `370a62d9b`.
- ~~`MCPToolAdapter(tool, execution_context=…)`, `ToolExecutionContext`, `structuredContent` in adapter.py~~ — adapter takes only `tool` (`adapter.py:19`), calls `tool._execute` (`:79`), emits text content only.
- ~~a principal / `PermissionContext` anywhere in `parrot/mcp/*.py`~~ — grep 0 hits; `handle_tools_call` passes only `arguments` (`server_base.py:124`).
- ~~`ToolkitSection.user` / `principal` / `token`~~ — fields are class/enabled/kwargs/include/exclude/llm/llm_kwargs/env (`toolkit_config.py:50-57`).
- ~~loopback redirect / `webbrowser` OAuth in `parrot.mcp`~~ — none; `MCPOAuth2Config.redirect_path` is the server callback (`oauth2_config.py:79-91`).
- ~~`OAuth2ProviderDescriptor.device_authorization_url`~~ — not in the S-1 descriptor (planned `spec:250-265`); M8 adds it.
- ~~`ConnectionEventKind` value `connection.token_pulled`~~ — S-1 defines three kinds (planned `spec:268`); M3 adds it.
- ~~`/api/v1/connections/me`, `/{provider}/token`, `/{provider}/complete`, `/{provider}/device/*`~~ — S-1 defines only list/start/get/delete (planned `spec:356-359`).
- ~~`IntegrationsService.whoami` / `pull_access_token` / `complete_connect` / `device_start` / `device_poll`~~ — do not exist (`service.py:74-490`).
- ~~navigator-auth `TokenAuth` as the CLI login path~~ — it validates partner JWTs (`token.py:104`), not `parrot-cli` device-grant tokens; the CLI path is `Oauth2Provider.authenticate` (`backend.py:2833`).
- ~~`Oauth2Provider` enabled in this repo's settings~~ — `settings/settings.py:111-121` lists only `BasicAuth`; a deployment prerequisite (§7, §8).
- ~~`CanonicalIdentityMapper.to_canonical(str)`~~ — takes a dict (`identity.py:75`); S-4 never calls it (identity comes from `/me`).
- ~~agentd reading `~/.parrot` today~~ — `_resolve_identity` only does peercred → username (`server.py:349-361`).
- ~~`AGENTD_LOGIN_FILE_LOOKUP`, `ServiceIdentityConfig.login_file_lookup`~~ — do not exist (`config.py:37-40, 161-166`).
- ~~`ToolManager` kwargs reaching `ToolkitTool._execute`~~ — `_broker` / `_cred_*` are popped in `AbstractTool.execute`; only `_permission_context` is re-injected into `_pre_execute` (`toolkit.py:176-179`); toolkits read the secret via `current_credential()` (`abstract.py:45`).

### Edit Sites (Blueprint Anchors)

Verified against: `370a62d9b` (`dev`, 2026-10-30). `/sdd-task` MUST re-run `grep -c -F` for every row it uses; rows marked **S-1 file** are anchored to `sdd/specs/delegated-auth-connections.spec.md` lines and MUST be re-anchored to code after FEAT-773 merges.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/cli/login.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/cli/principal.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/cli/connect.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/auth/oauth2/device_code.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/auth/oauth2/local_cache.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/auth/oauth2/remote_client.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/auth/oauth2/paste.py` | CREATE | — | — | — |
| `docs/cli/parrot-login-and-connections.md` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/cli/__init__.py` | MODIFY | `    "mcp-serve": "parrot.integrations.agentd.cli",` | `cli/__init__.py:140` | 1 (insert the six new entries after it, before `}` :141) |
| `packages/ai-parrot/src/parrot/cli/agent_repl.py` | MODIFY | `from parrot.cli.identity import bot_declares_o365_device_code, build_cli_permission_context` | `agent_repl.py:23` | 1 |
| `packages/ai-parrot/src/parrot/cli/agent_repl.py` | MODIFY | `        loader = ServerAgentProxy(server, token=token)` | `agent_repl.py:162` | 1 |
| `packages/ai-parrot/src/parrot/cli/agent_repl.py` | MODIFY | `    permission_context = None` | `agent_repl.py:218` | 1 |
| `packages/ai-parrot/src/parrot/cli/agent_repl.py` | MODIFY | `        user_id=None if server else (user_id or "cli-user"),` | `agent_repl.py:247` | 1 |
| `packages/ai-parrot/src/parrot/cli/identity.py` | MODIFY | `def resolve_cli_o365_principal() -> str:` | `identity.py:45` | 1 |
| `packages/ai-parrot/src/parrot/cli/identity.py` | MODIFY | `def build_cli_permission_context(user_id: Optional[str] = None) -> PermissionContext:` | `identity.py:76` | 1 |
| `packages/ai-parrot/src/parrot/cli/identity.py` | MODIFY | `def bot_declares_o365_device_code(bot: object) -> bool:` | `identity.py:108` | 1 |
| `packages/ai-parrot/src/parrot/cli/repl.py` | MODIFY | `    history_enabled: bool = True` | `repl.py:69` | 1 |
| `packages/ai-parrot/src/parrot/cli/commands.py` | MODIFY | `            SlashCommand("help", "List all available slash commands.", _cmd_help),` | `commands.py:207` | 1 (insert `/connect`, `/connections`, `/disconnect` before it) |
| `packages/ai-parrot/src/parrot/mcp/adapter.py` | MODIFY | `    def __init__(self, tool: AbstractTool):` | `adapter.py:19` | 1 |
| `packages/ai-parrot/src/parrot/mcp/adapter.py` | MODIFY | `            result = await self.tool._execute(**arguments)` | `adapter.py:79` | 1 |
| `packages/ai-parrot/src/parrot/mcp/server_base.py` | MODIFY | `    def __init__(self, config: LocalServerConfig):` | `server_base.py:60` | 1 |
| `packages/ai-parrot/src/parrot/mcp/server_base.py` | MODIFY | `        adapter = MCPToolAdapter(tool)` | `server_base.py:71` | 1 |
| `packages/ai-parrot/src/parrot/mcp/toolkit_server.py` | MODIFY | `    **overrides: Any,` | `toolkit_server.py:140` | 1 |
| `packages/ai-parrot/src/parrot/mcp/toolkit_server.py` | MODIFY | `    server = _ToolkitStdioMCPServer(LocalServerConfig(name=f"parrot-{name}", version="1.0.0"), toolkit)` | `toolkit_server.py:262` | 1 |
| `packages/ai-parrot/src/parrot/mcp/toolkit_server.py` | MODIFY | `    def __init__(self, config: LocalServerConfig, toolkit: AbstractToolkit) -> None:` | `toolkit_server.py:56` | 1 |
| `packages/ai-parrot/src/parrot/mcp/local_cli.py` | MODIFY | `    "--list",` | `local_cli.py:161` | 1 (add `--login-file` option after this option block, :160-166) |
| `packages/ai-parrot/src/parrot/mcp/local_cli.py` | MODIFY | `        server = create_toolkit_mcp_server(name, root, **overrides)` | `local_cli.py:218` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py` | MODIFY | `        "env": dict(section.env),` | `claude_code/assets.py:181` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py` | MODIFY | `        if section.env:` | `codex/assets.py:89` | 1 |
| `packages/ai-parrot/src/parrot/auth/oauth2/o365_devicecode_provider.py` | MODIFY | `def _default_prompt_callback(flow: Dict[str, Any]) -> None:` | `o365_devicecode_provider.py:57` | 1 |
| `packages/ai-parrot/src/parrot/auth/oauth2/service.py` | MODIFY | `    async def start_connect(` | `service.py:291` | 1 (S-1 M6 also modifies this method; serialize) |
| `packages/ai-parrot/src/parrot/auth/oauth2/service.py` | MODIFY | `    async def _check_pbac(` | `service.py:490` | 1 |
| `packages/ai-parrot/src/parrot/auth/oauth2/__init__.py` | MODIFY | `    UserAgentToolkitRow,` | `oauth2/__init__.py:26` | 1 (S-1 removes this symbol; `/sdd-task` re-anchors to the post-S-1 export list) |
| `packages/ai-parrot/src/parrot/auth/oauth2/descriptor.py` | MODIFY (S-1 file) | `    pbac_action_namespace: str = "integration"` | planned `delegated-auth-connections.spec.md:264` | re-anchor after FEAT-773 |
| `packages/ai-parrot/src/parrot/auth/oauth2/events.py` | MODIFY (S-1 file) | `ConnectionEventKind = Literal["connection.completed", "connection.revoked", "connection.refresh_failed"]` | planned `delegated-auth-connections.spec.md:268` | re-anchor after FEAT-773 |
| `packages/ai-parrot-server/src/parrot/handlers/connections.py` | MODIFY (S-1 file) | `class ConnectionsHandler(BaseView):` | planned `delegated-auth-connections.spec.md:605` | re-anchor after FEAT-773 |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | `        # OAuth2 Integrations routes (FEAT-144)` | `manager.py:2457` | 1 (S-1 adds the 4 `ConnectionsHandler` routes here; S-4 adds 5 more, `/me` before `/{provider}`) |
| `packages/ai-parrot-integrations/src/parrot/integrations/agentd/server.py` | MODIFY | `from parrot.auth.permission import PermissionContext, build_principal_context` | `agentd/server.py:28` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/agentd/server.py` | MODIFY | `            return build_principal_context(username, channel="agentd"), "peercred"` | `agentd/server.py:355` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/agentd/config.py` | MODIFY | `    roles: frozenset[str] = Field(default_factory=frozenset)` | `agentd/config.py:166` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY | `        if self.auth_type == "oauth2_local":` | `jiratoolkit.py:927` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY | `            user_key = "local:cli"` | `jiratoolkit.py:1350` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY | `from .jira_local_auth import FileTokenCredentialResolver` | `jiratoolkit.py:67` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/jira_cli.py` | MODIFY | `def parse_pasted_redirect(text: str) -> Tuple[str, Optional[str]]:` | `jira_cli.py:42` | 1 (body moves to `parrot/auth/oauth2/paste.py`; this becomes a re-export) |
| `packages/ai-parrot-tools/src/parrot_tools/jira_cli.py` | MODIFY | `def auth(site, scopes, env_file, client_id, client_secret, redirect_uri, allow_bare_code) -> None:` | `jira_cli.py:283` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/jira_cli.py` | MODIFY | `from parrot_tools.jira_local_auth import FileTokenCredentialResolver, LocalJiraTokenStore` | `jira_cli.py:32` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/jira_local_auth.py` | DELETE | — | — | — |
| `packages/ai-parrot-tools/tests/unit/test_jira_local_auth.py`, `test_oauth2_local_wiring.py` | DELETE | — | — | — |
| `docs/mcp-local-toolkits.md` | MODIFY | `# Expose Toolkits as Local MCP (\`parrot mcp-local\`)` | `docs/mcp-local-toolkits.md:1` | 1 |
| `docs/cli/parrot-agent.md` | MODIFY | (first heading; section appended) | `docs/cli/parrot-agent.md:1` | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **FEAT-485 lean stdio**: every new import inside `toolkit_server.py` / `local_cli.py` happens under the existing
  `contextlib.redirect_stdout(sys.stderr)` block (`toolkit_server.py:186`, `local_cli.py:201`); `parrot.auth.*`
  modules used by stdio code must not import navconfig at module level; user-facing prompts go to stderr or into
  the MCP result.
- **Reuse the FEAT-264 seam**: never re-implement the gate; feed `AbstractTool.execute` the four kwargs
  (`abstract.py:939, 950-952`) and read secrets with `current_credential()`.
- **agentd binding template** (`server.py:323-361`): `asyncio.to_thread` for every blocking lookup, explicit
  `identity_source`, fail-safe fallback.
- **principal_guard discipline**: tenant never defaults to the principal in S-4 code — always pass the server's
  tenant to `build_principal_context`.
- **FEAT-696 file hygiene** (`jira_local_auth.py:49-62, 95-106`): lock file, `os.fchmod(fd, 0o600)`, atomic
  rename, `expanduser()`; add `O_NOFOLLOW` and owner checks.
- **RFC 8628 client**: respect `interval`, add `OAUTH_DEVICE_SLOW_DOWN_INCREMENT` (5 s) on `slow_down`, stop at
  `expires_in`; PKCE S256 for the public client (`backend.py:2528-2540`).
- **S-1 conventions**: `channel` is a free string documented in the `Principal` docstring — add `agentd`; the
  `ConnectionEventKind` Literal is extended, not forked; durable-first stays on the server.
- Pydantic v2 models, `self.logger`, aiohttp only, Google docstrings, 120 columns.

### Known Risks / Gotchas
- **Deployment prerequisite**: `parrot login` requires the navigator-auth `Oauth2Provider` backend in
  `AUTHENTICATION_BACKENDS` and a static public client `parrot-cli` (`client_type="public"`,
  `allowed_grant_types` ⊇ {`urn:ietf:params:oauth:grant-type:device_code`, `refresh_token`}, `default_scopes`
  including `openid profile email` or the deployment's equivalents). This repo's `settings/settings.py` enables only
  `BasicAuth` today. Mitigation: AC-2 fail-loud message; docs list the exact settings; §8 Q1 owns the rollout.
- **Access-token lifetime vs cache**: provider access tokens pulled into the cache expire on their own schedule; the
  resolver re-pulls on expiry and the server refreshes. A revoked connection is noticed at the next pull (≤ token
  lifetime). Mitigation: `skew_s=60`; `parrot disconnect` wipes the cache entry immediately.
- **Cache key boundary** (S4): possession of `login.json` + the cache decrypts cached access tokens; no refresh
  token is ever cached (S5). `parrot logout` wipes both. OS keyring is §8 Q2.
- **agentd privilege** (S11): a daemon that cannot read the peer's home silently falls back to peercred; a daemon
  running as root can read any user's login file — ownership + mode + `O_NOFOLLOW` checks and `login_file_lookup`
  flag limit it; the privilege model is §8 Q3.
- **stdout corruption**: any `print()` in stdio code breaks the host; the O365 prompt is moved to stderr (M8) and
  tests assert `capsys.out == ""`.
- **Route ordering**: `/api/v1/connections/me` must be registered before `/api/v1/connections/{provider}` or aiohttp
  treats `me` as a provider (`manager.py:2457-2472` block).
- **S-1 anchors move**: `service.py:291`, `oauth2/__init__.py:26`, the descriptor/events/handler files and the Jira
  helpers `jira_cli.py` imports (`build_authorization_url`, `exchange_code`) are rewritten by FEAT-773 M6/M7;
  `/sdd-task` re-anchors after merge (table header).
- **Hard cuts** (project policy: no shims for internal APIs): `O365_PRINCIPAL` bootstrap, `oauth2_local`,
  `jira_local_auth.py` and its two test files are removed, not deprecated. The WorkIQ OBO interop assertion in
  `test_cli_devicecode_e2e.py` depends on the Entra-keyed `VaultTokenSync o365:*` write; S-4 keeps that write only
  through the server-side O365 `post_exchange` hook (S-1 registry) and moves the OBO assertion to S-3a's backlog.
- **Two MCP test trees**: root `tests/mcp/` and `packages/ai-parrot/tests/mcp/`; new tests go next to the module they
  cover and both trees are in the Validation Contract.
- **Local-MCP surface in flight**: hotfix `b80ea3a98` (2026-10-28) touched `local_cli.py` / `local_server.py`;
  re-grep anchors at task time.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `navigator-auth` | `>=0.28.7` (server) | `Oauth2Provider` device grant, userinfo, revoke, bearer validation (`backend.py:258-2884`) |
| `aiohttp` | existing | all CLI ↔ server and CLI ↔ IdP traffic |
| `cryptography` | existing (via `parrot.security.vault_utils`) | AES-GCM for `ConnectionCache` |
| `click` | existing | new commands |
| `pydantic` | `>=2` existing | models |

---

## 8. Open Questions

> Resolved items carried from the proposal (decision trail). Unresolved items are decisions the user or ops must take before or during implementation.

- [x] U1 — How does a CLI user obtain the login token? — *Resolved in proposal*: `parrot login` (browser/device): a new `parrot login` completes a navigator-auth browser or device login and stores a CLI token in a 0600 file under `~/.parrot/`; `parrot logout` removes it. *Refined at spec time*: the device login is navigator-auth's own RFC 8628 grant (public client `parrot-cli`, PKCE S256), which also settles the proposal's "login token shape" item: access JWT (`OAUTH_ACCESS_TOKEN_TTL`), rotating refresh token, identity from `/oauth2/userinfo` + `GET /api/v1/connections/me`.
- [x] U2 — How do stdio MCP toolkit servers get provider tokens? — *Resolved in proposal*: local encrypted token file, as an encrypted cache synced from the server: the server completes the 3LO and the Identity Vault stays the durable owner; `parrot connect` pulls the token set into a local encrypted file (key derived from the login token); refresh goes through the server when expired. *Refined at spec time (S4/S5)*: the file holds access tokens only; the key is a random per-login `cache_key` stored in the login file rather than the rotating access token.
- [x] U3 — How does a CLI connect complete? — *Resolved in proposal*: poll + paste fallback: print/open the authorize URL and poll `GET /api/v1/connections` until the connection appears; when the browser cannot reach back (SSH), paste the redirected URL and the CLI posts the code to the server. *Refined (S10)*: completion requires `connected_at >= started_at`; paste posts `{code, state}` to `/complete`.
- [x] U4 — Generic RFC 8628 device code in S-4? — *Resolved in proposal*: generic engine in S-4: add `device_authorization_url` to the S-1 descriptor and an RFC 8628 poller surfaced through the `AuthRequiredPayload` device fields (Microsoft, Google).
- [x] U5 — Is agentd in S-4 scope? — *Resolved in proposal*: yes, per-OS-user login file: the daemon resolves the peer's OS user (SO_PEERCRED) and reads that user's `~/.parrot` login file to obtain the Navigator principal. *Constrained (S11)*: owner/mode/symlink checks, `to_thread`, fallback, `AGENTD_LOGIN_FILE_LOOKUP`.
- [x] Token-pull endpoint policy (proposal §5 unresolved) — *Resolved at spec time (S5)*: PBAC action `integration:use` with the provider in context; audit event `connection.token_pulled`; refresh tokens never leave the server.
- [x] Login token shape (proposal §5 unresolved) — *Resolved at spec time (S6)*: see U1 refinement.
- [x] **Q1 — Rollout of the navigator-auth prerequisites** — *Resolved 2026-10-30*: **pre-task**. Ops enables `navigator_auth.backends.oauth2.Oauth2Provider` in `AUTHENTICATION_BACKENDS`, creates the static `parrot-cli` public client (`client_type="public"`, `allowed_grant_types` ⊇ {device_code, refresh_token}, `default_scopes` ⊇ {openid, profile, email}), and sets `OAUTH_DEVICE_VERIFICATION_URI` **before `/sdd-task FEAT-774` runs**. Tasks can integration-test against the real AS. AC-2 remains the runtime guard for deployments that have not yet enabled it.
- [x] **Q2 — Cache key owner (S4)** — *Resolved 2026-10-30*: **file only**. The random `cache_key` stays in `login.json` (0600). No `keyring` dependency. This is sufficient for the current deployment model; an OS-keyring backend can be added in a follow-up if desktop hardening requires it.
- [x] **Q3 — agentd privilege model (S11)** — *Resolved 2026-10-30*: **per-user daemon**. Each user runs their own agentd instance; it reads only `~/.parrot/login.json` owned by the same uid (enforced by the owner check in `LoginStore.load_optional(expected_uid=uid)`). Docs describe only the per-user deployment pattern. A shared-service-user model (daemon running as a different uid reading peers' homes) is out of scope.
- [x] **Q4 — First device-code providers** — *Resolved 2026-10-30*: **all providers that support RFC 8628**. Microsoft (`https://login.microsoftonline.com/{tenant}/oauth2/v2.0/devicecode`), Google (`https://oauth2.googleapis.com/device/code`), and any other provider whose docs confirm device-grant support get `device_authorization_url` set in their `OAuth2ProviderDescriptor`. Atlassian (no device grant) is documented as poll + paste only.
- [x] **Q5 — `--server` mode token refresh** — *Resolved 2026-10-30*: **auto-refresh once**. On a 401 in `ServerAgentProxy`, call `refresh_login` once via `LoginStore`, update the stored record, and retry the request. If the refresh also fails (expired refresh token, revoked, network), print `"Session expired — run 'parrot login' again"` and exit 2. `ServerAgentProxy.__init__` accepts an optional `LoginStore`; when absent (legacy callers), the 401 is surfaced without retry.

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted proposal** (never over this spec).
> Model: `gpt-5.6-luna` (codex-cli 0.164.0) · Status: completed · Transcript: `sdd/state/FEAT-774/design_research/`
> Every `affected_paths` entry passed repository containment and `test -e`; S1, S2, S4, S9 and S12 were verified against the cited code before disposition.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Make the ToolManager boundary real for stdio (architecture) | CONFIRM | Verified `adapter.py:79` bypasses `AbstractTool.execute`; S-4 adds `ToolExecutionContext` and routes through `execute`. | §2 Overview, §3 M5, AC-7 |
| S2 | Define structured MCP auth-required output (api) | CONFIRM | Verified no `structuredContent`; one envelope fixed, fields asserted by test, stdout purity kept. | §2 Data Models, §3 M5, AC-8 |
| S3 | Resolve the agentd channel contract (api) | CONFIRM (modified) | `channel="agentd"` kept and documented as valid; resolver accepts `cli` and `agentd`; `identity_source="login_file"`. | §3 M2, M9, §7 |
| S4 | Do not make login-token-derived encryption the only cache boundary (risk) | CONFIRM (modified) + ESCALATE | Random per-login `cache_key` (not the rotating token), cache stays re-pullable, wiped on logout; keyring backend is a decision. | §3 M4, §7, §8 Q2 |
| S5 | Pull access tokens only; keep refresh tokens server-side (risk) | CONFIRM | Matches the U2 follow-up; endpoint returns access token + expiry; PBAC + audit per pull. | §3 M3, M4, AC-5 |
| S6 | Freeze the login-token and identity-endpoint contract first (api) | CONFIRM | navigator-auth's RFC 8628 grant + `Oauth2Provider.authenticate` fix the contract: `parrot-cli` public client, PKCE, JWT TTLs, `/userinfo` `sub`, `/me` roles, 401 on invalid/revoked. | §2 Overview, §3 M1, M3, §8 |
| S7 | Return roles or scopes with CLI principal resolution (api) | CONFIRM | `/me` returns roles + scopes; `build_cli_permission_context` passes them. | §3 M2, M3 |
| S8 | Specify RFC 8628 as a typed engine, not only a URL field (architecture) | CONFIRM | `device_code.py` state machine with timeout/cancellation; descriptor field is only the endpoint. | §3 M8, AC-10 |
| S9 | Keep local cache I/O off the event loop (risk) | CONFIRM | `asyncio.to_thread`, per-provider single-flight lock. | §3 M4, AC-6 |
| S10 | Correlate connect polling with an attempt (api) | CONFIRM (modified) | No new server state: `(state, started_at)` on the CLI, `connected_at >= started_at` on poll, nonce check on paste. | §3 M3, M6, AC-9 |
| S11 | Do not make agentd read arbitrary peer home directories implicitly (risk) | CONFIRM (modified) + ESCALATE | Owner/mode/`O_NOFOLLOW` checks, `to_thread`, fallback, opt-out flag; privilege model is a decision. | §3 M9, §7, §8 Q3 |
| S12 | Keep server-proxy REPL identity bearer-owned (architecture) | CONFIRM | Verified `_ServerBotProxy` never sends `user_id`; resolver applies to standalone/mcp-local/agentd only; login token becomes the default bearer. | §3 M7, AC-3 |

Summary: **12** confirmed (4 with modifications, 2 of which also raise a §8 question) · **0** rejected · **0** escalated outright.

---

## Worktree Strategy

- **Default isolation unit**: ONE feature worktree for the spec (`feat-FEAT-774-connections-cli-local-mcp`); the `sdd-coder` engine gives each task its own sub-worktree inside it.
- **Module dependency graph** (edges = imports of a symbol fixed in §3):
  - M1 → M8 (`discover_authorization_server`, `request_device_authorization`, `poll_device_token`, `make_pkce_pair` — client half only)
  - M2 → M1 (`LoginStore`, `refresh_login`), M4 (`ServerConnectionsClient.me`)
  - M3 → M8 (`StandardOAuth2Manager.start_device_authorization` / `complete_device_authorization`), S-1 M2/M6
  - M4 → M1 (`LoginStore`), S-1 `AuthRequiredPayload`
  - M5 → M2, M4
  - M6 → M4, M8 (device variant), M1
  - M7 → M2, M4
  - M9 → M1, M2, M4
  - M10 → M4, M6
  - M11 → all
  - Concurrent: M8 (pure client engine) first; then M1 ∥ M3-server-half; then M4; then M2; then M5 ∥ M6 ∥ M7 ∥ M9; then M10; M11 last.
- **Shared files** (tasks serialized): `parrot/cli/__init__.py` (M1, M6); `parrot/auth/oauth2/__init__.py` (M4, M8 exports); `parrot/auth/oauth2/service.py` (M3 only, but S-1 M6 rewrites it first); `parrot/cli/agent_repl.py` (M7 only); `parrot_tools/jira_cli.py` (M10 only); `ai-parrot-server manager/manager.py` (M3 only, after S-1 M6).
- **Exclusive resources**: none (no compiled extensions, no lockfile, no DB migration — the `parrot-cli` OAuth client is a navigator-auth data row created by ops, §8 Q1).
- **Cross-feature dependencies**: **FEAT-773 must be merged into `dev` before `/sdd-task FEAT-774`** (planned symbols in §6). The local-MCP files carry hotfix `b80ea3a98` (2026-10-28); re-anchor at task time.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-30 | Jesus Lara (with Claude Fable 5.1) | Initial draft from proposal FEAT-774 (accepted). S-4 scope; U1–U5 carried forward; codex design research folded (12 CONFIRM, 2 with §8 escalations). Codebase Contract verified against `370a62d9b`; S-1 symbols marked planned pending FEAT-773 merge. |
| 0.2 | 2026-10-30 | Jesus Lara (with Claude Opus 4.6) | Resolved Q1–Q5: pre-task ops rollout; file-only cache key (no keyring); per-user agentd daemon; all RFC 8628 providers + Atlassian poll+paste; auto-refresh once on 401 in --server mode (ServerAgentProxy gains login_store). |
| 0.3 | 2026-10-31 | Jesus Lara (with Claude Opus 5.5) | `/sdd-task`: FEAT-773 test files and the 19 new per-task test files added to the Validation Contract. Re-anchoring drifts recorded in the tasks (not here): descriptor status is `connected` (not `active`); `AuthorizationRequired.to_payload()` has no `tool_name`; AES-GCM via `cryptography` (no helper in `vault_utils`); no `parrot.auth.oauth2/__init__` exports (import cycle); `WhoAmI`/`PulledToken`/`NotConnected` live in `oauth2/models.py`. |
