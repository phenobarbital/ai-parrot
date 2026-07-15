---
type: Wiki Summary
title: parrot.integrations.msteams.commands
id: mod:parrot.integrations.msteams.commands
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: MS Teams command routing infrastructure (FEAT-225).
relates_to:
- concept: class:parrot.integrations.msteams.commands.MSTeamsCommandRouter
  rel: defines
---

# `parrot.integrations.msteams.commands`

MS Teams command routing infrastructure (FEAT-225).

Provides ``MSTeamsCommandRouter``, which detects text commands in
``on_message_activity`` and dispatches them to registered handlers.

Usage::

    from parrot.integrations.msteams.commands import MSTeamsCommandRouter
    from parrot.integrations.msteams.commands.jira_commands import register_jira_commands

    router = MSTeamsCommandRouter()
    register_jira_commands(router, oauth_manager)

    # In on_message_activity:
    handled = await router.try_dispatch(text, turn_context)
    if handled:
        return  # skip agent processing

## Classes

- **`MSTeamsCommandRouter`** — Detects and routes text commands in ``on_message_activity``.
