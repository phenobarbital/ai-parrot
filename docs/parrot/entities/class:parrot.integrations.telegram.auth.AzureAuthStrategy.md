---
type: Wiki Entity
title: AzureAuthStrategy
id: class:parrot.integrations.telegram.auth.AzureAuthStrategy
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Navigator Azure AD SSO strategy.
relates_to:
- concept: class:parrot.integrations.telegram.auth.AbstractAuthStrategy
  rel: extends
---

# AzureAuthStrategy

Defined in [`parrot.integrations.telegram.auth`](../summaries/mod:parrot.integrations.telegram.auth.md).

```python
class AzureAuthStrategy(AbstractAuthStrategy)
```

Navigator Azure AD SSO strategy.

Delegates the full OAuth2 flow to Navigator's /api/v1/auth/azure/ endpoint.
The bot only captures the JWT token returned via redirect. No signature
verification is performed; Navigator is the trusted issuer.

Args:
    auth_url: Navigator base authentication endpoint URL (used for token
        validation via NavigatorAuthClient).
    azure_auth_url: Navigator's Azure SSO endpoint URL.
        E.g. ``https://nav.example.com/api/v1/auth/azure/``.
    login_page_url: URL of the static ``azure_login.html`` page served
        to the Telegram WebApp.
    post_auth_registry: Optional ``PostAuthRegistry`` injected at
        construction time (Approach A). When provided and non-empty,
        ``handle_callback`` invokes the chain providers after the JWT
        is successfully validated. When ``None`` (default) or empty, the
        strategy behaves as before FEAT-109.

## Methods

- `async def build_login_keyboard(self, config: Any, state: str, *, next_auth_url: Optional[str]=None, next_auth_required: bool=False) -> ReplyKeyboardMarkup` — Build the Azure SSO WebApp keyboard.
- `async def handle_callback(self, data: Dict[str, Any], session: TelegramUserSession) -> bool` — Process Azure SSO callback: decode JWT and populate session.
- `async def validate_token(self, token: str, session: Optional['TelegramUserSession']=None) -> bool` — Validate a Navigator JWT token, enforcing the 4-day session TTL.
