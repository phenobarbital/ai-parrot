---
type: Wiki Entity
title: TelegramUserSession
id: class:parrot.integrations.telegram.auth.TelegramUserSession
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Cached identity for a Telegram user within a chat session.
---

# TelegramUserSession

Defined in [`parrot.integrations.telegram.auth`](../summaries/mod:parrot.integrations.telegram.auth.md).

```python
class TelegramUserSession
```

Cached identity for a Telegram user within a chat session.

## Methods

- `def user_id(self) -> str` — Return nav_user_id if authenticated, else telegram identifier.
- `def session_id(self) -> str` — Stable session key for conversation memory.
- `def display_name(self) -> str` — Human-readable name for display.
- `def set_authenticated(self, nav_user_id: str, session_token: str, display_name: Optional[str]=None, email: Optional[str]=None, **extra_meta) -> None` — Mark session as authenticated with Navigator credentials.
- `def set_jira_authenticated(self, account_id: str, email: Optional[str], display_name: Optional[str], cloud_id: Optional[str]=None) -> None` — Record successful Jira OAuth2 3LO connection on this session.
- `def clear_jira_auth(self) -> None` — Clear the Jira OAuth2 connection fields (disconnect).
- `def set_o365_authenticated(self, access_token: str, id_token: Optional[str], provider: Optional[str]) -> None` — Record a delegated Office365 connection for this Telegram session.
- `def clear_o365_auth(self) -> None` — Clear Office365 delegated auth fields (disconnect).
- `def clear_auth(self) -> None` — Clear authentication state (logout).
