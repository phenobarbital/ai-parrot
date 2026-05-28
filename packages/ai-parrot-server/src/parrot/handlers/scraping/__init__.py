"""Scraping HTTP handlers for exposing WebScrapingToolkit over REST API."""
from aiohttp import web

from .handler import ScrapingHandler
from .info import ScrapingInfoHandler
from .models import (
    ActionInfo,
    CrawlRequest,
    DriverTypeInfo,
    PlanCreateRequest,
    PlanSaveRequest,
    ScrapeRequest,
    StrategyInfo,
)

__all__ = (
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
)


def setup_scraping_routes(app: web.Application) -> None:
    """Register all scraping handler routes on the aiohttp application.

    This is the single entry point for integrating scraping endpoints
    into an aiohttp app. It registers:
    - ScrapingHandler class-based view routes (plan CRUD, scrape, crawl, jobs)
    - ScrapingInfoHandler method-based routes (actions, drivers, config, strategies)
    - Startup/cleanup signals for toolkit and job manager lifecycle

    Args:
        app: The aiohttp web application.
    """
    # Register class-based view routes + lifecycle signals
    ScrapingHandler.setup(app)

    # Register info handler GET routes
    info_handler = ScrapingInfoHandler()
    info_handler.setup(app)
