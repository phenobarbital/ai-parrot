# Brainstorm: Jira OAuth2 3LO Authentication from Telegram WebApp

**Date**: 2026-04-19
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

Users who authenticate via the Telegram WebApp (BasicAuth against navigator-auth) need
to also authenticate against Jira Cloud via OAuth2 3LO in a seamless, chained flow.
Currently the two auth flows are completely separate: BasicAuth is triggered by `/login`
(WebApp opens, user enters credentials, WebApp closes) and Jira OAuth2 is triggered by
`/connect_jira` (inline button opens a browser window, user consents, callback notifies
the chat). This requires two distinct user interactions and there's no link between the
navigator-auth user identity and the Jira account identity.

**Who is affected**: End users interacting with AI-Parrot chatbots via Telegram who
need Jira access for tools like JiraToolkit.

**Why now**: JiraToolkit OAuth2 3LO (Feature 107) is already integrated. The Telegram
wrapper already has a WebApp-based BasicAuth flow. Chaining them delivers a single
sign-on experience and enables the credential resolver to find Jira tokens for any
authenticated user.

---

## Constraints & Requirements

- The BasicAuth WebApp flow must complete first (navigator-auth session is the foundation).
- Jira OAuth2 tokens must be stored in **both** Redis (fast access for JiraOAuthManager)
  and the user's navigator-auth Vault (encrypted persistence).
- Identity mapping must use the existing `auth.users_identities` table (`UserIdentity` model)
  to link: navigator-auth user_id ↔ Telegram numeric user ID ↔ Jira account_id.
- The post-auth callback mechanism must be **generic/configuration-driven** so future
  integrations (Confluence, GitHub, etc.) can hook into the same pattern.
- A YAML configuration flag must control whether secondary auth is optional or mandatory.
  If mandatory and secondary auth fails, the primary auth must be rolled back.
- The WebApp should ideally handle both flows in-place (redirect chain) without requiring
  two separate user interactions, but fallback to two-phase if complexity is excessive.
- Must not break the existing standalone `/connect_jira` command flow.

---

## Options Explored

### Option A: In-Place WebApp Redirect Chain (Seamless UX)

After BasicAuth succeeds on the login page, the page JavaScript detects a `next_auth_url`
parameter and redirects the browser (still inside the Telegram WebApp) to Jira's
`auth.atlassian.com/authorize` URL. After Jira consent, Atlassian redirects to a new
combined callback endpoint that packages **both** the BasicAuth result and the Jira auth
code into a single `WebApp.sendData()` payload, then closes the WebApp.

The wrapper's `handle_web_app_data` receives a combined payload, processes BasicAuth
first, then triggers Jira token exchange server-side, stores tokens, and creates
identity mappings.

A new `post_auth_actions` config section in the YAML defines which secondary OAuth
providers to chain. The `BasicAuthStrategy.build_login_keyboard()` appends the
secondary auth URL as a query parameter to the login page URL.

**Pros:**
- Single user interaction — user logs in once, consents to Jira, WebApp closes.
- No intermediate bot messages or second button click needed.
- Configuration-driven: add new providers by declaring them in YAML.
- The login page is already a WebApp we control — adding redirect logic is straightforward JS.

**Cons:**
- The login page JavaScript becomes more complex (multi-step redirect chain).
- If Jira auth fails mid-flow, we need to decide whether to still accept BasicAuth results.
- The combined callback endpoint needs to handle both complete and partial auth states.
- Requires a new aiohttp callback route that bridges Jira OAuth2 → WebApp.sendData().

