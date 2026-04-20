# TASK-765: Implement AzureAuthStrategy

**Feature**: FEAT-109 — Telegram Integration Azure SSO via Navigator
**Spec**: `sdd/specs/archived/telegram-integration-basicauth.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-764
**Assigned-to**: unassigned

---

## Context

> Implements Module 2 from the spec. This is the core auth strategy that
> handles the Azure SSO flow. It follows the existing `AbstractAuthStrategy`
> interface and delegates SSO entirely to Navigator's `/api/v1/auth/azure/`
> endpoint. The strategy only needs to build the WebApp URL, decode the JWT
> token returned by Navigator, and populate the user session.

---

## Scope

- Implement `AzureAuthStrategy(AbstractAuthStrategy)` in `auth.py`
- Constructor accepts `auth_url`, `azure_auth_url`, and optional `login_page_url`
- `build_login_keyboard()`: builds WebApp keyboard pointing to `azure_login.html` with `azure_auth_url` as query param
- `handle_callback()`: receives `{"auth_method": "azure", "token": jwt}`, decodes JWT payload, populates session
- `validate_token()`: delegates to `NavigatorAuthClient.validate_token()`
- `_decode_jwt_payload()`: static method to decode base64url JWT payload (no signature verification)
- Write comprehensive unit tests

**NOT in scope**: Config model changes (TASK-764), wrapper integration (TASK-766), HTML page (TASK-767)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/integrations/telegram/auth.py` | MODIFY | Add `AzureAuthStrategy` class after `BasicAuthStrategy` |
| `packages/ai-parrot/tests/integrations/telegram/test_azure_auth_strategy.py` | CREATE | Unit tests for AzureAuthStrategy |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Already imported in auth.py — reuse these:
import logging  # verified: auth.py top
from abc import ABC, abstractmethod  # verified: auth.py top
from typing import Any, Dict, Optional  # verified: auth.py top
from urllib.parse import urlencode  # verified: auth.py (used by BasicAuthStrategy line 284)

from aiogram.types import (
    ReplyKeyboardMarkup,  # verified: auth.py (used by BasicAuthStrategy line 286)
    KeyboardButton,       # verified: auth.py (used by BasicAuthStrategy line 288)
    WebAppInfo,           # verified: auth.py (used by BasicAuthStrategy line 290)
)

# For JWT decoding (stdlib — no new dependencies):
import base64  # stdlib
import json    # stdlib
```

### Existing Signatures to Use
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
    # Pattern to follow for constructor, keyboard building, callback handling
    def __init__(self, auth_url: str, login_page_url: Optional[str] = None):  # line 250
        self.auth_url = auth_url
        self.login_page_url = login_page_url
        self._client = NavigatorAuthClient(auth_url)
        self.logger = logging.getLogger("parrot.Telegram.Auth.Basic")  # line 258

    async def build_login_keyboard(self, config, state) -> ReplyKeyboardMarkup:  # line 260
        page_url = self.login_page_url or getattr(config, "login_page_url", None)
        full_url = f"{page_url}?{urlencode({'auth_url': self.auth_url})}"
        return ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(
                text="\U0001f510 Sign in to Navigator",
                web_app=WebAppInfo(url=full_url),
            )]],
            resize_keyboard=True,
            one_time_keyboard=True,
        )

    async def handle_callback(self, data, session) -> bool:  # line 297
        # Expects {"user_id": str, "token": str, ...}
        # Calls session.set_authenticated(...)
        ...


class NavigatorAuthClient:  # line 121
    def __init__(self, auth_url: str, timeout: int = 15):  # line 122
        ...
    async def validate_token(self, token: str) -> bool:  # line 167
        return bool(token)  # placeholder


@dataclass
class TelegramUserSession:  # line 35
    def set_authenticated(
        self, nav_user_id, session_token, display_name=None, email=None, **extra_meta
    ):  # line 84
        self.nav_user_id = str(nav_user_id)
        self.nav_session_token = session_token
        self.nav_display_name = display_name or self.nav_display_name
        self.nav_email = email or self.nav_email
        self.authenticated = True
        self.authenticated_at = datetime.now(tz=timezone.utc)
        self.metadata.update(extra_meta)
```

### Does NOT Exist
- ~~`AzureAuthStrategy`~~ — does not exist yet; this task creates it
- ~~`NavigatorAuthClient.validate_azure_token()`~~ — not a real method; use `validate_token()`
- ~~`TelegramUserSession.azure_token`~~ — no such field; use `nav_session_token`
- ~~`TelegramUserSession.azure_user_id`~~ — no such field; use `nav_user_id`
- ~~`parrot.integrations.telegram.azure_auth`~~ — no such module; add to `auth.py`

---

## Implementation Notes

