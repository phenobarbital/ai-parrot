---
type: Wiki Summary
title: parrot_tools.scraping.crawl_graph
id: mod:parrot_tools.scraping.crawl_graph
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: CrawlGraph & CrawlNode for the CrawlEngine.
relates_to:
- concept: class:parrot_tools.scraping.crawl_graph.CrawlGraph
  rel: defines
- concept: class:parrot_tools.scraping.crawl_graph.CrawlNode
  rel: defines
- concept: class:parrot_tools.scraping.crawl_graph.CrawlResult
  rel: defines
- concept: mod:parrot_tools.scraping.url_utils
  rel: references
---

# `parrot_tools.scraping.crawl_graph`

CrawlGraph & CrawlNode for the CrawlEngine.

Provides the in-memory graph structure that tracks which URLs have been
visited, which are pending in the frontier queue, and the results of
each scrape operation. CrawlGraph implements a BFS traversal strategy
using a FIFO frontier (collections.deque).

## Classes

- **`CrawlNode`** — A single node in the crawl graph representing one URL to visit.
- **`CrawlGraph`** — BFS-based crawl graph that manages the frontier and visited set.
- **`CrawlResult`** — Summary of a completed crawl session.