**Effort:** Medium

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiogram` | Telegram Bot API, WebApp integration | Already in use |
| `aiohttp` | HTTP server for callback routes | Already in use |
| `navigator-auth` | UserIdentity model, Vault crypto | Already integrated |
| `navigator-session` | Session vault, `load_vault_for_session` | Already integrated |

**Existing Code to Reuse:**
- `parrot/integrations/telegram/auth.py` — `BasicAuthStrategy`, `AbstractAuthStrategy` interface
- `parrot/integrations/telegram/oauth2_callback.py` — `oauth2_callback_handler` pattern for WebApp.sendData()
- `parrot/auth/jira_oauth.py` — `JiraOAuthManager.create_authorization_url()`, `handle_callback()`
- `parrot/auth/routes.py` — `jira_oauth_callback()` route pattern
- `parrot/integrations/telegram/models.py` — `TelegramAgentConfig` for new config fields
- `parrot/handlers/credentials.py` — Vault key loading and session credential storage patterns

---

### Option B: Two-Phase Sequential (Simple, Two Interactions)

BasicAuth completes normally — WebApp closes, `handle_web_app_data` processes the auth
result. After success, the wrapper checks `post_auth_actions` config and sends a new
message with an inline keyboard button (like `/connect_jira` does today) prompting the
user to authorize Jira. User clicks the inline button, browser opens Jira consent,
callback fires `TelegramOAuthNotifier`, done.

The only new logic: a generic `post_auth_dispatcher` that runs after
`BasicAuthStrategy.handle_callback()` returns True, iterating over configured secondary
auth providers and sending the appropriate inline keyboard for each.

**Pros:**
- Simpler implementation — reuses existing `/connect_jira` flow almost entirely.
- Each auth flow is self-contained with clear success/failure boundaries.
- No changes to the login page HTML/JS.
- Easier to test (each flow is independently testable).

**Cons:**
- Two user interactions: login page + Jira consent button click.
- User might ignore or postpone the Jira consent prompt.
- If secondary auth is mandatory, enforcing "rollback" is harder (user already got a success message).
- Less seamless UX — feels like two separate steps.

**Effort:** Low

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiogram` | InlineKeyboardButton for Jira auth prompt | Already in use |
| `aiohttp` | Existing Jira callback route | Already in use |

**Existing Code to Reuse:**
- `parrot/integrations/telegram/jira_commands.py` — `connect_jira_handler()`, `_auth_keyboard()`
- `parrot/auth/jira_oauth.py` — `JiraOAuthManager` (unchanged)
- `parrot/auth/routes.py` — `jira_oauth_callback()` (unchanged)
- `parrot/integrations/telegram/wrapper.py` — `handle_web_app_data()` (minor addition)

---

### Option C: Hybrid — In-Place With Fallback

Implement Option A (in-place redirect chain) as the primary flow, but if the Jira
OAuth2 step fails or the user declines consent, fall back to Option B behavior: close
the WebApp with just the BasicAuth result, and offer the Jira connection as a
follow-up inline button.

The login page checks for a `next_auth_url` parameter. If present, it redirects after
BasicAuth. If the redirect flow fails (timeout, user closes browser, etc.), a fallback
timer on the login page sends just the BasicAuth data via `WebApp.sendData()` and the
wrapper treats the secondary auth as pending.

**Pros:**
- Best of both worlds: seamless when it works, graceful degradation when it doesn't.
- Handles the "mandatory vs optional" flag naturally — mandatory retries, optional accepts partial.
- Resilient to network issues during the Jira redirect.

**Cons:**
- Most complex implementation: two code paths (in-place + fallback).
- Login page JavaScript needs timeout/error detection logic.
- Testing matrix is larger (success+success, success+fail, success+timeout).
- Risk of subtle state management bugs in the WebApp JS.

**Effort:** High

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| All from Option A | Same stack | — |

**Existing Code to Reuse:**
- Same as Option A, plus Option B's inline keyboard fallback.

---

## Recommendation

**Option A** is recommended because:

1. **UX is king for Telegram bots** — users expect a single, fluid interaction. Asking
   them to click a second button feels disconnected and increases drop-off.
2. **The complexity is bounded** — the login page is a controlled static HTML/JS we serve,
   adding a redirect chain is well-understood browser behavior.
3. **The combined callback endpoint** reuses the pattern from `oauth2_callback.py` (lines 58–67:
   `WebApp.sendData()` + `WebApp.close()`) and `jira_oauth_callback()` (token exchange +
   notification), so we're composing existing patterns, not inventing new ones.
4. **The mandatory/optional flag** maps cleanly: if `require_secondary_auth: true` and
   Jira auth fails, the WebApp sends only the BasicAuth data tagged with
   `jira_auth: "failed"`, and the wrapper rolls back the session. If optional, it
   proceeds with just BasicAuth and informs the user.

The tradeoff vs Option B (simplicity) is acceptable because the JS redirect logic is
a single `window.location.href = next_auth_url` call — not a fundamental complexity
increase.

---

## Feature Description

### User-Facing Behavior

