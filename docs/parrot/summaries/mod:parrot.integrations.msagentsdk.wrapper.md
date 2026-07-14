---
type: Wiki Summary
title: parrot.integrations.msagentsdk.wrapper
id: mod:parrot.integrations.msagentsdk.wrapper
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Integration wrapper for the Microsoft 365 Agents SDK.
relates_to:
- concept: class:parrot.integrations.msagentsdk.wrapper.MSAgentSDKWrapper
  rel: defines
- concept: mod:parrot.auth.audit
  rel: references
- concept: mod:parrot.auth.broker
  rel: references
- concept: mod:parrot.auth.identity
  rel: references
- concept: mod:parrot.bots.abstract
  rel: references
- concept: mod:parrot.integrations.msagentsdk._patches
  rel: references
- concept: mod:parrot.integrations.msagentsdk.agent
  rel: references
- concept: mod:parrot.integrations.msagentsdk.auth
  rel: references
- concept: mod:parrot.integrations.msagentsdk.models
  rel: references
---

# `parrot.integrations.msagentsdk.wrapper`

Integration wrapper for the Microsoft 365 Agents SDK.

Owns the CloudAdapter lifecycle, registers the per-bot HTTP route on the
aiohttp application, and bridges incoming HTTP requests to
``ParrotM365Agent.on_turn()``.

## Classes

- **`MSAgentSDKWrapper`** — ai-parrot integration wrapper for the Microsoft 365 Agents SDK.
