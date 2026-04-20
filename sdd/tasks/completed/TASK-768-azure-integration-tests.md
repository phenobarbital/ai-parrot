# TASK-768: Azure Auth Integration Tests

**Feature**: FEAT-109 — Telegram Integration Azure SSO via Navigator
**Spec**: `sdd/specs/archived/telegram-integration-basicauth.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-764, TASK-765, TASK-766
**Assigned-to**: unassigned

---

## Context

> Implements Module 5 from the spec. End-to-end integration tests that
> verify the complete Azure SSO flow: config → strategy creation → login
> keyboard → callback handling → session populated. Also tests backward
> compatibility with existing basic/oauth2 flows.

---

## Scope

- Write integration tests that exercise the full Azure auth flow
- Test strategy factory integration (config → wrapper → strategy)
- Test handle_web_app_data routing to AzureAuthStrategy
- Test force_authentication with Azure
- Test backward compatibility: basic auth and oauth2 flows unchanged
- Consolidate and verify all edge cases across the pipeline

**NOT in scope**: Modifying implementation code. This task only writes tests.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/integrations/telegram/test_azure_integration.py` | CREATE | Integration tests for full Azure flow |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Test infrastructure:
import pytest  # standard test framework
from unittest.mock import MagicMock, AsyncMock, patch  # stdlib mocking

# Components under test:
from parrot.integrations.telegram.auth import (
    AzureAuthStrategy,     # created by TASK-765
    BasicAuthStrategy,     # verified: auth.py:237
    TelegramUserSession,   # verified: auth.py:35
)
from parrot.integrations.telegram.models import (
    TelegramAgentConfig,   # verified: models.py:12
    TelegramBotsConfig,    # verified: models.py:134
)

# For JWT test helper:
import base64  # stdlib
import json    # stdlib
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/integrations/telegram/auth.py
class TelegramUserSession:  # line 35
    telegram_id: int
    authenticated: bool = False
    nav_user_id: Optional[str] = None
    nav_session_token: Optional[str] = None
    nav_display_name: Optional[str] = None
    nav_email: Optional[str] = None

    def set_authenticated(self, nav_user_id, session_token, display_name=None, email=None, **extra_meta):  # line 84
        ...
    def clear_auth(self):  # line 102
        ...

# AzureAuthStrategy (created by TASK-765):
class AzureAuthStrategy(AbstractAuthStrategy):
    def __init__(self, auth_url, azure_auth_url, login_page_url=None): ...
    async def build_login_keyboard(self, config, state) -> ReplyKeyboardMarkup: ...
    async def handle_callback(self, data, session) -> bool: ...
    async def validate_token(self, token) -> bool: ...
    @staticmethod
    def _decode_jwt_payload(token) -> Dict[str, Any]: ...
```

### Existing Test Patterns
```python
# packages/ai-parrot/tests/integrations/telegram/test_oauth2_integration.py — follow this pattern
# Uses @pytest.mark.asyncio for async tests
# Uses fixtures for config and session objects
# Tests full flows: config → strategy → keyboard → callback → session
```

### Does NOT Exist
- ~~`TelegramAgentWrapper` in tests~~ — do not instantiate the full wrapper (requires Bot, Agent); test strategy logic directly
- ~~`parrot.integrations.telegram.testing`~~ — no test utilities module; write helpers inline

---

## Implementation Notes

### JWT Helper
```python
def _make_jwt(claims: dict) -> str:
    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "HS256", "typ": "JWT"}).encode()
    ).rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(
        json.dumps(claims).encode()
    ).rstrip(b"=").decode()
    return f"{header}.{payload}.fakesignature"
