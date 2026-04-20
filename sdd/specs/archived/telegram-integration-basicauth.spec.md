# Feature Specification: Telegram Integration — Azure SSO via Navigator

**Feature ID**: FEAT-109
**Date**: 2026-04-19
**Author**: AI-Parrot Team
**Status**: implemented (superseded)
**Target version**: 1.7.0

> **Archived 2026-04-20.** Delivered in full by TASK-764 → TASK-768 (all
> `done`): `AzureAuthStrategy` at `packages/ai-parrot/src/parrot/integrations/telegram/auth.py:453`,
> `TelegramAgentConfig.azure_auth_url` at `models.py:92`, wrapper factory
> case at `wrapper.py:553`, and `static/telegram/azure_login.html`.
> Subsequently extended (and `FEAT-109` feature-id reused) by
> `sdd/specs/FEAT-109-telegram-multi-auth-negotiation.spec.md`, which
> wraps this Azure strategy inside `CompositeAuthStrategy` for multi-auth
> negotiation. No further implementation work is required against this
> spec — it is kept for historical traceability of TASK-764..768.

---

## 1. Motivation & Business Requirements

> Add Azure AD (O365) Single Sign-On as an authentication method for Telegram bots,
> delegating the OAuth2 flow entirely to Navigator-auth's `/api/v1/auth/azure/` endpoint.

### Problem Statement

The current Telegram integration's HTML login page (`static/telegram/login.html`) only
supports Navigator BasicAuth — a username/password form that POSTs to Navigator's auth
endpoint with `x-auth-method: BasicAuth`. However, Navigator-auth already exposes an
Azure AD SSO endpoint at `/api/v1/auth/azure/` that:

1. Accepts a `redirect_url` query parameter
2. Redirects the user to Microsoft O365 Azure AD SSO
3. After successful SSO, redirects back to the `redirect_url` with a JWT bearer token
   appended as a `token=` query parameter

There is currently no way for Telegram bots to leverage this Azure SSO flow. Users
who authenticate via Azure AD in other Navigator applications must use
username/password in Telegram, defeating the purpose of centralized SSO.

### Goals

- Add `auth_method: "azure"` as a new authentication strategy for Telegram bots
- Create a new `AzureAuthStrategy` that delegates SSO entirely to Navigator's
  `/api/v1/auth/azure/` endpoint
- Create a new HTML login page (`azure_login.html`) that:
  - Shows a "Sign in with Azure" button
  - Redirects to Navigator's Azure endpoint with a `redirect_url` pointing back to itself
  - On redirect-back, captures the `token=` JWT from the URL and sends it to Telegram via `WebApp.sendData()`
- Decode the Navigator JWT to extract user identity (user_id, email, display_name)
- Preserve full backward compatibility — `auth_method: "basic"` and `auth_method: "oauth2"` continue unchanged

### Non-Goals (explicitly out of scope)

- Modifying the existing `BasicAuthStrategy` or `OAuth2AuthStrategy`
- Implementing Azure OAuth2 directly (the bot does NOT do the code exchange — Navigator handles it)
- Token refresh or silent re-authentication
- Combining BasicAuth + Azure on the same login page (future enhancement — see Open Questions)
- PKCE or state/CSRF for the Azure flow (Navigator manages the OAuth2 state internally)

---

## 2. Architectural Design

### Overview

Add a third authentication strategy (`AzureAuthStrategy`) that follows the existing
`AbstractAuthStrategy` interface. Unlike `OAuth2AuthStrategy` which performs the full
OAuth2 code exchange itself, `AzureAuthStrategy` delegates entirely to Navigator's
Azure endpoint — the bot only needs to:

1. Open a WebApp with the Azure login page
2. The page redirects to Navigator's `/api/v1/auth/azure/?redirect_url=...`
3. Navigator handles Azure SSO and redirects back with `?token=jwt`
4. The page captures the JWT and sends it to Telegram
5. `AzureAuthStrategy.handle_callback()` decodes the JWT to extract user info

### Component Diagram

