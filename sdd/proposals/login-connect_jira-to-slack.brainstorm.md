# Brainstorm: Port `/login` (Azure SSO) and `/connect_jira` Commands to the Slack Integration

**Date**: 2026-04-23
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: B

---

## Problem Statement

The Telegram integration exposes two independent authentication commands that corporate users rely on:

1. `/login` — Azure AD single sign-on, delegated to Navigator's `/api/v1/auth/azure/` endpoint. Produces a Navigator JWT that stamps a `nav_user_id` onto the per-user session.
2. `/connect_jira` (plus `/disconnect_jira`, `/jira_status`) — Atlassian OAuth 2.0 (3LO) flow, producing per-user Jira access and refresh tokens stored in Redis and mirrored to Vault + `auth.user_identities`.

The Slack integration (`parrot/integrations/slack/`) currently has **zero authentication infrastructure**: no per-user session, no OAuth callback, no login or Jira commands. Slack authorization is a static channel/user whitelist. Corporate users who already use the Telegram bot cannot get equivalent Navigator/Jira identity on Slack today.

We want to bring Slack to parity for the two command families, with a unified identity model: a user who has logged in via Telegram and later via Slack should appear as the **same** `nav_user_id` in `auth.user_identities`.

The feature was confirmed to be **strictly Azure + Jira** (no Office365, no composite strategy, no post-auth chaining between them). Azure and Jira flows are independent — either command can be issued first.

## Constraints & Requirements

- **Strictly Azure + Jira**. No Office365 commands, no composite strategies, no post-auth chain wiring Azure→Jira.
- **Commands are independent.** `/connect_jira` does **not** require a prior `/login`. This matches current Telegram behaviour.
- **Multi-workspace Slack support.** External identity key must be `(team_id, slack_user_id)`. Using `slack_user_id` alone is rejected — it collides across workspaces.
- **Unified identity.** Tokens and identity rows must land in the same stores the Telegram flow uses: Redis (primary, keyed by `channel:user_id`) and the `auth.user_identities` PostgreSQL table. A user who logs in on Telegram and then on Slack is one `nav_user_id` with two identity rows.
- **Slash command names match Telegram.** `/login`, `/connect_jira`, `/disconnect_jira`, `/jira_status`.
- **Both HTTP mode and Socket Mode.** The Slack integration supports both (`wrapper.py` and `socket_handler.py`); command registration must dispatch from either entry point.
- **OAuth callback UX**: plain HTML success/error page in the browser tab + a **DM** from the bot to the Slack user confirming the connection (ephemeral messages die on page reload; DM persists).
- **Disconnection policy**: `/disconnect_jira` revokes the Jira token only. It does **not** delete the `auth.user_identities` row (audit trail is preserved).
- **Shared code must be lifted, not duplicated.** Touch Telegram imports as needed; hard-rename rather than leaving shims. Path (A) from Round 1.
- **3-second ack requirement.** Slack slash command handlers must respond within 3 seconds; actual OAuth work runs asynchronously after the ack.
- **Signature verification** on all HTTP-mode slash command requests (already wired via `verify_slack_signature_raw`). Socket Mode requests are trusted by the WebSocket.

---

## Options Explored

### Option A: Symmetric Port (duplicate Telegram's structure under `slack/`)

Build parallel modules under `parrot/integrations/slack/`: `auth.py` with a `SlackUserSession` and a `SlackAzureAuthStrategy`, `jira_commands.py`, `oauth2_callback.py`, `post_auth_jira.py`, etc. Leave `parrot/integrations/telegram/` entirely untouched. Where logic overlaps (post-auth protocol, OAuth2 provider catalog, identity writing), copy and adapt.

✅ **Pros:**
- Zero risk to the in-flight Telegram work (`wrapper.py` is currently modified on disk).
- Each integration owns its full auth stack — no indirection.
- Fastest to ship because no Telegram imports change.

❌ **Cons:**
- Two copies of the post-auth protocol, two copies of the OAuth2 provider catalog, two copies of the identity-write glue. Drift is guaranteed within 2–3 releases.
- Directly contradicts the user's explicit choice (A = lift-and-rename).
- Makes future third integration (MS Teams already has some auth; Matrix will eventually need it) even harder.

📊 **Effort:** Low-Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `slack-sdk >= 3.40` | Slack Web API client (already a dep of the Slack integration) | Used for `chat.postMessage` DM and signature verification |
| `aiohttp` | OAuth callback HTTP handler | Already the project's HTTP stack |
| `redis.asyncio` | Token/nonce storage | Already used by `JiraOAuthManager` |
| `asyncpg` via navigator-auth `authdb` pool | Write identity rows | Already used by `IdentityMappingService` |

