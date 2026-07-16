---
type: Wiki Entity
title: BasicAuthStrategy
id: class:parrot.integrations.telegram.auth.BasicAuthStrategy
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Navigator Basic Auth strategy.
relates_to:
- concept: class:parrot.integrations.telegram.auth.AbstractAuthStrategy
  rel: extends
---

# BasicAuthStrategy

Defined in [`parrot.integrations.telegram.auth`](../summaries/mod:parrot.integrations.telegram.auth.md).

```python
class BasicAuthStrategy(AbstractAuthStrategy)
```

Navigator Basic Auth strategy.

Wraps the existing ``NavigatorAuthClient`` and produces the same WebApp
keyboard / callback handling that the wrapper used before the strategy
refactor.

Args:
    auth_url: Navigator authentication endpoint URL.
    login_page_url: URL of the static login HTML page served to the
        Telegram WebApp.

## Methods

- `async def build_login_keyboard(self, config: Any, state: str, *, next_auth_url: Optional[str]=None, next_auth_required: bool=False) -> ReplyKeyboardMarkup` — Build the Navigator login WebApp keyboard.
- `async def handle_callback(self, data: Dict[str, Any], session: TelegramUserSession) -> bool` — Handle Navigator login callback data.
- `async def validate_token(self, token: str) -> bool` — Validate a Navigator session token.
