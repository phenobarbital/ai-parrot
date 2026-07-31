---
type: Wiki Entity
title: GigSmartAuth
id: class:parrot_tools.interfaces.gigsmart.auth.GigSmartAuth
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: OAuth 2.1 token lifecycle manager for the GigSmart API.
---

# GigSmartAuth

Defined in [`parrot_tools.interfaces.gigsmart.auth`](../summaries/mod:parrot_tools.interfaces.gigsmart.auth.md).

```python
class GigSmartAuth
```

OAuth 2.1 token lifecycle manager for the GigSmart API.

Args:
    config: GigSmartConfig instance carrying client credentials and endpoints.

Example::

    auth = GigSmartAuth(config)
    token = await auth.get_token(scopes=["read:gigs"])
    headers = await auth.build_headers()

## Methods

- `async def get_token(self, scopes: list[str] | None=None) -> str` — Return a valid access token, refreshing proactively if needed.
- `async def build_headers(self) -> dict[str, str]` — Return HTTP headers with a valid Bearer token.
- `async def ensure_scope(self, scope: str) -> None` — Assert that the current token grants *scope*, raising otherwise.
- `async def refresh_token(self) -> str` — Force a token refresh using the cached refresh_token.
- `def generate_pkce_pair() -> tuple[str, str]` — Generate a PKCE ``(code_verifier, code_challenge)`` pair.
- `def build_authorize_url(self, redirect_uri: str, scopes: list[str], code_challenge: str, state: str | None=None) -> str` — Build the OAuth authorisation URL for the auth_code + PKCE flow.
- `async def exchange_code(self, code: str, redirect_uri: str, code_verifier: str) -> str` — Exchange an authorisation code for an access token (auth_code+PKCE).
- `async def close(self) -> None` — Close the persistent token-fetch session.