🔗 **Existing Code to Reuse:**
- `parrot/auth/jira_oauth.py:86` — `JiraOAuthManager` (fully generic, reuse as-is)
- `parrot/services/identity_mapping.py:76` — `IdentityMappingService` (fully generic)
- `parrot/integrations/slack/security.py` — `verify_slack_signature_raw` for command request auth
- `parrot/integrations/slack/interactive.py` — `ActionRegistry` pattern for Block Kit button handlers

---

### Option B: Lift Shared Auth Primitives to `integrations/core/auth/` + add `AzureOAuthManager` peer under `parrot/auth/` *(recommended)*

Move provider-agnostic pieces out of `integrations/telegram/`:

- `telegram/post_auth.py` → `integrations/core/auth/post_auth.py` (`PostAuthProvider` protocol + `PostAuthRegistry` — already 100 % generic, just relocate).
- `telegram/oauth2_providers.py` → `integrations/core/auth/oauth2_providers.py` (and add the Azure provider config for completeness even though Azure SSO routes through Navigator).

Add a new module peer to the existing `JiraOAuthManager`:

- `parrot/auth/azure_oauth.py` — `AzureOAuthManager` that owns the state nonce, the redirect-to-Navigator URL construction, the JWT capture/validation, and the hand-off to `session.set_authenticated(...)` in a form that is not tied to `TelegramUserSession`. It exposes a single `create_login_url(channel, user_id, extra_state=None)` and `handle_callback(token, state)` pair, mirroring `JiraOAuthManager` shape.

Integration-specific bits remain in each integration directory:

- `integrations/telegram/auth.py`: `AzureAuthStrategy` thins down to UI plumbing (aiogram keyboard, WebApp URL) and delegates token capture to `AzureOAuthManager`. Telegram imports of `post_auth`/`oauth2_providers` are updated to the new paths (hard rename).
- `integrations/slack/auth.py` (new): small `SlackUserSession` dataclass keyed by `(team_id, user_id)`, plus a thin wrapper that calls into `AzureOAuthManager` / `JiraOAuthManager` and persists session state in Redis (no in-memory dict — Slack may have multiple workers).
- `integrations/slack/commands/` (new subpackage): `login.py`, `jira_commands.py` — each exports a `register_*_commands(dispatcher, ...)` function the wrapper calls. Symmetric to Telegram's `jira_commands.register_jira_commands`.
- `integrations/slack/oauth_callback.py` (new): aiohttp handler mounted at e.g. `/api/slack/{agent}/oauth/callback`. It receives Azure-JWT or Jira-code callbacks, looks up the `state` nonce (already in Redis), completes the flow, writes `auth.user_identities`, and (a) returns a plain HTML success page and (b) DMs the Slack user via `chat.postMessage`.

Command dispatch: both `SlackAgentWrapper._handle_command` (HTTP mode, wrapper.py:290) and `SlackSocketHandler._handle_slash_command` (socket_handler.py:266) delegate to a shared `SlackCommandRouter` that looks up the command (`/login`, `/connect_jira`, etc.) and invokes its handler with a normalized payload.

Redis keying: reuse `JiraOAuthManager` unchanged. Introduce a `_SLACK_CHANNEL = "slack"` constant in `integrations/slack/commands/jira_commands.py` and pass `user_id=f"{team_id}:{slack_user_id}"`. This preserves the `jira:oauth:{channel}:{user_id}` structure and keeps multi-workspace safe.

✅ **Pros:**
- Single source of truth for the post-auth protocol and OAuth2 provider catalog.
- Identity mapping is unified: `auth.user_identities` gets one `nav_user_id` with rows per provider (`telegram`, `slack`, `jira`).
- Slack integration becomes the template for future integrations (MS Teams, Matrix) that will eventually need login.
- Matches the user's stated architectural preference (A in Round 1).

❌ **Cons:**
- Touches Telegram imports (`auth.py`, `wrapper.py`, `post_auth_jira.py`). Coordinating with any in-flight Telegram work matters — `wrapper.py` currently has uncommitted changes on disk.
- `AzureAuthStrategy` cannot be fully ripped out; it still owns the aiogram keyboard shape. Only its non-UI logic moves.
- Slightly larger blast radius for the first PR.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `slack-sdk >= 3.40` | Web API client for DMs and user info lookup | Already the Slack integration dep |
| `redis.asyncio` | Session + nonce + token store | Same instance as Telegram |
| `asyncpg` via `authdb` pool | Identity-mapping writes | No change |
| `aiohttp` | OAuth callback handler | Existing stack |
| `PyJWT` *(if not already present)* | Decode Navigator JWT claims | Already used indirectly by `AzureAuthStrategy._decode_jwt_payload` at `telegram/auth.py` |

