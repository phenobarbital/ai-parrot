---
type: Wiki Summary
title: parrot.storage.backends.dynamodb
id: mod:parrot.storage.backends.dynamodb
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: DynamoDB backend implementing ConversationBackend.
relates_to:
- concept: class:parrot.storage.backends.dynamodb.ConversationDynamoDB
  rel: defines
- concept: mod:parrot.storage.backends.base
  rel: references
---

# `parrot.storage.backends.dynamodb`

DynamoDB backend implementing ConversationBackend.

Moved from parrot/storage/dynamodb.py in FEAT-116. Behavior is byte-identical
to the original; the only additions are:
  - Subclass of ``ConversationBackend`` ABC.
  - New ``delete_turn()`` method (extracted from ``chat.py:572-582``).
  - Override of ``build_overflow_prefix()`` to preserve existing S3 key layout.

FEAT-116: dynamodb-fallback-redis — Module 3 (ConversationDynamoDB refactor).

## Classes

- **`ConversationDynamoDB(ConversationBackend)`** — Domain wrapper around DynamoDB for conversation storage.
