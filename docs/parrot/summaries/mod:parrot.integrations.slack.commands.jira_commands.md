---
type: Wiki Summary
title: parrot.integrations.slack.commands.jira_commands
id: mod:parrot.integrations.slack.commands.jira_commands
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Slack command handlers for the Jira OAuth 2.0 (3LO) flow (FEAT-225).
relates_to:
- concept: func:parrot.integrations.slack.commands.jira_commands.connect_jira_handler
  rel: defines
- concept: func:parrot.integrations.slack.commands.jira_commands.disconnect_jira_handler
  rel: defines
- concept: func:parrot.integrations.slack.commands.jira_commands.jira_status_handler
  rel: defines
- concept: func:parrot.integrations.slack.commands.jira_commands.register_jira_commands
  rel: defines
- concept: mod:parrot.auth.jira_oauth
  rel: references
- concept: mod:parrot.integrations.slack.commands
  rel: references
---

# `parrot.integrations.slack.commands.jira_commands`

Slack command handlers for the Jira OAuth 2.0 (3LO) flow (FEAT-225).

Exposes three user-facing slash commands:

- ``/connect_jira`` — generates a Jira authorization URL and returns an
  ephemeral message with a button linking to the consent page.
- ``/disconnect_jira`` — revokes the user's stored Jira tokens.
- ``/jira_status`` — reports whether a valid Jira connection is on file.

All handlers are registered on a :class:`SlackCommandRouter` via
:func:`register_jira_commands`.

User identity in ``JiraOAuthManager`` is keyed as
``f"{team_id}:{slack_user_id}"`` to be multi-workspace safe.

## Functions

- `async def connect_jira_handler(payload: Dict[str, Any], oauth_manager: 'JiraOAuthManager') -> Dict[str, Any]` — Handle ``/connect_jira`` slash command.
- `async def disconnect_jira_handler(payload: Dict[str, Any], oauth_manager: 'JiraOAuthManager') -> Dict[str, Any]` — Handle ``/disconnect_jira`` slash command.
- `async def jira_status_handler(payload: Dict[str, Any], oauth_manager: 'JiraOAuthManager') -> Dict[str, Any]` — Handle ``/jira_status`` slash command.
- `def register_jira_commands(router: 'SlackCommandRouter', oauth_manager: 'JiraOAuthManager') -> None` — Register the three Jira commands on *router*.
