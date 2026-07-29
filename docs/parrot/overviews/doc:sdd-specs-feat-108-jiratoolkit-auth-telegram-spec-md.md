---
type: Wiki Overview
title: 'Feature Specification: Jira OAuth2 3LO Authentication from Telegram WebApp'
id: doc:sdd-specs-feat-108-jiratoolkit-auth-telegram-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Users who interact with AI-Parrot chatbots via Telegram must complete **two
relates_to:
- concept: mod:parrot.auth.jira_oauth
  rel: mentions
- concept: mod:parrot.auth.routes
  rel: mentions
- concept: mod:parrot.handlers.credentials
  rel: mentions
- concept: mod:parrot.integrations.manager
  rel: mentions
- concept: mod:parrot.integrations.telegram
  rel: mentions
- concept: mod:parrot.integrations.telegram.auth
  rel: mentions
- concept: mod:parrot.integrations.telegram.combined_callback
  rel: mentions
- concept: mod:parrot.integrations.telegram.jira_commands
  rel: mentions
- concept: mod:parrot.integrations.telegram.models
  rel: mentions
- concept: mod:parrot.integrations.telegram.oauth2_callback
  rel: mentions
- concept: mod:parrot.integrations.telegram.wrapper
  rel: mentions
- concept: mod:parrot.services.identity_mapping
  rel: mentions
- concept: mod:parrot.services.vault_token_sync
  rel: mentions
---

# Feature Specification: Jira OAuth2 3LO Authentication from Telegram WebApp

**Feature ID**: FEAT-108
**Date**: 2026-04-19
**Author**: Jesus Lara
**Status**: draft
**Target version**: next
**Brainstorm**: `sdd/proposals/jiratoolkit-auth-telegram.brainstorm.md`

---

## 1. Motivation & Business Requirements

### Problem Statement