🔗 **Existing Code to Reuse:**
- `parrot/auth/jira_oauth.py:86` — `JiraOAuthManager`, all public methods (`create_authorization_url`, `handle_callback`, `get_valid_token`, `revoke`)
- `parrot/services/identity_mapping.py:76` — `IdentityMappingService.upsert_identity`
- `parrot/integrations/telegram/post_auth.py` — lift to core unchanged
- `parrot/integrations/telegram/oauth2_providers.py` — lift to core, add Azure entry
- `parrot/integrations/telegram/auth.py:528` — `AzureAuthStrategy._decode_jwt_payload` logic and JWT claim handling (extract into `AzureOAuthManager`)
- `parrot/integrations/slack/security.py` — `verify_slack_signature_raw` (already in place)
- `parrot/integrations/slack/interactive.py` — `ActionRegistry` for the "Sign in with Azure" button handler
- `parrot/integrations/telegram/post_auth_jira.py:37` — `JiraPostAuthProvider` as template for the Jira-side Slack flow (the Redis + Vault + identity writes are the same; only the session type changes)

---

### Option C: Adopt `slack-bolt` and rely on its OAuth install flow

Re-wire the Slack integration on top of `slack-bolt`'s `AsyncApp` and lean on its built-in OAuth install flow + decorator-based command handlers. Azure login would still route through Navigator, but Jira OAuth and slash command dispatch would use bolt's primitives.

✅ **Pros:**
- Bolt's `@app.command("/login")` and `@app.action("connect_jira")` decorators are much cleaner than hand-rolled dispatch.
- Free state-store + retry handling.

❌ **Cons:**
- Adds a substantial dep (`slack-bolt`, plus indirect pulls).
- The existing `SlackAgentWrapper` is already hand-rolled with signature verification, dedup, interactive handler, and assistant support. Replacing the backbone is a rewrite of working code.
- Bolt's OAuth install flow is for installing the Slack **app** itself into a workspace — it is **not** the same as the per-user Azure/Jira OAuth we need. Using it here is a category mismatch.
- Doesn't unify with the Telegram auth surface, which still uses aiogram-native primitives.
- High churn, little real benefit for a two-command scope.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `slack-bolt >= 1.21` | Async Slack app framework with decorators and OAuth | Heavy dep; existing wrapper does not use it |
| `slack-sdk` | Still needed as bolt's transport | Already a dep |

🔗 **Existing Code to Reuse:**
- `parrot/auth/jira_oauth.py` — still reusable regardless of framework choice
- `parrot/services/identity_mapping.py` — unchanged
- Most of the existing `SlackAgentWrapper` would be replaced

---

## Recommendation

**Option B** is recommended because:

- It is exactly the path the user chose in Round 1 (lift, hard-rename, put `AzureOAuthManager` alongside `JiraOAuthManager`).
- It solves the real architectural problem — unified identity across chat integrations — instead of postponing it with another copy under `slack/`. Option A would mean three different `PostAuthRegistry` files (current + Slack + eventual MS Teams) inside six months.
- The effort premium over Option A is small and local: `post_auth.py` and `oauth2_providers.py` are already generic; lifting them is a move + import update. The real work — `AzureOAuthManager`, Slack command wiring, the OAuth callback handler — is the same either way.
- Option C is the wrong tool: `slack-bolt`'s OAuth flow is about installing the Slack app, not linking per-user Azure/Jira identities. The rewrite of the existing wrapper is unjustified.

What we trade off: coordinating the Telegram import-path changes with any in-flight work on `telegram/wrapper.py` (currently modified on disk). Mitigation — land the core lift as the first task, commit the Telegram-side import fix in the same commit, then branch to Slack work once `dev` is green.

---

## Feature Description

### User-Facing Behavior

**`/login` (Azure SSO) in Slack**

1. User types `/login` in any channel where the bot is present, or in a DM.
2. Slack acks within 3 s (Slack requirement).
3. Bot replies with an ephemeral message (visible only to the user) containing a single "🔐 Sign in with Azure" button. The button URL is Navigator's Azure endpoint, e.g. `https://nav.example.com/api/v1/auth/azure/?redirect_uri=<our_callback>&state=<nonce>`.
4. User clicks, completes Azure SSO in the browser.
5. Navigator redirects to our aiohttp callback with a JWT.
6. Callback validates the JWT, upserts `auth.user_identities` row `(nav_user_id, "slack", {team_id, slack_user_id})`, and stores `nav_user_id` in the Slack user session in Redis.
7. Browser shows a plain HTML success page: "You're signed in. You can close this tab."
8. Bot sends a DM to the Slack user: "✅ Signed in as *Jane Doe* (jane@example.com)."

