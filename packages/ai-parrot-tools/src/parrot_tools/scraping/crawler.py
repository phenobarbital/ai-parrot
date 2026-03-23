"""CrawlEngine — multi-page crawl orchestrator for the WebScrapingToolkit.

Coordinates ``CrawlGraph`` (state), ``CrawlStrategy`` (traversal order),
``LinkDiscoverer`` (link extraction), and a caller-provided ``scrape_fn``
(page execution) to perform breadth-first or depth-first crawls across
multiple pages.

This module is not exposed as a standalone tool; the public interface is
``WebScrapingToolkit.crawl()``.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Awaitable, Callable, Optional
from urllib.parse import urlparse

from .crawl_graph import CrawlGraph, CrawlNode, CrawlResult
from .crawl_strategy import BFSStrategy, CrawlStrategy
from .link_discoverer import LinkDiscoverer


class CrawlEngine:
    """Orchestrates multi-page crawling.

    Delegates:
      - Page execution  -> ``scrape_fn`` callable (provided by the toolkit)
      - Link discovery  -> ``LinkDiscoverer``
      - Traversal order -> ``CrawlStrategy``

    Args:
        scrape_fn: Async callable ``(url, plan) -> result`` that scrapes a
            single page. The result object must expose a ``raw_html`` attribute
            (or similar) for link discovery.
        strategy: Traversal strategy; defaults to ``BFSStrategy``.
        follow_selector: Default CSS selector for link elements.
        follow_pattern: Default regex pattern to filter discovered URLs.
        allow_external: Whether to follow links outside the start domain.
        concurrency: Number of concurrent page scrapes. ``1`` (default) is
            safe for all drivers; higher values require concurrent-capable
            drivers.
        logger: Optional logger; one is created if not provided.
    """

    def __init__(
        self,
        scrape_fn: Callable[..., Awaitable[Any]],
        strategy: Optional[CrawlStrategy] = None,
        follow_selector: str = "a[href]",
        follow_pattern: Optional[str] = None,
        allow_external: bool = False,
        concurrency: int = 1,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._scrape_fn = scrape_fn
        self._strategy = strategy or BFSStrategy()
        self._follow_selector = follow_selector
        self._follow_pattern = follow_pattern
        self._allow_external = allow_external
        self._concurrency = max(1, concurrency)
        self.logger = logger or logging.getLogger(self.__class__.__name__)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(
        self,
        start_url: str,
        plan: Any,
        depth: int = 1,
        max_pages: Optional[int] = None,
    ) -> CrawlResult:
        """Execute the crawl and return aggregated results.

        Args:
            start_url: Seed URL for the crawl.
            plan: Scraping plan object; its ``follow_selector``,
                ``follow_pattern``, and ``max_depth`` attributes are used
                as hints when available.
            depth: Maximum crawl depth (0 = only start_url).
            max_pages: Hard cap on total pages scraped.

        Returns:
            A ``CrawlResult`` summarising the crawl session.
        """
        base_domain = urlparse(start_url).netloc

        # Resolve hints from plan (duck-typed)
        follow_selector = getattr(plan, "follow_selector", None) or self._follow_selector
        follow_pattern = getattr(plan, "follow_pattern", None) or self._follow_pattern

        discoverer = LinkDiscoverer(
            follow_selector=follow_selector,
            follow_pattern=follow_pattern,
            base_domain=base_domain,
            allow_external=self._allow_external,
        )

        graph = CrawlGraph()
        root = graph.add_root(start_url)

        # The root is already in the graph frontier via add_root.
        # Strategy.next() will pop it.

        self.logger.info(
            "Starting crawl  url=%s depth=%d max_pages=%s",
            start_url, depth, max_pages,
        )

        loop = asyncio.get_event_loop()
        start_time = loop.time()

        if self._concurrency == 1:
            await self._run_sequential(graph, plan, discoverer, depth, max_pages)
        else:
            await self._run_concurrent(graph, plan, discoverer, depth, max_pages)

        elapsed = loop.time() - start_time

        result = CrawlResult(
            start_url=start_url,
            depth=depth,
            pages=[n.result for n in graph.done_nodes if n.result],
            visited_urls=[n.url for n in graph.nodes.values()],
            failed_urls=[n.url for n in graph.failed_nodes],
            total_pages=len(graph.done_nodes),
            total_elapsed_seconds=elapsed,
            plan_used=getattr(plan, "name", None),
        )

        self.logger.info(
            "Crawl complete  pages=%d failed=%d elapsed=%.1fs",
            result.total_pages, len(result.failed_urls), elapsed,
        )

        return result

    # ------------------------------------------------------------------
    # Sequential execution
    # ------------------------------------------------------------------

    async def _run_sequential(
        self,
        graph: CrawlGraph,
        plan: Any,
        discoverer: LinkDiscoverer,
        max_depth: int,
        max_pages: Optional[int],
    ) -> None:
        while True:
            node = self._strategy.next(graph)
            if node is None:
                break
            if max_pages is not None and len(graph.done_nodes) >= max_pages:
                self.logger.info("max_pages=%d reached, stopping.", max_pages)
                break
            await self._process_node(node, graph, plan, discoverer, max_depth)

    # ------------------------------------------------------------------
    # Concurrent execution
    # ------------------------------------------------------------------

    async def _run_concurrent(
        self,
        graph: CrawlGraph,
        plan: Any,
        discoverer: LinkDiscoverer,
        max_depth: int,
        max_pages: Optional[int],
    ) -> None:
        semaphore = asyncio.Semaphore(self._concurrency)

        async def bounded(node: CrawlNode) -> None:
            async with semaphore:
                await self._process_node(node, graph, plan, discoverer, max_depth)

        while True:
            batch: list[CrawlNode] = []
            for _ in range(self._concurrency):
                node = self._strategy.next(graph)
                if node is None:
                    break
                if max_pages is not None and len(graph.done_nodes) + len(batch) >= max_pages:
                    break
                batch.append(node)

            if not batch:
                break

            await asyncio.gather(
                *[bounded(n) for n in batch],
                return_exceptions=True,
            )

    # ------------------------------------------------------------------
    # Single-node processing
    # ------------------------------------------------------------------

    async def _process_node(
        self,
        node: CrawlNode,
        graph: CrawlGraph,
        plan: Any,
        discoverer: LinkDiscoverer,
        max_depth: int,
    ) -> None:
        node.started_at = datetime.utcnow()
        node.status = "scraping"

        self.logger.debug("Scraping  url=%s depth=%d", node.url, node.depth)

        try:
            result = await self._scrape_fn(node.url, plan)
            graph.mark_done(node, result)

            # Discover and enqueue child links
            raw_html = getattr(result, "raw_html", None) or getattr(result, "content", "")
            if raw_html and node.depth < max_depth:
                child_urls = discoverer.discover(
                    raw_html,
                    base_url=node.url,
                    current_depth=node.depth,
                    max_depth=max_depth,
                )
                new_nodes: list[CrawlNode] = []
                for url in child_urls:
                    if not graph.is_visited(url):
                        child = CrawlNode(
                            url=url,
                            normalized_url=url,
                            depth=node.depth + 1,
                            parent_url=node.normalized_url,
                        )
                        if graph.enqueue(child):
                            new_nodes.append(child)
                if new_nodes:
                    self._strategy.enqueue(graph, new_nodes)
                    self.logger.debug(
                        "Discovered  count=%d from=%s", len(new_nodes), node.url,
                    )
                node.discovered_links = child_urls

        except Exception as exc:
            graph.mark_failed(node, str(exc))
            self.logger.warning("Failed  url=%s error=%s", node.url, exc)
        finally:
            node.finished_at = datetime.utcnow()
