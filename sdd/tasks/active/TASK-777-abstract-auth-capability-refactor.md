# TASK-777: AbstractAuthStrategy Capability Refactor

**Feature**: FEAT-109 — Telegram Multi-Auth Negotiation
**Spec**: `sdd/specs/FEAT-109-telegram-multi-auth-negotiation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

FEAT-109 needs a uniform contract that the wrapper can introspect
without `isinstance` checks. Today `AbstractAuthStrategy`
(`auth.py:178`) defines only `build_login_keyboard`,
`handle_callback`, and `validate_token` — strategies have no
declarative way to say "I can carry a post_auth redirect chain" or
"my canonical name is `basic`". This task adds those class-level
declarations, lifts the FEAT-108 `next_auth_url` /
`next_auth_required` kwargs (today only on `BasicAuthStrategy`) up to
the abstract base, and — critically — patches `login.html` + the
wrapper's BasicAuth payload so BasicAuth callbacks carry an
`auth_method: "basic"` tag that `CompositeAuthStrategy` (TASK-779)
will dispatch on.

Implements **Module 1** of the spec.

---

## Scope

- Add two class attributes to `AbstractAuthStrategy`:
  - `name: str = "abstract"` — canonical short name used in callback
    payloads and YAML config. Subclasses override.
  - `supports_post_auth_chain: bool = False` — replaces the
    `isinstance(..., BasicAuthStrategy)` gate at `wrapper.py:1021`.
- Lift optional kwargs onto the abstract signature:
  ```python
  async def build_login_keyboard(
      self, config: Any, state: str, *,
      next_auth_url: Optional[str] = None,
      next_auth_required: bool = False,
  ) -> ReplyKeyboardMarkup: ...
  ```
  Strategies that do not yet support the chain (Azure, OAuth2) ignore
  the kwargs — this keeps the signature uniform so the wrapper can
  always forward them without introspection.
- Set per-class attributes on the three concrete strategies:
  - `BasicAuthStrategy`: `name = "basic"`,
    `supports_post_auth_chain = True`.
  - `AzureAuthStrategy`: `name = "azure"`,
    `supports_post_auth_chain = False` (TASK-778 flips this).
  - `OAuth2AuthStrategy`: `name = "oauth2"`,
    `supports_post_auth_chain = False`.
- Patch the BasicAuth payload pipeline so every callback is tagged
  with `auth_method`:
  - Update `static/telegram/login.html`'s `sendData` call to include
    `auth_method: "basic"`.
  - Update `BasicAuthStrategy.handle_callback` (`auth.py:313`) to
    stay tolerant of both forms — payloads that include
    `auth_method` AND legacy payloads that omit it. This preserves
    existing deployments during the transition.

**NOT in scope**:
- `AzureAuthStrategy` post_auth chain support — TASK-778.
- `CompositeAuthStrategy` — TASK-779.
- Wrapper changes (`isinstance` replacement) — TASK-782.
- `auth_methods` YAML field — TASK-780.
- `login_multi.html` — TASK-783.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/integrations/telegram/auth.py` | MODIFY | Add class attrs; lift kwargs onto abstract signature; set per-class `name` / `supports_post_auth_chain` |
| `static/telegram/login.html` | MODIFY | Add `auth_method: "basic"` to the `sendData` payload |
| `packages/ai-parrot/tests/integrations/telegram/test_auth_strategy_capabilities.py` | CREATE | Unit tests for the new class attrs + signature contract |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# packages/ai-parrot/src/parrot/integrations/telegram/auth.py (verified):
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, WebAppInfo
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/integrations/telegram/auth.py

class AbstractAuthStrategy(ABC):                                # line 178
    @abstractmethod
    async def build_login_keyboard(                             # line 188
        self, config: Any, state: str,
    ) -> ReplyKeyboardMarkup: ...
    @abstractmethod
    async def handle_callback(                                  # line 205
        self, data: Dict[str, Any], session: TelegramUserSession,
    ) -> bool: ...
    @abstractmethod
    async def validate_token(self, token: str) -> bool: ...     # line 222

class BasicAuthStrategy(AbstractAuthStrategy):                  # line 238
    async def build_login_keyboard(                             # line 261
        self, config: Any, state: str, *,
        next_auth_url: Optional[str] = None,
        next_auth_required: bool = False,
    ) -> ReplyKeyboardMarkup: ...
    # handle_callback at line 313 — reads data["user_id"], data["token"],
    # data["display_name"], data["email"]. Does NOT read auth_method today.

class AzureAuthStrategy(AbstractAuthStrategy):                  # line 374
    async def build_login_keyboard(                             # line 402
        self, config: Any, state: str,
    ) -> ReplyKeyboardMarkup: ...

class OAuth2AuthStrategy(AbstractAuthStrategy):                 # line 577
    async def build_login_keyboard(                             # line 667
        self, config: Any, state: str,
    ) -> ReplyKeyboardMarkup: ...
```

```html
<!-- static/telegram/login.html — the sendData call is at line 235.
     Today it posts { user_id, token, display_name, email } with no
     method tag. -->