```
User taps /login
    |
    v
TelegramAgentWrapper.handle_login()
    | delegates to AzureAuthStrategy.build_login_keyboard()
    |
    v
Bot sends WebApp button -> azure_login.html?azure_auth_url={url}
    |
    v
User sees "Sign in with Azure" button, clicks it
    |
    v
Browser redirects to: {navigator}/api/v1/auth/azure/?redirect_url={azure_login.html}
    |
    v
Navigator redirects to Azure O365 SSO
    |
    v
User authenticates with Azure AD (Microsoft SSO)
    |
    v
Azure redirects back to Navigator
    |
    v
Navigator creates JWT, redirects to: {azure_login.html}?token={jwt}
    |
    v
azure_login.html detects ?token= parameter
    | Calls Telegram.WebApp.sendData({"auth_method": "azure", "token": jwt})
    |
    v
TelegramAgentWrapper.handle_web_app_data()
    | delegates to AzureAuthStrategy.handle_callback()
    |
    v
AzureAuthStrategy decodes JWT payload -> extracts user_id, email, name
    |
    v
session.set_authenticated(user_id, token, display_name, email)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractAuthStrategy` (`auth.py`) | implements | New `AzureAuthStrategy` implements all three abstract methods |
| `TelegramAgentConfig` (`models.py`) | extends | Add `azure_auth_url` field; recognize `auth_method: "azure"` |
| `TelegramAgentWrapper` (`wrapper.py`) | modifies | Strategy factory adds `"azure"` case; `handle_login` adds Azure prompt text |
| `NavigatorAuthClient` (`auth.py`) | reuses | `validate_token()` reused for token validation |
| `static/telegram/login.html` | unchanged | Existing BasicAuth page is not modified |

### Data Models

```python
# Updated TelegramAgentConfig in models.py
@dataclass
class TelegramAgentConfig:
    # ... existing fields ...

    # NEW: Azure SSO URL (Navigator's Azure auth endpoint)
    # Used when auth_method="azure". Falls back to
    # {auth_url}/azure/ if not explicitly set.
    azure_auth_url: Optional[str] = None
```

```python
# New AzureAuthStrategy in auth.py

class AzureAuthStrategy(AbstractAuthStrategy):
    """Navigator Azure AD SSO strategy.

    Delegates the full OAuth2 flow to Navigator's /api/v1/auth/azure/ endpoint.
    The bot only captures the JWT token returned via redirect.
    """

    def __init__(
        self,
        auth_url: str,
        azure_auth_url: str,
        login_page_url: Optional[str] = None,
    ):
        ...

    async def build_login_keyboard(
        self, config: Any, state: str
    ) -> ReplyKeyboardMarkup:
        """Build keyboard with WebApp button pointing to azure_login.html."""
        ...

    async def handle_callback(
        self, data: Dict[str, Any], session: TelegramUserSession
    ) -> bool:
        """Process Azure callback: decode JWT and populate session."""
        ...

    async def validate_token(self, token: str) -> bool:
        """Validate Navigator JWT token."""
        ...

    @staticmethod
    def _decode_jwt_payload(token: str) -> Dict[str, Any]:
        """Decode JWT payload without signature verification.

        Navigator is trusted — we only need the claims.
        """
        ...
```

### New Public Interfaces

```python
# parrot/integrations/telegram/auth.py

class AzureAuthStrategy(AbstractAuthStrategy):
    def __init__(
        self,
        auth_url: str,
        azure_auth_url: str,
        login_page_url: Optional[str] = None,
    ): ...

    async def build_login_keyboard(
        self, config: Any, state: str
    ) -> ReplyKeyboardMarkup: ...

    async def handle_callback(
        self, data: Dict[str, Any], session: TelegramUserSession
    ) -> bool: ...

    async def validate_token(self, token: str) -> bool: ...

    @staticmethod
    def _decode_jwt_payload(token: str) -> Dict[str, Any]: ...
```

### Azure Login Page Flow (HTML)

