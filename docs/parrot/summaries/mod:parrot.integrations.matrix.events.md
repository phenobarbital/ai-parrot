---
type: Wiki Summary
title: parrot.integrations.matrix.events
id: mod:parrot.integrations.matrix.events
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Custom Matrix event types for AI-Parrot (m.parrot.* namespace).
relates_to:
- concept: class:parrot.integrations.matrix.events.AgentCardEventContent
  rel: defines
- concept: class:parrot.integrations.matrix.events.ParrotEventType
  rel: defines
- concept: class:parrot.integrations.matrix.events.ResultEventContent
  rel: defines
- concept: class:parrot.integrations.matrix.events.StatusEventContent
  rel: defines
- concept: class:parrot.integrations.matrix.events.TaskEventContent
  rel: defines
---

# `parrot.integrations.matrix.events`

Custom Matrix event types for AI-Parrot (m.parrot.* namespace).

These events extend the Matrix protocol to support agent-to-agent
communication, task lifecycle, and streaming within Matrix rooms.

## Classes

- **`ParrotEventType`** — Matrix event type constants for AI-Parrot.
- **`AgentCardEventContent(BaseModel)`** — Content of m.parrot.agent_card state event.
- **`TaskEventContent(BaseModel)`** — Content of m.parrot.task message event.
- **`ResultEventContent(BaseModel)`** — Content of m.parrot.result message event.
- **`StatusEventContent(BaseModel)`** — Content of m.parrot.status message event.
