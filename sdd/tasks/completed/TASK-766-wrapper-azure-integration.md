# TASK-766: Integrate AzureAuthStrategy into TelegramAgentWrapper

**Feature**: FEAT-109 — Telegram Integration Azure SSO via Navigator
**Spec**: `sdd/specs/telegram-integration-basicauth.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-764, TASK-765
**Assigned-to**: unassigned

---

## Context

> Implements Module 3 from the spec. The wrapper's strategy factory (in
> `__init__`) must recognize `auth_method: "azure"` and instantiate
> `AzureAuthStrategy`. The `handle_login` method must show Azure-specific
> prompt text when the strategy is Azure.

---

## Scope

- Add `"azure"` case to the strategy factory in `TelegramAgentWrapper.__init__()` (lines 88-94)
- Add Azure-specific prompt text in `handle_login()` (lines 868-879)
- Import `AzureAuthStrategy` at the top of wrapper.py
- Write unit tests for factory creation and prompt text

**NOT in scope**: AzureAuthStrategy implementation (TASK-765), config model (TASK-764), HTML page (TASK-767)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py` | MODIFY | Add azure case to factory, azure prompt text, import |
| `packages/ai-parrot/tests/integrations/telegram/test_azure_wrapper.py` | CREATE | Unit tests for wrapper integration |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Existing imports in wrapper.py that are relevant:
import json       # verified: wrapper.py top
import secrets    # verified: wrapper.py top (used in handle_login line 859)

# Auth strategies currently imported in wrapper.py:
from parrot.integrations.telegram.auth import (
    BasicAuthStrategy,     # verified: wrapper.py imports
    OAuth2AuthStrategy,    # verified: wrapper.py imports
    TelegramUserSession,   # verified: wrapper.py imports
)
# AzureAuthStrategy will be added to this import
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py

class TelegramAgentWrapper:  # line 50
    def __init__(
        self,
        agent: 'AbstractBot',
        bot: Bot,
        config: TelegramAgentConfig,
        agent_commands: list = None,
    ):  # line 68
        # ... setup ...

        # Auth strategy (Basic or OAuth2, depending on config) — lines 87-94:
        self._auth_strategy = None
        if config.auth_method == "oauth2" and config.oauth2_client_id:
            self._auth_strategy = OAuth2AuthStrategy(config)
        elif config.auth_url:
            self._auth_strategy = BasicAuthStrategy(
                config.auth_url, config.login_page_url
            )

    async def handle_login(self, message: Message) -> None:  # line 837
        # ... auth check, strategy check ...
        state = secrets.token_urlsafe(32)  # line 859
        keyboard = await self._auth_strategy.build_login_keyboard(
            self.config, state
        )  # line 861-863

        # Prompt text selection — lines 868-879:
        if self.config.auth_method == "oauth2":
            provider = self.config.oauth2_provider.capitalize()
            prompt_text = (
                f"\U0001f510 *{provider} Authentication*\n\n"
                f"Tap the button below to sign in with {provider}."
            )
        else:
            prompt_text = (
                "\U0001f510 *Navigator Authentication*\n\n"
                "Tap the button below to sign in with your Navigator credentials."
            )
```

```python
# packages/ai-parrot/src/parrot/integrations/telegram/models.py
# After TASK-764, TelegramAgentConfig will have:
@dataclass
class TelegramAgentConfig:
    auth_method: str = "basic"  # "basic" | "oauth2" | "azure"
    auth_url: Optional[str] = None
    azure_auth_url: Optional[str] = None  # NEW from TASK-764
    login_page_url: Optional[str] = None
```

### Does NOT Exist
- ~~`TelegramAgentWrapper._create_auth_strategy()`~~ — no such method; factory is inline in `__init__`
- ~~`TelegramAgentWrapper.auth_strategy`~~ (public) — the attribute is `_auth_strategy` (private)

---

## Implementation Notes

### Strategy Factory Change
```python
# In __init__, replace lines 87-94 with:
self._auth_strategy = None
if config.auth_method == "azure" and config.azure_auth_url:
    self._auth_strategy = AzureAuthStrategy(
        auth_url=config.auth_url or config.azure_auth_url,
        azure_auth_url=config.azure_auth_url,
        login_page_url=config.login_page_url,
    )
elif config.auth_method == "oauth2" and config.oauth2_client_id:
    self._auth_strategy = OAuth2AuthStrategy(config)
elif config.auth_url:
    self._auth_strategy = BasicAuthStrategy(
        config.auth_url, config.login_page_url
    )
```

**IMPORTANT**: Azure case must come BEFORE oauth2 check. Order: azure → oauth2 → basic.

### Prompt Text Change
```python
# In handle_login, add azure case before the oauth2 check:
if self.config.auth_method == "azure":
    prompt_text = (
        "\U0001f510 *Azure SSO*\n\n"
        "Tap the button below to sign in with your organization's Azure account."
    )
