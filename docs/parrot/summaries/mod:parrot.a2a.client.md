---
type: Wiki Summary
title: parrot.a2a.client
id: mod:parrot.a2a.client
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: A2A Client - Connect to remote A2A agents from AI-Parrot.
relates_to:
- concept: class:parrot.a2a.client.A2AAgentConnection
  rel: defines
- concept: class:parrot.a2a.client.A2AClient
  rel: defines
- concept: class:parrot.a2a.client.A2ARemoteAgentInput
  rel: defines
- concept: class:parrot.a2a.client.A2ARemoteAgentTool
  rel: defines
- concept: class:parrot.a2a.client.A2ARemoteSkillTool
  rel: defines
- concept: mod:parrot.a2a.models
  rel: references
- concept: mod:parrot.tools.abstract
  rel: references
---

# `parrot.a2a.client`

A2A Client - Connect to remote A2A agents from AI-Parrot.

## Classes

- **`A2AAgentConnection`** — Represents a connection to a remote A2A agent.
- **`A2AClient`** — Client for communicating with remote A2A agents.
- **`A2ARemoteAgentInput(AbstractToolArgsSchema)`** — Input schema for A2A remote agent tool.
- **`A2ARemoteAgentTool(AbstractTool)`** — Wraps a remote A2A agent as a tool that can be used by local agents.
- **`A2ARemoteSkillTool(AbstractTool)`** — Wraps a specific skill from a remote A2A agent as a tool.
