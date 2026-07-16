---
type: Wiki Summary
title: parrot.core.events.lifecycle.yaml_loader
id: mod:parrot.core.events.lifecycle.yaml_loader
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: YAML declarative events block parser and wiring helper.
relates_to:
- concept: func:parrot.core.events.lifecycle.yaml_loader.wire_events
  rel: defines
- concept: mod:parrot.core.events.lifecycle.base
  rel: references
- concept: mod:parrot.core.events.lifecycle.events
  rel: references
- concept: mod:parrot.core.events.lifecycle.registry
  rel: references
---

# `parrot.core.events.lifecycle.yaml_loader`

YAML declarative events block parser and wiring helper.

FEAT-176 — Lifecycle Events System (TASK-1196).

Allows agent YAML definitions to declare lifecycle event subscribers inline::

    events:
      forward_to_global: false
      subscribers:
        - handler: mypackage.callbacks:on_tool_call
          events: [BeforeToolCallEvent, AfterToolCallEvent]
          where:
            tool_name: [jira_create_issue, jira_update_issue]
          forward_to_bus: false
        - provider: mypackage.providers:MyProvider
          config:
            endpoint: "https://hooks.example.com"

## Functions

- `def wire_events(bot: Any, events_block: Optional[dict]) -> None` — Apply a parsed YAML ``events:`` block to the bot's event registry.
