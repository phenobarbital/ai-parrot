---
type: Wiki Summary
title: parrot.cli.loaders
id: mod:parrot.cli.loaders
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Agent loading strategies for the AI-Parrot CLI REPL.
relates_to:
- concept: class:parrot.cli.loaders.AgentLoadError
  rel: defines
- concept: class:parrot.cli.loaders.ServerAgentProxy
  rel: defines
- concept: class:parrot.cli.loaders.StandaloneAgentLoader
  rel: defines
- concept: mod:parrot.bots.abstract
  rel: references
- concept: mod:parrot.registry
  rel: references
- concept: mod:parrot.registry.registry
  rel: references
---

# `parrot.cli.loaders`

Agent loading strategies for the AI-Parrot CLI REPL.

Provides two loading strategies:

- ``StandaloneAgentLoader`` — loads agents from the in-process
  ``AgentRegistry`` without requiring a running server.
- ``ServerAgentProxy`` — proxies agent interactions to a running
  AI-Parrot server via HTTP.

## Classes

- **`AgentLoadError(Exception)`** — Raised when an agent cannot be loaded.
- **`StandaloneAgentLoader`** — Load agents from the in-process AgentRegistry.
- **`ServerAgentProxy`** — Proxy agent interactions to a running AI-Parrot server via HTTP.