1. User sends `/login` in Telegram.
2. Bot presents a WebApp keyboard button: "Sign in to Navigator".
3. User taps the button — Telegram WebApp opens the login page.
4. User enters navigator-auth credentials and submits.
5. Login page authenticates against Navigator API; on success, it immediately
   redirects the WebApp browser to `auth.atlassian.com/authorize` with the
   correct client_id, scopes, and state.
6. Atlassian consent page loads inside the WebApp. User reviews permissions
   and clicks "Accept".
7. Atlassian redirects to the combined callback endpoint. The callback page
   runs `Telegram.WebApp.sendData(JSON.stringify({basic_auth: {...}, jira: {code, state}}))`
   and calls `Telegram.WebApp.close()`.
8. Back in the Telegram chat, the bot confirms: "Authenticated as [name].
   Jira connected as [jira_display_name] ([site_url])."

If the user declines Jira consent (step 6), the behavior depends on configuration:
- **Optional** (`require_secondary_auth: false`): WebApp sends just BasicAuth data,
  bot confirms login and notes "Jira not connected — use /connect_jira anytime."
- **Mandatory** (`require_secondary_auth: true`): WebApp sends failure data,
  bot reports "Login requires Jira authorization. Please try again." and rolls
  back the BasicAuth session.

### Internal Behavior

**Login Page (Static HTML/JS) — modified:**
1. Receives `next_auth_url` and `next_auth_required` as query params from the keyboard URL.
2. After BasicAuth succeeds (existing flow), stores the BasicAuth result in JS memory.
3. Redirects to `next_auth_url` (the Jira authorization URL).
4. If no `next_auth_url`, falls back to existing behavior (sends BasicAuth data directly).

**Combined Callback Endpoint (new aiohttp route):**
1. Receives `code` and `state` from Jira's redirect.
2. Retrieves the stored BasicAuth data from the state nonce (embedded in Redis alongside
   the channel/user_id).
3. Returns HTML that calls `Telegram.WebApp.sendData()` with the combined payload.

**TelegramAgentWrapper.handle_web_app_data() — extended:**
1. Detects combined payload (has `jira` key).
2. Processes BasicAuth first via `BasicAuthStrategy.handle_callback()`.
3. If BasicAuth succeeds, exchanges Jira code via `JiraOAuthManager.handle_callback()`.
4. Stores Jira tokens in Redis (existing) AND in user's Vault (new).
5. Creates/updates `UserIdentity` records for both Telegram and Jira identities.
6. Sends confirmation message.

**Configuration (integrations_bots.yaml) — new fields:**
```yaml
agents:
  MyBot:
    chatbot_id: my_bot
    auth_method: basic
    post_auth_actions:
      - provider: jira
        required: true
    # ... existing fields
```

**Identity Mapping:**
After successful dual auth, three `UserIdentity` rows exist:
- `(user_id=nav_id, auth_provider="navigator", auth_data={...})`
- `(user_id=nav_id, auth_provider="telegram", auth_data={"telegram_id": 123456789})`
- `(user_id=nav_id, auth_provider="jira", auth_data={"account_id": "...", "cloud_id": "...", "site_url": "..."})`

**Vault Storage:**
Flat keys in the user's session vault:
- `jira:access_token` → encrypted access token
- `jira:refresh_token` → encrypted refresh token
- `jira:cloud_id` → cloud ID
- `jira:site_url` → Jira site URL
- `jira:account_id` → Jira account ID

### Edge Cases & Error Handling

- **Jira OAuth2 timeout**: If the Jira consent page takes too long (>10 min), the
  Redis nonce expires. The callback endpoint returns an error page. If secondary auth
  is optional, user is already logged in via BasicAuth. If mandatory, login needs retry.
- **User closes WebApp mid-Jira-flow**: BasicAuth data is lost (WebApp.sendData was
  never called). User must restart with `/login`.
- **Duplicate identity**: If a `UserIdentity` row for `(nav_user_id, "jira")` already
  exists, update it rather than creating a duplicate.
- **Token refresh failure**: `JiraOAuthManager._refresh_tokens()` already handles
  rotating refresh tokens with Redis distributed locking. Vault tokens should be
  updated when Redis tokens are refreshed.
- **Multiple Telegram users → same Jira account**: Allowed (each navigator-auth user
  gets their own identity mapping; the same Jira account_id can appear in multiple
  UserIdentity rows with different user_ids).
- **Existing `/connect_jira` flow**: Must continue to work independently for users
  who skip the combined login flow or need to reconnect.

---

