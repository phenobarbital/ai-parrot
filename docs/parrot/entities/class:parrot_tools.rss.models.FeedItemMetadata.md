---
type: Wiki Entity
title: FeedItemMetadata
id: class:parrot_tools.rss.models.FeedItemMetadata
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: LLM-facing record for a retrieved feed item.
---

# FeedItemMetadata

Defined in [`parrot_tools.rss.models`](../summaries/mod:parrot_tools.rss.models.md).

```python
class FeedItemMetadata(BaseModel)
```

LLM-facing record for a retrieved feed item.

This is the ONLY thing returned to the LLM by ``read_feeds`` — it carries
metadata plus the paths of the archived content, never the content itself.

Attributes:
    item_id: Stable id (sha256(link)[:16]) usable with ``get_content``.
    feed: Slug of the feed the item came from.
    feed_url: URL of the feed the item came from.
    title: Item title.
    link: Article URL.
    published: Publication timestamp (ISO-8601) when available.
    summary: Feed-provided summary, truncated to 500 chars.
    author: Item author when available.
    html_path: Absolute path of the saved raw HTML page.
    text_path: Absolute path of the saved extracted text.
    fetch_method: How the page was retrieved.
    fetch_status: Outcome of the retrieval.
    error: Error detail when the fetch failed or degraded.

## Methods

- `def to_llm_dict(self) -> Dict[str, Any]` — Serialize for the LLM, dropping empty fields to save tokens.
