---
type: Wiki Entity
title: CrawlGraph
id: class:parrot_tools.scraping.crawl_graph.CrawlGraph
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: BFS-based crawl graph that manages the frontier and visited set.
---

# CrawlGraph

Defined in [`parrot_tools.scraping.crawl_graph`](../summaries/mod:parrot_tools.scraping.crawl_graph.md).

```python
class CrawlGraph
```

BFS-based crawl graph that manages the frontier and visited set.

The graph stores CrawlNode instances keyed by their normalized URL
and exposes a FIFO frontier for breadth-first traversal.

## Methods

- `def add_root(self, url: str) -> CrawlNode` — Create the root node at depth 0 and seed the frontier.
- `def enqueue(self, node: CrawlNode) -> bool` — Add a node to the frontier if its URL has not been visited.
- `def next(self) -> Optional[CrawlNode]` — Pop the next node from the frontier (FIFO / BFS order).
- `def mark_done(self, node: CrawlNode, result: Any) -> None` — Transition a node to 'done' and attach its result.
- `def mark_failed(self, node: CrawlNode, error: str) -> None` — Transition a node to 'failed' and record the error.
- `def is_visited(self, normalized_url: str) -> bool` — Check whether a normalized URL has already been visited.
- `def visited_count(self) -> int` — Return the number of unique URLs that have been visited.
- `def done_nodes(self) -> List[CrawlNode]` — Return all nodes whose status is 'done'.
- `def failed_nodes(self) -> List[CrawlNode]` — Return all nodes whose status is 'failed'.
