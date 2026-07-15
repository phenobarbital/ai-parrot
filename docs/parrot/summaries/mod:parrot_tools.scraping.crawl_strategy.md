---
type: Wiki Summary
title: parrot_tools.scraping.crawl_strategy
id: mod:parrot_tools.scraping.crawl_strategy
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Pluggable crawl traversal strategies for the CrawlEngine.
relates_to:
- concept: class:parrot_tools.scraping.crawl_strategy.BFSStrategy
  rel: defines
- concept: class:parrot_tools.scraping.crawl_strategy.CrawlStrategy
  rel: defines
- concept: class:parrot_tools.scraping.crawl_strategy.DFSStrategy
  rel: defines
- concept: mod:parrot_tools.scraping.crawl_graph
  rel: references
---

# `parrot_tools.scraping.crawl_strategy`

Pluggable crawl traversal strategies for the CrawlEngine.

Defines the ``CrawlStrategy`` protocol and two built-in implementations:

* **BFSStrategy** — breadth-first (default): visits all nodes at depth *N*
  before any node at depth *N+1*.
* **DFSStrategy** — depth-first: follows links deep into a branch before
  backtracking to siblings.

Custom strategies can be created by implementing the ``CrawlStrategy``
protocol (structural subtyping — no inheritance required).

## Classes

- **`CrawlStrategy(Protocol)`** — Protocol that determines traversal order for the CrawlEngine.
- **`BFSStrategy`** — Breadth-first strategy: visits all nodes at depth N before depth N+1.
- **`DFSStrategy`** — Depth-first strategy: follows links deep before backtracking.
