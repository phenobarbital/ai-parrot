---
type: Wiki Summary
title: parrot.integrations.telegram.crew.coordinator
id: mod:parrot.integrations.telegram.crew.coordinator
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: CoordinatorBot — manages the pinned registry message in a crew supergroup.
relates_to:
- concept: class:parrot.integrations.telegram.crew.coordinator.CoordinatorBot
  rel: defines
- concept: mod:parrot.integrations.telegram.crew.agent_card
  rel: references
- concept: mod:parrot.integrations.telegram.crew.registry
  rel: references
---

# `parrot.integrations.telegram.crew.coordinator`

CoordinatorBot — manages the pinned registry message in a crew supergroup.

The CoordinatorBot is a non-agent bot that maintains a pinned message
showing which agents are online, busy, or offline. It provides real-time
visibility of the crew's collective state.

## Classes

- **`CoordinatorBot`** — Non-agent bot that manages the pinned registry message.