**`/connect_jira`**

1. User types `/connect_jira`. No prior `/login` required.
2. Slack acks within 3 s.
3. Bot replies ephemerally with a "🔗 Connect Jira" button linking to the Atlassian authorize URL (via `JiraOAuthManager.create_authorization_url(channel="slack", user_id="T123:U456")`).
4. User consents in the Atlassian tenant.
5. Atlassian redirects to our callback with a code + state.
6. Callback exchanges the code (via `JiraOAuthManager.handle_callback`), which itself writes the token set to Redis at `jira:oauth:slack:T123:U456`.
7. Callback additionally writes an `auth.user_identities` row for the Jira provider (if a `nav_user_id` is known for this Slack user, link it; otherwise write an unlinked row).
8. HTML success page + DM: "✅ Jira connected as *jane.doe@company.com* on site *mycompany.atlassian.net*."

**`/disconnect_jira`**

- Calls `JiraOAuthManager.revoke("slack", "T123:U456")`. Sends ephemeral confirmation. Does not touch `auth.user_identities` (audit trail preserved).

**`/jira_status`**

- Looks up the Redis token via `JiraOAuthManager.get_valid_token("slack", "T123:U456")`. Sends an ephemeral reply with the Jira account email, display name, and cloud site, or "Not connected."

### Internal Behavior

**Shared infrastructure (lifted to `integrations/core/auth/`):**

- `PostAuthProvider` protocol + `PostAuthRegistry` class — moved verbatim from `telegram/post_auth.py`. No Telegram imports anywhere.
- `OAUTH2_PROVIDERS` dict + `OAuth2ProviderConfig` dataclass — moved from `telegram/oauth2_providers.py`, with a new Azure entry added for completeness.

**New Azure manager (`parrot/auth/azure_oauth.py`):**

- Mirrors `JiraOAuthManager` public surface.
- `create_login_url(channel, user_id, extra_state=None) -> (url, nonce)` stores the nonce in Redis keyed `azure:nonce:{nonce}`, constructs the Navigator Azure SSO URL with `redirect_uri` and `state=nonce`, and returns it.
- `handle_callback(token, state) -> AzureClaims` validates the state nonce, decodes the JWT claims (`user_id`/`sub`, `email`, `name`), and returns them. It does **not** write to `auth.user_identities` — the caller does, so the integration can attach provider-specific data.
- Token persistence for Navigator sessions: Redis at `azure:session:{channel}:{user_id}` with the TTL already used by Telegram (`_AZURE_TOKEN_TTL = 4 days`).

**Telegram refactor:**

- `AzureAuthStrategy` at `telegram/auth.py:528` keeps its aiogram UI methods (`build_login_keyboard`) but delegates `handle_callback`'s JWT decoding to `AzureOAuthManager`. No behavioural change for Telegram users.
- Imports updated: `from parrot.integrations.core.auth.post_auth import PostAuthRegistry` etc. `telegram/post_auth.py` and `telegram/oauth2_providers.py` are deleted (hard rename — no shims).

**Slack wiring:**

- `SlackAgentConfig` (`slack/models.py`) gains optional fields: `azure_auth_url`, `signing_secret` (already present), and a generic `auth` sub-model.
- New `integrations/slack/auth.py` defines a small `SlackUserSession` dataclass — Redis-persisted, keyed by `(team_id, user_id)` — with the identity fields from `TelegramUserSession` stripped to what Slack actually uses: `nav_user_id`, `nav_email`, `nav_display_name`, `jira_connected`, `jira_account_id`.
- New `integrations/slack/commands/__init__.py` with a `SlackCommandRouter` dispatching `/login`, `/connect_jira`, `/disconnect_jira`, `/jira_status`. Both `_handle_command` (HTTP) and `_handle_slash_command` (Socket Mode) call this router.
- New `integrations/slack/oauth_callback.py` with one aiohttp route `/api/slack/{agent}/oauth/callback` that dispatches on state prefix (`azure:*` vs `jira:*`) to the right manager.
- Route registration happens in `SlackAgentWrapper.__init__` alongside the existing events/commands/interactive routes.

**Callback → DM mechanics:**

- On the callback, after successful token capture, we know the Slack `team_id + user_id` from the state payload. We obtain a bot token (already in `SlackAgentConfig`) and call `chat.postMessage(channel=user_id, text=...)`. Slack's Web API accepts a `user_id` as `channel` for DM delivery (after the bot has been installed in that workspace).

### Edge Cases & Error Handling

