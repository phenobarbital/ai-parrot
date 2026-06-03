---
id: F004
query_id: Q003
type: read
intent: Understand CrawlEngine concurrency model and reusability for fan-out
executed_at: 2026-06-04T00:00:00Z
duration_ms: 50946
parent_id: null
depth: 0
---

# F004 — CrawlEngine uses asyncio.Semaphore for concurrency but interface is URL-centric

## Summary

`CrawlEngine` (crawler.py:46-138) manages concurrent scraping via `asyncio.Semaphore(concurrency)` with batch gathering. The `scrape_fn` is called as `await scrape_fn(node.url, plan)` — a fixed (url, plan) signature. The engine handles link discovery, deduplication, and graph traversal (BFS/DFS). However, it has NO checkpoint mechanism (in-memory only, progress lost on interruption). The interface is tightly coupled to URL-based crawling; fan-out in a FlowExecutor context requires different semantics (resolve inputs, bind template, manage session context). The semaphore pattern is reusable but CrawlEngine itself likely isn't — better to replicate the concurrency pattern.

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/crawler.py`
  lines: 46-62
  symbol: `CrawlEngine.__init__`
  excerpt: |
    def __init__(self, scrape_fn, strategy=None, follow_selector="a[href]",
                 follow_pattern=None, allow_external=False, concurrency=1, logger=None):

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/crawler.py`
  lines: 173-195
  symbol: `_run_concurrent` (semaphore pattern)
  excerpt: |
    semaphore = asyncio.Semaphore(self._concurrency)
    # ... batches nodes, wraps each in bounded coroutine
    # asyncio.gather(..., return_exceptions=True)

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/crawler.py`
  lines: 215
  symbol: `scrape_fn call`
  excerpt: |
    result = await self._scrape_fn(node.url, plan)

## Notes

CrawlEngine's concurrency pattern (Semaphore + gather) is the reusable piece, not the CrawlEngine class itself. For FlowExecutor fan-out, create a similar bounded-concurrency executor that works on FlowNodes instead of CrawlNodes.
