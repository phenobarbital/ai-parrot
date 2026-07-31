---
type: Wiki Summary
title: parrot.integrations.slack.commands
id: mod:parrot.integrations.slack.commands
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Slack command routing infrastructure (FEAT-225).
relates_to:
- concept: class:parrot.integrations.slack.commands.SlackCommandRouter
  rel: defines
---

# `parrot.integrations.slack.commands`

Slack command routing infrastructure (FEAT-225).

Provides ``SlackCommandRouter``, a simple registry that decouples slash-command
dispatch from ``SlackAgentWrapper`` and ``SlackSocketHandler``.

Usage::

    from parrot.integrations.slack.commands import SlackCommandRouter
    from parrot.integrations.slack.commands.jira_commands import register_jira_commands

    router = SlackCommandRouter()
    register_jira_commands(router, oauth_manager)

    # In the command handler:
    result = await router.dispatch("connect_jira", payload)
    if result is not None:
        return web.json_response(result)

## Classes

- **`SlackCommandRouter`** — Routes slash commands to registered async handler functions.