```

### Test Categories

1. **Full Azure Flow**: config → strategy → keyboard → simulate callback → assert session
2. **Force Authentication**: config with `force_authentication=True` + azure
3. **Backward Compat**: ensure basic and oauth2 configs still produce correct strategies
4. **Edge Cases**: expired JWT, missing claims, malformed token

### Key Constraints
- All async tests need `@pytest.mark.asyncio`
- Do NOT instantiate `TelegramAgentWrapper` (requires aiogram Bot) — test strategy directly
- Do NOT make real HTTP calls — test the strategy logic only
- Follow existing test patterns from `test_oauth2_integration.py`

### References in Codebase
- `packages/ai-parrot/tests/integrations/telegram/test_oauth2_integration.py` — integration test pattern
- `packages/ai-parrot/tests/integrations/telegram/test_wrapper_strategy_factory.py` — factory test pattern

---

## Acceptance Criteria

- [ ] Full Azure flow test passes: config → strategy → keyboard → callback → authenticated session
- [ ] Force authentication test validates Azure blocks unauthenticated
- [ ] Backward compat tests confirm basic and oauth2 still work
- [ ] Edge cases tested: missing token, invalid JWT, missing claims
- [ ] All tests pass: `pytest packages/ai-parrot/tests/integrations/telegram/test_azure_integration.py -v`
- [ ] Existing test suite still passes: `pytest packages/ai-parrot/tests/integrations/telegram/ -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/integrations/telegram/test_azure_integration.py
import base64
import json
import pytest
from parrot.integrations.telegram.auth import (
    AzureAuthStrategy, BasicAuthStrategy, TelegramUserSession,
)
from parrot.integrations.telegram.models import TelegramAgentConfig


def _make_jwt(claims: dict) -> str:
    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "HS256", "typ": "JWT"}).encode()
    ).rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(
        json.dumps(claims).encode()
    ).rstrip(b"=").decode()
    return f"{header}.{payload}.fakesig"


@pytest.fixture
def azure_config():
    return TelegramAgentConfig(
        name="AzureBot",
        chatbot_id="azure_bot",
        bot_token="test:token",
        auth_method="azure",
        auth_url="https://nav.example.com/api/v1/auth/login",
        azure_auth_url="https://nav.example.com/api/v1/auth/azure/",
        login_page_url="https://static.example.com/telegram/azure_login.html",
        force_authentication=True,
    )


@pytest.fixture
def basic_config():
    return TelegramAgentConfig(
        name="BasicBot",
        chatbot_id="basic_bot",
        bot_token="test:token",
        auth_url="https://nav.example.com/api/v1/auth/login",
        login_page_url="https://static.example.com/telegram/login.html",
    )


class TestAzureFullFlow:
    """Test complete Azure SSO flow from config to authenticated session."""

    @pytest.mark.asyncio
    async def test_full_azure_login_flow(self, azure_config):
        strategy = AzureAuthStrategy(
            auth_url=azure_config.auth_url,
            azure_auth_url=azure_config.azure_auth_url,
            login_page_url=azure_config.login_page_url,
        )

        # Step 1: Build keyboard
        keyboard = await strategy.build_login_keyboard(azure_config, "state123")
        assert keyboard is not None
        button = keyboard.keyboard[0][0]
        assert button.web_app is not None
        assert "azure_auth_url=" in button.web_app.url
        assert "azure_login.html" in button.web_app.url

        # Step 2: Simulate callback with JWT
        session = TelegramUserSession(telegram_id=42)
        jwt = _make_jwt({
            "user_id": "emp-001",
            "email": "alice@company.com",
            "name": "Alice Johnson",
            "exp": 9999999999,
        })
        callback_data = {"auth_method": "azure", "token": jwt}
        success = await strategy.handle_callback(callback_data, session)

        # Step 3: Verify session
        assert success is True
        assert session.authenticated is True
        assert session.nav_user_id == "emp-001"
        assert session.nav_email == "alice@company.com"
        assert session.nav_display_name == "Alice Johnson"
        assert session.nav_session_token == jwt

    @pytest.mark.asyncio
    async def test_azure_with_sub_claim(self, azure_config):
        strategy = AzureAuthStrategy(
            auth_url=azure_config.auth_url,
            azure_auth_url=azure_config.azure_auth_url,
            login_page_url=azure_config.login_page_url,
        )
        session = TelegramUserSession(telegram_id=42)
        jwt = _make_jwt({"sub": "sub-123", "email": "b@c.com", "first_name": "Bob", "last_name": "Smith"})
        success = await strategy.handle_callback({"auth_method": "azure", "token": jwt}, session)
        assert success is True
        assert session.nav_user_id == "sub-123"
        assert "Bob" in session.nav_display_name
        assert "Smith" in session.nav_display_name


