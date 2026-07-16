---
type: Wiki Summary
title: parrot.storage.chat
id: mod:parrot.storage.chat
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Unified hot+cold chat storage.
relates_to:
- concept: class:parrot.storage.chat.ChatStorage
  rel: defines
- concept: mod:parrot.memory
  rel: references
- concept: mod:parrot.memory.abstract
  rel: references
- concept: mod:parrot.storage.backends
  rel: references
- concept: mod:parrot.storage.models
  rel: references
---

# `parrot.storage.chat`

Unified hot+cold chat storage.

Redis (via RedisConversation) for fast access to recent turns.
DynamoDB (via ConversationDynamoDB) for permanent history, search, and analytics.

FEAT-103: Migrated from DocumentDB to DynamoDB.

## Classes

- **`ChatStorage`** — Unified chat persistence with Redis hot cache and DynamoDB cold storage.
