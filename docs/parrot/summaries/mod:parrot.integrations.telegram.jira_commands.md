---
type: Wiki Summary
title: parrot.integrations.telegram.jira_commands
id: mod:parrot.integrations.telegram.jira_commands
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Telegram command handlers for the Jira OAuth 2.0 (3LO) flow.
relates_to:
- concept: class:parrot.integrations.telegram.jira_commands.TelegramOAuthNotifier
  rel: defines
- concept: func:parrot.integrations.telegram.jira_commands.connect_jira_handler
  rel: defines
- concept: func:parrot.integrations.telegram.jira_commands.disconnect_jira_handler
  rel: defines
- concept: func:parrot.integrations.telegram.jira_commands.jira_status_handler
  rel: defines
- concept: func:parrot.integrations.telegram.jira_commands.register_jira_commands
  rel: defines
- concept: mod:parrot.auth.jira_oauth
  rel: references
---

# `parrot.integrations.telegram.jira_commands`

Telegram command handlers for the Jira OAuth 2.0 (3LO) flow.

Exposes three user-facing bot commands:

- ``/connect_jira`` — generates a Jira authorization URL and sends it as
  an inline button.  Clicking the button opens Atlassian's consent page in
  the user's default browser; after consent Atlassian redirects back to
  AI-Parrot's OAuth callback (see ``parrot.auth.routes``).
- ``/disconnect_jira`` — revokes the user's stored Jira tokens.
- ``/jira_status`` — reports whether a valid Jira connection is on file
  and, if so, the display name and site URL.

A ``TelegramOAuthNotifier`` helper is also exported so the OAuth callback
route can push a confirmation message back to the originating chat.

## Classes

- **`TelegramOAuthNotifier`** — Push a confirmation message to the originating Telegram chat after

## Functions

- `async def connect_jira_handler(message: Message, oauth_manager: 'JiraOAuthManager') -> None` — Handle ``/connect_jira`` — send the authorization URL or a status.
- `async def disconnect_jira_handler(message: Message, oauth_manager: 'JiraOAuthManager', session_clearer: Optional[SessionClearer]=None) -> None` — Handle ``/disconnect_jira`` — revoke stored tokens and clear session.
- `async def jira_status_handler(message: Message, oauth_manager: 'JiraOAuthManager') -> None` — Handle ``/jira_status`` — report the user's Jira connection state.
- `def register_jira_commands(router: Router, oauth_manager: 'JiraOAuthManager', session_clearer: Optional[SessionClearer]=None) -> None` — Register the three Jira commands on *router*.
