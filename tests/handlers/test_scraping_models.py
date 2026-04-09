"""Unit tests for scraping handler request/response Pydantic models."""
import pytest
from pydantic import ValidationError

from parrot.handlers.scraping.models import (
    PlanCreateRequest,
    ScrapeRequest,
    CrawlRequest,
    PlanSaveRequest,
    ActionInfo,
    DriverTypeInfo,
    StrategyInfo,
)


class TestPlanCreateRequest:
    """Tests for PlanCreateRequest model."""

    def test_valid_minimal(self):
        """Accepts minimal required fields."""
        req = PlanCreateRequest(url="https://example.com", objective="Extract data")
        assert req.url == "https://example.com"
        assert req.objective == "Extract data"
        assert req.hints is None
        assert req.force_regenerate is False
        assert req.save is False

    def test_missing_url_raises(self):
        """Raises ValidationError when url is missing."""
        with pytest.raises(ValidationError):
            PlanCreateRequest(objective="Extract data")

    def test_missing_objective_raises(self):
        """Raises ValidationError when objective is missing."""
        with pytest.raises(ValidationError):
            PlanCreateRequest(url="https://example.com")

    def test_all_fields(self):
        """Accepts all fields with explicit values."""
        req = PlanCreateRequest(
            url="https://example.com",
            objective="Extract data",
            hints={"pagination": True, "auth": "cookie"},
            force_regenerate=True,
            save=True,
        )
        assert req.hints == {"pagination": True, "auth": "cookie"}
        assert req.force_regenerate is True
        assert req.save is True

    def test_json_serialization(self):
        """Model serializes to JSON-compatible dict."""
        req = PlanCreateRequest(url="https://example.com", objective="Extract")
        data = req.model_dump()
        assert isinstance(data, dict)
        assert data["url"] == "https://example.com"
        assert data["hints"] is None


class TestScrapeRequest:
    """Tests for ScrapeRequest model."""

    def test_minimal(self):
        """Accepts just a url."""
        req = ScrapeRequest(url="https://example.com")
        assert req.url == "https://example.com"
        assert req.plan_name is None
        assert req.plan is None
        assert req.objective is None
        assert req.steps is None
        assert req.selectors is None
        assert req.save_plan is False
        assert req.browser_config_override is None

    def test_missing_url_raises(self):
        """Raises ValidationError when url is missing."""
        with pytest.raises(ValidationError):
            ScrapeRequest()

    def test_with_plan_name(self):
        """Accepts plan_name for saved plan lookup."""
        req = ScrapeRequest(url="https://example.com", plan_name="my-plan")
        assert req.plan_name == "my-plan"

    def test_with_inline_plan(self):
        """Accepts inline plan dict."""
        plan_data = {"steps": [{"action": "navigate"}], "url": "https://example.com"}
        req = ScrapeRequest(url="https://example.com", plan=plan_data)
        assert req.plan == plan_data

    def test_with_inline_steps(self):
        """Accepts raw steps + selectors for ad-hoc execution."""
        req = ScrapeRequest(
            url="https://example.com",
            steps=[{"action": "navigate", "url": "https://example.com"}],
            selectors=[{"name": "title", "selector": "h1"}],
        )
        assert len(req.steps) == 1
        assert len(req.selectors) == 1

    def test_with_browser_config_override(self):
        """Accepts browser config override dict."""
        req = ScrapeRequest(
            url="https://example.com",
            browser_config_override={"headless": False, "browser": "firefox"},
        )
        assert req.browser_config_override["headless"] is False

    def test_json_serialization(self):
        """Model serializes to JSON-compatible dict."""
        req = ScrapeRequest(url="https://example.com", save_plan=True)
        data = req.model_dump()
        assert data["save_plan"] is True
        assert data["plan_name"] is None


