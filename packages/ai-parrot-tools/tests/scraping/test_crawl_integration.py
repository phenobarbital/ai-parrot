"""Integration tests for CrawlEngine ↔ WebScrapingToolkit wiring (TASK-048)."""
import pytest

from parrot.tools.scraping import (
    CrawlEngine,
    CrawlResult,
    CrawlNode,
    BFSStrategy,
    DFSStrategy,
    CrawlStrategy,
    LinkDiscoverer,
    normalize_url,
)
from parrot.tools.scraping.crawler import CrawlEngine as CrawlEngineDirect
from parrot.tools.scraping.crawl_graph import CrawlResult as CrawlResultDirect


# ---------------------------------------------------------------------------
# Import tests — verify __init__.py exports
# ---------------------------------------------------------------------------


class TestImports:
    """All new public components importable from ``parrot.tools.scraping``."""

    def test_crawl_engine_importable(self):
        assert CrawlEngine is not None

    def test_crawl_result_importable(self):
        assert CrawlResult is not None

    def test_crawl_node_importable(self):
        assert CrawlNode is not None

    def test_strategies_importable(self):
        assert BFSStrategy is not None
        assert DFSStrategy is not None

    def test_crawl_strategy_protocol_importable(self):
        assert CrawlStrategy is not None

    def test_link_discoverer_importable(self):
        assert LinkDiscoverer is not None

    def test_normalize_url_importable(self):
        assert normalize_url is not None

    def test_reexport_identity(self):
        """Re-exports resolve to the canonical classes."""
        assert CrawlEngine is CrawlEngineDirect
        assert CrawlResult is CrawlResultDirect


# ---------------------------------------------------------------------------
# Mock site for crawl integration
# ---------------------------------------------------------------------------

MOCK_SITE = {
    "https://shop.example.com": (
        '<a href="/products">Products</a>'
        '<a href="/about">About</a>'
    ),
    "https://shop.example.com/products": (
        '<a href="/products/1">Widget</a>'
        '<a href="/products/2">Gadget</a>'
    ),
    "https://shop.example.com/about": "<p>About us.</p>",
    "https://shop.example.com/products/1": "<p>Widget detail.</p>",
    "https://shop.example.com/products/2": "<p>Gadget detail.</p>",
}


class FakeResult:
    """Minimal result with raw_html for link discovery."""

    def __init__(self, url: str, html: str):
        self.url = url
        self.content = html
        self.raw_html = html
        self.success = True


class FakePlan:
    """Stand-in plan with crawl hints."""
    name = "integration-plan"
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


# ---------------------------------------------------------------------------
# End-to-end crawl tests
# ---------------------------------------------------------------------------


class TestCrawlIntegration:
    """Full crawl through the engine with mock scrape function."""

    @pytest.mark.asyncio
    async def test_bfs_depth2_mock_site(self, mock_scrape_fn):
        """BFS crawl on 3-level mock site visits all 5 pages."""
        engine = CrawlEngine(scrape_fn=mock_scrape_fn)
        result = await engine.run(
            "https://shop.example.com", FakePlan(), depth=2,
        )
        assert isinstance(result, CrawlResult)
        assert result.total_pages == 5
        assert len(result.failed_urls) == 0

    @pytest.mark.asyncio
    async def test_dfs_depth2_mock_site(self, mock_scrape_fn):
        """DFS strategy also visits all 5 pages."""
        engine = CrawlEngine(
            scrape_fn=mock_scrape_fn, strategy=DFSStrategy(),
        )
        result = await engine.run(
            "https://shop.example.com", FakePlan(), depth=2,
        )
        assert result.total_pages == 5

    @pytest.mark.asyncio
    async def test_crawl_with_plan_hints(self, mock_scrape_fn):
        """Plan's follow_selector restricts link discovery."""
        class SelectivePlan:
            name = "selective"
            # Only follow links that have class "nav" — none in our mock HTML
            follow_selector = "a.nav"
            follow_pattern = None
            max_depth = None

        engine = CrawlEngine(scrape_fn=mock_scrape_fn)
        result = await engine.run(
            "https://shop.example.com", SelectivePlan(), depth=2,
        )
        # Only root is scraped because no links match the selector
        assert result.total_pages == 1

    @pytest.mark.asyncio
    async def test_crawl_with_pattern_filter(self, mock_scrape_fn):
        """Plan's follow_pattern filters discovered URLs."""
        class PatternPlan:
            name = "pattern"
            follow_selector = "a[href]"
            follow_pattern = r"/products"  # only follow /products paths
            max_depth = None

        engine = CrawlEngine(scrape_fn=mock_scrape_fn)
        result = await engine.run(
            "https://shop.example.com", PatternPlan(), depth=2,
        )
        # root + /products + /products/1 + /products/2 = 4
        # /about is excluded by the pattern
        assert result.total_pages == 4
        assert all(
            "about" not in u for u in result.visited_urls
        )

    @pytest.mark.asyncio
    async def test_crawl_result_fields(self, mock_scrape_fn):
        """CrawlResult contains expected metadata."""
        engine = CrawlEngine(scrape_fn=mock_scrape_fn)
        result = await engine.run(
            "https://shop.example.com", FakePlan(), depth=1,
        )
        assert result.start_url == "https://shop.example.com"
        assert result.depth == 1
        assert result.plan_used == "integration-plan"
        assert result.total_elapsed_seconds >= 0
        assert result.total_pages == 3  # root + /products + /about

    @pytest.mark.asyncio
    async def test_concurrent_crawl(self, mock_scrape_fn):
        """Concurrent mode matches sequential results."""
        seq = CrawlEngine(scrape_fn=mock_scrape_fn, concurrency=1)
        con = CrawlEngine(scrape_fn=mock_scrape_fn, concurrency=3)

        r_seq = await seq.run("https://shop.example.com", FakePlan(), depth=2)
        r_con = await con.run("https://shop.example.com", FakePlan(), depth=2)

        assert r_seq.total_pages == r_con.total_pages
        assert set(r_seq.visited_urls) == set(r_con.visited_urls)

    @pytest.mark.asyncio
    async def test_max_pages_with_deep_crawl(self, mock_scrape_fn):
        """max_pages stops before exhausting full depth."""
        engine = CrawlEngine(scrape_fn=mock_scrape_fn)
        result = await engine.run(
            "https://shop.example.com", FakePlan(), depth=10, max_pages=3,
        )
        assert result.total_pages <= 3


class TestWebScrapingToolCrawlMethod:
    """Verify the ``crawl()`` method exists on ``WebScrapingTool``."""

    def test_crawl_method_exists(self):
        from parrot.tools.scraping import WebScrapingTool
        assert hasattr(WebScrapingTool, "crawl")
        assert callable(getattr(WebScrapingTool, "crawl"))