class TestAzureForceAuthentication:
    """Test that force_authentication works with Azure."""

    def test_config_force_auth_with_azure(self, azure_config):
        assert azure_config.force_authentication is True
        assert azure_config.auth_method == "azure"

    @pytest.mark.asyncio
    async def test_unauthenticated_session(self, azure_config):
        session = TelegramUserSession(telegram_id=42)
        assert session.authenticated is False


class TestBackwardCompatibility:
    """Ensure existing auth flows are not broken."""

    def test_basic_config_defaults(self, basic_config):
        assert basic_config.auth_method == "basic"
        assert basic_config.azure_auth_url is None

    @pytest.mark.asyncio
    async def test_basic_strategy_still_works(self, basic_config):
        strategy = BasicAuthStrategy(
            auth_url=basic_config.auth_url,
            login_page_url=basic_config.login_page_url,
        )
        kb = await strategy.build_login_keyboard(basic_config, "state")
        button = kb.keyboard[0][0]
        assert "auth_url=" in button.web_app.url
        assert "azure" not in button.web_app.url.lower()

    @pytest.mark.asyncio
    async def test_basic_callback_still_works(self, basic_config):
        strategy = BasicAuthStrategy(
            auth_url=basic_config.auth_url,
            login_page_url=basic_config.login_page_url,
        )
        session = TelegramUserSession(telegram_id=42)
        data = {"user_id": "nav-1", "token": "tok", "display_name": "Nav User", "email": "n@n.com"}
        success = await strategy.handle_callback(data, session)
        assert success is True
        assert session.nav_user_id == "nav-1"


class TestAzureEdgeCases:
    """Edge cases for Azure auth."""

    @pytest.mark.asyncio
    async def test_empty_token_rejected(self, azure_config):
        strategy = AzureAuthStrategy(
            auth_url=azure_config.auth_url,
            azure_auth_url=azure_config.azure_auth_url,
        )
        session = TelegramUserSession(telegram_id=42)
        result = await strategy.handle_callback({"auth_method": "azure", "token": ""}, session)
        assert result is False

    @pytest.mark.asyncio
    async def test_malformed_jwt_rejected(self, azure_config):
        strategy = AzureAuthStrategy(
            auth_url=azure_config.auth_url,
            azure_auth_url=azure_config.azure_auth_url,
        )
        session = TelegramUserSession(telegram_id=42)
        result = await strategy.handle_callback({"auth_method": "azure", "token": "garbage"}, session)
        assert result is False

    @pytest.mark.asyncio
    async def test_jwt_without_user_id_rejected(self, azure_config):
        strategy = AzureAuthStrategy(
            auth_url=azure_config.auth_url,
            azure_auth_url=azure_config.azure_auth_url,
        )
        session = TelegramUserSession(telegram_id=42)
        jwt = _make_jwt({"email": "a@b.com", "name": "No ID"})
        result = await strategy.handle_callback({"auth_method": "azure", "token": jwt}, session)
        assert result is False

    @pytest.mark.asyncio
    async def test_logout_clears_azure_session(self, azure_config):
        strategy = AzureAuthStrategy(
            auth_url=azure_config.auth_url,
            azure_auth_url=azure_config.azure_auth_url,
            login_page_url=azure_config.login_page_url,
        )
        session = TelegramUserSession(telegram_id=42)
        jwt = _make_jwt({"user_id": "42", "email": "a@b.com", "name": "Alice"})
        await strategy.handle_callback({"auth_method": "azure", "token": jwt}, session)
        assert session.authenticated is True

        session.clear_auth()
        assert session.authenticated is False
        assert session.nav_user_id is None
        assert session.nav_session_token is None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/archived/telegram-integration-basicauth.spec.md` for full context
2. **Check dependencies** — verify TASK-764, TASK-765, TASK-766 are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm `AzureAuthStrategy` and config changes exist
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
5. **Write tests** in test_azure_integration.py
6. **Run**: `pytest packages/ai-parrot/tests/integrations/telegram/test_azure_integration.py -v`
7. **Run full suite**: `pytest packages/ai-parrot/tests/integrations/telegram/ -v`
8. **Move this file** to `sdd/tasks/completed/`
9. **Update index** → `"done"`

---

## Completion Note

**Completed by**: claude-sonnet-4-6
**Date**: 2026-04-19
**Notes**: Created test_azure_integration.py with 16 integration tests covering full flow, force auth, backward compat, and edge cases. Full suite 178 tests pass.

**Deviations from spec**: none
