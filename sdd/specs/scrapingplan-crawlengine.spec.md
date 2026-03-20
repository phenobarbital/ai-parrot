# Feature Specification: CrawlEngine

**Feature ID**: FEAT-013
**Date**: 2026-02-25
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.x

---

## 1. Motivation & Business Requirements

### Problem Statement

`WebScrapingTool` currently handles single-page scraping. Multi-page crawling logic
(following links, managing depth, deduplicating URLs) is either missing or ad-hoc in
the orchestrator layer. There is no structured way to perform breadth-first or
depth-first crawls, enforce domain scoping, limit page counts, or handle per-page
failures gracefully during a multi-page scrape.

The crawling "what to visit next" logic is tightly coupled to "how to visit it,"
making it impossible to test traversal strategies without a real browser.

### Goals

- **Separated crawl orchestration**: Extract multi-page crawl logic into an
  independent, testable `CrawlEngine` that does not depend on the browser driver.
- **Pluggable traversal strategies**: Support BFS (default) and DFS via a
  `CrawlStrategy` protocol, extensible to priority-based or LLM-guided strategies.
- **Strict URL deduplication**: Normalize URLs (strip query/fragment, remove `www.`,
  trailing slash) to prevent redundant page visits.
- **Domain scoping**: Only follow same-domain links by default; opt-in for external.
- **Fault isolation**: Failed pages are recorded but do not halt the crawl.
- **Configurable concurrency**: Default `concurrency=1` (safe for all drivers);
  higher values available for Playwright or other concurrent-capable drivers.
- **Depth and page-count limits**: Both `depth` and `max_pages` are enforced;
  whichever limit is hit first stops the crawl.

### Non-Goals (explicitly out of scope)

- Exposing `CrawlEngine` as a standalone tool — the public API is
  `WebScrapingToolkit.crawl()`.
- robots.txt enforcement (handled at the orchestrator/toolkit level).
- JavaScript-rendered link discovery (depends on the driver, not the engine).
- Sitemap-guided or LLM-guided strategies (future enhancement via `CrawlStrategy`).

---

## 2. Architectural Design

### Overview

`CrawlEngine` is an internal component that receives a `scrape_fn` callable
(provided by `WebScrapingToolkit`) and orchestrates multi-page crawling using a
`CrawlGraph` for state tracking and a `CrawlStrategy` for traversal ordering.
`LinkDiscoverer` extracts and normalizes outgoing links from scraped HTML.

### Component Diagram

```
WebScrapingToolkit.crawl()
        │
        ▼
   CrawlEngine.run(start_url, plan, depth, max_pages)
        │
   ┌────┴────────────────────────┐
   │        CrawlGraph           │
   │  ┌─────────┐  ┌──────────┐ │
   │  │ frontier │  │ visited  │ │
   │  │ (deque)  │  │  (set)   │ │
   │  └─────────┘  └──────────┘ │
   └────┬────────────────────────┘
        │
   ┌────┴──────┐
   │ Strategy  │  BFSStrategy (default)
   │ .next()   │  DFSStrategy
   │ .enqueue()│
   └────┬──────┘
        │
        ▼
   _process_node(node)
        │
   ┌────┴────┐        ┌──────────────┐
   │scrape_fn│───────→│ScrapingResult│
   └────┬────┘        └──────────────┘
        │
        ▼
   LinkDiscoverer.discover(html)
        │
        ▼
   enqueue new CrawlNodes
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `WebScrapingTool` | provides `scrape_fn` | Engine calls this for each page |
| `ScrapingPlan` (FEAT-012) | consumed | Engine reads `follow_selector`, `follow_pattern`, `max_depth` from plan |
| `ScrapingResult` (`models.py`) | produced | Each scraped page returns a `ScrapingResult` |
| `ScrapingOrchestrator` | refactored | Existing orchestrator delegates multi-page logic to engine |

### Data Models

```python
@dataclass
class CrawlNode:
    """Tracks the state of a single URL within the crawl."""
    url: str
    normalized_url: str
    depth: int
    parent_url: Optional[str] = None
    status: str = "pending"          # pending | scraping | done | failed | skipped
    result: Optional[ScrapingResult] = None
    discovered_links: list = field(default_factory=list)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error: Optional[str] = None
```

```python
@dataclass
class CrawlResult:
    """Aggregated result of a complete crawl session."""
    start_url: str
    depth: int
    pages: List[ScrapingResult]
    visited_urls: List[str]
    failed_urls: List[str]
    total_pages: int
    total_elapsed_seconds: float
    plan_used: Optional[str] = None
```

### New Public Interfaces

```python
class CrawlStrategy(Protocol):
    def next(self, graph: CrawlGraph) -> Optional[CrawlNode]: ...
    def enqueue(self, graph: CrawlGraph, nodes: List[CrawlNode]) -> None: ...

class BFSStrategy:
    """Breadth-first: all nodes at depth N before depth N+1."""
    ...

