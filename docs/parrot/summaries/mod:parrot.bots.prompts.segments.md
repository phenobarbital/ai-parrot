---
type: Wiki Summary
title: parrot.bots.prompts.segments
id: mod:parrot.bots.prompts.segments
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: CacheableSegment dataclass for provider-agnostic prompt caching.
relates_to:
- concept: class:parrot.bots.prompts.segments.CacheableSegment
  rel: defines
---

# `parrot.bots.prompts.segments`

CacheableSegment dataclass for provider-agnostic prompt caching.

FEAT-181 — Provider-Agnostic Prompt Caching (Module 1).

A CacheableSegment represents one chunk of the system prompt with a
cache-eligibility flag. The PromptBuilder.build_segments() method produces
a list of these for consumption by AbstractClient._apply_cache_hints().

The ``ttl_hint`` field is reserved for forward-compatibility but is not
translated by any provider in v1.

## Classes

- **`CacheableSegment`** — One chunk of the system prompt with a cache-eligibility flag.