```
azure_login.html loaded in Telegram WebApp:

  1. Parse query params:
     - azure_auth_url: Navigator's Azure endpoint
     - token: JWT from Navigator redirect (may or may not be present)

  2. If ?token= present:
     - Build payload: {"auth_method": "azure", "token": <jwt>}
     - Call Telegram.WebApp.sendData(JSON.stringify(payload))
     - Show "Authentication complete" message
     - Close WebApp after 500ms

  3. If ?token= NOT present:
     - Show "Sign in with Azure" button
     - On click: redirect to {azure_auth_url}?redirect_url={current_page_url}
     - (current_page_url includes the azure_auth_url param so it's preserved)
```

---

## 3. Module Breakdown

### Module 1: Config Model Updates

- **Path**: `packages/ai-parrot/src/parrot/integrations/telegram/models.py`
- **Responsibility**: Add `azure_auth_url` field to `TelegramAgentConfig`, handle env var fallback, update `from_dict()` and `validate()`
- **Depends on**: None
- **Priority**: Critical (Phase 1)

### Module 2: Azure Auth Strategy

- **Path**: `packages/ai-parrot/src/parrot/integrations/telegram/auth.py`
- **Responsibility**: Implement `AzureAuthStrategy` — build login keyboard, handle JWT callback, decode JWT payload
- **Depends on**: Module 1
- **Priority**: Critical (Phase 1)

### Module 3: Wrapper Integration

- **Path**: `packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py`
- **Responsibility**: Add `"azure"` case to strategy factory in `__init__`, add Azure prompt text in `handle_login`
- **Depends on**: Module 1, Module 2
- **Priority**: Critical (Phase 2)

### Module 4: Azure Login HTML Page

- **Path**: `static/telegram/azure_login.html`
- **Responsibility**: HTML/JS page that shows Azure SSO button, handles redirect-back with `?token=`, sends JWT to Telegram via `WebApp.sendData()`
- **Depends on**: None (standalone static file)
- **Priority**: Critical (Phase 2)

### Module 5: Tests

- **Path**: `packages/ai-parrot/tests/integrations/telegram/test_azure_auth_strategy.py`
- **Responsibility**: Unit tests for `AzureAuthStrategy`, config changes, strategy factory
- **Depends on**: Module 1, Module 2, Module 3
- **Priority**: High (Phase 2)

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_config_azure_auth_url_default` | models | Default `azure_auth_url` is None |
| `test_config_azure_auth_url_from_yaml` | models | `azure_auth_url` populated from YAML dict |
| `test_config_azure_auth_url_env_fallback` | models | Falls back to `{NAME}_AZURE_AUTH_URL` env var |
| `test_config_azure_auth_url_derived` | models | Derives from `auth_url` + `/azure/` when not explicit |
| `test_config_validate_azure_missing_url` | models | Validation error when `auth_method="azure"` but no `azure_auth_url` and no `auth_url` |
| `test_azure_strategy_init` | auth | `AzureAuthStrategy` initializes with correct fields |
| `test_azure_strategy_build_keyboard` | auth | Returns WebApp keyboard with azure_login.html URL |
| `test_azure_strategy_build_keyboard_no_page_url` | auth | Raises ValueError if no login_page_url |
| `test_azure_strategy_handle_callback_success` | auth | Decodes JWT, populates session fields |
| `test_azure_strategy_handle_callback_missing_token` | auth | Returns False if no token in data |
| `test_azure_strategy_handle_callback_invalid_jwt` | auth | Returns False for malformed JWT |
| `test_azure_strategy_decode_jwt_payload` | auth | Correctly decodes base64url JWT payload |
| `test_azure_strategy_decode_jwt_padding` | auth | Handles base64 padding correctly |
| `test_azure_strategy_validate_token` | auth | Delegates to NavigatorAuthClient |
| `test_strategy_factory_azure` | wrapper | Config with `auth_method="azure"` creates AzureAuthStrategy |
| `test_strategy_factory_azure_derived_url` | wrapper | Azure URL derived from auth_url when not explicit |
| `test_handle_login_azure_prompt` | wrapper | `/login` shows Azure-specific prompt text |
| `test_backward_compat_basic_unchanged` | wrapper | BasicAuth flow unaffected by new code |
| `test_backward_compat_oauth2_unchanged` | wrapper | OAuth2 flow unaffected by new code |

### Integration Tests

| Test | Description |
|---|---|
| `test_azure_full_flow` | Simulate: /login -> WebApp button -> callback with JWT -> session authenticated |
| `test_azure_handle_web_app_data_routes_to_strategy` | WebApp data with `auth_method: "azure"` is routed to AzureAuthStrategy |
| `test_force_auth_with_azure` | `force_authentication=True` + `auth_method="azure"` blocks unauthenticated |

### Test Fixtures

```python
import base64
import json