- **3-second ack breach.** All slash command handlers return `HTTP 200 { "response_type": "ephemeral", "text": "Working on it..." }` immediately; the OAuth URL is then posted back via the `response_url` that Slack provides in every slash command payload. This avoids blocking the ack on Redis nonce creation.
- **Signature verification failure** (HTTP mode) — return 401, log, do nothing. Slack will not retry auth failures.
- **Socket Mode** — no signature check, trust the WebSocket.
- **State nonce expired or unknown** — callback returns an HTML error page, no DM sent.
- **Azure JWT missing `user_id`/`sub` claim** — same behaviour as Telegram today (reject, log). HTML error page.
- **`auth.user_identities` write fails** — log and continue. Redis is the primary store; identity mapping is secondary (same policy as `JiraPostAuthProvider`).
- **DM delivery fails** (bot not allowed to DM user, user has DMs disabled) — log and continue. The browser HTML success page is the fallback confirmation.
- **Multi-workspace**: `user_id` passed to `JiraOAuthManager` is `f"{team_id}:{slack_user_id}"`, so two identical Slack user IDs from different workspaces do not collide in Redis. The `auth.user_identities.auth_data` JSONB stores `{team_id, slack_user_id}` explicitly.
- **Re-connecting Jira** when a valid token already exists: re-run the flow, replace the token set in Redis (upsert), keep the same `auth.user_identities` row with updated `auth_data`.
- **`/disconnect_jira` when not connected** — ephemeral reply "Not connected; nothing to do." (Success, not error.)
- **Slack user de-installs / leaves workspace** — out of scope for this feature. Token remains in Redis until TTL expiry (90 days for Jira, 4 days for Azure session).

---

## Capabilities

### New Capabilities

- `slack-login-azure`: Slack slash command `/login` that completes Navigator Azure SSO and persists a Slack user session with a `nav_user_id`.
- `slack-jira-connect`: Slack slash commands `/connect_jira`, `/disconnect_jira`, `/jira_status` that complete Atlassian OAuth 2.0 (3LO) and persist per-user tokens to Redis + Vault + `auth.user_identities`.
- `cross-integration-auth-core`: Lifted `PostAuthProvider` / `PostAuthRegistry` / OAuth2 provider catalog under `integrations/core/auth/`, plus a new `AzureOAuthManager` alongside `JiraOAuthManager` under `parrot/auth/`. Consumed by both Telegram and Slack.

### Modified Capabilities

- Telegram auth strategy — imports move to `integrations.core.auth.*`. Behavior unchanged.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/integrations/telegram/post_auth.py` | **moved** → `parrot/integrations/core/auth/post_auth.py` | Hard rename, no shim |
| `parrot/integrations/telegram/oauth2_providers.py` | **moved** → `parrot/integrations/core/auth/oauth2_providers.py` | Adds Azure entry |
| `parrot/integrations/telegram/auth.py` | **modifies** | Imports updated; `AzureAuthStrategy` delegates JWT decode to `AzureOAuthManager` |
| `parrot/integrations/telegram/post_auth_jira.py` | **modifies** | Import of `PostAuthProvider` moves to new path |
| `parrot/integrations/telegram/jira_commands.py` | **modifies** | `_TELEGRAM_CHANNEL` unchanged; any lifted imports updated |
| `parrot/integrations/telegram/wrapper.py` | **modifies** | Import updates only |
| `parrot/auth/azure_oauth.py` | **new** | New `AzureOAuthManager`, peer to `JiraOAuthManager` |
| `parrot/integrations/slack/auth.py` | **new** | `SlackUserSession` + Redis helpers |
| `parrot/integrations/slack/commands/__init__.py` | **new** | `SlackCommandRouter` |
| `parrot/integrations/slack/commands/login.py` | **new** | `/login` handler |
| `parrot/integrations/slack/commands/jira_commands.py` | **new** | Jira command triad |
| `parrot/integrations/slack/oauth_callback.py` | **new** | aiohttp handler for Azure + Jira redirect |
| `parrot/integrations/slack/wrapper.py` | **modifies** | Registers the new route; delegates slash commands to `SlackCommandRouter` |
| `parrot/integrations/slack/socket_handler.py` | **modifies** | `_handle_slash_command` delegates to `SlackCommandRouter` |
| `parrot/integrations/slack/models.py` | **modifies** | Add `azure_auth_url`, `jira_oauth_manager` resolution, DM preferences |
| `parrot/services/identity_mapping.py` | **depends on** | No change |
| `parrot/services/vault_token_sync.py` | **depends on** | No change |
| navigator-auth Azure SSO endpoint | **depends on** | Must accept a `redirect_uri` query param pointing at our Slack callback route |

Breaking changes: none to runtime behavior. Import-path breaks only apply within the repo and are fixed atomically by the first task.

New runtime dependencies: none. All already in the project.

Configuration: each deployed Slack agent needs the same `azure_auth_url`, `jira_client_id`, `jira_client_secret`, and a `redirect_uri` distinct from the Telegram one (because the Slack callback lives at a different path).

---

## Code Context

### User-Provided Code

No code snippets were pasted by the user during brainstorming. Decisions were expressed in prose and are captured in the Problem Statement and Constraints sections above.

### Verified Codebase References

#### Classes & Signatures

```python
# From packages/ai-parrot/src/parrot/auth/jira_oauth.py:86
class JiraOAuthManager:
    async def create_authorization_url(  # line 258
        self,
        channel: str,
        user_id: str,
        extra_state: dict | None = None,
    ) -> tuple[str, str]:  # (url, nonce)
        ...
    async def handle_callback(  # line 304
        self,
        code: str,
        state: str,
    ) -> tuple["JiraTokenSet", dict]:
        ...
    async def get_valid_token(  # line 384
        self,
        channel: str,
        user_id: str,
    ) -> "JiraTokenSet | None":
        ...
    async def revoke(  # line 400
        self,
        channel: str,
        user_id: str,
    ) -> None:
        ...

