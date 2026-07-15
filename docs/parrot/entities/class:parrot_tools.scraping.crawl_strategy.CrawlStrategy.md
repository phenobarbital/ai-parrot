---
type: Wiki Entity
title: CrawlStrategy
id: class:parrot_tools.scraping.crawl_strategy.CrawlStrategy
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Protocol that determines traversal order for the CrawlEngine.
---

# CrawlStrategy

Defined in [`parrot_tools.scraping.crawl_strategy`](../summaries/mod:parrot_tools.scraping.crawl_strategy.md).

```python
class CrawlStrategy(Protocol)
```

Protocol that determines traversal order for the CrawlEngine.

Implementations receive the current ``CrawlGraph`` and manipulate its
``_frontier`` deque to control which URLs are visited next.

## Methods

- `def next(self, graph: CrawlGraph) -> Optional[CrawlNode]` — Pop and return the next node to process.
- `def enqueue(self, graph: CrawlGraph, nodes: List[CrawlNode]) -> None` — Add newly discovered nodes to the traversal frontier.