### Pattern to Follow
```python
# Follow BasicAuthStrategy's structure exactly.
# Place AzureAuthStrategy AFTER BasicAuthStrategy, BEFORE OAuth2AuthStrategy in auth.py.

class AzureAuthStrategy(AbstractAuthStrategy):
    """Navigator Azure AD SSO strategy.

    Delegates the OAuth2 flow to Navigator's /api/v1/auth/azure/ endpoint.
    The bot only captures the JWT token returned via redirect.
    """

    def __init__(
        self,
        auth_url: str,
        azure_auth_url: str,
        login_page_url: Optional[str] = None,
    ):
        self.auth_url = auth_url
        self.azure_auth_url = azure_auth_url
        self.login_page_url = login_page_url
        self._client = NavigatorAuthClient(auth_url)
        self.logger = logging.getLogger("parrot.Telegram.Auth.Azure")

    async def build_login_keyboard(self, config, state):
        page_url = self.login_page_url or getattr(config, "login_page_url", None)
        if not page_url:
            raise ValueError("login_page_url is required for AzureAuthStrategy")
        full_url = f"{page_url}?{urlencode({'azure_auth_url': self.azure_auth_url})}"
        return ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(
                text="\U0001f510 Sign in with Azure",
                web_app=WebAppInfo(url=full_url),
            )]],
            resize_keyboard=True,
            one_time_keyboard=True,
        )

    async def handle_callback(self, data, session):
        token = data.get("token")
        if not token:
            self.logger.warning("Azure auth callback missing token")
            return False
        try:
            claims = self._decode_jwt_payload(token)
        except (ValueError, Exception) as exc:
            self.logger.warning("Failed to decode Azure JWT: %s", exc)
            return False
        user_id = claims.get("user_id") or claims.get("sub") or ""
        email = claims.get("email", "")
        display_name = claims.get("name") or claims.get("first_name", "")
        if claims.get("last_name"):
            display_name = f"{display_name} {claims['last_name']}".strip()
        if not user_id:
            self.logger.warning("Azure JWT missing user_id/sub claim")
            return False
        session.set_authenticated(
            nav_user_id=str(user_id),
            session_token=token,
            display_name=display_name,
            email=email,
        )
        self.logger.info(
            "User tg:%s authenticated via Azure as %s (%s)",
            session.telegram_id, user_id, display_name,
        )
        return True

    async def validate_token(self, token):
        return await self._client.validate_token(token)

    @staticmethod
    def _decode_jwt_payload(token: str) -> Dict[str, Any]:
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("Invalid JWT format: expected 3 parts")
        payload_b64 = parts[1]
        # Add base64 padding
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        return json.loads(payload_bytes)
```

### Key Constraints
- Use stdlib `base64` + `json` for JWT decode — no external JWT library
- No signature verification (Navigator is trusted)
- Gracefully handle missing JWT claims (`user_id` vs `sub`, `name` vs `first_name`+`last_name`)
- Use `self.logger` for all logging (no print statements)
- Must be fully async (even though current methods are simple)

### References in Codebase
- `packages/ai-parrot/src/parrot/integrations/telegram/auth.py:237` — `BasicAuthStrategy` to follow as pattern
- `packages/ai-parrot/src/parrot/integrations/telegram/auth.py:177` — `AbstractAuthStrategy` interface

---

## Acceptance Criteria