## Capabilities

### New Capabilities
- `telegram-post-auth-chain`: Generic, configuration-driven post-authentication action
  system for the Telegram wrapper. Chains secondary OAuth providers after primary auth.
- `telegram-jira-combined-callback`: Combined callback endpoint that bridges Jira OAuth2
  redirect → Telegram WebApp.sendData().
- `identity-mapping-service`: Service to create/update UserIdentity records linking
  navigator-auth users to external provider identities (Telegram, Jira, etc.).
- `vault-token-sync`: Sync mechanism to store OAuth tokens in the user's navigator-auth
  Vault alongside the existing Redis storage.

### Modified Capabilities
- `telegram-basic-auth-strategy`: Extended to support `next_auth_url` parameter in
  the login keyboard URL, enabling redirect chain.
- `telegram-agent-config`: New `post_auth_actions` field in TelegramAgentConfig.
- `telegram-handle-web-app-data`: Extended to process combined auth payloads.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/integrations/telegram/auth.py` | modifies | BasicAuthStrategy gets `next_auth_url` in keyboard URL |
| `parrot/integrations/telegram/wrapper.py` | modifies | `handle_web_app_data()` handles combined payloads |
| `parrot/integrations/telegram/models.py` | extends | `TelegramAgentConfig` gets `post_auth_actions` field |
| `parrot/integrations/telegram/oauth2_callback.py` | extends | New combined callback route |
| `parrot/auth/jira_oauth.py` | modifies | `create_authorization_url()` stores BasicAuth context in state |
| `parrot/auth/routes.py` | extends | May need adjustments for combined flow |
| `parrot/handlers/credentials.py` | reference | Vault storage patterns reused |
| Login page HTML/JS | modifies | Redirect chain after BasicAuth success |
| `integrations_bots.yaml` | extends | `post_auth_actions` configuration section |
| `auth.users_identities` table | uses | UserIdentity records for identity mapping |

---

## Code Context

### User-Provided Code

```python
# Source: user-provided (navigator-auth VaultView pattern)
async def _get_vault(self, session):
    """Helper to get the vault from session, or load it on demand."""
    vault = session.get(VAULT_SESSION_KEY)
    if vault is not None:
        return vault

    user_id = getattr(session, "user_id", None)
    if not user_id:
        raise web.HTTPUnauthorized(
            reason="User ID not found for vault access."
        )

    db_pool = self.request.app.get("authdb")
    redis = self.request.app.get("redis")
    if not db_pool:
        raise web.HTTPInternalServerError(
            reason="Database pool not configured."
        )

    try:
        vault = await load_vault_for_session(
            session, user_id=user_id, db_pool=db_pool, redis=redis
        )
        if vault:
            session[VAULT_SESSION_KEY] = vault
            return vault
    except Exception:
        logger.exception("Failed to load vault dynamically")

    raise web.HTTPInternalServerError(
        reason="Failed to load user vault."
    )
```

```python
# Source: user-provided (navigator-auth UserIdentity model)
class UserIdentity(Model):
    identity_id: UUID = Column(
        required=False, primary_key=True, db_default="auto", repr=False
    )
    display_name: str = Column(required=False)
    title: str = Column(required=False)
    nickname: str = Column(required=False)
    email: str = Column(required=False)
    phone: str = Column(required=False)
    short_bio: Text = Column(required=False)
    avatar: Text = Column(required=False)
    user_id: User = Column(
        required=True, fk="user_id|username", api="users", label="User"
    )
    auth_provider: str = Column(required=False)
    auth_data: Optional[dict] = Column(required=False, repr=False)
    attributes: Optional[dict] = Column(required=False, repr=False)
    created_at: datetime = Column(
        required=False, default=datetime.now, repr=False
    )

    class Meta:
        name = "user_identities"
        schema = AUTH_DB_SCHEMA
        strict = True
        connection = None
        frozen = False
```

### Verified Codebase References

#### Classes & Signatures
```python
# From parrot/integrations/telegram/auth.py:177
class AbstractAuthStrategy(ABC):
    async def build_login_keyboard(self, config: Any, state: str) -> ReplyKeyboardMarkup:  # line 186
    async def handle_callback(self, data: Dict[str, Any], session: TelegramUserSession) -> bool:  # line 203
    async def validate_token(self, token: str) -> bool:  # line 220