class DFSStrategy:
    """Depth-first: follows links deep before backtracking."""
    ...

class CrawlGraph:
    def add_root(self, url: str) -> CrawlNode: ...
    def enqueue(self, node: CrawlNode) -> None: ...
    def next(self) -> Optional[CrawlNode]: ...
    def mark_done(self, node: CrawlNode, result) -> None: ...
    def mark_failed(self, node: CrawlNode, error: str) -> None: ...
    def is_visited(self, normalized_url: str) -> bool: ...

class LinkDiscoverer:
    def discover(self, html: str, base_url: str, current_depth: int, max_depth: int) -> List[str]: ...

class CrawlEngine:
    async def run(self, start_url: str, plan: ScrapingPlan, depth: int = 1, max_pages: Optional[int] = None) -> CrawlResult: ...
```

```python
def normalize_url(url: str, base: str) -> Optional[str]:
    """Normalize URL for deduplication. Returns None if URL should be discarded."""
    ...
```

---

## 3. Module Breakdown

### Module 1: URL Normalization Utilities
- **Path**: `parrot/tools/scraping/url_utils.py`
- **Responsibility**: `normalize_url()` function — resolves relative URLs, strips
  query/fragment, removes `www.` prefix, rejects non-HTTP schemes, removes trailing
  slashes.
- **Depends on**: None (standard library only)

### Module 2: CrawlGraph & CrawlNode
- **Path**: `parrot/tools/scraping/crawl_graph.py`
- **Responsibility**: `CrawlNode` dataclass and `CrawlGraph` — lightweight directed
  graph that serves as both the frontier queue and the result collector. Manages
  visited set, node state transitions, and provides `done_nodes` / `failed_nodes`
  properties.
- **Depends on**: Module 1 (normalize_url)

### Module 3: CrawlStrategy Protocol & Built-in Strategies
- **Path**: `parrot/tools/scraping/crawl_strategy.py`
- **Responsibility**: `CrawlStrategy` protocol definition, `BFSStrategy`, and
  `DFSStrategy` implementations.
- **Depends on**: Module 2 (CrawlGraph)

### Module 4: LinkDiscoverer
- **Path**: `parrot/tools/scraping/link_discoverer.py`
- **Responsibility**: Extract links from HTML using CSS selector filtering, regex
  pattern matching, and domain scoping. Returns deduplicated normalized URLs.
- **Depends on**: Module 1 (normalize_url)

### Module 5: CrawlEngine
- **Path**: `parrot/tools/scraping/crawler.py`
- **Responsibility**: Orchestrates multi-page crawling. Delegates page execution to
  `scrape_fn`, link discovery to `LinkDiscoverer`, and traversal order to
  `CrawlStrategy`. Supports sequential and concurrent execution modes.
- **Depends on**: Module 2, Module 3, Module 4, FEAT-012 (ScrapingPlan)

### Module 6: WebScrapingToolkit Integration
- **Path**: `parrot/tools/scraping/tool.py` (modification)
- **Responsibility**: Add `crawl()` method to the existing tool/toolkit that
  instantiates and runs `CrawlEngine`.
- **Depends on**: Module 5

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_normalize_relative_url` | Module 1 | Relative URLs resolved against base |
| `test_normalize_strips_query_fragment` | Module 1 | Query params and fragments removed |
| `test_normalize_removes_www` | Module 1 | `www.` prefix stripped from domain |
| `test_normalize_trailing_slash` | Module 1 | `/products/` and `/products` treated as same |
| `test_normalize_rejects_non_http` | Module 1 | `mailto:`, `javascript:`, `data:` return None |
| `test_graph_add_root` | Module 2 | Root node added and tracked correctly |
| `test_graph_enqueue_dedup` | Module 2 | Same normalized URL not enqueued twice |
| `test_graph_mark_done` | Module 2 | Node transitions to done, appears in `done_nodes` |
| `test_graph_mark_failed` | Module 2 | Node transitions to failed, appears in `failed_nodes` |
| `test_bfs_visits_breadth_first` | Module 3 | BFS visits all depth-N nodes before depth-N+1 |
| `test_dfs_visits_depth_first` | Module 3 | DFS reaches deepest pages before siblings |
| `test_discoverer_css_selector` | Module 4 | Only links matching selector are returned |
| `test_discoverer_pattern_filter` | Module 4 | Regex pattern rejects non-matching URLs |
| `test_discoverer_domain_scoping` | Module 4 | External links blocked when `allow_external=False` |
| `test_discoverer_depth_guard` | Module 4 | Returns empty list when `current_depth >= max_depth` |
| `test_engine_depth_0_single_page` | Module 5 | `depth=0` scrapes only start_url |
| `test_engine_depth_1` | Module 5 | `depth=1` scrapes start_url + direct links |
| `test_engine_max_pages_cap` | Module 5 | Crawl stops at `max_pages` limit |
| `test_engine_failed_page_continues` | Module 5 | One page failure does not stop crawl |
| `test_engine_concurrent` | Module 5 | `concurrency=3` completes without race conditions |

