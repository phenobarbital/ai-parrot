---
type: Wiki Entity
title: RSSStorage
id: class:parrot_tools.rss.storage.RSSStorage
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Filesystem archive for fetched feed items.
---

# RSSStorage

Defined in [`parrot_tools.rss.storage`](../summaries/mod:parrot_tools.rss.storage.md).

```python
class RSSStorage
```

Filesystem archive for fetched feed items.

All blocking I/O is dispatched through ``asyncio.to_thread`` in the
async methods; the sync helpers are cheap path/metadata operations.

## Methods

- `def item_dir(self, feed_slug: str, item_id: str) -> Path` — Return the directory for a feed item (not created).
- `def has_item(self, feed_slug: str, item_id: str) -> bool` — Check whether an item is already archived (dedup check).
- `async def save_item(self, meta: FeedItemMetadata, html: str, text: str) -> FeedItemMetadata` — Persist an item's content and metadata to disk.
- `def load_metadata(self, feed_slug: str, item_id: str) -> Optional[FeedItemMetadata]` — Load archived metadata for an item, or None when absent/corrupt.
- `def find_item(self, item_id: str) -> Optional[Path]` — Locate an item directory by id across all feeds.
- `def list_saved(self, feed_slug: Optional[str]=None, limit: int=50) -> List[Dict[str, Any]]` — List archived item metadata, newest first.
- `def resolve_content_path(self, ref: str, fmt: str='text') -> Path` — Resolve an item reference to a readable content file.
- `async def read_content(self, ref: str, fmt: str='text') -> str` — Read archived content for an item reference.