# From parrot/integrations/telegram/auth.py:237
class BasicAuthStrategy(AbstractAuthStrategy):
    def __init__(self, auth_url: str, login_page_url: Optional[str] = None):  # line 250
    async def build_login_keyboard(self, config: Any, state: str) -> ReplyKeyboardMarkup:  # line 260
    async def handle_callback(self, data: Dict[str, Any], session: TelegramUserSession) -> bool:  # line 297

# From parrot/integrations/telegram/auth.py:36
class TelegramUserSession:  # dataclass
    telegram_id: int  # line 39
    nav_user_id: Optional[str]  # line 44
    nav_session_token: Optional[str]  # line 45
    nav_display_name: Optional[str]  # line 46
    nav_email: Optional[str]  # line 47
    authenticated: bool  # line 48
    oauth2_access_token: Optional[str]  # line 52
    def set_authenticated(self, nav_user_id: str, session_token: str, display_name: Optional[str] = None, email: Optional[str] = None, **extra_meta) -> None:  # line 84

# From parrot/auth/jira_oauth.py:85
class JiraOAuthManager:
    def __init__(self, client_id: str, client_secret: str, redirect_uri: str, redis_client: Any, scopes: Optional[List[str]] = None, http_session: Optional[aiohttp.ClientSession] = None) -> None:  # line 97
    async def create_authorization_url(self, channel: str, user_id: str, extra_state: Optional[Dict[str, Any]] = None) -> Tuple[str, str]:  # line 157
    async def handle_callback(self, code: str, state: str) -> Tuple[JiraTokenSet, Dict[str, Any]]:  # line 203
    async def get_valid_token(self, channel: str, user_id: str) -> Optional[JiraTokenSet]:  # line 283
    async def revoke(self, channel: str, user_id: str) -> None:  # line 299
    def _token_key(channel: str, user_id: str) -> str:  # line 118

# From parrot/auth/jira_oauth.py:58
class JiraTokenSet(BaseModel):  # frozen=True
    access_token: str
    refresh_token: str
    expires_at: float
    cloud_id: str
    site_url: str
    account_id: str
    display_name: str
    email: Optional[str]
    @property
    def is_expired(self) -> bool:  # line 74
    @property
    def api_base_url(self) -> str:  # line 79

# From parrot/integrations/telegram/models.py:13
class TelegramAgentConfig:  # dataclass
    auth_method: str = "basic"  # line 55
    auth_url: Optional[str]  # line 49
    login_page_url: Optional[str]  # line 50
    force_authentication: bool = False  # line 53
    oauth2_provider: str = "google"  # line 57
    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> 'TelegramAgentConfig':  # line 95

# From parrot/integrations/telegram/jira_commands.py:127
class TelegramOAuthNotifier:
    def __init__(self, bot: "Bot") -> None:  # line 136
    async def notify_connected(self, chat_id: int, display_name: str, site_url: str) -> None:  # line 140
    async def notify_failure(self, chat_id: int, reason: str) -> None:  # line 157
