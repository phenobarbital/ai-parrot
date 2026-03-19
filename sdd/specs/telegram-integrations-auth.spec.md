# Feature Specification: Telegram Integration — OAuth2 Authentication

**Feature ID**: FEAT-036
**Date**: 2026-03-09
**Author**: AI-Parrot Team
**Status**: approved
**Target version**: 1.6.0

---

## 1. Motivation & Business Requirements

> Decouple Telegram bot authentication from Navigator's Basic Auth and support any OAuth2-compliant identity provider, starting with Google.

### Problem Statement

The current Telegram integration (`parrot/integrations/telegram/`) has authentication tightly coupled to Navigator's Basic Auth:

1. **`NavigatorAuthClient`** (`auth.py`) sends `username`/`password` with `x-auth-method: BasicAuth` — it only supports one auth flow.
2. **`TelegramAgentConfig`** (`models.py`) exposes `auth_url` and `login_page_url` — both assume a single Navigator endpoint serving a username/password HTML page.
3. **`handle_login`** (`wrapper.py:771`) builds a URL with `auth_url` as query param and opens a WebApp that collects credentials via Basic Auth form.
4. **`handle_web_app_data`** (`wrapper.py:844`) expects `{user_id, token, display_name}` from the WebApp — the contract is Navigator-specific.

This means:
- Bots that want **Google Sign-In** (or any OAuth2 provider) cannot use the current auth system.
- There is no way to configure different auth strategies per bot.
- The `NavigatorAuthClient` class is not extensible to new providers.

### Goals

- Introduce an `auth_method` config parameter to select between `"basic"` (current Navigator) and `"oauth2"` strategies
- When `auth_method = "oauth2"`, support a full OAuth2 Authorization Code flow via Telegram WebApp
- Implement Google as the first OAuth2 provider (`provider = "google"`)
- Make the OAuth2 provider pluggable so future providers (GitHub, Microsoft, etc.) require minimal code
- Preserve full backward compatibility — existing `auth_url` + `login_page_url` configs continue to work unchanged

### Non-Goals (explicitly out of scope)

- Implementing providers other than Google in this iteration (but architecture must support them)
- Token refresh / silent re-authentication (future enhancement)
- Multi-provider per bot (pick one auth method per bot config)
- Moving auth state to persistent storage (Redis) — stays in-memory for now
- PKCE support (will be added when mobile/SPA clients need it)

---

## 2. Architectural Design

### Overview

Introduce an **auth strategy abstraction** (`AbstractAuthStrategy`) that `TelegramAgentWrapper` delegates to. The existing `NavigatorAuthClient` becomes one strategy (`BasicAuthStrategy`). A new `OAuth2AuthStrategy` handles the Authorization Code flow via Telegram WebApp redirects.

### Component Diagram

