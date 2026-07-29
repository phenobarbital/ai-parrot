---
type: Wiki Entity
title: CrawlNode
id: class:parrot_tools.scraping.crawl_graph.CrawlNode
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A single node in the crawl graph representing one URL to visit.
---

# CrawlNode

Defined in [`parrot_tools.scraping.crawl_graph`](../summaries/mod:parrot_tools.scraping.crawl_graph.md).

```python
class CrawlNode
```

A single node in the crawl graph representing one URL to visit.

Attributes:
    url: The original (un-normalized) URL.
    normalized_url: The canonical form used for deduplication.
    depth: BFS depth from the root URL (root = 0).
    parent_url: Normalized URL of the page that linked to this one.
    status: Lifecycle state — pending | scraping | done | failed | skipped.
    result: Arbitrary scrape payload stored after successful processing.
    discovered_links: Raw URLs found on this page during scraping.
    started_at: Timestamp when scraping began.
    finished_at: Timestamp when scraping completed (success or failure).
    error: Human-readable error message if status is 'failed'.
