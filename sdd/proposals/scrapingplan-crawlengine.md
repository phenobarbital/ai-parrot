# SPEC-03 — `CrawlEngine`
**Project:** AI-Parrot · WebScrapingToolkit  
**Version:** 1.0  
**Status:** Draft  
**File:** `parrot/tools/scraping/crawler.py`

---

## 1. Purpose

`CrawlEngine` is the internal component responsible for multi-page crawling
logic. It is not exposed directly as a tool; `WebScrapingToolkit.crawl()` is
the public interface. The engine is extracted into its own module for:

- Independent testability (no browser required for graph/routing logic).
- Clean separation between "what to visit next" (engine) and "how to visit it" (driver).
- Future extensibility: different crawl strategies (BFS, DFS, sitemap-guided, LLM-guided) without touching the toolkit.

---

## 2. Design Principles

- **BFS by default.** Breadth-first guarantees predictable depth semantics and avoids deep-diving into a single branch.
- **Pluggable strategy.** A `CrawlStrategy` protocol makes it easy to add DFS or priority-based traversal later.
- **URL deduplication is strict.** Normalized URLs (scheme + netloc + path, no query/fragment) are used for the visited set to prevent re-visiting URLs that differ only in tracking parameters.
- **Domain scoping by default.** The engine only follows links within the same `netloc` as `start_url` unless `allow_external=True` is set.
- **Fault isolation.** A failure on one page is recorded and does not stop the crawl; the engine continues with the next URL in the frontier.
- **Concurrency is opt-in.** `concurrency=1` (default) is safe with both Selenium and Playwright. Higher values require the caller to confirm driver support.

---

## 3. Core Structures

### 3.1 `CrawlNode`

Tracks the state of a single URL within the crawl.

```python
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime


@dataclass
class CrawlNode:
    url: str
    normalized_url: str
    depth: int
    parent_url: Optional[str] = None
    status: str = "pending"          # pending | scraping | done | failed | skipped
    result: Optional["ScrapingResult"] = None
    discovered_links: list = field(default_factory=list)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error: Optional[str] = None
```

### 3.2 `CrawlGraph`

A lightweight directed graph of `CrawlNode` objects that serves as both the
frontier queue and the result collector.

```python
from collections import deque
from typing import Dict, List, Set


class CrawlGraph:
    def __init__(self):
        self.nodes: Dict[str, CrawlNode] = {}
        self._frontier: deque[CrawlNode] = deque()
        self._visited: Set[str] = set()

    def add_root(self, url: str) -> CrawlNode: ...
    def enqueue(self, node: CrawlNode) -> None: ...
    def next(self) -> Optional[CrawlNode]: ...
    def mark_done(self, node: CrawlNode, result) -> None: ...
    def mark_failed(self, node: CrawlNode, error: str) -> None: ...

    @property
    def visited_count(self) -> int: ...

    @property
    def done_nodes(self) -> List[CrawlNode]: ...

    @property
    def failed_nodes(self) -> List[CrawlNode]: ...

    def is_visited(self, normalized_url: str) -> bool:
        return normalized_url in self._visited
```

---

## 4. `CrawlStrategy` Protocol

```python
from typing import Protocol, List


class CrawlStrategy(Protocol):
    """
    Determines the order in which pending URLs are visited.
    Implementations receive the current CrawlGraph and return the next
    node to process.
    """

    def next(self, graph: CrawlGraph) -> Optional[CrawlNode]:
        """Pop and return the next node, or None if the frontier is empty."""
        ...

    def enqueue(self, graph: CrawlGraph, nodes: List[CrawlNode]) -> None:
        """Add newly discovered nodes to the traversal frontier."""
        ...
```

### 4.1 Built-in Strategies

#### `BFSStrategy` (default)

```python
class BFSStrategy:
    """Standard breadth-first: visits all nodes at depth N before depth N+1."""

    def next(self, graph: CrawlGraph) -> Optional[CrawlNode]:
        return graph._frontier.popleft() if graph._frontier else None

    def enqueue(self, graph: CrawlGraph, nodes: List[CrawlNode]) -> None:
        graph._frontier.extend(nodes)
```

#### `DFSStrategy`

```python
class DFSStrategy:
    """Depth-first: follows links deep into a branch before backtracking."""

    def next(self, graph: CrawlGraph) -> Optional[CrawlNode]:
        return graph._frontier.pop() if graph._frontier else None

    def enqueue(self, graph: CrawlGraph, nodes: List[CrawlNode]) -> None:
        graph._frontier.extend(nodes)  # reversed because pop() takes from end
```

---

## 5. `LinkDiscoverer`

Responsible for extracting and normalizing outgoing links from a scraped page.

