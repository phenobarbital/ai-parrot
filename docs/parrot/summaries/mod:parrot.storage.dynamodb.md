---
type: Wiki Summary
title: parrot.storage.dynamodb
id: mod:parrot.storage.dynamodb
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Backward-compatible re-export shim for ConversationDynamoDB.
relates_to:
- concept: mod:parrot.storage.backends.dynamodb
  rel: references
---

# `parrot.storage.dynamodb`

Backward-compatible re-export shim for ConversationDynamoDB.

The class was moved to parrot.storage.backends.dynamodb in FEAT-116.
This shim is kept for one release cycle to avoid breaking existing imports.

FEAT-116: dynamodb-fallback-redis — Module 3 (re-export shim).
