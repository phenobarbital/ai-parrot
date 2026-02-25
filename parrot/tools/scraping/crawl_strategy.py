"""Pluggable crawl traversal strategies for the CrawlEngine.

Defines the ``CrawlStrategy`` protocol and two built-in implementations:

* **BFSStrategy** — breadth-first (default): visits all nodes at depth *N*
  before any node at depth *N+1*.
* **DFSStrategy** — depth-first: follows links deep into a branch before
  backtracking to siblings.

Custom strategies can be created by implementing the ``CrawlStrategy``
protocol (structural subtyping — no inheritance required).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .crawl_graph import CrawlGraph, CrawlNode


@runtime_checkable
class CrawlStrategy(Protocol):
    """Protocol that determines traversal order for the CrawlEngine.

    Implementations receive the current ``CrawlGraph`` and manipulate its
    ``_frontier`` deque to control which URLs are visited next.
    """

    def next(self, graph: CrawlGraph) -> Optional[CrawlNode]:
        """Pop and return the next node to process.

        Returns:
            The next ``CrawlNode``, or ``None`` if the frontier is empty.
        """
        ...

    def enqueue(self, graph: CrawlGraph, nodes: List[CrawlNode]) -> None:
        """Add newly discovered nodes to the traversal frontier.

        Args:
            graph: The crawl graph whose frontier should be extended.
            nodes: Newly discovered nodes to add.
        """
        ...


class BFSStrategy:
    """Breadth-first strategy: visits all nodes at depth N before depth N+1.

    Uses ``deque.popleft()`` (FIFO) for ``next()`` and ``deque.extend()``
    for ``enqueue()``.
    """

    def next(self, graph: CrawlGraph) -> Optional[CrawlNode]:
        """Pop the oldest node from the frontier (FIFO)."""
        if not graph._frontier:
            return None
        return graph._frontier.popleft()

    def enqueue(self, graph: CrawlGraph, nodes: List[CrawlNode]) -> None:
        """Append nodes to the end of the frontier."""
        graph._frontier.extend(nodes)


class DFSStrategy:
    """Depth-first strategy: follows links deep before backtracking.

    Uses ``deque.pop()`` (LIFO) for ``next()`` and ``deque.extend()``
    for ``enqueue()``.
    """

    def next(self, graph: CrawlGraph) -> Optional[CrawlNode]:
        """Pop the newest node from the frontier (LIFO)."""
        if not graph._frontier:
            return None
        return graph._frontier.pop()

    def enqueue(self, graph: CrawlGraph, nodes: List[CrawlNode]) -> None:
        """Append nodes to the end of the frontier."""
        graph._frontier.extend(nodes)