```
                    ┌──────────────────────────────────┐
                    │     TelegramAgentWrapper          │
                    │  (delegates auth to strategy)     │
                    └───────────────┬──────────────────┘
                                    │
                    ┌───────────────┴──────────────────┐
                    │      AbstractAuthStrategy         │
                    │  login_url() → str                │
                    │  handle_callback(data) → Session  │
                    │  validate_token(token) → bool     │
                    └───────────────┬──────────────────┘
                                    │
              ┌─────────────────────┼─────────────────────┐
              │                                           │
    ┌─────────┴──────────┐                   ┌────────────┴──────────┐
    │  BasicAuthStrategy │                   │  OAuth2AuthStrategy   │
    │  (current flow)    │                   │  (new)                │
    │  NavigatorAuthClient│                  │                       │
    └────────────────────┘                   └────────────┬──────────┘
                                                          │
                                          ┌───────────────┼──────────┐
                                          │               │          │
                                  ┌───────┴──┐   ┌───────┴──┐  (future)
                                  │  Google  │   │  GitHub  │
                                  │ Provider │   │ Provider │
                                  └──────────┘   └──────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `TelegramAgentConfig` (`models.py`) | extends | Add `auth_method`, `oauth2_provider`, `oauth2_client_id`, `oauth2_client_secret`, `oauth2_scopes`, `oauth2_redirect_uri` |
| `NavigatorAuthClient` (`auth.py`) | wraps | Becomes internal to `BasicAuthStrategy` |
| `TelegramUserSession` (`auth.py`) | extends | Add `oauth2_access_token`, `oauth2_id_token`, `oauth2_provider` fields |
| `TelegramAgentWrapper` (`wrapper.py`) | modifies | `handle_login` delegates to strategy; `handle_web_app_data` routes to strategy |
| `handle_login` (`wrapper.py:771`) | refactors | Strategy decides URL and keyboard |
| `handle_web_app_data` (`wrapper.py:844`) | refactors | Strategy parses callback data |

### Data Models

```python
# Updated TelegramAgentConfig in parrot/integrations/telegram/models.py
@dataclass
class TelegramAgentConfig:
    # ... existing fields ...

    # Authentication settings (existing)
    auth_url: Optional[str] = None
    login_page_url: Optional[str] = None
    enable_login: bool = True
    use_html: bool = False
    force_authentication: bool = False

    # NEW: Auth method selection
    auth_method: str = "basic"  # "basic" | "oauth2"

    # NEW: OAuth2 settings (used when auth_method="oauth2")
    oauth2_provider: str = "google"  # "google" | "github" | "microsoft" (future)
    oauth2_client_id: Optional[str] = None
    oauth2_client_secret: Optional[str] = None
    oauth2_scopes: Optional[list[str]] = None
    oauth2_redirect_uri: Optional[str] = None

    def __post_init__(self):
        # Existing env-var resolution ...
        if self.auth_method == "oauth2" and not self.oauth2_client_id:
            self.oauth2_client_id = config.get(
                f"{self.name.upper()}_OAUTH2_CLIENT_ID"
            )
        if self.auth_method == "oauth2" and not self.oauth2_client_secret:
            self.oauth2_client_secret = config.get(
                f"{self.name.upper()}_OAUTH2_CLIENT_SECRET"
            )
```

```python
# parrot/integrations/telegram/auth.py — Strategy abstraction

from abc import ABC, abstractmethod

class AbstractAuthStrategy(ABC):
    """Base class for Telegram authentication strategies."""

    @abstractmethod
    async def build_login_keyboard(
        self, config: TelegramAgentConfig, state: str
    ) -> ReplyKeyboardMarkup:
        """Return the keyboard markup with the login button/WebApp."""
        ...

    @abstractmethod
    async def handle_callback(
        self, data: dict, session: TelegramUserSession
    ) -> bool:
        """Process auth callback data. Returns True if authenticated."""
        ...

    @abstractmethod
    async def validate_token(self, token: str) -> bool:
        """Validate an existing session token."""
        ...


class BasicAuthStrategy(AbstractAuthStrategy):
    """Navigator Basic Auth strategy (existing flow, refactored)."""
    ...


class OAuth2AuthStrategy(AbstractAuthStrategy):
    """OAuth2 Authorization Code strategy via Telegram WebApp."""
    ...
```

```python
# OAuth2 provider configuration
@dataclass
class OAuth2ProviderConfig:
    """Configuration for a specific OAuth2 provider."""
    name: str
    authorization_url: str
    token_url: str
    userinfo_url: str
    default_scopes: list[str]

# Built-in providers
OAUTH2_PROVIDERS = {
    "google": OAuth2ProviderConfig(
        name="google",
        authorization_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        userinfo_url="https://www.googleapis.com/oauth2/v3/userinfo",
        default_scopes=["openid", "email", "profile"],
    ),
}
```

### New Public Interfaces

```python
# parrot/integrations/telegram/auth.py

class AbstractAuthStrategy(ABC):
    async def build_login_keyboard(
        self, config: TelegramAgentConfig, state: str
    ) -> ReplyKeyboardMarkup: ...

    async def handle_callback(
        self, data: dict, session: TelegramUserSession
    ) -> bool: ...

    async def validate_token(self, token: str) -> bool: ...


class BasicAuthStrategy(AbstractAuthStrategy):
    """Wraps existing NavigatorAuthClient."""
    def __init__(self, auth_url: str, login_page_url: str): ...