class TestCrawlRequest:
    """Tests for CrawlRequest model."""

    def test_defaults(self):
        """Default values match spec: depth=1, strategy='bfs', concurrency=1."""
        req = CrawlRequest(start_url="https://example.com")
        assert req.start_url == "https://example.com"
        assert req.depth == 1
        assert req.max_pages is None
        assert req.follow_selector is None
        assert req.follow_pattern is None
        assert req.plan_name is None
        assert req.plan is None
        assert req.objective is None
        assert req.save_plan is False
        assert req.strategy == "bfs"
        assert req.concurrency == 1

    def test_missing_start_url_raises(self):
        """Raises ValidationError when start_url is missing."""
        with pytest.raises(ValidationError):
            CrawlRequest()

    def test_invalid_strategy_raises(self):
        """Raises ValidationError for invalid strategy value."""
        with pytest.raises(ValidationError):
            CrawlRequest(start_url="https://example.com", strategy="invalid")

    def test_valid_strategies(self):
        """Accepts both 'bfs' and 'dfs' strategies."""
        bfs = CrawlRequest(start_url="https://example.com", strategy="bfs")
        dfs = CrawlRequest(start_url="https://example.com", strategy="dfs")
        assert bfs.strategy == "bfs"
        assert dfs.strategy == "dfs"

    def test_all_fields(self):
        """Accepts all fields with explicit values."""
        req = CrawlRequest(
            start_url="https://example.com",
            depth=3,
            max_pages=100,
            follow_selector="a.next-page",
            follow_pattern=r"/products/\d+",
            plan_name="product-plan",
            objective="Extract product details",
            save_plan=True,
            strategy="dfs",
            concurrency=5,
        )
        assert req.depth == 3
        assert req.max_pages == 100
        assert req.strategy == "dfs"
        assert req.concurrency == 5

    def test_depth_zero_allowed(self):
        """Depth of 0 is valid (scrape only start page)."""
        req = CrawlRequest(start_url="https://example.com", depth=0)
        assert req.depth == 0

    def test_concurrency_minimum(self):
        """Concurrency must be at least 1."""
        with pytest.raises(ValidationError):
            CrawlRequest(start_url="https://example.com", concurrency=0)

    def test_json_serialization(self):
        """Model serializes to JSON-compatible dict."""
        req = CrawlRequest(start_url="https://example.com", depth=2)
        data = req.model_dump()
        assert data["depth"] == 2
        assert data["strategy"] == "bfs"


class TestPlanSaveRequest:
    """Tests for PlanSaveRequest model."""

    def test_valid(self):
        """Accepts plan dict with default overwrite=False."""
        req = PlanSaveRequest(plan={"url": "https://example.com", "steps": []})
        assert req.plan["url"] == "https://example.com"
        assert req.overwrite is False

    def test_missing_plan_raises(self):
        """Raises ValidationError when plan is missing."""
        with pytest.raises(ValidationError):
            PlanSaveRequest()

    def test_overwrite_true(self):
        """Accepts overwrite=True."""
        req = PlanSaveRequest(plan={"steps": []}, overwrite=True)
        assert req.overwrite is True


class TestActionInfo:
    """Tests for ActionInfo response model."""

    def test_valid(self):
        """Accepts all fields."""
        info = ActionInfo(
            name="click",
            description="Click an element",
            fields={"selector": {"type": "string"}},
            required=["selector"],
        )
        assert info.name == "click"
        assert info.description == "Click an element"
        assert "selector" in info.fields

    def test_defaults(self):
        """Empty fields and required by default."""
        info = ActionInfo(name="refresh")
        assert info.description == ""
        assert info.fields == {}
        assert info.required == []

    def test_json_serialization(self):
        """Model serializes cleanly."""
        info = ActionInfo(name="navigate", fields={"url": {"type": "string"}})
        data = info.model_dump()
        assert data["name"] == "navigate"


class TestDriverTypeInfo:
    """Tests for DriverTypeInfo response model."""

    def test_valid(self):
        """Accepts name and browsers list."""
        info = DriverTypeInfo(
            name="selenium",
            browsers=["chrome", "firefox", "edge"],
        )
        assert info.name == "selenium"
        assert "chrome" in info.browsers

    def test_defaults(self):
        """Empty browsers list by default."""
        info = DriverTypeInfo(name="playwright")
        assert info.browsers == []


class TestStrategyInfo:
    """Tests for StrategyInfo response model."""

    def test_valid(self):
        """Accepts name and description."""
        info = StrategyInfo(name="bfs", description="Breadth-first search crawl strategy")
        assert info.name == "bfs"
        assert "Breadth-first" in info.description

    def test_defaults(self):
        """Empty description by default."""
        info = StrategyInfo(name="dfs")
        assert info.description == ""