# Redis keys used by JiraOAuthManager
#   _TOKEN_KEY_PREFIX  = "jira:oauth"        (packages/ai-parrot/src/parrot/auth/jira_oauth.py:37)
#   _NONCE_KEY_PREFIX  = "jira:nonce"        (packages/ai-parrot/src/parrot/auth/jira_oauth.py:38)
#   _LOCK_KEY_PREFIX   = "lock:jira:refresh" (packages/ai-parrot/src/parrot/auth/jira_oauth.py:39)

# From packages/ai-parrot/src/parrot/auth/jira_oauth.py:59
class JiraTokenSet(BaseModel):
    access_token: str
    refresh_token: str
    expires_at: float
    cloud_id: str
    site_url: str
    account_id: str
    display_name: str
    email: Optional[str] = None
    scopes: List[str] = Field(default_factory=list)
    # ... plus granted_at, last_refreshed_at, available_sites

# From packages/ai-parrot/src/parrot/services/identity_mapping.py:76
class IdentityMappingService:
    def __init__(self, db_pool: Any) -> None:  # line 95
        ...
    async def upsert_identity(  # line 99
        self,
        nav_user_id: str,
        auth_provider: str,       # e.g. "telegram", "slack", "jira"
        auth_data: Dict[str, Any],
        display_name: Optional[str] = None,
        email: Optional[str] = None,
    ) -> None:
        ...

# From packages/ai-parrot/src/parrot/integrations/telegram/auth.py:528
class AzureAuthStrategy(AbstractAuthStrategy):
    name = "azure"                        # line 549
    supports_post_auth_chain = True       # line 550
    def __init__(
        self,
        auth_url: str,
        azure_auth_url: str,
        login_page_url: Optional[str] = None,
        post_auth_registry: Optional[Any] = None,
    ) -> None: ...
    async def build_login_keyboard(self, config, state, *, next_auth_url=None, next_auth_required=False) -> ReplyKeyboardMarkup: ...   # line 566
    async def handle_callback(self, data: dict, session: "TelegramUserSession") -> bool: ...  # line 617
# Azure session TTL:
#   _AZURE_TOKEN_TTL = timedelta(days=4)   (packages/ai-parrot/src/parrot/integrations/telegram/auth.py:525)

# From packages/ai-parrot/src/parrot/integrations/telegram/post_auth_jira.py:37
class JiraPostAuthProvider:
    provider_name = "jira"
    def __init__(
        self,
        oauth_manager: "JiraOAuthManager",
        identity_service: "IdentityMappingService",
        vault_sync: "VaultTokenSync",
    ) -> None: ...
    async def build_auth_url(self, session, config, callback_base_url) -> str: ...  # line 63
    async def handle_result(self, data, session) -> None: ...                       # line 118

# From packages/ai-parrot/src/parrot/integrations/telegram/jira_commands.py:39
_TELEGRAM_CHANNEL = "telegram"   # module-level constant passed as `channel` to JiraOAuthManager

# From packages/ai-parrot/src/parrot/integrations/slack/wrapper.py:68
class SlackAgentWrapper:
    def __init__(self, agent, config: SlackAgentConfig, app: web.Application): ...       # line 79
    # Routes registered in __init__:
    #   self.commands_route = f"/api/slack/{safe_id}/commands"   (line 110)
    #   app.router.add_post(self.commands_route, self._handle_command)  (line 114)
    async def _handle_command(self, request: web.Request) -> web.Response: ...          # line 290