### Integration Tests

| Test | Description |
|---|---|
| `test_bfs_depth2_mock_site` | BFS crawl on 3-level mock site with expected visit order |
| `test_dfs_depth2_mock_site` | DFS crawl on 3-level mock site reaches deepest first |
| `test_crawl_with_plan_hints` | Plan's `follow_selector` and `follow_pattern` respected |

### Test Data / Fixtures

```python
@pytest.fixture
def mock_site():
    """3-level mock site structure for crawl testing."""
    return {
        "https://example.com": {
            "html": '<a href="/a">A</a><a href="/b">B</a>',
            "links": ["https://example.com/a", "https://example.com/b"],
        },
        "https://example.com/a": {
            "html": '<a href="/a/1">A1</a><a href="/a/2">A2</a>',
            "links": ["https://example.com/a/1", "https://example.com/a/2"],
        },
        "https://example.com/b": {
            "html": '<a href="/b/1">B1</a>',
            "links": ["https://example.com/b/1"],
        },
        # depth-2 pages (no outgoing links)
        "https://example.com/a/1": {"html": "<p>Leaf</p>", "links": []},
        "https://example.com/a/2": {"html": "<p>Leaf</p>", "links": []},
        "https://example.com/b/1": {"html": "<p>Leaf</p>", "links": []},
    }

@pytest.fixture
def mock_scrape_fn(mock_site):
    """scrape_fn that returns ScrapingResult from mock_site dict."""
    async def _scrape(url, plan):
        page = mock_site.get(url)
        if page is None:
            raise ValueError(f"Page not found: {url}")
        return ScrapingResult(
            url=url,
            content=page["html"],
            raw_html=page["html"],
            success=True,
        )
    return _scrape
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `CrawlEngine.run()` correctly performs BFS and DFS crawls on mock site fixtures
- [ ] `depth` parameter controls crawl depth (0 = single page, 1 = direct links, etc.)
- [ ] `max_pages` cap stops crawl at the specified count regardless of depth
- [ ] Failed pages are recorded in `CrawlResult.failed_urls` without halting the crawl
- [ ] URL normalization prevents re-visiting URLs that differ only in query/fragment/www/trailing slash
- [ ] Domain scoping blocks external links by default
- [ ] `LinkDiscoverer` respects CSS selector and regex pattern filters
- [ ] Concurrent mode (`concurrency > 1`) completes without race conditions
- [ ] All unit tests pass: `pytest tests/tools/scraping/test_crawler.py -v`
- [ ] No new external dependencies (uses `BeautifulSoup` already in project)
- [ ] `CrawlResult` dataclass is importable from `parrot.tools.scraping`

---

## 6. Implementation Notes & Constraints

### Patterns to Follow

- Use `dataclass` for `CrawlNode` and `CrawlResult` (lightweight, no validation needed — internal data structures)
- Use `Protocol` for `CrawlStrategy` (structural subtyping, no inheritance required)
- Use `BeautifulSoup` for HTML link extraction (already a dependency via `models.py`)
- Use `asyncio.Semaphore` for bounding concurrent scrape calls
- Follow logging pattern: `self.logger = logging.getLogger(self.__class__.__name__)`

### Depth Semantics

| `depth` value | Meaning |
|---|---|
| 0 | Only scrape `start_url`, follow no links |
| 1 | `start_url` + its direct links (default) |
| 2 | `start_url` + direct links + their links |
| N | N levels below `start_url` |

### Known Risks / Gotchas

- **Concurrent mode safety**: `CrawlGraph` mutations (enqueue, mark_done) are not
  thread-safe. With `concurrency > 1`, all coroutines run on the same event loop
  (single thread), so this is safe for asyncio but would need locks if threads are
  introduced.
- **Large crawls**: No built-in rate limiting — the caller (`WebScrapingToolkit`)
  should handle politeness delays between requests.
- **Playwright page reuse**: Concurrent mode assumes the driver supports multiple
  simultaneous page loads. Selenium does not; caller must verify driver capability.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `beautifulsoup4` | `>=4.12` | HTML parsing for link discovery (already in project) |

No new dependencies required.

---

## 7. Open Questions

- [ ] Should `CrawlEngine` emit events/callbacks for progress monitoring (e.g., `on_page_scraped`, `on_page_failed`)? — *Owner: Jesus Lara*: Yes
- [ ] Should `CrawlResult` include the full `CrawlGraph` for post-crawl analysis, or just the flattened lists? — *Owner: Jesus Lara*: CrawlGraph
- [ ] Should rate-limiting / politeness delays be built into the engine or remain the toolkit's responsibility? — *Owner: Jesus Lara*: built into the engine

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-02-25 | Jesus Lara | Initial draft from proposal SPEC-03 |
