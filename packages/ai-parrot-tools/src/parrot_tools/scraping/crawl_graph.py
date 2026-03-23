"""CrawlGraph & CrawlNode for the CrawlEngine.

Provides the in-memory graph structure that tracks which URLs have been
visited, which are pending in the frontier queue, and the results of
each scrape operation. CrawlGraph implements a BFS traversal strategy
using a FIFO frontier (collections.deque).
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from .url_utils import normalize_url


@dataclass
class CrawlNode:
    """A single node in the crawl graph representing one URL to visit.

    Attributes:
        url: The original (un-normalized) URL.
        normalized_url: The canonical form used for deduplication.
        depth: BFS depth from the root URL (root = 0).
        parent_url: Normalized URL of the page that linked to this one.
        status: Lifecycle state — pending | scraping | done | failed | skipped.
        result: Arbitrary scrape payload stored after successful processing.
        discovered_links: Raw URLs found on this page during scraping.
        started_at: Timestamp when scraping began.
        finished_at: Timestamp when scraping completed (success or failure).
        error: Human-readable error message if status is 'failed'.
    """

    url: str
    normalized_url: str
    depth: int
    parent_url: Optional[str] = None
    status: str = "pending"
    result: Optional[Any] = None
    discovered_links: list = field(default_factory=list)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error: Optional[str] = None


class CrawlGraph:
    """BFS-based crawl graph that manages the frontier and visited set.

    The graph stores CrawlNode instances keyed by their normalized URL
    and exposes a FIFO frontier for breadth-first traversal.
    """

    def __init__(self) -> None:
        self.nodes: Dict[str, CrawlNode] = {}
        self._frontier: deque[CrawlNode] = deque()
        self._visited: Set[str] = set()

    # ------------------------------------------------------------------
    # Mutation helpers
    # ------------------------------------------------------------------

    def add_root(self, url: str) -> CrawlNode:
        """Create the root node at depth 0 and seed the frontier.

        Args:
            url: The starting URL for the crawl.

        Returns:
            The newly created root CrawlNode.
        """
        norm = normalize_url(url)
        if norm is None:
            norm = url  # fallback for unusual schemes during testing
        node = CrawlNode(url=url, normalized_url=norm, depth=0)
        self.nodes[norm] = node
        self._visited.add(norm)
        self._frontier.append(node)
        return node

    def enqueue(self, node: CrawlNode) -> bool:
        """Add a node to the frontier if its URL has not been visited.

        Args:
            node: The CrawlNode to enqueue.

        Returns:
            True if the node was added, False if the URL was already visited.
        """
        if node.normalized_url in self._visited:
            return False
        self._visited.add(node.normalized_url)
        self.nodes[node.normalized_url] = node
        self._frontier.append(node)
        return True

    def next(self) -> Optional[CrawlNode]:
        """Pop the next node from the frontier (FIFO / BFS order).

        Returns:
            The next CrawlNode, or None if the frontier is empty.
        """
        if not self._frontier:
            return None
        return self._frontier.popleft()

    # ------------------------------------------------------------------
    # Status transitions
    # ------------------------------------------------------------------

    def mark_done(self, node: CrawlNode, result: Any) -> None:
        """Transition a node to 'done' and attach its result.

        Args:
            node: The CrawlNode that finished successfully.
            result: Arbitrary scrape result to store on the node.
        """
        node.status = "done"
        node.result = result

    def mark_failed(self, node: CrawlNode, error: str) -> None:
        """Transition a node to 'failed' and record the error.

        Args:
            node: The CrawlNode that failed.
            error: Human-readable error description.
        """
        node.status = "failed"
        node.error = error

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def is_visited(self, normalized_url: str) -> bool:
        """Check whether a normalized URL has already been visited.

        Args:
            normalized_url: The canonical URL to check.

        Returns:
            True if the URL is in the visited set.
        """
        return normalized_url in self._visited

    @property
    def visited_count(self) -> int:
        """Return the number of unique URLs that have been visited."""
        return len(self._visited)

    @property
    def done_nodes(self) -> List[CrawlNode]:
        """Return all nodes whose status is 'done'."""
        return [n for n in self.nodes.values() if n.status == "done"]

    @property
    def failed_nodes(self) -> List[CrawlNode]:
        """Return all nodes whose status is 'failed'."""
        return [n for n in self.nodes.values() if n.status == "failed"]


@dataclass
class CrawlResult:
    """Summary of a completed crawl session.

    Attributes:
        start_url: The seed URL that initiated the crawl.
        depth: Maximum BFS depth that was configured.
        pages: Collected page data from all successfully scraped nodes.
        visited_urls: List of all normalized URLs that were visited.
        failed_urls: List of normalized URLs that failed during scraping.
        total_pages: Count of successfully scraped pages.
        total_elapsed_seconds: Wall-clock time for the entire crawl.
        plan_used: Optional identifier of the scraping plan used.
    """

    start_url: str
    depth: int
    pages: List[Any]
    visited_urls: List[str]
    failed_urls: List[str]
    total_pages: int
    total_elapsed_seconds: float
    plan_used: Optional[str] = None