# From packages/ai-parrot/src/parrot/integrations/slack/socket_handler.py:266
class SlackSocketHandler:
    async def _handle_slash_command(self, payload: Dict[str, Any]) -> None: ...

# From packages/ai-parrot/src/parrot/integrations/slack/security.py:17
def verify_slack_signature_raw(
    raw_body: bytes,
    headers: Mapping[str, str],
    signing_secret: str,
    max_age_seconds: int = 300,
) -> bool: ...
```

#### Verified Imports

```python
# These imports have been confirmed to work against the codebase today:
from parrot.auth.jira_oauth import JiraOAuthManager, JiraTokenSet
from parrot.services.identity_mapping import IdentityMappingService
from parrot.integrations.telegram.post_auth import PostAuthProvider, PostAuthRegistry
from parrot.integrations.telegram.oauth2_providers import OAUTH2_PROVIDERS, OAuth2ProviderConfig, get_provider
from parrot.integrations.telegram.auth import AzureAuthStrategy, TelegramUserSession, NavigatorAuthClient
from parrot.integrations.telegram.post_auth_jira import JiraPostAuthProvider
from parrot.integrations.slack.wrapper import SlackAgentWrapper
from parrot.integrations.slack.socket_handler import SlackSocketHandler
from parrot.integrations.slack.security import verify_slack_signature_raw
from parrot.integrations.slack.interactive import ActionRegistry, SlackInteractiveHandler
from parrot.integrations.slack.models import SlackAgentConfig
```

#### Key Attributes & Constants

- `JiraOAuthManager._TOKEN_KEY_PREFIX` → `"jira:oauth"` (`parrot/auth/jira_oauth.py:37`) — Redis key prefix, tokens stored at `jira:oauth:{channel}:{user_id}`.
- `JiraOAuthManager._TOKEN_TTL_SECONDS` → `90 * 24 * 60 * 60` (`parrot/auth/jira_oauth.py:42`) — 90 days.
- `AzureAuthStrategy._AZURE_TOKEN_TTL` → `timedelta(days=4)` (`parrot/integrations/telegram/auth.py:525`) — session TTL to replicate in `AzureOAuthManager`.
- `_TELEGRAM_CHANNEL` → `"telegram"` (`parrot/integrations/telegram/jira_commands.py:39`) — model for the new `_SLACK_CHANNEL = "slack"` constant.
- `SlackAgentWrapper.commands_route` → `f"/api/slack/{safe_id}/commands"` (`parrot/integrations/slack/wrapper.py:110`) — existing route the slash command dispatcher already hangs off; `/login`, `/connect_jira`, etc. will arrive here in HTTP mode.
- `IdentityMappingService.upsert_identity` upserts on `(user_id, auth_provider)` (SQL at `parrot/services/identity_mapping.py:22`) — the natural place to record a Slack identity with `auth_provider="slack"` and `auth_data={"team_id": ..., "slack_user_id": ...}`.

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.auth.azure_oauth.AzureOAuthManager`~~ — does not exist today. This brainstorm proposes creating it.
- ~~`parrot.integrations.core.auth`~~ — subpackage does not exist today. `integrations/core/` exists and contains only `state.py`. This brainstorm proposes creating `integrations/core/auth/`.
- ~~`parrot.integrations.slack.auth`~~ — does not exist.
- ~~`parrot.integrations.slack.commands`~~ — subpackage does not exist.
- ~~`parrot.integrations.slack.oauth_callback`~~ — does not exist.
- ~~`SlackUserSession`~~ — no equivalent to `TelegramUserSession` exists for Slack today.
- ~~`SlackAgentConfig.azure_auth_url`~~ — no `azure_auth_url`, no `jira_*`, and no auth-related fields exist in `slack/models.py` today. They will be added.
- ~~Azure entry in `OAUTH2_PROVIDERS`~~ — only Google is present in the dict today (`telegram/oauth2_providers.py:32`).
- ~~Slack OAuth callback aiohttp route~~ — no route of the shape `/api/slack/{agent}/oauth/callback` is registered in `wrapper.py` today.
- ~~Any `/login` / `/connect_jira` handler in the Slack integration~~ — the only recognized slash-command tokens today are `commands` / `help` / `clear` (`wrapper.py:319`, `socket_handler.py:304`).

---

## Parallelism Assessment

