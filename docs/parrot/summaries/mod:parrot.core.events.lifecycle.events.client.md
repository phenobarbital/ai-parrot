---
type: Wiki Summary
title: parrot.core.events.lifecycle.events.client
id: mod:parrot.core.events.lifecycle.events.client
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: LLM Client lifecycle events.
relates_to:
- concept: class:parrot.core.events.lifecycle.events.client.AfterClientCallEvent
  rel: defines
- concept: class:parrot.core.events.lifecycle.events.client.BeforeClientCallEvent
  rel: defines
- concept: class:parrot.core.events.lifecycle.events.client.ClientCallFailedEvent
  rel: defines
- concept: class:parrot.core.events.lifecycle.events.client.ClientStreamChunkEvent
  rel: defines
- concept: class:parrot.core.events.lifecycle.events.client.PromptCacheAppliedEvent
  rel: defines
- concept: class:parrot.core.events.lifecycle.events.client.PromptCacheSkippedEvent
  rel: defines
- concept: mod:parrot.core.events.lifecycle.base
  rel: references
---

# `parrot.core.events.lifecycle.events.client`

LLM Client lifecycle events.

FEAT-176 — Lifecycle Events System.

Covers: before/after/failed LLM API calls and per-chunk streaming events.

Note: ClientStreamChunkEvent is high-frequency and NEVER dual-emits to
EventBus by default. It must be explicitly opted in via forward_to_bus=True
on the subscription.

## Classes

- **`BeforeClientCallEvent(LifecycleEvent)`** — Emitted just before an LLM API call is made.
- **`AfterClientCallEvent(LifecycleEvent)`** — Emitted after a successful LLM API call completes.
- **`ClientCallFailedEvent(LifecycleEvent)`** — Emitted when an LLM API call raises an exception.
- **`ClientStreamChunkEvent(LifecycleEvent)`** — Emitted for each chunk received during a streaming response.
- **`PromptCacheAppliedEvent(LifecycleEvent)`** — Emitted when prompt caching is applied to an LLM call.
- **`PromptCacheSkippedEvent(LifecycleEvent)`** — Emitted when prompt caching is skipped.
