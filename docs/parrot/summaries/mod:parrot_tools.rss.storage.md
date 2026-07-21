---
type: Wiki Summary
title: parrot_tools.rss.storage
id: mod:parrot_tools.rss.storage
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Disk storage for archived RSS articles.
relates_to:
- concept: class:parrot_tools.rss.storage.RSSStorage
  rel: defines
- concept: mod:parrot_tools.rss.models
  rel: references
---

# `parrot_tools.rss.storage`

Disk storage for archived RSS articles.

Layout::

    {base_dir}/{feed_slug}/{item_id}/page.html     raw fetched HTML
    {base_dir}/{feed_slug}/{item_id}/content.txt   extracted main text
    {base_dir}/{feed_slug}/{item_id}/item.json     FeedItemMetadata dump

## Classes

- **`RSSStorage`** — Filesystem archive for fetched feed items.
