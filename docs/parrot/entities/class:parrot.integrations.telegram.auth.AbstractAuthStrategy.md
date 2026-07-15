---
type: Wiki Entity
title: AbstractAuthStrategy
id: class:parrot.integrations.telegram.auth.AbstractAuthStrategy
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Base class for Telegram authentication strategies.
---

# AbstractAuthStrategy

Defined in [`parrot.integrations.telegram.auth`](../summaries/mod:parrot.integrations.telegram.auth.md).

```python
class AbstractAuthStrategy(ABC)
```

Base class for Telegram authentication strategies.

Each strategy knows how to:
- Build a login keyboard (WebApp button) for the Telegram user.
- Handle the callback data returned from the WebApp.
- Validate an existing session token.

Class Attributes:
    name: Canonical short name used in callback payloads and YAML config.
        Subclasses must override this.
    supports_post_auth_chain: Whether this strategy can carry a post-auth
        redirect chain (e.g., for Jira OAuth2 after BasicAuth). Subclasses
        that support the chain must set this to True.

## Methods

- `async def build_login_keyboard(self, config: Any, state: str, *, next_auth_url: Optional[str]=None, next_auth_required: bool=False) -> ReplyKeyboardMarkup` — Return the keyboard markup with the login button/WebApp.
- `async def handle_callback(self, data: Dict[str, Any], session: TelegramUserSession) -> bool` — Process auth callback data returned from the WebApp.
- `async def validate_token(self, token: str) -> bool` — Validate an existing session token.