```python
class LinkDiscoverer:
    """
    Extracts links from raw HTML, applying selector and pattern filters.
    """

    def __init__(
        self,
        follow_selector: str = "a[href]",
        follow_pattern: Optional[str] = None,
        base_domain: Optional[str] = None,
        allow_external: bool = False,
    ):
        self.follow_selector = follow_selector
        self.follow_pattern = re.compile(follow_pattern) if follow_pattern else None
        self.base_domain = base_domain
        self.allow_external = allow_external

    def discover(
        self,
        html: str,
        base_url: str,
        current_depth: int,
        max_depth: int,
    ) -> List[str]:
        """
        Parse html, extract matching links, apply filters, return absolute URLs.

        Filters applied in order:
          1. CSS selector (BeautifulSoup).
          2. Regex pattern on the resolved absolute href.
          3. Domain scope (same netloc as base_domain unless allow_external).
          4. Depth guard (current_depth >= max_depth → return []).
        """
        if current_depth >= max_depth:
            return []

        soup = BeautifulSoup(html, "html.parser")
        links = []

        for tag in soup.select(self.follow_selector):
            href = tag.get("href") or tag.get("src")
            if not href:
                continue

            absolute = urljoin(base_url, href)
            parsed = urlparse(absolute)

            # Strip query params and fragment for deduplication
            normalized = urlunparse(
                (parsed.scheme, parsed.netloc, parsed.path, "", "", "")
            )

            # Domain scope
            if not self.allow_external and parsed.netloc != self.base_domain:
                continue

            # Regex pattern
            if self.follow_pattern and not self.follow_pattern.search(absolute):
                continue

            links.append(normalized)

        return list(dict.fromkeys(links))  # preserve order, deduplicate
```

---

## 6. `CrawlEngine`

```python
class CrawlEngine:
    """
    Orchestrates multi-page crawling.

    Delegates:
      - Page execution  → scrape_fn callable (provided by WebScrapingToolkit)
      - Link discovery  → LinkDiscoverer
      - Traversal order → CrawlStrategy
    """

    def __init__(
        self,
        scrape_fn: Callable[[str, ScrapingPlan], Awaitable[ScrapingResult]],
        strategy: Optional[CrawlStrategy] = None,
        follow_selector: str = "a[href]",
        follow_pattern: Optional[str] = None,
        allow_external: bool = False,
        concurrency: int = 1,
        logger: Optional[logging.Logger] = None,
    ):
        self._scrape_fn = scrape_fn
        self._strategy = strategy or BFSStrategy()
        self._concurrency = concurrency
        self.logger = logger or logging.getLogger(self.__class__.__name__)
        self._follow_selector = follow_selector
        self._follow_pattern = follow_pattern
        self._allow_external = allow_external

    async def run(
        self,
        start_url: str,
        plan: ScrapingPlan,
        depth: int = 1,
        max_pages: Optional[int] = None,
    ) -> CrawlResult:
        """
        Execute the crawl and return aggregated results.
        """
        base_domain = urlparse(start_url).netloc
        discoverer = LinkDiscoverer(
            follow_selector=plan.follow_selector or self._follow_selector,
            follow_pattern=plan.follow_pattern or self._follow_pattern,
            base_domain=base_domain,
            allow_external=self._allow_external,
        )

        graph = CrawlGraph()
        root = graph.add_root(start_url)
        self._strategy.enqueue(graph, [root])

        start_time = asyncio.get_event_loop().time()

        if self._concurrency == 1:
            await self._run_sequential(graph, plan, discoverer, depth, max_pages)
        else:
            await self._run_concurrent(graph, plan, discoverer, depth, max_pages)

        elapsed = asyncio.get_event_loop().time() - start_time

        return CrawlResult(
            start_url=start_url,
            depth=depth,
            pages=[n.result for n in graph.done_nodes if n.result],
            visited_urls=[n.url for n in graph.nodes.values()],
            failed_urls=[n.url for n in graph.failed_nodes],
            total_pages=graph.visited_count,
            total_elapsed_seconds=elapsed,
            plan_used=plan.name,
        )

    # ------------------------------------------------------------------
    # Sequential execution
    # ------------------------------------------------------------------

    async def _run_sequential(
        self,
        graph: CrawlGraph,
        plan: ScrapingPlan,
        discoverer: LinkDiscoverer,
        max_depth: int,
        max_pages: Optional[int],
    ) -> None:
        while True:
            node = self._strategy.next(graph)
            if node is None:
                break
            if max_pages is not None and graph.visited_count >= max_pages:
                self.logger.info(f"max_pages={max_pages} reached, stopping.")
                break

            await self._process_node(node, graph, plan, discoverer, max_depth)

    # ------------------------------------------------------------------
    # Concurrent execution
    # ------------------------------------------------------------------

    async def _run_concurrent(
        self,
        graph: CrawlGraph,
        plan: ScrapingPlan,
        discoverer: LinkDiscoverer,
        max_depth: int,
        max_pages: Optional[int],
    ) -> None:
        semaphore = asyncio.Semaphore(self._concurrency)

        async def bounded(node: CrawlNode):
            async with semaphore:
                await self._process_node(node, graph, plan, discoverer, max_depth)

        while True:
            batch = []
            for _ in range(self._concurrency):
                node = self._strategy.next(graph)
                if node is None:
                    break
                if max_pages and graph.visited_count >= max_pages:
                    break
                batch.append(node)

            if not batch:
                break

            await asyncio.gather(*[bounded(n) for n in batch], return_exceptions=True)

    # ------------------------------------------------------------------
    # Single-node processing
    # ------------------------------------------------------------------

    async def _process_node(
        self,
        node: CrawlNode,
        graph: CrawlGraph,
        plan: ScrapingPlan,
        discoverer: LinkDiscoverer,
        max_depth: int,
    ) -> None:
        node.started_at = datetime.utcnow()
        node.status = "scraping"

        try:
            result = await self._scrape_fn(node.url, plan)
            node.result = result
            node.status = "done"
            graph.mark_done(node, result)

            # Discover and enqueue child links
            if result.raw_html and node.depth < max_depth:
                child_urls = discoverer.discover(
                    result.raw_html,
                    base_url=node.url,
                    current_depth=node.depth,
                    max_depth=max_depth,
                )
                new_nodes = []
                for url in child_urls:
                    if not graph.is_visited(url):
                        child = CrawlNode(
                            url=url,
                            normalized_url=url,
                            depth=node.depth + 1,
                            parent_url=node.url,
                        )
                        graph.enqueue(child)
                        new_nodes.append(child)
                self._strategy.enqueue(graph, new_nodes)
                node.discovered_links = child_urls

        except Exception as e:
            node.status = "failed"
            node.error = str(e)
            graph.mark_failed(node, str(e))
            self.logger.warning(f"Failed to scrape {node.url}: {e}")
        finally:
            node.finished_at = datetime.utcnow()
```

