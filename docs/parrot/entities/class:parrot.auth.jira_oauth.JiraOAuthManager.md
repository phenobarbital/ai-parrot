---
type: Wiki Entity
title: JiraOAuthManager
id: class:parrot.auth.jira_oauth.JiraOAuthManager
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: OAuth 2.0 (3LO) lifecycle manager for Jira Cloud.
---

# JiraOAuthManager

Defined in [`parrot.auth.jira_oauth`](../summaries/mod:parrot.auth.jira_oauth.md).

```python
class JiraOAuthManager
```

OAuth 2.0 (3LO) lifecycle manager for Jira Cloud.

The manager exposes primitives for starting an authorization flow,
exchanging codes for tokens, reading valid tokens from Redis (with
transparent refresh), and revoking a user's tokens.

## Methods

- `def setup(self) -> None` — Wire this manager into the aiohttp app passed at construction.
- `async def create_authorization_url(self, channel: str, user_id: str, extra_state: Optional[Dict[str, Any]]=None) -> Tuple[str, str]` — Generate an Atlassian consent URL with a CSRF state nonce.
- `async def handle_callback(self, code: str, state: str) -> Tuple[JiraTokenSet, Dict[str, Any]]` — Process the OAuth callback: validate state, exchange code, store.
- `async def consume_state(self, state: str) -> Dict[str, Any]` — Resolve and delete a one-time CSRF state nonce.
- `async def get_valid_token(self, channel: str, user_id: str) -> Optional[JiraTokenSet]` — Return a non-expired token, refreshing it transparently if needed.
- `async def is_connected(self, channel: str, user_id: str) -> bool` — Return True when a valid token is available for the user.
- `async def validate_token(self, channel: str, user_id: str) -> Optional[JiraTokenSet]` — Return the stored token only if Atlassian still accepts it.
- `async def revoke(self, channel: str, user_id: str) -> None` — Delete the user's token from Redis.
- `async def aclose(self) -> None` — Close the underlying aiohttp session if this manager owns it.