- [ ] `AzureAuthStrategy` class exists in `auth.py`
- [ ] `build_login_keyboard()` returns WebApp keyboard with `azure_login.html?azure_auth_url=...`
- [ ] `handle_callback()` decodes JWT and populates session with user_id, email, display_name
- [ ] `handle_callback()` returns False for missing token or invalid JWT
- [ ] `validate_token()` delegates to NavigatorAuthClient
- [ ] `_decode_jwt_payload()` correctly decodes base64url JWT payloads
- [ ] All tests pass: `pytest packages/ai-parrot/tests/integrations/telegram/test_azure_auth_strategy.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/integrations/telegram/test_azure_auth_strategy.py
import base64
import json
import pytest
from parrot.integrations.telegram.auth import AzureAuthStrategy, TelegramUserSession


def _make_jwt(claims: dict) -> str:
    """Helper to build a fake JWT with the given payload claims."""
    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "HS256", "typ": "JWT"}).encode()
    ).rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(
        json.dumps(claims).encode()
    ).rstrip(b"=").decode()
    return f"{header}.{payload}.fakesig"


@pytest.fixture
def strategy():
    return AzureAuthStrategy(
        auth_url="https://nav.example.com/api/v1/auth/login",
        azure_auth_url="https://nav.example.com/api/v1/auth/azure/",
        login_page_url="https://static.example.com/telegram/azure_login.html",
    )


@pytest.fixture
def session():
    return TelegramUserSession(telegram_id=12345)


class TestAzureAuthStrategyInit:
    def test_init_stores_fields(self, strategy):
        assert strategy.auth_url == "https://nav.example.com/api/v1/auth/login"
        assert strategy.azure_auth_url == "https://nav.example.com/api/v1/auth/azure/"
        assert strategy.login_page_url is not None


class TestBuildLoginKeyboard:
    @pytest.mark.asyncio
    async def test_keyboard_has_webapp_button(self, strategy):
        config = type("Cfg", (), {"login_page_url": None})()
        kb = await strategy.build_login_keyboard(config, "state123")
        assert kb.keyboard
        button = kb.keyboard[0][0]
        assert button.web_app is not None
        assert "azure_auth_url=" in button.web_app.url

    @pytest.mark.asyncio
    async def test_keyboard_no_page_url_raises(self):
        s = AzureAuthStrategy(
            auth_url="https://x.com", azure_auth_url="https://x.com/azure/",
        )
        config = type("Cfg", (), {"login_page_url": None})()
        with pytest.raises(ValueError, match="login_page_url"):
            await s.build_login_keyboard(config, "state")


class TestHandleCallback:
    @pytest.mark.asyncio
    async def test_success_with_user_id(self, strategy, session):
        token = _make_jwt({"user_id": "42", "email": "a@b.com", "name": "Alice"})
        result = await strategy.handle_callback({"auth_method": "azure", "token": token}, session)
        assert result is True
        assert session.authenticated
        assert session.nav_user_id == "42"
        assert session.nav_email == "a@b.com"
        assert session.nav_display_name == "Alice"

    @pytest.mark.asyncio
    async def test_success_with_sub_claim(self, strategy, session):
        token = _make_jwt({"sub": "99", "email": "b@c.com", "first_name": "Bob", "last_name": "Smith"})
        result = await strategy.handle_callback({"auth_method": "azure", "token": token}, session)
        assert result is True
        assert session.nav_user_id == "99"
        assert session.nav_display_name == "Bob Smith"

    @pytest.mark.asyncio
    async def test_missing_token_returns_false(self, strategy, session):
        result = await strategy.handle_callback({"auth_method": "azure"}, session)
        assert result is False
        assert not session.authenticated

    @pytest.mark.asyncio
    async def test_invalid_jwt_returns_false(self, strategy, session):
        result = await strategy.handle_callback({"auth_method": "azure", "token": "not.a.jwt!"}, session)
        assert result is False

    @pytest.mark.asyncio
    async def test_jwt_missing_user_id_returns_false(self, strategy, session):
        token = _make_jwt({"email": "a@b.com"})
        result = await strategy.handle_callback({"auth_method": "azure", "token": token}, session)
        assert result is False


class TestDecodeJwtPayload:
    def test_decode_valid_jwt(self):
        claims = {"user_id": "1", "email": "test@test.com"}
        token = _make_jwt(claims)
        decoded = AzureAuthStrategy._decode_jwt_payload(token)
        assert decoded["user_id"] == "1"
        assert decoded["email"] == "test@test.com"

    def test_decode_with_padding(self):
        claims = {"a": "x"}
        token = _make_jwt(claims)
        decoded = AzureAuthStrategy._decode_jwt_payload(token)
        assert decoded["a"] == "x"

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match="Invalid JWT"):
            AzureAuthStrategy._decode_jwt_payload("onlytwoparts.here")

    def test_non_json_payload_raises(self):
        bad = "header." + base64.urlsafe_b64encode(b"notjson").rstrip(b"=").decode() + ".sig"
        with pytest.raises(json.JSONDecodeError):
            AzureAuthStrategy._decode_jwt_payload(bad)


class TestValidateToken:
    @pytest.mark.asyncio
    async def test_validates_non_empty(self, strategy):
        result = await strategy.validate_token("sometoken")
        assert result is True

    @pytest.mark.asyncio
    async def test_rejects_empty(self, strategy):
        result = await strategy.validate_token("")
        assert result is False
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/archived/telegram-integration-basicauth.spec.md` for full context
2. **Check dependencies** — verify TASK-764 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — `read` auth.py to confirm `AbstractAuthStrategy` and `BasicAuthStrategy` signatures
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
5. **Implement** `AzureAuthStrategy` in auth.py (after BasicAuthStrategy, before OAuth2AuthStrategy)
6. **Write tests** in test_azure_auth_strategy.py
7. **Run**: `pytest packages/ai-parrot/tests/integrations/telegram/test_azure_auth_strategy.py -v`
8. **Move this file** to `sdd/tasks/completed/`
9. **Update index** → `"done"`

---

## Completion Note

**Completed by**: claude-sonnet-4-6
**Date**: 2026-04-19
**Notes**: Implemented AzureAuthStrategy in auth.py after BasicAuthStrategy. Added import json. All 27 unit tests pass.

**Deviations from spec**: none