```

#### Verified Imports
```python
# These imports have been confirmed to work:
from parrot.integrations.telegram.auth import BasicAuthStrategy, AbstractAuthStrategy, TelegramUserSession  # auth.py
from parrot.integrations.telegram.auth import OAuth2AuthStrategy  # auth.py:361
from parrot.integrations.telegram.models import TelegramAgentConfig, TelegramBotsConfig  # models.py
from parrot.auth.jira_oauth import JiraOAuthManager, JiraTokenSet  # jira_oauth.py
from parrot.integrations.telegram.jira_commands import TelegramOAuthNotifier, register_jira_commands  # jira_commands.py
from parrot.integrations.telegram.oauth2_callback import oauth2_callback_handler, setup_oauth2_routes  # oauth2_callback.py
from parrot.auth.routes import setup_jira_oauth_routes, jira_oauth_callback  # routes.py
from parrot.handlers.credentials import CredentialsHandler  # credentials.py
from navigator_session.vault.config import get_active_key_id, load_master_keys  # external, used in credentials.py:40
from navigator_session.vault.crypto import encrypt_for_db, decrypt_for_db  # external, used in credentials_utils.py
```

#### Key Attributes & Constants
- `BasicAuthStrategy.auth_url` → `str` (auth.py:255)
- `BasicAuthStrategy.login_page_url` → `Optional[str]` (auth.py:256)
- `JiraOAuthManager.authorization_url` → `str` = `"https://auth.atlassian.com/authorize"` (jira_oauth.py:93)
- `JiraOAuthManager.token_url` → `str` = `"https://auth.atlassian.com/oauth/token"` (jira_oauth.py:94)
- `_TELEGRAM_CHANNEL` → `str` = `"telegram"` (jira_commands.py:33)
- `CredentialsHandler.SESSION_PREFIX` → `str` = `"_credentials:"` (credentials.py)
- `TelegramUserSession.user_id` property returns `nav_user_id` if authenticated, else `f"tg:{telegram_id}"` (auth.py:56-61)

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.auth.jira_oauth.JiraOAuthManager.store_in_vault()`~~ — no vault integration exists in JiraOAuthManager yet
- ~~`parrot.integrations.telegram.auth.BasicAuthStrategy.on_success_callback`~~ — no callback hook exists
- ~~`parrot.integrations.telegram.auth.BasicAuthStrategy.next_auth_url`~~ — no chaining parameter exists
- ~~`parrot.integrations.telegram.models.TelegramAgentConfig.post_auth_actions`~~ — field does not exist yet
- ~~`parrot.integrations.telegram.wrapper.TelegramAgentWrapper.post_auth_dispatcher`~~ — no post-auth dispatch exists
- ~~`UserIdentity` import in ai-parrot~~ — model exists only in navigator-auth, not imported in ai-parrot
- ~~`load_vault_for_session` in ai-parrot~~ — exists only in navigator-auth/navigator-session, not directly used in parrot
- ~~`VAULT_SESSION_KEY` in ai-parrot~~ — constant exists only in navigator-auth, not in parrot code
- ~~`parrot.integrations.telegram.oauth2_providers.OAUTH2_PROVIDERS["jira"]`~~ — only "google" provider exists in the registry

---

## Parallelism Assessment

- **Internal parallelism**: Yes — several independent work streams:
  1. Login page JS modifications (frontend, no Python)
  2. Combined callback endpoint (new route, independent)
  3. `TelegramAgentConfig` + YAML config extensions (config layer)
  4. Identity mapping service (DB layer, `UserIdentity`)
  5. Vault token sync (storage layer)
  6. `handle_web_app_data()` + `BasicAuthStrategy` extensions (orchestration, depends on 1-5)
- **Cross-feature independence**: Touches `auth.py`, `wrapper.py`, `models.py` in the
  Telegram integration — these overlap with any Telegram auth changes. The Jira OAuth
  modules (`jira_oauth.py`, `routes.py`) are lightly modified (adding vault storage).
  No conflict with in-flight specs unless another feature modifies the Telegram auth flow.
- **Recommended isolation**: `per-spec` — tasks 1-5 are independent but task 6
  (orchestration) depends on all of them, creating a funnel. A single worktree keeps
  the integration clean.
- **Rationale**: The orchestration task at the end needs all pieces in place. Splitting
  into multiple worktrees would require constant rebasing. A single worktree with
  sequential task execution is simpler and avoids merge conflicts in shared files
  (`auth.py`, `wrapper.py`).

---

## Open Questions

- [ ] **Login page location**: Where is the static login HTML/JS served from? Need to identify the file to modify for the redirect chain. — *Owner: Jesus*
- [ ] **navigator-auth UserIdentity import path**: What is the exact Python import path for `UserIdentity` in navigator-auth? Need to confirm `from navigator_auth.models import UserIdentity` or similar. — *Owner: Jesus*
- [ ] **Vault access from Telegram context**: The Telegram wrapper doesn't have an aiohttp request context (it runs via aiogram polling). How do we access the Vault (which uses `request.app.get("authdb")`)? Do we need to pass the DB pool and Redis through the wrapper? — *Owner: Jesus*
- [ ] **State bridging**: When the login page redirects to Jira OAuth2, how do we pass the BasicAuth result (user_id, token) to the Jira callback? Options: (a) embed in Redis state nonce, (b) pass as extra query params to Jira (not ideal — Atlassian strips unknown params), (c) store in a short-lived Redis key that the combined callback retrieves. — *Owner: Jesus*
- [ ] **Jira provider in oauth2_providers.py**: Should we add a "jira" entry to `OAUTH2_PROVIDERS` in `oauth2_providers.py`, or keep the Jira OAuth2 flow separate since it has a different pattern (cloud_id discovery, accessible resources)? — *Owner: Jesus*
