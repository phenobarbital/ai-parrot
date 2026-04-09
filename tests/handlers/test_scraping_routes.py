"""Unit tests for scraping route registration via setup_scraping_routes."""
from aiohttp import web

from parrot.handlers.scraping import setup_scraping_routes


def _get_registered_paths(app: web.Application) -> set:
    """Extract all registered route paths from the app router."""
    paths = set()
    for resource in app.router.resources():
        info = resource.get_info()
        path = info.get("formatter") or info.get("path", "")
        if path:
            paths.add(path)
    return paths


class TestSetupScrapingRoutes:
    """Tests for setup_scraping_routes() route registration."""

    def test_registers_plan_routes(self):
        """Plan CRUD routes are registered."""
        app = web.Application()
        setup_scraping_routes(app)
        paths = _get_registered_paths(app)
        assert "/api/v1/scraping/plans" in paths
        assert "/api/v1/scraping/plans/{name}" in paths

    def test_registers_execution_routes(self):
        """Scrape and crawl execution routes are registered."""
        app = web.Application()
        setup_scraping_routes(app)
        paths = _get_registered_paths(app)
        assert "/api/v1/scraping/scrape" in paths
        assert "/api/v1/scraping/crawl" in paths

    def test_registers_job_status_route(self):
        """Job status route is registered."""
        app = web.Application()
        setup_scraping_routes(app)
        paths = _get_registered_paths(app)
        assert "/api/v1/scraping/jobs/{name}" in paths

    def test_registers_info_routes(self):
        """Info handler GET routes are registered."""
        app = web.Application()
        setup_scraping_routes(app)
        paths = _get_registered_paths(app)
        assert "/api/v1/scraping/info/actions" in paths
        assert "/api/v1/scraping/info/drivers" in paths
        assert "/api/v1/scraping/info/config" in paths
        assert "/api/v1/scraping/info/strategies" in paths

    def test_registers_lifecycle_signals(self):
        """Startup and cleanup signals are registered."""
        app = web.Application()
        initial_startup = len(app.on_startup)
        initial_cleanup = len(app.on_cleanup)
        setup_scraping_routes(app)
        assert len(app.on_startup) == initial_startup + 1
        assert len(app.on_cleanup) == initial_cleanup + 1

    def test_total_route_count(self):
        """All 9 routes are registered (5 view + 4 info)."""
        app = web.Application()
        setup_scraping_routes(app)
        paths = _get_registered_paths(app)
        expected = {
            "/api/v1/scraping/plans",
            "/api/v1/scraping/plans/{name}",
            "/api/v1/scraping/scrape",
            "/api/v1/scraping/crawl",
            "/api/v1/scraping/jobs/{name}",
            "/api/v1/scraping/info/actions",
            "/api/v1/scraping/info/drivers",
            "/api/v1/scraping/info/config",
            "/api/v1/scraping/info/strategies",
        }
        assert expected.issubset(paths)


class TestImports:
    """Tests for package imports."""

    def test_import_setup_function(self):
        """setup_scraping_routes can be imported."""
        from parrot.handlers.scraping import setup_scraping_routes
        assert callable(setup_scraping_routes)

    def test_import_handlers(self):
        """Both handler classes can be imported."""
        from parrot.handlers.scraping import ScrapingHandler, ScrapingInfoHandler
        assert ScrapingHandler is not None
        assert ScrapingInfoHandler is not None

    def test_import_models(self):
        """All request/response models can be imported."""
        from parrot.handlers.scraping import (
            PlanCreateRequest,
            ScrapeRequest,
            CrawlRequest,
            PlanSaveRequest,
            ActionInfo,
            DriverTypeInfo,
            StrategyInfo,
        )
        assert PlanCreateRequest is not None
        assert ScrapeRequest is not None
        assert CrawlRequest is not None
        assert PlanSaveRequest is not None
        assert ActionInfo is not None
        assert DriverTypeInfo is not None
        assert StrategyInfo is not None

    def test_all_exports(self):
        """__all__ contains all expected symbols."""
        import parrot.handlers.scraping as pkg
        expected = {
            "ScrapingHandler",
            "ScrapingInfoHandler",
            "PlanCreateRequest",
            "ScrapeRequest",
            "CrawlRequest",
            "PlanSaveRequest",
            "ActionInfo",
            "DriverTypeInfo",
            "StrategyInfo",
            "setup_scraping_routes",
        }
        assert expected == set(pkg.__all__)