class OAuth2AuthStrategy(AbstractAuthStrategy):
    """Handles OAuth2 Authorization Code flow."""
    def __init__(self, config: TelegramAgentConfig): ...

    async def exchange_code(self, code: str) -> dict:
        """Exchange authorization code for tokens."""
        ...

    async def fetch_userinfo(self, access_token: str) -> dict:
        """Fetch user profile from provider's userinfo endpoint."""
        ...


# parrot/integrations/telegram/oauth2_providers.py

@dataclass
class OAuth2ProviderConfig:
    name: str
    authorization_url: str
    token_url: str
    userinfo_url: str
    default_scopes: list[str]

def get_provider(name: str) -> OAuth2ProviderConfig: ...
```

### OAuth2 Flow (Telegram WebApp)

```
User taps /login
    │
    ▼
TelegramAgentWrapper.handle_login()
    │ delegates to OAuth2AuthStrategy.build_login_keyboard()
    │
    ▼
Bot sends WebApp button with OAuth2 authorize URL
    │ URL = {authorization_url}?client_id=...&redirect_uri=...&scope=...&state=...
    │
    ▼
User authenticates with Google in WebApp
    │
    ▼
Google redirects to redirect_uri with ?code=...&state=...
    │
    ▼
WebApp JS captures the code and sends it back via Telegram.WebApp.sendData()
    │ data = {"provider": "google", "code": "...", "state": "..."}
    │
    ▼
TelegramAgentWrapper.handle_web_app_data()
    │ delegates to OAuth2AuthStrategy.handle_callback()
    │
    ▼
OAuth2AuthStrategy.exchange_code(code)
    │ POST to token_url → {access_token, id_token}
    │
    ▼
OAuth2AuthStrategy.fetch_userinfo(access_token)
    │ GET userinfo_url → {sub, email, name, picture}
    │
    ▼
session.set_authenticated(user_id=sub, token=access_token, ...)
```

---

## 3. Module Breakdown

### Module 1: Auth Strategy Abstraction

- **Path**: `parrot/integrations/telegram/auth.py`
- **Responsibility**: Define `AbstractAuthStrategy`, refactor `NavigatorAuthClient` into `BasicAuthStrategy`
- **Depends on**: None
- **Priority**: Critical (Phase 1)
- **Changes**: Refactor existing code, add ABC, wrap `NavigatorAuthClient`

### Module 2: OAuth2 Provider Registry

- **Path**: `parrot/integrations/telegram/oauth2_providers.py`
- **Responsibility**: Define `OAuth2ProviderConfig` dataclass, built-in provider configs (Google), `get_provider()` lookup
- **Depends on**: None
- **Priority**: Critical (Phase 1)

### Module 3: OAuth2 Auth Strategy

- **Path**: `parrot/integrations/telegram/auth.py`
- **Responsibility**: `OAuth2AuthStrategy` — build authorize URL, exchange code for tokens, fetch userinfo
- **Depends on**: Module 1, Module 2
- **Priority**: Critical (Phase 1)

### Module 4: Config Model Updates

- **Path**: `parrot/integrations/telegram/models.py`
- **Responsibility**: Add `auth_method`, `oauth2_provider`, `oauth2_client_id`, `oauth2_client_secret`, `oauth2_scopes`, `oauth2_redirect_uri` to `TelegramAgentConfig`
- **Depends on**: None
- **Priority**: Critical (Phase 1)

### Module 5: Wrapper Integration

- **Path**: `parrot/integrations/telegram/wrapper.py`
- **Responsibility**: Refactor `handle_login` and `handle_web_app_data` to delegate to auth strategy. Factory creates correct strategy from config.
- **Depends on**: Module 1, Module 3, Module 4
- **Priority**: Critical (Phase 2)

### Module 6: OAuth2 WebApp Login Page

- **Path**: `parrot/integrations/telegram/static/oauth2_login.html`
- **Responsibility**: Minimal HTML/JS page that initiates OAuth2 flow and sends authorization code back to Telegram via `Telegram.WebApp.sendData()`
- **Depends on**: Module 3
- **Priority**: High (Phase 2)

### Module 7: Session Model Updates

- **Path**: `parrot/integrations/telegram/auth.py`
- **Responsibility**: Add `oauth2_access_token`, `oauth2_id_token`, `oauth2_provider` fields to `TelegramUserSession`
- **Depends on**: None
- **Priority**: Medium (Phase 1)

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_basic_strategy_login_keyboard` | auth | BasicAuthStrategy returns WebApp keyboard with auth_url |
| `test_basic_strategy_handle_callback` | auth | BasicAuthStrategy processes navigator response data |
| `test_oauth2_strategy_build_authorize_url` | auth | OAuth2AuthStrategy builds correct Google authorize URL with scopes and state |
| `test_oauth2_strategy_exchange_code` | auth | OAuth2AuthStrategy exchanges code for tokens via POST |
| `test_oauth2_strategy_exchange_code_failure` | auth | Handles token exchange errors gracefully |
| `test_oauth2_strategy_fetch_userinfo` | auth | Fetches and parses Google userinfo response |
| `test_oauth2_provider_google_config` | oauth2_providers | Google provider has correct URLs and default scopes |
| `test_oauth2_provider_unknown_raises` | oauth2_providers | `get_provider("unknown")` raises ValueError |
| `test_config_auth_method_default` | models | Default `auth_method` is `"basic"` |
| `test_config_oauth2_env_fallback` | models | OAuth2 client_id/secret resolved from env vars |
| `test_session_oauth2_fields` | auth | TelegramUserSession stores OAuth2 tokens |
| `test_strategy_factory_basic` | wrapper | Config with `auth_method="basic"` creates BasicAuthStrategy |
| `test_strategy_factory_oauth2` | wrapper | Config with `auth_method="oauth2"` creates OAuth2AuthStrategy |
| `test_backward_compat_no_auth_method` | wrapper | Config without `auth_method` defaults to BasicAuth behavior |

