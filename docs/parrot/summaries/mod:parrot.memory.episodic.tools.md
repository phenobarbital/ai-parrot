---
type: Wiki Summary
title: parrot.memory.episodic.tools
id: mod:parrot.memory.episodic.tools
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Agent-usable tools for episodic memory.
relates_to:
- concept: class:parrot.memory.episodic.tools.EpisodicMemoryToolkit
  rel: defines
- concept: mod:parrot.memory.episodic.models
  rel: references
- concept: mod:parrot.memory.episodic.store
  rel: references
- concept: mod:parrot.tools.toolkit
  rel: references
---

# `parrot.memory.episodic.tools`

Agent-usable tools for episodic memory.

Exposes episodic memory operations as agent-callable tools via AbstractToolkit.
LLM agents can search past experiences, record lessons, and retrieve warnings
during their reasoning loop.

## Classes

- **`EpisodicMemoryToolkit(AbstractToolkit)`** — Toolkit exposing episodic memory as agent-callable tools.
