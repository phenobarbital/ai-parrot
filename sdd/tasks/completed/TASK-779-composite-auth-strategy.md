# TASK-779: CompositeAuthStrategy — Multi-Method Router

**Feature**: FEAT-109 — Telegram Multi-Auth Negotiation
**Spec**: `sdd/specs/FEAT-109-telegram-multi-auth-negotiation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (3-4h)
**Depends-on**: TASK-777, TASK-778
**Assigned-to**: unassigned

---

## Context

The architectural centerpiece of FEAT-109 is a composite strategy
that routes callbacks to the right per-method strategy based on the
`auth_method` field in the WebApp's `sendData` payload. The
composite owns no auth primitives — it is pure dispatch.

Implements **Module 3** of the spec.

---

## Scope

- Implement `CompositeAuthStrategy(AbstractAuthStrategy)` in
  `packages/ai-parrot/src/parrot/integrations/telegram/auth.py`.
- Constructor:
  ```python
  def __init__(
      self,
      strategies: Dict[str, AbstractAuthStrategy],
      login_page_url: str,
  ) -> None
  ```
  `strategies` is keyed by each member's `.name`
  (`"basic"`, `"azure"`, …). `login_page_url` MUST be the URL of the
  `login_multi.html` page (TASK-783 delivers it).
- `build_login_keyboard(config, state, *, next_auth_url=None,
  next_auth_required=False)`:
  1. Collect per-method auth URLs by peeking at each strategy:
     - BasicAuth → `strategy.auth_url` → `?auth_url=…`
     - Azure    → `strategy.azure_auth_url` → `?azure_auth_url=…`
  2. Forward `next_auth_url` / `next_auth_required` to every member
     that supports it (capability-gated).
  3. Emit ONE WebApp button pointing at `login_multi.html` with the
     merged query string.
- `handle_callback(data, session)`:
  1. Read `method = data.get("auth_method")`.
  2. If `method` not in `self.strategies`, log warning and return
     False.
  3. Otherwise, delegate to
     `self.strategies[method].handle_callback(data, session)`.
- `validate_token(token)`:
  Delegate to the strategy whose `.name` matches
  `session.auth_method` if tracked; otherwise try BasicAuth first
  (most common path). Document this ordering.
- Class attributes:
  - `name = "composite"`.
  - `supports_post_auth_chain` is a `@property` that returns
    `all(s.supports_post_auth_chain for s in self.strategies.values())`
    — AND semantics, per the spec's risk section.

**NOT in scope**:
- Wrapper integration (choosing Composite vs single) — TASK-781.
- `auth_methods` YAML field — TASK-780.
- `login_multi.html` — TASK-783.
- Validation rules — TASK-784.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/integrations/telegram/auth.py` | MODIFY | Append new `CompositeAuthStrategy` class (after OAuth2AuthStrategy) |
| `packages/ai-parrot/tests/integrations/telegram/test_composite_auth.py` | CREATE | Comprehensive unit tests for dispatch, build, capability flag |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# packages/ai-parrot/src/parrot/integrations/telegram/auth.py — already present:
from abc import ABC
from typing import Any, Dict, Optional
from urllib.parse import urlencode
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, WebAppInfo
```

### Existing Signatures to Use

```python
# Post TASK-777 + TASK-778, the base contract is:
class AbstractAuthStrategy(ABC):
    name: str = "abstract"
    supports_post_auth_chain: bool = False
    async def build_login_keyboard(
        self, config: Any, state: str, *,
        next_auth_url: Optional[str] = None,
        next_auth_required: bool = False,
    ) -> ReplyKeyboardMarkup: ...
    async def handle_callback(
        self, data: Dict[str, Any], session: "TelegramUserSession",
    ) -> bool: ...
    async def validate_token(self, token: str) -> bool: ...

