---
type: Wiki Entity
title: OAuth2AuthStrategy
id: class:parrot.integrations.telegram.auth.OAuth2AuthStrategy
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: OAuth2 Authorization Code strategy with PKCE.
relates_to:
- concept: class:parrot.integrations.telegram.auth.AbstractAuthStrategy
  rel: extends
---

# OAuth2AuthStrategy

Defined in [`parrot.integrations.telegram.auth`](../summaries/mod:parrot.integrations.telegram.auth.md).

```python
class OAuth2AuthStrategy(AbstractAuthStrategy)
```

OAuth2 Authorization Code strategy with PKCE.

Handles the full OAuth2 flow:
1. Build an authorization URL (with PKCE code_challenge).
2. After the user authenticates, exchange the code for tokens.
3. Fetch user profile from the provider's userinfo endpoint.

Args:
    config: TelegramAgentConfig with OAuth2 settings populated.

## Methods

- `async def build_login_keyboard(self, config: Any, state: str, *, next_auth_url: Optional[str]=None, next_auth_required: bool=False) -> ReplyKeyboardMarkup` — Build the OAuth2 authorization keyboard.
- `async def handle_callback(self, data: Dict[str, Any], session: TelegramUserSession) -> bool` — Handle the OAuth2 callback from Telegram WebApp.
- `async def validate_token(self, token: str, session: Optional[TelegramUserSession]=None) -> bool` — Check that the token is non-empty and the session hasn't exceeded the 7-day TTL.
- `def is_session_expired(self, session: TelegramUserSession) -> bool` — Check if a session's authentication has exceeded the 7-day TTL.
- `async def exchange_code(self, code: str, code_verifier: str) -> Optional[Dict[str, Any]]` — Exchange an authorization code for tokens.
- `async def fetch_userinfo(self, access_token: str) -> Optional[Dict[str, Any]]` — Fetch user profile from the provider's userinfo endpoint.
