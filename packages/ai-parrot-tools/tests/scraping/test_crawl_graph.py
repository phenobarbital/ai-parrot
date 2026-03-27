"""Tests for parrot.tools.scraping.crawl_graph module."""
import pytest

from parrot.tools.scraping.crawl_graph import CrawlGraph, CrawlNode, CrawlResult


# ------------------------------------------------------------------
# CrawlNode basics
# ------------------------------------------------------------------

class TestCrawlNode:
    """CrawlNode dataclass sanity checks."""

    def test_defaults(self):
        node = CrawlNode(url="https://example.com", normalized_url="https://example.com", depth=0)
        assert node.status == "pending"
        assert node.parent_url is None
        assert node.result is None
        assert node.discovered_links == []
        assert node.started_at is None
        assert node.finished_at is None
        assert node.error is None


# ------------------------------------------------------------------
# CrawlGraph.add_root
# ------------------------------------------------------------------

class TestAddRoot:
    """Tests for CrawlGraph.add_root."""

    def test_creates_node_at_depth_zero(self):
        g = CrawlGraph()
        node = g.add_root("https://example.com/page")
        assert node.depth == 0
        assert node.url == "https://example.com/page"

    def test_normalizes_url(self):
        g = CrawlGraph()
        node = g.add_root("https://www.Example.COM/page/")
        # normalize_url strips www., lowercases, removes trailing slash
        assert node.normalized_url == "https://example.com/page"

    def test_root_added_to_nodes_and_visited(self):
        g = CrawlGraph()
        node = g.add_root("https://example.com")
        assert node.normalized_url in g.nodes
        assert g.is_visited(node.normalized_url)

    def test_root_in_frontier(self):
        g = CrawlGraph()
        g.add_root("https://example.com")
        popped = g.next()
        assert popped is not None
        assert popped.depth == 0


# ------------------------------------------------------------------
# CrawlGraph.enqueue
# ------------------------------------------------------------------

class TestEnqueue:
    """Tests for CrawlGraph.enqueue."""

    def test_prevents_duplicate_normalized_urls(self):
        g = CrawlGraph()
        root = g.add_root("https://example.com")
        # Use the same normalized URL that add_root produced
        dup = CrawlNode(
            url="https://example.com",
            normalized_url=root.normalized_url,
            depth=1,
        )
        assert g.enqueue(dup) is False

    def test_allows_new_urls(self):
        g = CrawlGraph()
        g.add_root("https://example.com")
        new_node = CrawlNode(
            url="https://example.com/about",
            normalized_url="https://example.com/about",
            depth=1,
        )
        assert g.enqueue(new_node) is True
        assert g.is_visited("https://example.com/about")


# ------------------------------------------------------------------
# CrawlGraph.next (FIFO)
# ------------------------------------------------------------------

class TestNext:
    """Tests for CrawlGraph.next (BFS / FIFO order)."""

    def test_fifo_order(self):
        g = CrawlGraph()
        # Use URLs with paths so normalization is predictable (no trailing-slash ambiguity)
        g.add_root("https://a.com/page")
        g.enqueue(CrawlNode(url="https://b.com/page", normalized_url="https://b.com/page", depth=1))
        g.enqueue(CrawlNode(url="https://c.com/page", normalized_url="https://c.com/page", depth=1))

        first = g.next()
        second = g.next()
        third = g.next()
        assert first.normalized_url == "https://a.com/page"
        assert second.normalized_url == "https://b.com/page"
        assert third.normalized_url == "https://c.com/page"

    def test_returns_none_on_empty(self):
        g = CrawlGraph()
        assert g.next() is None


# ------------------------------------------------------------------
# mark_done / mark_failed
# ------------------------------------------------------------------

class TestMarkTransitions:
    """Tests for status transitions."""

    def test_mark_done(self):
        g = CrawlGraph()
        node = g.add_root("https://example.com")
        payload = {"html": "<h1>Hello</h1>"}
        g.mark_done(node, payload)
        assert node.status == "done"
        assert node.result == payload

    def test_mark_failed(self):
        g = CrawlGraph()
        node = g.add_root("https://example.com")
        g.mark_failed(node, "timeout")
        assert node.status == "failed"
        assert node.error == "timeout"


# ------------------------------------------------------------------
# Properties: done_nodes, failed_nodes, visited_count, is_visited
# ------------------------------------------------------------------

class TestProperties:
    """Tests for read-only properties and queries."""

    def test_done_nodes_filters_correctly(self):
        g = CrawlGraph()
        n1 = g.add_root("https://a.com")
        n2 = CrawlNode(url="https://b.com", normalized_url="https://b.com", depth=1)
        g.enqueue(n2)
        g.mark_done(n1, "ok")
        # n2 still pending
        assert len(g.done_nodes) == 1
        assert g.done_nodes[0] is n1

    def test_failed_nodes_filters_correctly(self):
        g = CrawlGraph()
        n1 = g.add_root("https://a.com")
        n2 = CrawlNode(url="https://b.com", normalized_url="https://b.com", depth=1)
        g.enqueue(n2)
        g.mark_failed(n2, "404")
        assert len(g.failed_nodes) == 1
        assert g.failed_nodes[0] is n2

    def test_visited_count(self):
        g = CrawlGraph()
        assert g.visited_count == 0
        g.add_root("https://a.com")
        assert g.visited_count == 1
        g.enqueue(CrawlNode(url="https://b.com", normalized_url="https://b.com", depth=1))
        assert g.visited_count == 2

    def test_is_visited_true(self):
        g = CrawlGraph()
        g.add_root("https://example.com")
        node = g.next()
        assert g.is_visited(node.normalized_url)

    def test_is_visited_false(self):
        g = CrawlGraph()
        assert not g.is_visited("https://never-seen.com")


# ------------------------------------------------------------------
# CrawlResult
# ------------------------------------------------------------------

class TestCrawlResult:
    """CrawlResult dataclass sanity checks."""

    def test_instantiation(self):
        cr = CrawlResult(
            start_url="https://example.com",
            depth=2,
            pages=[{"url": "https://example.com", "title": "Home"}],
            visited_urls=["https://example.com"],
            failed_urls=[],
            total_pages=1,
            total_elapsed_seconds=1.23,
        )
        assert cr.start_url == "https://example.com"
        assert cr.depth == 2
        assert cr.total_pages == 1
        assert cr.plan_used is None

    def test_with_plan_used(self):
        cr = CrawlResult(
            start_url="https://example.com",
            depth=1,
            pages=[],
            visited_urls=[],
            failed_urls=[],
            total_pages=0,
            total_elapsed_seconds=0.0,
            plan_used="my-plan-v1",
        )
        assert cr.plan_used == "my-plan-v1"