@pytest.fixture
def sample_navigator_jwt():
    """Create a sample Navigator JWT for testing."""
    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "HS256", "typ": "JWT"}).encode()
    ).rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(
        json.dumps({
            "user_id": "12345",
            "email": "user@company.com",
            "first_name": "Test",
            "last_name": "User",
            "sub": "12345",
            "iss": "navigator-auth",
            "exp": 9999999999,
        }).encode()
    ).rstrip(b"=").decode()
    signature = "fake_signature"
    return f"{header}.{payload}.{signature}"


@pytest.fixture
def azure_auth_config():
    return TelegramAgentConfig(
        name="TestBot",
        chatbot_id="test_bot",
        bot_token="test:token",
        auth_method="azure",
        auth_url="https://nav.example.com/api/v1/auth/login",
        azure_auth_url="https://nav.example.com/api/v1/auth/azure/",
        login_page_url="https://static.example.com/telegram/azure_login.html",
    )


@pytest.fixture
def basic_auth_config():
    return TelegramAgentConfig(
        name="TestBot",
        chatbot_id="test_bot",
        bot_token="test:token",
        auth_url="https://nav.example.com/api/v1/auth/login",
        login_page_url="https://static.example.com/telegram/login.html",
    )
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] Setting `auth_method: "azure"` + `azure_auth_url` (or deriving from `auth_url`) enables Azure SSO login
- [ ] `/login` shows a WebApp button that opens `azure_login.html`
- [ ] `azure_login.html` shows "Sign in with Azure" button that redirects to Navigator's Azure endpoint
- [ ] After Azure SSO, `azure_login.html` captures the `?token=` JWT and sends it back to Telegram
- [ ] `AzureAuthStrategy.handle_callback()` decodes the JWT and populates `TelegramUserSession` with user_id, email, display_name
- [ ] `TelegramUserSession` is correctly authenticated after Azure SSO flow
- [ ] `/logout` clears Azure session state
- [ ] `force_authentication: true` + `auth_method: "azure"` blocks unauthenticated users
- [ ] `azure_auth_url` can be set explicitly or derived from `auth_url` + `/azure/`
- [ ] `azure_auth_url` can be set via env var `{BOTNAME}_AZURE_AUTH_URL`
- [ ] Existing `auth_method: "basic"` bots work identically (no breaking changes)
- [ ] Existing `auth_method: "oauth2"` bots work identically (no breaking changes)
- [ ] All unit tests pass (`pytest packages/ai-parrot/tests/integrations/telegram/ -v`)
- [ ] No breaking changes to `TelegramAgentConfig.from_dict()` with existing YAML configs

---

## 6. Codebase Contract

> **CRITICAL -- Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.

### Verified Imports

