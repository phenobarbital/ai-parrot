---
type: Wiki Entity
title: AbstractOAuth2Manager
id: class:parrot.auth.oauth2_base.AbstractOAuth2Manager
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: OAuth 2.0 lifecycle manager — provider-agnostic base.
---

# AbstractOAuth2Manager

Defined in [`parrot.auth.oauth2_base`](../summaries/mod:parrot.auth.oauth2_base.md).

```python
class AbstractOAuth2Manager(ABC)
```

OAuth 2.0 lifecycle manager — provider-agnostic base.

Subclasses must set the following class attributes:

- ``provider_id``: short, unique string (``"o365"``, ``"github"``, …).
- ``authorization_url``: the provider's consent URL.
- ``token_url``: the provider's token endpoint.
- ``default_scopes``: scopes to request by default.
- ``token_set_cls``: subclass of :class:`AbstractOAuth2TokenSet`.

And implement the four hooks:

- :meth:`_exchange_code` — code + verifier → raw token JSON.
- :meth:`_refresh_request` — refresh_token → raw token JSON.
- :meth:`_discover_identity` — access_token → identity dict.
- :meth:`_build_token_set` — raw token JSON + identity → token set.

## Methods

- `def setup(self) -> None` — Wire this manager into the aiohttp app passed at construction.
- `async def aclose(self) -> None` — Close the underlying aiohttp session if this manager owns it.
- `async def create_authorization_url(self, channel: str, user_id: str, extra_state: Optional[Dict[str, Any]]=None) -> Tuple[str, str]` — Generate a provider consent URL with a CSRF state nonce.
- `def authorization_url_extra_params(self) -> Dict[str, str]` — Provider hook for adding extra query params (e.g. ``prompt=consent``).
- `async def handle_callback(self, code: str, state: str) -> Tuple[AbstractOAuth2TokenSet, Dict[str, Any]]` — Validate state, exchange code for tokens, persist, return token+state.
- `async def get_valid_token(self, channel: str, user_id: str) -> Optional[AbstractOAuth2TokenSet]` — Return a non-expired token, hydrating from vault if cache is cold.
- `async def is_connected(self, channel: str, user_id: str) -> bool` — Cheap connectivity check — does not call the provider.
- `async def revoke(self, channel: str, user_id: str) -> None` — Delete the user's token from both vault and Redis.
