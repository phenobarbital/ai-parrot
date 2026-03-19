# TASK-047: CrawlEngine

**Feature**: FEAT-013 — CrawlEngine
**Spec**: `sdd/specs/scrapingplan-crawlengine.spec.md`
**Status**: in-progress
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-044, TASK-045, TASK-046
**Assigned-to**: claude-session

---

## Context

`CrawlEngine` is the core orchestrator for multi-page crawling. It coordinates
`CrawlGraph` (state), `CrawlStrategy` (traversal order), `LinkDiscoverer` (link
extraction), and a caller-provided `scrape_fn` (page execution). It supports both
sequential and concurrent execution modes.

Implements spec Module 5 and proposal Section 6.

---

## Scope

- Implement `CrawlEngine` class with:
  - Constructor accepting `scrape_fn`, `strategy`, `follow_selector`, `follow_pattern`,
    `allow_external`, `concurrency`, `logger`
  - `async run(start_url, plan, depth=1, max_pages=None) -> CrawlResult`
  - Sequential execution path (`_run_sequential`)
  - Concurrent execution path (`_run_concurrent`) using `asyncio.Semaphore`
  - Per-node processing (`_process_node`) — scrape, discover links, enqueue children
- Handle fault isolation: failed pages recorded, crawl continues
- Respect `depth` and `max_pages` limits (whichever hit first stops crawl)
- Emit structured log messages at state transitions
- Use plan's `follow_selector`, `follow_pattern`, `max_depth` as hints
- Write unit tests using mock `scrape_fn`

**NOT in scope**: WebScrapingToolkit integration (TASK-048), actual browser invocation.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/scraping/crawler.py` | CREATE | `CrawlEngine` class |
| `tests/tools/scraping/test_crawler.py` | CREATE | Unit tests with mock scrape_fn |

---

## Implementation Notes

### Pattern to Follow
```python
import asyncio
import logging
from typing import Callable, Awaitable, Optional
from datetime import datetime
from urllib.parse import urlparse

class CrawlEngine:
    def __init__(
        self,
        scrape_fn: Callable[[str, "ScrapingPlan"], Awaitable["ScrapingResult"]],
        strategy: Optional["CrawlStrategy"] = None,
        concurrency: int = 1,
        logger: Optional[logging.Logger] = None,
        ...
    ):
        self._scrape_fn = scrape_fn
        self._strategy = strategy or BFSStrategy()
        self._concurrency = concurrency
        self.logger = logger or logging.getLogger(self.__class__.__name__)
        ...

    async def run(self, start_url, plan, depth=1, max_pages=None) -> CrawlResult:
        ...
```

### Key Constraints
- Must be async throughout
- Use `asyncio.Semaphore` for bounding concurrent calls
- `CrawlGraph` mutations are safe within a single event loop (no threading)
- Log at INFO for start/complete, DEBUG for per-page, WARN for failures
- `depth=0` means scrape only the start URL
- `scrape_fn` is awaitable and returns `ScrapingResult`

### References in Codebase
- `parrot/tools/scraping/crawl_graph.py` (TASK-044) — `CrawlGraph`, `CrawlNode`, `CrawlResult`
- `parrot/tools/scraping/crawl_strategy.py` (TASK-045) — `BFSStrategy`, `DFSStrategy`
- `parrot/tools/scraping/link_discoverer.py` (TASK-046) — `LinkDiscoverer`
- `parrot/tools/scraping/models.py` — `ScrapingResult`

---

## Acceptance Criteria

- [ ] `CrawlEngine.run()` performs BFS crawl correctly on mock site
- [ ] `depth=0` scrapes only the start URL
- [ ] `depth=1` scrapes start URL + direct links
- [ ] `max_pages` stops crawl at correct count
- [ ] Failed pages do not stop the crawl; appear in `CrawlResult.failed_urls`
- [ ] Concurrent mode (`concurrency > 1`) completes without errors
- [ ] Structured log messages emitted at state transitions
- [ ] All tests pass: `pytest tests/tools/scraping/test_crawler.py -v`
- [ ] Import works: `from parrot.tools.scraping.crawler import CrawlEngine`

---

## Test Specification

```python
# tests/tools/scraping/test_crawler.py
import pytest
import asyncio
from unittest.mock import AsyncMock
from parrot.tools.scraping.crawler import CrawlEngine
from parrot.tools.scraping.crawl_strategy import BFSStrategy, DFSStrategy
from parrot.tools.scraping.crawl_graph import CrawlResult