```python
# Auth strategy base and existing strategies
from parrot.integrations.telegram.auth import (
    AbstractAuthStrategy,       # verified: auth.py:177
    BasicAuthStrategy,          # verified: auth.py:237
    OAuth2AuthStrategy,         # verified: auth.py:361
    TelegramUserSession,        # verified: auth.py:35
    NavigatorAuthClient,        # verified: auth.py:121
)

# Config model
from parrot.integrations.telegram.models import (
    TelegramAgentConfig,        # verified: models.py:12
)

# Aiogram types used by strategies
from aiogram.types import (
    ReplyKeyboardMarkup,        # used in auth.py:260
    KeyboardButton,             # used in auth.py:288
    WebAppInfo,                 # used in auth.py:290
)

# Standard library for JWT decode
import base64                   # stdlib
import json                     # stdlib

# URL encoding
from urllib.parse import urlencode  # used in auth.py:284

# Environment config
from navconfig import config    # used in models.py:6

# Logging
from navconfig.logging import logging  # used in oauth2_callback.py:4
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/integrations/telegram/auth.py

class AbstractAuthStrategy(ABC):  # line 177
    @abstractmethod
    async def build_login_keyboard(
        self, config: Any, state: str
    ) -> ReplyKeyboardMarkup:  # line 187
        ...

    @abstractmethod
    async def handle_callback(
        self, data: Dict[str, Any], session: TelegramUserSession
    ) -> bool:  # line 204
        ...

    @abstractmethod
    async def validate_token(self, token: str) -> bool:  # line 221
        ...


class BasicAuthStrategy(AbstractAuthStrategy):  # line 237
    def __init__(self, auth_url: str, login_page_url: Optional[str] = None):  # line 250
        self.auth_url = auth_url          # line 255
        self.login_page_url = login_page_url  # line 256
        self._client = NavigatorAuthClient(auth_url)  # line 257
        self.logger = logging.getLogger("parrot.Telegram.Auth.Basic")  # line 258

    async def build_login_keyboard(self, config, state) -> ReplyKeyboardMarkup:  # line 260
        # Builds WebApp button with: f"{page_url}?{urlencode({'auth_url': self.auth_url})}"
        ...

    async def handle_callback(self, data, session) -> bool:  # line 297
        # Expects: {"user_id": str, "token": str, "display_name"?: str, "email"?: str}
        ...

    async def validate_token(self, token) -> bool:  # line 338
        # Delegates to NavigatorAuthClient.validate_token()
        ...


class NavigatorAuthClient:  # line 121
    def __init__(self, auth_url: str, timeout: int = 15):  # line 122
        ...
    async def login(self, username: str, password: str) -> Optional[Dict]:  # line 128
        ...
    async def validate_token(self, token: str) -> bool:  # line 167
        # Currently: return bool(token) — placeholder
        ...


@dataclass
class TelegramUserSession:  # line 35
    telegram_id: int
    telegram_username: Optional[str] = None
    telegram_first_name: Optional[str] = None
    telegram_last_name: Optional[str] = None
    nav_user_id: Optional[str] = None
    nav_session_token: Optional[str] = None
    nav_display_name: Optional[str] = None
    nav_email: Optional[str] = None
    authenticated: bool = False
    authenticated_at: Optional[datetime] = None
    oauth2_access_token: Optional[str] = None
    oauth2_id_token: Optional[str] = None
    oauth2_provider: Optional[str] = None
    metadata: Dict = field(default_factory=dict)

    def set_authenticated(
        self, nav_user_id, session_token, display_name=None, email=None, **extra_meta
    ):  # line 84
        ...

    def clear_auth(self):  # line 102
        ...
```

```python
# packages/ai-parrot/src/parrot/integrations/telegram/models.py

@dataclass
class TelegramAgentConfig:  # line 12
    name: str                           # line 34
    chatbot_id: str                     # line 35
    bot_token: Optional[str] = None     # line 36
    auth_url: Optional[str] = None      # line 49
    login_page_url: Optional[str] = None  # line 50
    enable_login: bool = True           # line 51
    use_html: bool = False              # line 52
    force_authentication: bool = False  # line 53
    auth_method: str = "basic"          # line 55
    oauth2_provider: str = "google"     # line 57
    oauth2_client_id: Optional[str] = None      # line 58
    oauth2_client_secret: Optional[str] = None  # line 59
    oauth2_scopes: Optional[List[str]] = None   # line 60
    oauth2_redirect_uri: Optional[str] = None   # line 61
    # NOTE: azure_auth_url does NOT exist yet — this spec adds it

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> 'TelegramAgentConfig':
        # line 94 — creates from YAML dict
        ...
```

