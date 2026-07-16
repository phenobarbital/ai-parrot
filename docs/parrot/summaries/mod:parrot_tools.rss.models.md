---
type: Wiki Summary
title: parrot_tools.rss.models
id: mod:parrot_tools.rss.models
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Pydantic models and internal data structures for the RSS Feed Reader Toolkit.
relates_to:
- concept: class:parrot_tools.rss.models.FeedItemMetadata
  rel: defines
- concept: class:parrot_tools.rss.models.FeedSite
  rel: defines
- concept: class:parrot_tools.rss.models.FetchedPage
  rel: defines
- concept: class:parrot_tools.rss.models.GetContentInput
  rel: defines
- concept: func:parrot_tools.rss.models.is_item_id
  rel: defines
- concept: func:parrot_tools.rss.models.make_item_id
  rel: defines
---

# `parrot_tools.rss.models`

Pydantic models and internal data structures for the RSS Feed Reader Toolkit.

## Classes

- **`FeedSite(BaseModel)`** — A configured RSS/Atom feed source.
- **`FeedItemMetadata(BaseModel)`** — LLM-facing record for a retrieved feed item.
- **`FetchedPage`** — Internal result of a single article-page fetch attempt.
- **`GetContentInput(BaseModel)`** — Input schema for ``rss_get_content``.

## Functions

- `def make_item_id(link: str) -> str` — Derive a stable item identifier from an article link.
- `def is_item_id(value: str) -> bool` — Check whether a string looks like an item id produced by :func:`make_item_id`.
