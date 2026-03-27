"""Tests for CrawlStrategy protocol and built-in strategies."""
import pytest

from parrot.tools.scraping.crawl_graph import CrawlGraph, CrawlNode
from parrot.tools.scraping.crawl_strategy import (
    BFSStrategy,
    CrawlStrategy,
    DFSStrategy,
)


def _make_nodes(urls: list, depth: int = 1) -> list:
    """Helper to create CrawlNode instances for testing."""
    return [CrawlNode(url=u, normalized_url=u, depth=depth) for u in urls]


class TestCrawlStrategyProtocol:
    """Verify the Protocol is runtime-checkable."""

    def test_bfs_satisfies_protocol(self):
        assert isinstance(BFSStrategy(), CrawlStrategy)

    def test_dfs_satisfies_protocol(self):
        assert isinstance(DFSStrategy(), CrawlStrategy)


class TestBFSStrategy:
    """BFS visits all nodes at depth N before depth N+1."""

    def test_breadth_first_order(self):
        graph = CrawlGraph()
        strategy = BFSStrategy()
        # Root is added to frontier by add_root; consume it first
        graph.add_root("https://example.com")
        root = strategy.next(graph)
        assert root.url == "https://example.com"

        # Enqueue depth-1 children
        children = _make_nodes(
            ["https://example.com/a", "https://example.com/b"], depth=1
        )
        strategy.enqueue(graph, children)

        # Enqueue depth-2 grandchild
        grandchild = _make_nodes(["https://example.com/a/1"], depth=2)
        strategy.enqueue(graph, grandchild)

        # BFS: /a, /b before /a/1
        assert strategy.next(graph).url == "https://example.com/a"
        assert strategy.next(graph).url == "https://example.com/b"
        assert strategy.next(graph).url == "https://example.com/a/1"

    def test_empty_frontier_returns_none(self):
        graph = CrawlGraph()
        strategy = BFSStrategy()
        assert strategy.next(graph) is None

    def test_enqueue_empty_list(self):
        graph = CrawlGraph()
        strategy = BFSStrategy()
        strategy.enqueue(graph, [])
        assert strategy.next(graph) is None

    def test_multiple_enqueue_batches(self):
        graph = CrawlGraph()
        strategy = BFSStrategy()
        batch1 = _make_nodes(["https://a.com", "https://b.com"])
        batch2 = _make_nodes(["https://c.com"])
        strategy.enqueue(graph, batch1)
        strategy.enqueue(graph, batch2)
        # FIFO order: a, b, c
        assert strategy.next(graph).url == "https://a.com"
        assert strategy.next(graph).url == "https://b.com"
        assert strategy.next(graph).url == "https://c.com"
        assert strategy.next(graph) is None


class TestDFSStrategy:
    """DFS follows links deep before backtracking."""

    def test_depth_first_order(self):
        graph = CrawlGraph()
        strategy = DFSStrategy()
        children = _make_nodes(
            ["https://example.com/a", "https://example.com/b"], depth=1
        )
        strategy.enqueue(graph, children)
        # DFS: pop from end → /b first, then /a
        assert strategy.next(graph).url == "https://example.com/b"
        assert strategy.next(graph).url == "https://example.com/a"

    def test_dfs_deep_dive(self):
        """DFS should go deep before siblings."""
        graph = CrawlGraph()
        strategy = DFSStrategy()

        # Enqueue two siblings
        siblings = _make_nodes(
            ["https://example.com/a", "https://example.com/b"], depth=1
        )
        strategy.enqueue(graph, siblings)

        # Pop /b (DFS), then enqueue /b's child
        b_node = strategy.next(graph)
        assert b_node.url == "https://example.com/b"
        b_child = _make_nodes(["https://example.com/b/1"], depth=2)
        strategy.enqueue(graph, b_child)

        # Next should be /b/1 (deep), not /a (sibling)
        assert strategy.next(graph).url == "https://example.com/b/1"
        # Now /a
        assert strategy.next(graph).url == "https://example.com/a"

    def test_empty_frontier_returns_none(self):
        graph = CrawlGraph()
        strategy = DFSStrategy()
        assert strategy.next(graph) is None

    def test_enqueue_empty_list(self):
        graph = CrawlGraph()
        strategy = DFSStrategy()
        strategy.enqueue(graph, [])
        assert strategy.next(graph) is None
