---
type: Wiki Summary
title: parrot.integrations.slack.dedup
id: mod:parrot.integrations.slack.dedup
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Event deduplication for Slack integration.
relates_to:
- concept: class:parrot.integrations.slack.dedup.EventDeduplicator
  rel: defines
- concept: class:parrot.integrations.slack.dedup.EventDeduplicatorProtocol
  rel: defines
- concept: class:parrot.integrations.slack.dedup.RedisEventDeduplicator
  rel: defines
---

# `parrot.integrations.slack.dedup`

Event deduplication for Slack integration.

Slack retries event delivery if it doesn't receive HTTP 200 within ~3 seconds.
Without deduplication, the same message can be processed multiple times,
causing duplicate agent responses. This module provides both in-memory
and Redis-backed deduplication strategies.

## Classes

- **`EventDeduplicatorProtocol(Protocol)`** — Protocol for event deduplication backends.
- **`EventDeduplicator`** — In-memory event deduplication with TTL.
- **`RedisEventDeduplicator`** — Redis-backed deduplication for multi-instance deployments.
