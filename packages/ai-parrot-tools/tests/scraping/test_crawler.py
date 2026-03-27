"""Tests for the CrawlEngine."""
import pytest

from parrot.tools.scraping.crawler import CrawlEngine
from parrot.tools.scraping.crawl_strategy import BFSStrategy, DFSStrategy
from parrot.tools.scraping.crawl_graph import CrawlResult


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

MOCK_SITE = {
    "https://example.com": '<a href="/a">A</a><a href="/b">B</a>',
    "https://example.com/a": '<a href="/a/1">A1</a>',
    "https://example.com/b": '<a href="/b/1">B1</a>',
    "https://example.com/a/1": "<p>Leaf A1</p>",
    "https://example.com/b/1": "<p>Leaf B1</p>",
}


class FakeResult:
    """Minimal result object with raw_html attribute."""
    def __init__(self, url: str, html: str):
        self.url = url
        self.content = html
        self.raw_html = html
        self.success = True


class FakePlan:
    """Minimal plan stub with crawl-hint attributes."""
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCrawlEngineDepth:
    """Verify depth semantics."""

    @pytest.mark.asyncio
    async def test_depth_0_single_page(self, mock_scrape_fn):
        engine = CrawlEngine(scrape_fn=mock_scrape_fn)
        result = await engine.run("https://example.com", FakePlan(), depth=0)
        assert result.total_pages == 1
        assert len(result.pages) == 1
        assert result.pages[0].url == "https://example.com"

    @pytest.mark.asyncio
    async def test_depth_1(self, mock_scrape_fn):
        engine = CrawlEngine(scrape_fn=mock_scrape_fn)
        result = await engine.run("https://example.com", FakePlan(), depth=1)
        # root + /a + /b = 3
        assert result.total_pages == 3

    @pytest.mark.asyncio
    async def test_depth_2(self, mock_scrape_fn):
        engine = CrawlEngine(scrape_fn=mock_scrape_fn)
        result = await engine.run("https://example.com", FakePlan(), depth=2)
        # root + /a + /b + /a/1 + /b/1 = 5
        assert result.total_pages == 5


class TestCrawlEngineMaxPages:
    """Verify max_pages cap."""

    @pytest.mark.asyncio
    async def test_max_pages_cap(self, mock_scrape_fn):
        engine = CrawlEngine(scrape_fn=mock_scrape_fn)
        result = await engine.run(
            "https://example.com", FakePlan(), depth=3, max_pages=2
        )
        assert result.total_pages <= 2

    @pytest.mark.asyncio
    async def test_max_pages_1(self, mock_scrape_fn):
        engine = CrawlEngine(scrape_fn=mock_scrape_fn)
        result = await engine.run(
            "https://example.com", FakePlan(), depth=3, max_pages=1
        )
        assert result.total_pages == 1


class TestCrawlEngineFaultIsolation:
    """Failed pages recorded but crawl continues."""

    @pytest.mark.asyncio
    async def test_failed_page_continues(self):
        async def flaky_scrape(url, plan):
            if "fail" in url:
                raise RuntimeError("Simulated failure")
            return FakeResult(
                url, '<a href="/fail">Fail</a><a href="/ok">OK</a>'
            )

        engine = CrawlEngine(scrape_fn=flaky_scrape)
        result = await engine.run("https://example.com", FakePlan(), depth=1)
        assert len(result.failed_urls) >= 1
        assert result.total_pages >= 1  # at least root succeeded

    @pytest.mark.asyncio
    async def test_all_children_fail(self):
        """Engine completes even if all child pages fail."""
        call_count = 0

        async def only_root(url, plan):
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                raise RuntimeError("child failure")
            return FakeResult(url, '<a href="/c1">C1</a><a href="/c2">C2</a>')

        engine = CrawlEngine(scrape_fn=only_root)
        result = await engine.run("https://example.com", FakePlan(), depth=1)
        assert result.total_pages == 1
        assert len(result.failed_urls) == 2


class TestCrawlEngineConcurrent:
    """Concurrent mode completes without errors."""

    @pytest.mark.asyncio
    async def test_concurrent_mode(self, mock_scrape_fn):
        engine = CrawlEngine(scrape_fn=mock_scrape_fn, concurrency=3)
        result = await engine.run("https://example.com", FakePlan(), depth=2)
        assert result.total_pages >= 1
        assert isinstance(result, CrawlResult)

    @pytest.mark.asyncio
    async def test_concurrent_matches_sequential(self, mock_scrape_fn):
        """Concurrent crawl should visit the same pages as sequential."""
        seq = CrawlEngine(scrape_fn=mock_scrape_fn, concurrency=1)
        con = CrawlEngine(scrape_fn=mock_scrape_fn, concurrency=3)

        r_seq = await seq.run("https://example.com", FakePlan(), depth=2)
        r_con = await con.run("https://example.com", FakePlan(), depth=2)

        assert r_seq.total_pages == r_con.total_pages
        assert set(r_seq.visited_urls) == set(r_con.visited_urls)


class TestCrawlEngineResult:
    """Verify CrawlResult fields."""

    @pytest.mark.asyncio
    async def test_result_fields(self, mock_scrape_fn):
        engine = CrawlEngine(scrape_fn=mock_scrape_fn)
        result = await engine.run("https://example.com", FakePlan(), depth=1)
        assert result.start_url == "https://example.com"
        assert result.depth == 1
        assert result.plan_used == "test-plan"
        assert result.total_elapsed_seconds >= 0
        assert len(result.visited_urls) == result.total_pages
        assert len(result.failed_urls) == 0

    @pytest.mark.asyncio
    async def test_dfs_strategy(self, mock_scrape_fn):
        """DFS strategy can be plugged in."""
        engine = CrawlEngine(
            scrape_fn=mock_scrape_fn, strategy=DFSStrategy()
        )
        result = await engine.run("https://example.com", FakePlan(), depth=2)
        # Should still visit all 5 pages, just in different order
        assert result.total_pages == 5


class TestCrawlEngineImport:
    """Verify importability."""

    def test_import(self):
        from parrot.tools.scraping.crawler import CrawlEngine
        assert CrawlEngine is not None
