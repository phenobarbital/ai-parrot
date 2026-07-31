---
type: Wiki Entity
title: DFSStrategy
id: class:parrot_tools.scraping.crawl_strategy.DFSStrategy
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Depth-first strategy: follows links deep before backtracking.'
---

# DFSStrategy

Defined in [`parrot_tools.scraping.crawl_strategy`](../summaries/mod:parrot_tools.scraping.crawl_strategy.md).

```python
class DFSStrategy
```

Depth-first strategy: follows links deep before backtracking.

Uses ``deque.pop()`` (LIFO) for ``next()`` and ``deque.extend()``
for ``enqueue()``.

## Methods

- `def next(self, graph: CrawlGraph) -> Optional[CrawlNode]` — Pop the newest node from the frontier (LIFO).
- `def enqueue(self, graph: CrawlGraph, nodes: List[CrawlNode]) -> None` — Append nodes to the end of the frontier.
