---
type: Wiki Summary
title: parrot.integrations.msteams.commands.jira_commands
id: mod:parrot.integrations.msteams.commands.jira_commands
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: MS Teams command handlers for the Jira OAuth 2.0 (3LO) flow (FEAT-225).
relates_to:
- concept: func:parrot.integrations.msteams.commands.jira_commands.connect_jira_handler
  rel: defines
- concept: func:parrot.integrations.msteams.commands.jira_commands.disconnect_jira_handler
  rel: defines
- concept: func:parrot.integrations.msteams.commands.jira_commands.jira_menu_handler
  rel: defines
- concept: func:parrot.integrations.msteams.commands.jira_commands.jira_status_handler
  rel: defines
- concept: func:parrot.integrations.msteams.commands.jira_commands.register_jira_commands
  rel: defines
- concept: mod:parrot.auth.jira_oauth
  rel: references
- concept: mod:parrot.integrations.msteams.commands
  rel: references
---

# `parrot.integrations.msteams.commands.jira_commands`

MS Teams command handlers for the Jira OAuth 2.0 (3LO) flow (FEAT-225).

Exposes three user-facing text commands:

- ``/connect_jira`` — generates a Jira authorization URL and sends an
  Adaptive Card with a "Connect Jira" button.
- ``/disconnect_jira`` — revokes the user's stored Jira tokens.
- ``/jira_status`` — reports whether a valid Jira connection is on file.
- ``jira`` / ``integrations`` — shows an Adaptive Card menu for Jira commands.

User identity is the ``aad_object_id`` (Azure AD object ID), falling back to
``from_property.id`` for non-AAD environments.

The ``conversation_reference`` is stored in ``extra_state`` so the OAuth
callback can send a proactive message after the user returns from Atlassian.

## Functions

- `async def connect_jira_handler(turn_context: 'TurnContext', oauth_manager: 'JiraOAuthManager') -> None` — Handle ``/connect_jira`` text command.
- `async def disconnect_jira_handler(turn_context: 'TurnContext', oauth_manager: 'JiraOAuthManager') -> None` — Handle ``/disconnect_jira`` text command.
- `async def jira_status_handler(turn_context: 'TurnContext', oauth_manager: 'JiraOAuthManager') -> None` — Handle ``/jira_status`` text command.
- `async def jira_menu_handler(turn_context: 'TurnContext', oauth_manager: 'JiraOAuthManager') -> None` — Show a discoverability menu with all Jira commands.
- `def register_jira_commands(router: 'MSTeamsCommandRouter', oauth_manager: 'JiraOAuthManager') -> None` — Register Jira commands on *router*.