# Attribute access on concrete members (used to harvest query params):
#   BasicAuthStrategy.auth_url        (str)
#   AzureAuthStrategy.azure_auth_url  (str)
# Both are assigned in their __init__ — verify before reading.
```

### Does NOT Exist

- ~~`CompositeAuthStrategy`~~ — this task creates it.
- ~~`AbstractAuthStrategy.auth_url`~~ / `.azure_auth_url` — these are
  instance attributes on the concrete subclasses, NOT on the base.
  `CompositeAuthStrategy.build_login_keyboard` must `getattr(strat,
  'auth_url', None)` / `getattr(strat, 'azure_auth_url', None)` and
  skip `None` values.
- ~~`TelegramUserSession.auth_method`~~ — the session's storage of
  the chosen method is an OPEN QUESTION. If `validate_token` needs
  the method, read it from `session.metadata` or equivalent — grep
  `TelegramUserSession` (`auth.py:37`) before assuming any field.

---

## Implementation Notes

### Construction example (post TASK-781 wiring)

```python
composite = CompositeAuthStrategy(
    strategies={
        "basic": BasicAuthStrategy(...),
        "azure": AzureAuthStrategy(...),
    },
    login_page_url="https://host/static/telegram/login_multi.html",
)
```

### build_login_keyboard logic

```python
async def build_login_keyboard(
    self, config, state, *, next_auth_url=None, next_auth_required=False,
) -> ReplyKeyboardMarkup:
    params: Dict[str, str] = {}
    if basic := self.strategies.get("basic"):
        if auth_url := getattr(basic, "auth_url", None):
            params["auth_url"] = auth_url
    if azure := self.strategies.get("azure"):
        if azure_url := getattr(azure, "azure_auth_url", None):
            params["azure_auth_url"] = azure_url
    if next_auth_url:
        params["next_auth_url"] = next_auth_url
        params["next_auth_required"] = "true" if next_auth_required else "false"
    full_url = f"{self.login_page_url}?{urlencode(params)}"
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(
            text="🔐 Sign in",
            web_app=WebAppInfo(url=full_url),
        )]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
```

### Dispatch

```python
async def handle_callback(self, data, session) -> bool:
    method = data.get("auth_method")
    strat = self.strategies.get(method) if method else None
    if strat is None:
        self.logger.warning(
            "CompositeAuthStrategy: callback with unknown "
            "auth_method=%r (known: %s)", method,
            list(self.strategies),
        )
        return False
    return await strat.handle_callback(data, session)
```

---

## Acceptance Criteria

- [ ] `CompositeAuthStrategy` exists in `auth.py` and subclasses
      `AbstractAuthStrategy`.
- [ ] `build_login_keyboard` emits a URL with one query param per
      member strategy + optional post_auth params.
- [ ] `handle_callback({auth_method: "basic", ...})` delegates to
      the basic member; `{auth_method: "azure", ...}` delegates to
      Azure.
- [ ] Unknown `auth_method` logs a warning and returns False.
- [ ] `supports_post_auth_chain` is True only when every member
      supports the chain.
- [ ] `validate_token` delegates consistently; behavior documented.
- [ ] Tests cover dispatch, build, capability AND/property, unknown
      method, and empty strategies dict (should raise on init).

---

## Test Specification (sketch)

```python
# tests/integrations/telegram/test_composite_auth.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.integrations.telegram.auth import (
    CompositeAuthStrategy,
    BasicAuthStrategy,
    AzureAuthStrategy,
)


def _basic():
    s = MagicMock(spec=BasicAuthStrategy)
    s.name = "basic"
    s.supports_post_auth_chain = True
    s.auth_url = "https://h/api/v1/login"
    return s


def _azure():
    s = MagicMock(spec=AzureAuthStrategy)
    s.name = "azure"
    s.supports_post_auth_chain = True
    s.azure_auth_url = "https://h/api/v1/auth/azure/"
    return s


@pytest.fixture
def composite():
    return CompositeAuthStrategy(
        strategies={"basic": _basic(), "azure": _azure()},
        login_page_url="https://h/static/telegram/login_multi.html",
    )


@pytest.mark.asyncio
async def test_build_login_keyboard_emits_all_urls(composite):
    kb = await composite.build_login_keyboard(MagicMock(), "nonce")
    url = kb.keyboard[0][0].web_app.url
    assert "auth_url=https" in url
    assert "azure_auth_url=https" in url


@pytest.mark.asyncio
async def test_dispatch_basic(composite):
    composite.strategies["basic"].handle_callback = AsyncMock(return_value=True)
    session = MagicMock()
    ok = await composite.handle_callback(
        {"auth_method": "basic", "token": "t"}, session,
    )
    assert ok is True
    composite.strategies["basic"].handle_callback.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatch_unknown_returns_false(composite):
    session = MagicMock()
    ok = await composite.handle_callback(
        {"auth_method": "linkedin"}, session,
    )
    assert ok is False


def test_capability_flag_all_members_support(composite):
    assert composite.supports_post_auth_chain is True


def test_capability_flag_requires_all(composite):
    composite.strategies["azure"].supports_post_auth_chain = False
    assert composite.supports_post_auth_chain is False


def test_empty_strategies_raises():
    with pytest.raises(ValueError, match="at least one"):
        CompositeAuthStrategy(
            strategies={},
            login_page_url="https://h/static/telegram/login_multi.html",
        )
```

---

## Agent Instructions

1. Read the spec and TASK-777 / TASK-778 completion notes.
2. Implement CompositeAuthStrategy at the END of `auth.py` (after
   OAuth2AuthStrategy for consistency).
3. Tests first (TDD) if practical.
4. Commit.

---

## Completion Note

*(Agent fills this in when done)*