elif self.config.auth_method == "oauth2":
    # ... existing oauth2 prompt ...
else:
    # ... existing basic prompt ...
```

### Key Constraints
- Must not break existing Basic Auth or OAuth2 flows
- Import `AzureAuthStrategy` alongside existing strategy imports
- Azure check uses `config.azure_auth_url` (set by TASK-764's `__post_init__` derivation)

### References in Codebase
- `packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py:88-94` — current strategy factory
- `packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py:868-879` — current prompt text logic

---

## Acceptance Criteria

- [ ] `auth_method="azure"` creates `AzureAuthStrategy` in wrapper
- [ ] `handle_login` shows Azure-specific prompt text
- [ ] Existing `auth_method="basic"` still creates `BasicAuthStrategy`
- [ ] Existing `auth_method="oauth2"` still creates `OAuth2AuthStrategy`
- [ ] No breaking changes to existing handler registration or behavior
- [ ] All tests pass: `pytest packages/ai-parrot/tests/integrations/telegram/test_azure_wrapper.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/integrations/telegram/test_azure_wrapper.py
import pytest
from unittest.mock import MagicMock, AsyncMock
from parrot.integrations.telegram.auth import (
    AzureAuthStrategy, BasicAuthStrategy, OAuth2AuthStrategy,
)
from parrot.integrations.telegram.models import TelegramAgentConfig


class TestStrategyFactory:
    def _make_wrapper_strategy(self, config):
        """Extract just the strategy selection logic without full wrapper init."""
        # Replicate the factory logic to test it in isolation
        if config.auth_method == "azure" and config.azure_auth_url:
            from parrot.integrations.telegram.auth import AzureAuthStrategy
            return AzureAuthStrategy(
                auth_url=config.auth_url or config.azure_auth_url,
                azure_auth_url=config.azure_auth_url,
                login_page_url=config.login_page_url,
            )
        elif config.auth_method == "oauth2" and config.oauth2_client_id:
            return "oauth2"  # placeholder — just testing selection
        elif config.auth_url:
            return BasicAuthStrategy(config.auth_url, config.login_page_url)
        return None

    def test_azure_config_creates_azure_strategy(self):
        config = TelegramAgentConfig(
            name="Test", chatbot_id="test", bot_token="t:k",
            auth_method="azure",
            auth_url="https://nav.example.com/api/v1/auth/login",
            azure_auth_url="https://nav.example.com/api/v1/auth/azure/",
            login_page_url="https://static.example.com/azure_login.html",
        )
        strategy = self._make_wrapper_strategy(config)
        assert isinstance(strategy, AzureAuthStrategy)

    def test_basic_config_creates_basic_strategy(self):
        config = TelegramAgentConfig(
            name="Test", chatbot_id="test", bot_token="t:k",
            auth_url="https://nav.example.com/api/v1/auth/login",
            login_page_url="https://static.example.com/login.html",
        )
        strategy = self._make_wrapper_strategy(config)
        assert isinstance(strategy, BasicAuthStrategy)

    def test_no_auth_returns_none(self):
        config = TelegramAgentConfig(
            name="Test", chatbot_id="test", bot_token="t:k",
        )
        strategy = self._make_wrapper_strategy(config)
        assert strategy is None

    def test_azure_without_url_falls_through(self):
        """auth_method=azure but no azure_auth_url falls to basic if auth_url set."""
        config = TelegramAgentConfig(
            name="Test", chatbot_id="test", bot_token="t:k",
            auth_method="azure",
            auth_url="https://nav.example.com/api/v1/auth/login",
            login_page_url="https://static.example.com/login.html",
        )
        # After TASK-764, __post_init__ derives azure_auth_url from auth_url
        # so this should actually create AzureAuthStrategy
        strategy = self._make_wrapper_strategy(config)
        assert isinstance(strategy, AzureAuthStrategy)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/telegram-integration-basicauth.spec.md` for full context
2. **Check dependencies** — verify TASK-764 and TASK-765 are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — `read` wrapper.py lines 86-94 and 868-879
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
5. **Implement** the wrapper changes (import, factory, prompt text)
6. **Write tests** in test_azure_wrapper.py
7. **Run**: `pytest packages/ai-parrot/tests/integrations/telegram/test_azure_wrapper.py -v`
8. **Also run existing tests** to verify no regression: `pytest packages/ai-parrot/tests/integrations/telegram/ -v`
9. **Move this file** to `sdd/tasks/completed/`
10. **Update index** → `"done"`

---

## Completion Note

**Completed by**: claude-sonnet-4-6
**Date**: 2026-04-19
**Notes**: Added AzureAuthStrategy import, azure case to strategy factory (before oauth2), and azure prompt text to handle_login. 9 tests pass.

**Deviations from spec**: none