```python
# packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py

class TelegramAgentWrapper:  # line 50
    def __init__(self, agent, bot, config, agent_commands=None):  # line 68
        # Strategy factory at lines 88-94:
        # if config.auth_method == "oauth2" and config.oauth2_client_id:
        #     self._auth_strategy = OAuth2AuthStrategy(config)
        # elif config.auth_url:
        #     self._auth_strategy = BasicAuthStrategy(config.auth_url, config.login_page_url)
        ...

    async def handle_login(self, message: Message) -> None:  # line 837
        # Generates state = secrets.token_urlsafe(32) at line 859
        # Calls self._auth_strategy.build_login_keyboard(self.config, state) at line 861
        # Prompt text selection at lines 869-879
        ...

    async def handle_web_app_data(self, message: Message) -> None:  # line 907
        # Parses JSON from message.web_app_data.data at line 919
        # Calls self._auth_strategy.handle_callback(data, session) at line 926
        ...
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `AzureAuthStrategy` | `AbstractAuthStrategy` | subclass | `auth.py:177` |
| `AzureAuthStrategy` | `NavigatorAuthClient.validate_token()` | method call | `auth.py:167` |
| `AzureAuthStrategy` | `TelegramUserSession.set_authenticated()` | method call | `auth.py:84` |
| `TelegramAgentWrapper.__init__` | `AzureAuthStrategy.__init__()` | factory creation | `wrapper.py:88` |
| `azure_login.html` | `Telegram.WebApp.sendData()` | JS API | same pattern as `login.html:235` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.integrations.telegram.auth.AzureAuthStrategy`~~ — does not exist yet (this spec creates it)
- ~~`TelegramAgentConfig.azure_auth_url`~~ — does not exist yet (this spec adds it)
- ~~`static/telegram/azure_login.html`~~ — does not exist yet (this spec creates it)
- ~~`TelegramUserSession.azure_token`~~ — no such field; use `nav_session_token` for the JWT
- ~~`TelegramUserSession.azure_user_id`~~ — no such field; use `nav_user_id`
- ~~`NavigatorAuthClient.validate_azure_token()`~~ — does not exist; use `validate_token()`
- ~~`parrot.integrations.telegram.azure_providers`~~ — does not exist; not needed (Navigator manages Azure config)

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Follow `BasicAuthStrategy` pattern exactly — same constructor style, same logger naming
- Use `self.logger = logging.getLogger("parrot.Telegram.Auth.Azure")`
- Use `urlencode()` for building WebApp URLs (same as `BasicAuthStrategy.build_login_keyboard`)
- Use `session.set_authenticated()` for populating session (same as `BasicAuthStrategy.handle_callback`)
- HTML page must use `Telegram.WebApp.sendData()` (same as `login.html` and `oauth2_callback.py`)
- Use `navconfig.config.get()` for env var resolution (same as existing `__post_init__`)

### JWT Decoding

The Navigator JWT is a standard three-part token: `header.payload.signature`.
We decode only the payload (base64url) to extract claims. **No signature verification**
is needed because:

1. The token comes from Navigator (trusted internal service)
2. The token was delivered via HTTPS redirect
3. `validate_token()` can be used for server-side validation if needed

```python
import base64
import json

def _decode_jwt_payload(token: str) -> Dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid JWT format")
    payload_b64 = parts[1]
    # Add padding if needed
    padding = 4 - len(payload_b64) % 4
    if padding != 4:
        payload_b64 += "=" * padding
    payload_bytes = base64.urlsafe_b64decode(payload_b64)
    return json.loads(payload_bytes)
```

Expected Navigator JWT claims (based on standard Navigator-auth):
- `user_id` or `sub` — user identifier
- `email` — user email
- `first_name` / `last_name` or `name` — display name
- `exp` — expiration timestamp
- `iss` — issuer (e.g., "navigator-auth")

### Azure Auth URL Derivation

When `azure_auth_url` is not explicitly set, derive it from `auth_url`:

```python
# If auth_url = "https://nav.example.com/api/v1/auth/login"
# Then azure_auth_url = "https://nav.example.com/api/v1/auth/azure/"

# If auth_url = "https://nav.example.com/api/v1/auth"
# Then azure_auth_url = "https://nav.example.com/api/v1/auth/azure/"
```

Heuristic: strip trailing path component if it looks like an endpoint name
(e.g., `/login`), then append `/azure/`.

### WebApp URL Construction