---

## 7. Depth Semantics

| `depth` value | Meaning |
|---|---|
| 0 | Only scrape `start_url`, follow no links |
| 1 | `start_url` + its direct links (default) |
| 2 | `start_url` + direct links + their links |
| N | N levels below `start_url` |

This matches the intuitive "number of hops from root" model. `depth=0` is
equivalent to a single `scrape()` call and is provided for API consistency.

---

## 8. `max_pages` Interaction with `depth`

`max_pages` is a hard cap applied **after** the depth guard. This prevents
runaway crawls on large sites. When both are set, whichever limit is hit first
stops the crawl. A warning is logged identifying which limit triggered.

---

## 9. URL Normalization Rules

All discovered URLs go through normalization before deduplication:

1. Resolve relative URLs against the current page's URL.
2. Convert scheme to lowercase.
3. Remove `www.` prefix for domain comparison.
4. Strip query string and fragment.
5. Remove trailing slash (treat `/products/` and `/products` as the same).
6. Reject non-HTTP(S) schemes (`mailto:`, `javascript:`, `data:`, etc.).

```python
def normalize_url(url: str, base: str) -> Optional[str]:
    """Returns normalized URL or None if the URL should be discarded."""
    try:
        absolute = urljoin(base, url)
        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https"):
            return None
        netloc = parsed.netloc.lower().lstrip("www.")
        path = parsed.path.rstrip("/") or "/"
        return urlunparse((parsed.scheme, netloc, path, "", "", ""))
    except Exception:
        return None
```

---

## 10. Observability

`CrawlEngine` emits structured log messages at every state transition:

```
INFO  CrawlEngine: Starting crawl  url=https://example.com depth=2 max_pages=50
DEBUG CrawlEngine: Scraping        url=https://example.com/p1 depth=0
DEBUG CrawlEngine: Discovered      count=12 from=https://example.com/p1
DEBUG CrawlEngine: Scraping        url=https://example.com/products depth=1
WARN  CrawlEngine: Failed          url=https://example.com/broken error="Timeout"
INFO  CrawlEngine: Crawl complete  pages=23 failed=1 elapsed=45.2s
```

---

## 11. Tests (expected coverage)

- BFS depth-1 and depth-2 on a 3-level mock site.
- DFS reaches deepest pages before siblings.
- `max_pages` stops crawl at correct count.
- Domain scoping blocks external links.
- Pattern filter rejects non-matching URLs.
- URL normalization: relative, trailing slash, `www.`, query params.
- Failed page does not stop crawl; appears in `failed_urls`.
- Concurrent crawl with `concurrency=3` completes without race conditions.

---

*Previous: [SPEC-02 — WebScrapingToolkit](./SPEC-02-WebScrapingToolkit.md)*  
*Next: [SPEC-04 — PlaywrightDriver](./SPEC-04-PlaywrightDriver.md)*
