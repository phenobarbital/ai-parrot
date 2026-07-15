---
type: Wiki Summary
title: parrot.core.events.lifecycle.events.agent
id: mod:parrot.core.events.lifecycle.events.agent
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Agent lifecycle events.
relates_to:
- concept: class:parrot.core.events.lifecycle.events.agent.AgentConfiguredEvent
  rel: defines
- concept: class:parrot.core.events.lifecycle.events.agent.AgentInitializedEvent
  rel: defines
- concept: class:parrot.core.events.lifecycle.events.agent.AgentStatusChangedEvent
  rel: defines
- concept: class:parrot.core.events.lifecycle.events.agent.ToolManagerReadyEvent
  rel: defines
- concept: mod:parrot.core.events.lifecycle.base
  rel: references
---

# `parrot.core.events.lifecycle.events.agent`

Agent lifecycle events.

FEAT-176 — Lifecycle Events System.

Covers: agent initialization, configuration, tool-manager readiness,
and status changes.

## Classes

- **`AgentInitializedEvent(LifecycleEvent)`** — Emitted at the end of AbstractBot.__init__.
- **`AgentConfiguredEvent(LifecycleEvent)`** — Emitted at the end of AbstractBot.configure().
- **`ToolManagerReadyEvent(LifecycleEvent)`** — Emitted after the ToolManager is fully populated.
- **`AgentStatusChangedEvent(LifecycleEvent)`** — Emitted when the agent's status property changes.