### Integration Tests

| Test | Description |
|---|---|
| `test_oauth2_full_flow_google` | Simulate: /login → authorize URL → code callback → token exchange → userinfo → session authenticated |
| `test_basic_auth_unchanged` | Existing Basic Auth flow works identically after refactor |
| `test_handle_login_delegates_to_strategy` | `/login` command produces correct keyboard based on auth_method |
| `test_handle_web_app_data_routes_to_strategy` | WebApp callback data is routed to correct strategy |
| `test_force_auth_with_oauth2` | `force_authentication=True` + `auth_method="oauth2"` blocks unauthenticated messages |

### Test Fixtures

```python
@pytest.fixture
def google_oauth2_config():
    return TelegramAgentConfig(
        name="TestBot",
        chatbot_id="test_bot",
        bot_token="test:token",
        auth_method="oauth2",
        oauth2_provider="google",
        oauth2_client_id="test-client-id.apps.googleusercontent.com",
        oauth2_client_secret="test-secret",
        oauth2_scopes=["openid", "email", "profile"],
        oauth2_redirect_uri="https://example.com/oauth2/callback",
    )

@pytest.fixture
def basic_auth_config():
    return TelegramAgentConfig(
        name="TestBot",
        chatbot_id="test_bot",
        bot_token="test:token",
        auth_url="https://nav.example.com/api/auth",
        login_page_url="https://static.example.com/login.html",
    )

@pytest.fixture
def mock_google_token_response():
    return {
        "access_token": "ya29.a0AfB_test",
        "id_token": "eyJhbGciOiJSUzI1NiJ9.test",
        "token_type": "Bearer",
        "expires_in": 3600,
        "scope": "openid email profile",
    }

@pytest.fixture
def mock_google_userinfo():
    return {
        "sub": "118234567890",
        "email": "user@example.com",
        "name": "Test User",
        "picture": "https://lh3.googleusercontent.com/a/test",
        "email_verified": True,
    }
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] Existing bots with `auth_url` + `login_page_url` (no `auth_method`) work identically (backward compat)
- [ ] Setting `auth_method: "oauth2"` + `oauth2_provider: "google"` + client credentials enables Google Sign-In
- [ ] `/login` shows a WebApp button that initiates the OAuth2 Authorization Code flow
- [ ] After Google authentication, `handle_web_app_data` exchanges the code for tokens and fetches user profile
- [ ] `TelegramUserSession` is populated with Google user info (email, name, sub as user_id)
- [ ] `/logout` clears OAuth2 session state
- [ ] `force_authentication: true` blocks unauthenticated users and prompts OAuth2 login
- [ ] OAuth2 client_id/secret can be set via env vars (`{BOTNAME}_OAUTH2_CLIENT_ID`, etc.)
- [ ] `OAuth2ProviderConfig` for Google has correct endpoints and default scopes
- [ ] Adding a new OAuth2 provider requires only a new entry in `OAUTH2_PROVIDERS` dict
- [ ] All unit tests pass (`pytest tests/integrations/telegram/ -v`)
- [ ] No breaking changes to `TelegramAgentConfig.from_dict()` with existing YAML configs

---

## 6. Implementation Notes & Constraints

### Patterns to Follow

- Use `aiohttp.ClientSession` for all HTTP calls (token exchange, userinfo)
- async/await throughout — no blocking I/O
- Use `self.logger` for logging (no print statements)
- Use dataclasses for config; Pydantic is acceptable for validation models
- Follow existing patterns from `NavigatorAuthClient` for error handling
- Use `navconfig.config.get()` for env var resolution

### CSRF / State Protection

The OAuth2 `state` parameter MUST be:
1. Generated as a random string per login attempt
2. Stored in `_user_sessions` keyed by Telegram user ID
3. Validated when the callback arrives in `handle_web_app_data`

```python
import secrets
state = secrets.token_urlsafe(32)
# Store: self._pending_oauth_states[telegram_user_id] = state
# Validate: if data["state"] != self._pending_oauth_states.get(user_id): reject
```

### Known Risks / Gotchas

| Risk | Mitigation |
|---|---|
| Telegram WebApp limitations | WebApp can open URLs and send data back; the OAuth2 redirect must land on a page that calls `Telegram.WebApp.sendData()` |
| OAuth2 redirect_uri must be HTTPS | Use a hosted static page or the bot's own webhook endpoint |
| State parameter validation | Store pending states in-memory; cleared after use or TTL |
| Token expiry not handled | Out of scope — document as future enhancement |
| Google requires verified domain for redirect_uri | Document in setup instructions |
| `oauth2_client_secret` in config | Support env var fallback; never log secrets |

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `aiohttp` | existing | HTTP client for token exchange and userinfo |
| `aiogram` | existing | Telegram bot framework, WebApp support |
| No new dependencies required | — | OAuth2 is standard HTTP; no SDK needed |

### YAML Configuration Example

```yaml
agents:
  FinanceBot:
    chatbot_id: finance_agent
    auth_method: oauth2
    oauth2_provider: google
    # oauth2_client_id: from FINANCEBOT_OAUTH2_CLIENT_ID env var
    # oauth2_client_secret: from FINANCEBOT_OAUTH2_CLIENT_SECRET env var
    oauth2_scopes:
      - openid
      - email
      - profile
    oauth2_redirect_uri: https://bots.example.com/oauth2/callback
    force_authentication: true
    enable_login: true

  HRAgent:
    chatbot_id: hr_agent
    # Legacy Basic Auth — works as before
    auth_url: https://nav.example.com/api/auth
    login_page_url: https://static.example.com/login.html
    enable_login: true
```

---

## 7. Open Questions

- [ ] Question 1: Should the OAuth2 callback page be a static HTML hosted externally, or should the bot expose an aiohttp endpoint to handle the redirect? — *Owner: Team*: Exposes as a aiohttp endpoint registered then Bot used the bearer token provided.
- [ ] Question 2: Should we support PKCE (Proof Key for Code Exchange) from the start for improved security? — *Owner: Team*: Yes.
- [ ] Question 3: Should authenticated OAuth2 users also be registered/synced with Navigator's user database? — *Owner: Team*: No.
- [ ] Question 4: What is the desired token TTL before requiring re-authentication? — *Owner: Team*: 7 days.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-03-09 | Claude | Initial draft from user requirements |