# --- Fixtures ---

MOCK_SITE = {
    "https://example.com": '<a href="/a">A</a><a href="/b">B</a>',
    "https://example.com/a": '<a href="/a/1">A1</a>',
    "https://example.com/b": '<a href="/b/1">B1</a>',
    "https://example.com/a/1": "<p>Leaf A1</p>",
    "https://example.com/b/1": "<p>Leaf B1</p>",
}


class FakeResult:
    def __init__(self, url, html):
        self.url = url
        self.content = html
        self.raw_html = html
        self.success = True


class FakePlan:
    name = "test-plan"
    follow_selector = "a[href]"
    follow_pattern = None
    max_depth = None


@pytest.fixture
def mock_scrape_fn():
    async def _scrape(url, plan):
        html = MOCK_SITE.get(url)
        if html is None:
            raise ValueError(f"Not found: {url}")
        return FakeResult(url, html)
    return _scrape


# --- Tests ---

class TestCrawlEngine:
    @pytest.mark.asyncio
    async def test_depth_0_single_page(self, mock_scrape_fn):
        engine = CrawlEngine(scrape_fn=mock_scrape_fn)
        result = await engine.run("https://example.com", FakePlan(), depth=0)
        assert result.total_pages == 1
        assert len(result.pages) == 1

    @pytest.mark.asyncio
    async def test_depth_1(self, mock_scrape_fn):
        engine = CrawlEngine(scrape_fn=mock_scrape_fn)
        result = await engine.run("https://example.com", FakePlan(), depth=1)
        assert result.total_pages == 3  # root + /a + /b

    @pytest.mark.asyncio
    async def test_max_pages_cap(self, mock_scrape_fn):
        engine = CrawlEngine(scrape_fn=mock_scrape_fn)
        result = await engine.run("https://example.com", FakePlan(), depth=3, max_pages=2)
        assert result.total_pages <= 2

    @pytest.mark.asyncio
    async def test_failed_page_continues(self):
        call_count = 0
        async def flaky_scrape(url, plan):
            nonlocal call_count
            call_count += 1
            if "fail" in url:
                raise RuntimeError("Simulated failure")
            return FakeResult(url, '<a href="/fail">Fail</a><a href="/ok">OK</a>')

        engine = CrawlEngine(scrape_fn=flaky_scrape)
        result = await engine.run("https://example.com", FakePlan(), depth=1)
        assert len(result.failed_urls) >= 1
        assert result.total_pages >= 1  # at least root succeeded

    @pytest.mark.asyncio
    async def test_concurrent_mode(self, mock_scrape_fn):
        engine = CrawlEngine(scrape_fn=mock_scrape_fn, concurrency=3)
        result = await engine.run("https://example.com", FakePlan(), depth=2)
        assert result.total_pages >= 1
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/scrapingplan-crawlengine.spec.md` for full context
2. **Check dependencies** — verify TASK-044, TASK-045, TASK-046 are in `sdd/tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-047-crawl-engine.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-25
**Notes**: Implemented `CrawlEngine` class with `run()`, `_run_sequential()`, `_run_concurrent()`, and `_process_node()` methods. Supports BFS/DFS strategies via pluggable `CrawlStrategy`, concurrent execution via `asyncio.Semaphore`, fault isolation (failed pages recorded, crawl continues), and `depth`/`max_pages` limits. 12 unit tests passing covering depth semantics (0/1/2), max_pages cap, fault isolation, concurrent mode, result fields, DFS strategy, and importability.

**Deviations from spec**: none
