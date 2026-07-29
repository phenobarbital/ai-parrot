---
type: Wiki Summary
title: parrot.core.hooks.whatsapp_redis
id: mod:parrot.core.hooks.whatsapp_redis
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: WhatsApp Redis Bridge Hook.
relates_to:
- concept: class:parrot.core.hooks.whatsapp_redis.WhatsAppRedisHook
  rel: defines
- concept: mod:parrot.core.hooks.base
  rel: references
- concept: mod:parrot.core.hooks.models
  rel: references
---

# `parrot.core.hooks.whatsapp_redis`

WhatsApp Redis Bridge Hook.

Listens to WhatsApp messages via Redis Pub/Sub (published by an external bridge)
and routes them to agents in AutonomousOrchestrator.

Based on BaseHook pattern for AI-Parrot.

## Classes

- **`WhatsAppRedisHook(BaseHook)`** — WhatsApp message listener via Redis Pub/Sub.