```python
# AzureAuthStrategy.build_login_keyboard():
login_page = self.login_page_url or getattr(config, "login_page_url", None)
params = urlencode({"azure_auth_url": self.azure_auth_url})
full_url = f"{login_page}?{params}"
# e.g.: https://static.example.com/telegram/azure_login.html?azure_auth_url=https%3A//nav.example.com/api/v1/auth/azure/
```

### Callback Data Format

The `azure_login.html` sends back to Telegram:

```json
{
  "auth_method": "azure",
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VyX2lkIjoiMTIzNDUiLCJlbWFpbCI6InVzZXJAY29tcGFueS5jb20ifQ.signature"
}
```

`AzureAuthStrategy.handle_callback()` checks for `data.get("auth_method") == "azure"` and
`data.get("token")`, then decodes the JWT to extract user info.

### Known Risks / Gotchas

| Risk | Mitigation |
|---|---|
| JWT payload claims vary by Navigator version | Gracefully handle missing fields; use `sub` or `user_id` for user_id, `name` or `first_name`+`last_name` for display_name |
| Telegram WebApp redirect chain | WebApp supports navigating to external URLs and back; tested with OAuth2 callback flow already |
| `redirect_url` must be HTTPS | Login page must be served over HTTPS (same requirement as existing `login_page_url`) |
| Navigator Azure endpoint may require trailing slash | Use `azure_auth_url` with trailing slash by default |
| JWT may be expired by the time callback reaches bot | Decode `exp` claim and check; warn but still authenticate (Navigator just issued it) |
| Token in URL query param visible in browser history | Telegram WebApp runs in embedded browser — no persistent history; page closes after sendData |

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| No new dependencies | — | JWT decode uses stdlib `base64` + `json`; no external JWT library needed |
| `aiohttp` | existing | Only if adding server-side token validation endpoint |
| `aiogram` | existing | Telegram bot framework, WebApp support |

### YAML Configuration Example

```yaml
agents:
  HRAgent:
    chatbot_id: hr_agent
    auth_method: azure
    # Explicit Azure auth URL
    azure_auth_url: https://nav.example.com/api/v1/auth/azure/
    # Login page for Azure SSO WebApp
    login_page_url: https://static.example.com/telegram/azure_login.html
    force_authentication: true
    enable_login: true

  FinanceBot:
    chatbot_id: finance_agent
    auth_method: azure
    # Azure URL derived from auth_url: {auth_url}/../azure/
    auth_url: https://nav.example.com/api/v1/auth/login
    login_page_url: https://static.example.com/telegram/azure_login.html
    force_authentication: true

  LegacyBot:
    chatbot_id: legacy_bot
    # Basic Auth — works as before, no changes
    auth_url: https://nav.example.com/api/v1/auth/login
    login_page_url: https://static.example.com/telegram/login.html
    enable_login: true
```

---

## 8. Worktree Strategy

- **Isolation unit**: per-spec (sequential tasks in one worktree)
- **Rationale**: All modules touch the same files (`auth.py`, `models.py`, `wrapper.py`) — parallel execution would cause conflicts
- **Cross-feature dependencies**: None (FEAT-036 OAuth2 is already merged)

---

## 9. Open Questions

- [ ] **Question 1**: Should we support a "combined" login page that shows BOTH BasicAuth form AND Azure SSO button on the same page? This would allow users to choose their method. — *Owner: Team*
- [ ] **Question 2**: What exact JWT claims does Navigator's Azure endpoint return? Need to confirm field names (`user_id` vs `sub`, `name` vs `first_name`/`last_name`). — *Owner: Team*
- [ ] **Question 3**: Should the bot validate the JWT signature server-side (requires knowing Navigator's signing key), or is payload decoding sufficient? — *Owner: Team*
- [ ] **Question 4**: Does Navigator's `/api/v1/auth/azure/` endpoint require any additional query parameters beyond `redirect_url`? — *Owner: Team*
- [ ] **Question 5**: Should we add a session TTL for Azure-authenticated sessions (like the 7-day TTL on OAuth2 sessions)? — *Owner: Team*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-19 | Claude | Initial draft from user requirements |