```

### Does NOT Exist

- ~~`AbstractAuthStrategy.name`~~ — new in this task.
- ~~`AbstractAuthStrategy.supports_post_auth_chain`~~ — new.
- ~~`AzureAuthStrategy` / `OAuth2AuthStrategy` accepting
  `next_auth_url`~~ — only BasicAuth accepts it today. Lifting to
  the base signature does **not** add behavior; TASK-778 wires Azure.
- ~~`login.html` sending `auth_method`~~ — added in this task.
- ~~`CompositeAuthStrategy`~~ — future task (TASK-779).

---

## Implementation Notes

### Pattern

```python
class AbstractAuthStrategy(ABC):
    name: str = "abstract"
    supports_post_auth_chain: bool = False

    @abstractmethod
    async def build_login_keyboard(
        self,
        config: Any,
        state: str,
        *,
        next_auth_url: Optional[str] = None,
        next_auth_required: bool = False,
    ) -> ReplyKeyboardMarkup:
        ...
```

Concrete classes declare their name at class level:
```python
class BasicAuthStrategy(AbstractAuthStrategy):
    name = "basic"
    supports_post_auth_chain = True
```

### Backward-compatibility for BasicAuth callbacks

`BasicAuthStrategy.handle_callback` must accept BOTH payload shapes:

```python
async def handle_callback(self, data, session) -> bool:
    # Accept payloads with or without auth_method (pre-FEAT-109 bots).
    method = data.get("auth_method")
    if method is not None and method != "basic":
        self.logger.warning(
            "BasicAuth callback invoked with auth_method=%r; "
            "ignoring mismatch and proceeding with basic.", method,
        )
    # ... existing logic (user_id, token, display_name, email) ...
```

### login.html change

In `static/telegram/login.html`, find the `sendData` call at line
235. The payload today looks roughly like:
```js
const payload = JSON.stringify({
    user_id: userId,
    token: data.token,
    display_name: data.display_name,
    email: data.email,
});
```
Add `auth_method: "basic"` as the first key for clarity.

---

## Acceptance Criteria

- [ ] `AbstractAuthStrategy.name` and
      `AbstractAuthStrategy.supports_post_auth_chain` class attrs
      exist with the defaults above.
- [ ] `AbstractAuthStrategy.build_login_keyboard` signature includes
      the `next_auth_url` / `next_auth_required` kwargs.
- [ ] `BasicAuthStrategy.name == "basic"` and
      `BasicAuthStrategy.supports_post_auth_chain is True`.
- [ ] `AzureAuthStrategy.name == "azure"` and
      `AzureAuthStrategy.supports_post_auth_chain is False`.
- [ ] `OAuth2AuthStrategy.name == "oauth2"` and
      `OAuth2AuthStrategy.supports_post_auth_chain is False`.
- [ ] `login.html` `sendData` payload includes
      `auth_method: "basic"`.
- [ ] `BasicAuthStrategy.handle_callback` still succeeds with legacy
      payloads that omit `auth_method`.
- [ ] All existing tests pass:
      `pytest packages/ai-parrot/tests/integrations/telegram/ -v`
- [ ] New tests cover the class attrs + callback back-compat.

---

## Test Specification (sketch)

```python
# tests/integrations/telegram/test_auth_strategy_capabilities.py
import pytest
from parrot.integrations.telegram.auth import (
    AbstractAuthStrategy,
    BasicAuthStrategy,
    AzureAuthStrategy,
    OAuth2AuthStrategy,
)


def test_abstract_defaults():
    assert AbstractAuthStrategy.name == "abstract"
    assert AbstractAuthStrategy.supports_post_auth_chain is False


def test_concrete_class_names():
    assert BasicAuthStrategy.name == "basic"
    assert AzureAuthStrategy.name == "azure"
    assert OAuth2AuthStrategy.name == "oauth2"


def test_post_auth_chain_capability():
    assert BasicAuthStrategy.supports_post_auth_chain is True
    assert AzureAuthStrategy.supports_post_auth_chain is False
    assert OAuth2AuthStrategy.supports_post_auth_chain is False


async def test_basic_callback_accepts_payload_with_auth_method():
    strategy = BasicAuthStrategy(auth_url="https://h/api/v1/login")
    session = ...  # TelegramUserSession fixture
    ok = await strategy.handle_callback(
        {"auth_method": "basic", "user_id": "u1", "token": "t"},
        session,
    )
    assert ok is True


async def test_basic_callback_accepts_legacy_payload_without_auth_method():
    strategy = BasicAuthStrategy(auth_url="https://h/api/v1/login")
    session = ...
    ok = await strategy.handle_callback(
        {"user_id": "u1", "token": "t"},  # no auth_method
        session,
    )
    assert ok is True
```

---

## Agent Instructions

1. Read the spec for the full rationale.
2. Verify the Codebase Contract — especially `auth.py` line numbers
   (code may have shifted).
3. Implement in this order: base class attrs → concrete overrides →
   `login.html` payload → BasicAuth tolerance → tests.
4. Run the full Telegram test suite before committing.
5. Move this file to `sdd/tasks/completed/` and update the index.

---

## Completion Note

*(Agent fills this in when done)*
