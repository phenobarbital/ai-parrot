---
type: Wiki Entity
title: BFSStrategy
id: class:parrot_tools.scraping.crawl_strategy.BFSStrategy
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: 'Breadth-first strategy: visits all nodes at depth N before depth N+1.'
---

# BFSStrategy

Defined in [`parrot_tools.scraping.crawl_strategy`](../summaries/mod:parrot_tools.scraping.crawl_strategy.md).

```python
class BFSStrategy
```

Breadth-first strategy: visits all nodes at depth N before depth N+1.

Uses ``deque.popleft()`` (FIFO) for ``next()`` and ``deque.extend()``
for ``enqueue()``.

## Methods

- `def next(self, graph: CrawlGraph) -> Optional[CrawlNode]` — Pop the oldest node from the frontier (FIFO).
- `def enqueue(self, graph: CrawlGraph, nodes: List[CrawlNode]) -> None` — Append nodes to the end of the frontier.