- **Internal parallelism**: Moderate. The tasks form a short chain with some fan-out:
  1. Lift `post_auth.py` and `oauth2_providers.py` to `integrations/core/auth/`, update Telegram imports. *(gating)*
  2. `AzureOAuthManager` under `parrot/auth/`. *(can run after 1)*
  3. Slack `SlackUserSession` + Redis helpers. *(can run after 1)*
  4. Slack OAuth callback handler + route registration. *(depends on 2)*
  5. Slack command modules (`login`, `jira_commands`) + `SlackCommandRouter`. *(depends on 3)*
  6. Wiring in `SlackAgentWrapper` and `SlackSocketHandler`. *(depends on 4 and 5)*
  7. Telegram thin-down of `AzureAuthStrategy.handle_callback` to delegate to `AzureOAuthManager`. *(depends on 2)*

  Tasks 2/3 and 4/5 can pair up in parallel within a single worktree, but the gating task 1 and the final wiring task 6 keep the critical path sequential.

- **Cross-feature independence**: Low risk overall. Conflicts to watch:
  - `packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py` is currently modified on disk (uncommitted). The Telegram-side import updates in this feature will conflict with any in-flight change there. Coordinate by committing the current modifications on `dev` (or stashing) before starting task 1.
  - `sdd/proposals/slack-integration.md` is a prior broad-scope brainstorm about the Slack integration. It does not cover login/Jira specifically, so no content overlap, but any `slack/wrapper.py` changes it triggers would collide.

- **Recommended isolation**: **per-spec** — a single worktree with tasks executed sequentially. The tasks are tightly coupled by the import-path lift and the wrapper wiring, and Telegram plus Slack both touch `wrapper.py` and share the lifted modules. Splitting across worktrees would create merge conflicts on `integrations/core/auth/*` and `telegram/auth.py` without real throughput benefit.

- **Rationale**: A per-spec worktree keeps the core lift + Telegram import fix + Slack wiring in a single atomic PR against `dev`, which matches how auth refactors should land (one coherent slice of behaviour, one review). The short internal chain (1 → 2/3 → 4/5 → 6) is executed by one agent in a single session.

---

## Open Questions

- [x] Scope — *Owner: Jesus Lara*: Strictly Azure SSO + Jira. No Office365, no composite strategy. `/login` and `/connect_jira` are fully independent commands — either can run first, neither requires the other.
- [x] Identity persistence — *Owner: Jesus Lara*: Redis for session/token state, plus `auth.user_identities` rows so a user appears as one `nav_user_id` across Telegram and Slack.
- [x] OAuth callback UX — *Owner: Jesus Lara*: Plain HTML success/error page in the browser tab, plus a bot DM confirming the connection via the Slack Web API.
- [x] Shared-code location — *Owner: Jesus Lara*: Lift-and-rename to `integrations/core/auth/`; add `AzureOAuthManager` under `parrot/auth/` as a peer to `JiraOAuthManager`. Hard-rename, no backwards-compat shims.
- [x] Slash command names — *Owner: Jesus Lara*: Match Telegram: `/login`, `/connect_jira`, `/disconnect_jira`, `/jira_status`.
- [x] Deployment modes — *Owner: Jesus Lara*: Support both HTTP (Events API) mode and Socket Mode; command registration dispatches from either entry point.
- [x] Multi-workspace — *Owner: Jesus Lara*: External identity key is `(team_id, slack_user_id)`. Redis key for Jira uses `channel="slack"`, `user_id=f"{team_id}:{slack_user_id}"`.
- [x] Disconnect policy — *Owner: Jesus Lara*: `/disconnect_jira` revokes the Jira token only; the `auth.user_identities` row is preserved for audit.
- [ ] Navigator Azure endpoint `redirect_uri` parameter — *Owner: Jesus Lara*: Does `/api/v1/auth/azure/` accept a `redirect_uri` query param we can set to our Slack callback, or is the redirect target fixed server-side? If fixed, we need a server config change in navigator-auth or a shared callback route that multiplexes between Telegram and Slack by state prefix.
- [ ] JWT claim shape parity — *Owner: Jesus Lara*: Does Navigator's JWT for a Slack-initiated Azure login carry the same claims (`user_id`/`sub`, `email`, `name`) as the Telegram one? If yes, `AzureOAuthManager._decode_jwt_payload` is directly reusable. If not, we branch on an issuer/audience claim.
- [ ] Slack app install model — *Owner: Jesus Lara*: Single-tenant install (one bot, one workspace) vs multi-tenant (one app distributed to many workspaces)? The feature is multi-workspace-safe at the identity layer, but the app install and `signing_secret` rotation story is different between the two. If multi-tenant, we likely need a per-workspace bot-token lookup, which is not yet in `SlackAgentConfig`.
- [ ] Re-run semantics — *Owner: Jesus Lara*: If a user runs `/connect_jira` while already connected, should we (a) short-circuit with "already connected, run `/disconnect_jira` first", (b) silently re-run and upsert, or (c) offer both options via a button in the ephemeral reply?