Users who interact with AI-Parrot chatbots via Telegram must complete **two
separate authentication flows** to use Jira tools: first BasicAuth against
navigator-auth (via the Telegram WebApp), then `/connect_jira` which opens
an inline button to Atlassian's consent page. There is no link between the
navigator-auth user identity and the Jira account identity, and the Jira
tokens are only stored in Redis (no encrypted persistence in the user's Vault).

### Goals

- **G1**: Chain BasicAuth and Jira OAuth2 3LO into a single seamless WebApp
  interaction — user logs in once and authorizes Jira in-place before the
  WebApp closes.
- **G2**: Implement a generic, configuration-driven `post_auth_actions`
  mechanism in the Telegram wrapper so future secondary OAuth providers
  (Confluence, GitHub, etc.) can be added without code changes.
- **G3**: Store Jira OAuth tokens in **both** Redis (fast access) and the
  user's navigator-auth Vault (encrypted persistence with flat keys).
- **G4**: Create identity mappings in the `auth.users_identities` table
  (`UserIdentity` model) linking navigator-auth user_id, Telegram numeric
  user ID, and Jira account_id.
- **G5**: Make secondary auth mandatory or optional via a YAML configuration
  flag (`required`). When mandatory and secondary auth fails, roll back the
  primary auth session.

### Non-Goals (explicitly out of scope)

- Replacing the standalone `/connect_jira` command — it must continue to work
  independently for users who skip the combined login flow.
- Implementing secondary auth for providers other than Jira — only the
  generic framework is built; concrete providers beyond Jira are future work.
- Modifying the `OAuth2AuthStrategy` (used for Google/GitHub primary auth) —
  only `BasicAuthStrategy` gets the redirect chain capability.
- Migrating existing Redis-only Jira tokens to the Vault — only new
  authentications store in both.

---

## 2. Architectural Design

### Overview

After BasicAuth succeeds on the login page, the page JavaScript detects a
`next_auth_url` query parameter and redirects the browser (still inside the
Telegram WebApp) to Jira's `auth.atlassian.com/authorize` URL. After user
consent, Atlassian redirects to a **combined callback endpoint** that
packages both the BasicAuth result and the Jira authorization code into a
single `Telegram.WebApp.sendData()` payload, then closes the WebApp.

The wrapper's `handle_web_app_data()` receives the combined payload,
processes BasicAuth via `BasicAuthStrategy.handle_callback()`, then
exchanges the Jira code via `JiraOAuthManager.handle_callback()`, stores
tokens in Redis + Vault, creates `UserIdentity` records, and sends a
confirmation message.

### Component Diagram

```
User ─── Telegram WebApp ─── Login Page (BasicAuth)
                │                    │
                │                    ▼ (redirect on success)
                │             auth.atlassian.com/authorize
                │                    │
                │                    ▼ (redirect after consent)
                │         /api/auth/telegram/combined-callback
                │                    │
                │                    ▼ WebApp.sendData({basic_auth, jira})
                │                    │ WebApp.close()
                ▼                    │
      handle_web_app_data() ◄───────┘
                │
        ┌───────┴───────┐
        ▼               ▼
  BasicAuth         JiraOAuth
  handle_callback   handle_callback
        │               │
        ▼               ├──► Redis (token)
  Session populated     ├──► Vault (flat keys)
        │               └──► UserIdentity (DB)
        ▼
  Telegram: "✅ Authenticated + Jira connected"
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `BasicAuthStrategy` | modifies | Appends `next_auth_url` + `next_auth_required` to login keyboard URL |
| `TelegramAgentWrapper.handle_web_app_data()` | modifies | Detects combined payload, dispatches secondary auth |
| `TelegramAgentConfig` | extends | New `post_auth_actions` field |
| `TelegramAgentConfig.from_dict()` | modifies | Parses `post_auth_actions` from YAML |
| `JiraOAuthManager` | uses | `create_authorization_url()`, `handle_callback()` for token exchange |
| `JiraOAuthManager._write_token()` | extends (or wraps) | Additionally stores tokens in Vault |
| `oauth2_callback.py` | extends | New combined callback route alongside existing |
| `auth/routes.py` / `jira_oauth_callback()` | reference | Existing Jira callback remains for standalone flow |
| `UserIdentity` (navigator-auth) | uses | Create identity mapping records |
| `navigator_session.vault` | uses | Encrypt and store tokens as flat keys |
| Login page HTML/JS | modifies | Redirect chain after BasicAuth success |

### Data Models

```python
# New: Post-auth action configuration (parsed from YAML)
@dataclass
class PostAuthAction:
    provider: str          # e.g., "jira", "confluence", "github"
    required: bool = False # If True, rollback primary auth on failure

# Extended: TelegramAgentConfig gets new field
@dataclass
class TelegramAgentConfig:
    # ... existing fields ...
    post_auth_actions: List[PostAuthAction] = field(default_factory=list)

# Vault flat key scheme for Jira tokens
# Keys stored in user session vault:
#   "jira:access_token"  → str
#   "jira:refresh_token" → str
#   "jira:cloud_id"      → str
#   "jira:site_url"      → str
#   "jira:account_id"    → str

# UserIdentity records (navigator-auth model, stored in auth.users_identities)
# Example rows after successful combined auth:
#   (user_id=nav_id, auth_provider="telegram", auth_data={"telegram_id": 123456789, "username": "john"})
#   (user_id=nav_id, auth_provider="jira", auth_data={"account_id": "...", "cloud_id": "...", "site_url": "...", "display_name": "..."})
```

### New Public Interfaces

```python
# Module 1: PostAuthAction dataclass
@dataclass
class PostAuthAction:
    provider: str
    required: bool = False

# Module 2: PostAuthProvider protocol
class PostAuthProvider(Protocol):
    """Protocol for secondary auth providers."""
    provider_name: str
    async def build_auth_url(
        self,
        session: TelegramUserSession,
        config: TelegramAgentConfig,
        callback_base_url: str,
    ) -> str:
        """Return the authorization URL for this provider."""
        ...
    async def handle_result(
        self,
        data: Dict[str, Any],
        session: TelegramUserSession,
        primary_auth_data: Dict[str, Any],
    ) -> bool:
        """Process the secondary auth result. Return True on success."""
        ...

# Module 3: JiraPostAuthProvider (implements PostAuthProvider)
class JiraPostAuthProvider:
    provider_name = "jira"
    def __init__(self, oauth_manager: JiraOAuthManager): ...
    async def build_auth_url(self, session, config, callback_base_url) -> str: ...
    async def handle_result(self, data, session, primary_auth_data) -> bool: ...

# Module 5: IdentityMappingService
class IdentityMappingService:
    async def upsert_identity(
        self,
        nav_user_id: str,
        auth_provider: str,
        auth_data: Dict[str, Any],
        display_name: Optional[str] = None,
        email: Optional[str] = None,
    ) -> None:
        """Create or update a UserIdentity record."""
        ...
    async def get_identity(
        self,
        nav_user_id: str,
        auth_provider: str,
    ) -> Optional[Dict[str, Any]]:
        """Retrieve auth_data for a provider identity."""
        ...

# Module 6: VaultTokenSync
class VaultTokenSync:
    async def store_tokens(
        self,
        nav_user_id: str,
        provider: str,
        tokens: Dict[str, str],
        db_pool: Any,
        redis: Any,
    ) -> None:
        """Store flat-keyed tokens in the user's Vault."""
        ...
    async def read_tokens(
        self,
        nav_user_id: str,
        provider: str,
        db_pool: Any,
        redis: Any,
    ) -> Optional[Dict[str, str]]:
        """Read flat-keyed tokens from the user's Vault."""
        ...
```

---

## 3. Module Breakdown

### Module 1: PostAuthAction Config Model & YAML Parsing

- **Path**: `parrot/integrations/telegram/models.py`
- **Responsibility**: Define `PostAuthAction` dataclass. Extend
  `TelegramAgentConfig` with `post_auth_actions: List[PostAuthAction]`.
  Update `from_dict()` to parse the new field from YAML.
- **Depends on**: Nothing

**YAML config structure:**
```yaml
agents:
  MyBot:
    chatbot_id: my_bot
    auth_method: basic
    post_auth_actions:
      - provider: jira
        required: true
```

### Module 2: PostAuthProvider Protocol & Registry

- **Path**: `parrot/integrations/telegram/post_auth.py` (new file)
- **Responsibility**: Define the `PostAuthProvider` protocol (or ABC) and a
  `PostAuthRegistry` that maps provider names to provider instances. The
  registry is populated at wrapper initialization based on `post_auth_actions`
  config.
- **Depends on**: Module 1 (for `PostAuthAction`)

### Module 3: JiraPostAuthProvider

- **Path**: `parrot/integrations/telegram/post_auth_jira.py` (new file)
- **Responsibility**: Implement `PostAuthProvider` for Jira. Wraps
  `JiraOAuthManager` to:
  - Build the Jira authorization URL (via `create_authorization_url()`).
  - Handle the result after callback (via `handle_callback()`).
  - Store tokens in Redis (existing) + Vault (new, via Module 6).
  - Create UserIdentity records (via Module 5).
- **Depends on**: Module 2, Module 5, Module 6

### Module 4: Combined Callback Endpoint

- **Path**: `parrot/integrations/telegram/combined_callback.py` (new file)
- **Responsibility**: New aiohttp route at
  `GET /api/auth/telegram/combined-callback` that:
  1. Receives `code` and `state` from Jira's redirect.
  2. Retrieves the stashed BasicAuth data from a short-lived Redis key
     (stored by the login page via a pre-redirect API call or embedded in
     the Jira state nonce via `extra_state`).
  3. Returns HTML that calls `Telegram.WebApp.sendData()` with the combined
     payload `{basic_auth: {...}, jira: {code, state}}` and then
     `Telegram.WebApp.close()`.
- **Depends on**: Nothing (pure HTTP endpoint, pattern from `oauth2_callback.py`)

**State bridging strategy**: The BasicAuth result (user_id, token,
display_name, email) is stashed in Redis under a short-lived key
(`combined_auth:<nonce>`, 10-min TTL) before the login page redirects to
Jira. The nonce is passed as part of `extra_state` in
`JiraOAuthManager.create_authorization_url()`. When the combined callback
fires, it retrieves the BasicAuth data from Redis using the nonce from the
state payload.

### Module 5: Identity Mapping Service

- **Path**: `parrot/services/identity_mapping.py` (new file)
- **Responsibility**: CRUD operations on `auth.users_identities` table via
  the `UserIdentity` model (from navigator-auth). Provides:
  - `upsert_identity(nav_user_id, auth_provider, auth_data, ...)` — insert
    or update (on `user_id + auth_provider` conflict).
  - `get_identity(nav_user_id, auth_provider)` — lookup by provider.
  - `get_all_identities(nav_user_id)` — list all linked providers.
- **Depends on**: Nothing (uses navigator-auth's `UserIdentity` model directly)

### Module 6: Vault Token Sync

- **Path**: `parrot/services/vault_token_sync.py` (new file)
- **Responsibility**: Store and retrieve OAuth tokens as flat keys in the
  user's navigator-auth Vault. Uses `load_vault_for_session` pattern from
  navigator-auth to access the vault without an HTTP request context.
  Provides:
  - `store_tokens(nav_user_id, provider, tokens_dict, db_pool, redis)`
  - `read_tokens(nav_user_id, provider, db_pool, redis)`
- **Depends on**: Nothing (uses navigator-session vault API directly)

### Module 7: Login Page JS Modifications

- **Path**: Login page static HTML/JS (path TBD — see Open Questions)
- **Responsibility**: After BasicAuth success:
  1. Check for `next_auth_url` query parameter.
  2. If present, stash BasicAuth result via a pre-redirect API call
     (POST to a short-lived Redis store endpoint) or encode in the redirect URL.
  3. Redirect browser to `next_auth_url`.
  4. If `next_auth_required` is false and redirect fails, fall back to
     sending BasicAuth data via `WebApp.sendData()` as before.
- **Depends on**: Module 4 (combined callback must be ready to receive the redirect)

### Module 8: Wrapper Orchestration (handle_web_app_data Extension)

- **Path**: `parrot/integrations/telegram/wrapper.py`
- **Responsibility**: Extend `handle_web_app_data()` to:
  1. Detect combined payload (presence of `jira` key or similar marker).
  2. Process BasicAuth via existing `BasicAuthStrategy.handle_callback()`.
  3. If BasicAuth succeeds and combined payload has secondary auth data,
     dispatch to the appropriate `PostAuthProvider.handle_result()` via
     the `PostAuthRegistry`.
  4. If secondary auth fails and `required=true`, roll back BasicAuth
     session (`session.clear_auth()`).
  5. Send appropriate confirmation/error messages.
  Also extends `BasicAuthStrategy.build_login_keyboard()` to append
  `next_auth_url` and `next_auth_required` params when `post_auth_actions`
  are configured.
- **Depends on**: Modules 1–7 (orchestrates everything)

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_post_auth_action_from_dict` | 1 | Parse PostAuthAction from YAML dict |
| `test_config_with_post_auth_actions` | 1 | TelegramAgentConfig.from_dict parses post_auth_actions |
| `test_config_without_post_auth_actions` | 1 | Config without post_auth_actions defaults to empty list |
| `test_post_auth_registry_register` | 2 | Register a provider, retrieve by name |
| `test_post_auth_registry_unknown` | 2 | Unknown provider returns None |
| `test_jira_provider_build_auth_url` | 3 | Generates valid Atlassian authorization URL |
| `test_jira_provider_handle_result_success` | 3 | Successful token exchange stores in Redis + Vault |
| `test_jira_provider_handle_result_failure` | 3 | Failed exchange returns False, no side effects |
| `test_combined_callback_success` | 4 | Returns HTML with WebApp.sendData + close |
| `test_combined_callback_missing_code` | 4 | Returns error HTML on missing code |
| `test_combined_callback_expired_state` | 4 | Returns error HTML on expired nonce |
| `test_identity_mapping_upsert` | 5 | Create new identity record |
| `test_identity_mapping_upsert_existing` | 5 | Update existing identity (same user+provider) |
| `test_identity_mapping_get` | 5 | Retrieve identity by provider |
| `test_vault_store_tokens` | 6 | Store flat keys, verify encrypted |
| `test_vault_read_tokens` | 6 | Read back stored tokens |
| `test_vault_read_missing` | 6 | Returns None for non-existent tokens |
| `test_handle_combined_payload_success` | 8 | Combined auth succeeds, session + Jira populated |
| `test_handle_combined_payload_jira_fail_optional` | 8 | Jira fails but optional — session stays authenticated |
| `test_handle_combined_payload_jira_fail_required` | 8 | Jira fails and required — session rolled back |
| `test_handle_basic_only_payload` | 8 | Standard BasicAuth payload still works (backward compat) |
| `test_login_keyboard_with_post_auth` | 8 | Keyboard URL includes next_auth_url param |
| `test_login_keyboard_without_post_auth` | 8 | Keyboard URL unchanged when no post_auth_actions |

### Integration Tests

| Test | Description |
|---|---|
| `test_full_combined_auth_flow` | Simulate: login page → Jira consent → combined callback → wrapper processes combined data → session + tokens + identity verified |
| `test_combined_auth_with_rollback` | Simulate: login page → Jira consent denied → wrapper detects failure → session rolled back (required=true) |
| `test_standalone_connect_jira_still_works` | Verify `/connect_jira` command still functions independently after changes |

### Test Data / Fixtures

```python
@pytest.fixture
def basic_auth_data():
    return {
        "user_id": "test-nav-user-123",
        "token": "nav-session-token-abc",
        "display_name": "Test User",
        "email": "test@example.com",
    }

@pytest.fixture
def jira_auth_data():
    return {
        "code": "jira-auth-code-xyz",
        "state": "csrf-nonce-123",
    }

@pytest.fixture
def combined_payload(basic_auth_data, jira_auth_data):
    return {
        "basic_auth": basic_auth_data,
        "jira": jira_auth_data,
    }

@pytest.fixture
def post_auth_config():
    return TelegramAgentConfig(
        name="test_bot",
        chatbot_id="test",
        auth_method="basic",
        auth_url="https://auth.example.com/api/login",
        login_page_url="https://auth.example.com/login",
        post_auth_actions=[
            PostAuthAction(provider="jira", required=True),
        ],
    )

@pytest.fixture
def mock_jira_token_set():
    return JiraTokenSet(
        access_token="at-123",
        refresh_token="rt-456",
        expires_at=time.time() + 3600,
        cloud_id="cloud-abc",
        site_url="https://mysite.atlassian.net",
        account_id="jira-user-789",
        display_name="Test Jira User",
        email="test@example.com",
        scopes=["read:jira-work", "write:jira-work"],
        granted_at=time.time(),
        last_refreshed_at=time.time(),
        available_sites=[],
    )
```

---

## 5. Acceptance Criteria

- [ ] Combined auth flow works end-to-end: user logs in via WebApp, Jira
      consent happens in-place, WebApp closes, bot confirms both auths.
- [ ] `post_auth_actions` YAML config is parsed correctly and drives the
      flow — no code changes needed to add a new provider (just a new
      `PostAuthProvider` implementation).
- [ ] Jira OAuth tokens are stored in both Redis and the user's Vault
      (flat keys: `jira:access_token`, `jira:refresh_token`, etc.).
- [ ] `UserIdentity` records are created for both `telegram` and `jira`
      providers, linked to the navigator-auth `user_id`.
- [ ] When `required: true` and Jira auth fails, the BasicAuth session is
      rolled back and the user is informed.
- [ ] When `required: false` and Jira auth fails, the BasicAuth session
      persists and the user is informed Jira is not connected.
- [ ] Standalone `/connect_jira` command still works independently.
- [ ] All unit tests pass: `pytest tests/unit/test_post_auth*.py tests/unit/test_combined_callback.py tests/unit/test_identity_mapping.py tests/unit/test_vault_token_sync.py -v`
- [ ] All integration tests pass.
- [ ] Backward compatible: bots without `post_auth_actions` config behave
      exactly as before (no regression).
- [ ] No breaking changes to existing public API.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### User-Provided Code

```python
# Source: user-provided (navigator-auth VaultView pattern)
# Shows how to access the vault from a session context.
async def _get_vault(self, session):
    """Helper to get the vault from session, or load it on demand."""
    vault = session.get(VAULT_SESSION_KEY)
    if vault is not None:
        return vault
    user_id = getattr(session, "user_id", None)
    if not user_id:
        raise web.HTTPUnauthorized(reason="User ID not found for vault access.")
    db_pool = self.request.app.get("authdb")
    redis = self.request.app.get("redis")
    if not db_pool:
        raise web.HTTPInternalServerError(reason="Database pool not configured.")
    try:
        vault = await load_vault_for_session(
            session, user_id=user_id, db_pool=db_pool, redis=redis
        )
        if vault:
            session[VAULT_SESSION_KEY] = vault
            return vault
    except Exception:
        logger.exception("Failed to load vault dynamically")
    raise web.HTTPInternalServerError(reason="Failed to load user vault.")
```

```python
# Source: user-provided (navigator-auth UserIdentity model)
# Table: auth.users_identities
class UserIdentity(Model):
    identity_id: UUID = Column(required=False, primary_key=True, db_default="auto", repr=False)
    display_name: str = Column(required=False)
    title: str = Column(required=False)
    nickname: str = Column(required=False)
    email: str = Column(required=False)
    phone: str = Column(required=False)
    short_bio: Text = Column(required=False)
    avatar: Text = Column(required=False)
    user_id: User = Column(required=True, fk="user_id|username", api="users", label="User")
    auth_provider: str = Column(required=False)
    auth_data: Optional[dict] = Column(required=False, repr=False)
    attributes: Optional[dict] = Column(required=False, repr=False)
    created_at: datetime = Column(required=False, default=datetime.now, repr=False)
    class Meta:
        name = "user_identities"
        schema = AUTH_DB_SCHEMA
        strict = True
        connection = None
        frozen = False
```

### Verified Imports

```python
# These imports have been confirmed to work in the current codebase:
from parrot.integrations.telegram.auth import (
    AbstractAuthStrategy,          # auth.py:177
    BasicAuthStrategy,             # auth.py:237
    OAuth2AuthStrategy,            # auth.py:361
    TelegramUserSession,           # auth.py:36
    NavigatorAuthClient,           # auth.py:121
)
from parrot.integrations.telegram.models import (
    TelegramAgentConfig,           # models.py:13
    TelegramBotsConfig,            # models.py:134
)
from parrot.integrations.telegram.oauth2_callback import (
    oauth2_callback_handler,       # oauth2_callback.py:133
    setup_oauth2_routes,           # oauth2_callback.py:188
    _json_escape,                  # oauth2_callback.py:113
    _SUCCESS_HTML_TEMPLATE,        # oauth2_callback.py:15
    _ERROR_HTML_TEMPLATE,          # oauth2_callback.py:77
)
from parrot.auth.jira_oauth import (
    JiraOAuthManager,              # jira_oauth.py:85
    JiraTokenSet,                  # jira_oauth.py:58
    AUTHORIZATION_URL,             # jira_oauth.py:31
    TOKEN_URL,                     # jira_oauth.py:32
    DEFAULT_SCOPES,                # jira_oauth.py:47
)
from parrot.auth.routes import (
    jira_oauth_callback,           # routes.py:83
    setup_jira_oauth_routes,       # routes.py:139
)
from parrot.integrations.telegram.jira_commands import (
    TelegramOAuthNotifier,         # jira_commands.py:127
    register_jira_commands,        # jira_commands.py:104
    connect_jira_handler,          # jira_commands.py:44
    _TELEGRAM_CHANNEL,             # jira_commands.py:33 (= "telegram")
)
from parrot.handlers.credentials import (
    CredentialsHandler,            # credentials.py:71
)

# navigator-auth / navigator-session (external packages, verified via credentials.py):
from navigator_session.vault.config import get_active_key_id, load_master_keys  # used at credentials.py:40
from navigator_session.vault.crypto import encrypt_for_db, decrypt_for_db       # used at credentials_utils.py
```

### Existing Class Signatures

```python
# parrot/integrations/telegram/auth.py
class AbstractAuthStrategy(ABC):                                    # line 177
    async def build_login_keyboard(self, config: Any, state: str) -> ReplyKeyboardMarkup: ...  # line 186
    async def handle_callback(self, data: Dict[str, Any], session: TelegramUserSession) -> bool: ...  # line 203
    async def validate_token(self, token: str) -> bool: ...         # line 220

class BasicAuthStrategy(AbstractAuthStrategy):                      # line 237

…(truncated)…
