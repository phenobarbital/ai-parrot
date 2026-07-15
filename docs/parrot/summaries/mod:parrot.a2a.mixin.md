---
type: Wiki Summary
title: parrot.a2a.mixin
id: mod:parrot.a2a.mixin
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: A2A Client Mixin - Add A2A client capabilities to AI-Parrot agents.
relates_to:
- concept: class:parrot.a2a.mixin.A2AClientMixin
  rel: defines
- concept: mod:parrot.a2a.client
  rel: references
- concept: mod:parrot.a2a.mesh
  rel: references
- concept: mod:parrot.a2a.models
  rel: references
- concept: mod:parrot.a2a.orchestrator
  rel: references
- concept: mod:parrot.a2a.router
  rel: references
---

# `parrot.a2a.mixin`

A2A Client Mixin - Add A2A client capabilities to AI-Parrot agents.

This mixin enables agents to:
- Connect to remote A2A agents directly
- Discover agents from a centralized mesh
- Use remote agents as callable tools
- Integrate with Router and Orchestrator for complex workflows

## Classes

- **`A2AClientMixin`** — Mixin to add A2A client capabilities to any AbstractBot.
