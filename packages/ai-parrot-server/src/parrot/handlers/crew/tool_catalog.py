"""Curated tool catalog for the crew builder UI.

Exposes a hand-picked list of tools/toolkits that the frontend can present
when configuring agents inside a crew.  Each entry carries display metadata
and an optional JSON Schema fragment for user-configurable parameters.

Route:
    GET /api/v1/crew/tools
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from navconfig.logging import logging
from navigator.views import BaseView
from navigator_auth.decorators import is_authenticated, user_session


CREW_TOOL_CATALOG: List[Dict[str, Any]] = [
    # ── Research ──────────────────────────────────────────────────────
    {
        "slug": "ibisworld",
        "name": "IBISWorldTool",
        "display_name": "IBISWorld Research",
        "description": "Search IBISWorld industry research and extract detailed content from articles",
        "category": "research",
        "type": "tool",
        "config_schema": None,
    },
    {
        "slug": "google_site_search",
        "name": "GoogleSiteSearchTool",
        "display_name": "Google Site Search",
        "description": "Search within specific websites using Google Custom Search API",
        "category": "research",
        "type": "tool",
        "config_schema": {
            "sites": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Domains to restrict search to",
                "examples": ["ibisworld.com", "statista.com"],
            }
        },
    },
    {
        "slug": "google_search",
        "name": "GoogleSearchTool",
        "display_name": "Google Search",
        "description": "Search the web using Google Custom Search API with optional content preview",
        "category": "research",
        "type": "tool",
        "config_schema": None,
    },
    {
        "slug": "ddg_search",
        "name": "DdgSearchTool",
        "display_name": "DuckDuckGo Search",
        "description": "Privacy-focused web search via DuckDuckGo",
        "category": "research",
        "type": "tool",
        "config_schema": None,
    },
    {
        "slug": "bing_search",
        "name": "BingSearchTool",
        "display_name": "Bing Search",
        "description": "Web search using the Bing Search API",
        "category": "research",
        "type": "tool",
        "config_schema": None,
    },
    {
        "slug": "serpapi",
        "name": "SerpApiSearchTool",
        "display_name": "SerpAPI Search",
        "description": "Search engine results via SerpAPI (Google, Bing, Yahoo, etc.)",
        "category": "research",
        "type": "tool",
        "config_schema": None,
    },
    {
        "slug": "sitesearch",
        "name": "SiteSearchToolkit",
        "display_name": "Site Search",
        "description": "Full-text search toolkit for crawling and querying website content",
        "category": "research",
        "type": "toolkit",
        "config_schema": {
            "sites": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Domains to crawl and index for search",
                "examples": ["docs.example.com"],
            }
        },
    },
    {
        "slug": "web_scraping",
        "name": "WebScrapingToolkit",
        "display_name": "Web Scraping",
        "description": "Extract structured data from web pages using multiple scraping methods",
        "category": "research",
        "type": "toolkit",
        "config_schema": None,
    },
    {
        "slug": "arxiv",
        "name": "ArxivTool",
        "display_name": "ArXiv Papers",
        "description": "Search and retrieve academic papers from ArXiv",
        "category": "research",
        "type": "tool",
        "config_schema": None,
    },
    {
        "slug": "product_info",
        "name": "ProductInfoTool",
        "display_name": "Product Information",
        "description": "Look up detailed product information by name or identifier",
        "category": "research",
        "type": "tool",
        "config_schema": None,
    },
    {
        "slug": "product_list",
        "name": "ProductListTool",
        "display_name": "Product Listing",
        "description": "Search and list products matching given criteria",
        "category": "research",
        "type": "tool",
        "config_schema": None,
    },
    # ── Geolocation ───────────────────────────────────────────────────
    {
        "slug": "google_location",
        "name": "GoogleLocationTool",
        "display_name": "Google Location",
        "description": "Find location information using Google Geocoding API",
        "category": "geolocation",
        "type": "tool",
        "config_schema": None,
    },
    {
        "slug": "google_routes",
        "name": "GoogleRoutesTool",
        "display_name": "Google Routes",
        "description": "Calculate routes, distances, and travel times between locations",
        "category": "geolocation",
        "type": "tool",
        "config_schema": None,
    },
    # ── Finance ───────────────────────────────────────────────────────
    {
        "slug": "yfinance",
        "name": "YFinanceTool",
        "display_name": "Yahoo Finance",
        "description": "Financial data, stock prices, and market information from Yahoo Finance",
        "category": "finance",
        "type": "tool",
        "config_schema": None,
    },
    {
        "slug": "bloomberg",
        "name": "BloombergTool",
        "display_name": "Bloomberg",
        "description": "Access Bloomberg financial data and market analytics",
        "category": "finance",
        "type": "tool",
        "config_schema": None,
    },
    {
        "slug": "fred_api",
        "name": "FredAPITool",
        "display_name": "FRED Economic Data",
        "description": "Federal Reserve Economic Data — macroeconomic time series and indicators",
        "category": "finance",
        "type": "tool",
        "config_schema": None,
    },
    {
        "slug": "technical_analysis",
        "name": "TechnicalAnalysisTool",
        "display_name": "Technical Analysis",
        "description": "Technical analysis indicators and charting for financial instruments",
        "category": "finance",
        "type": "tool",
        "config_schema": None,
    },
    # ── Company Intelligence ──────────────────────────────────────────
    {
        "slug": "company_info",
        "name": "CompanyInfoToolkit",
        "display_name": "Company Research",
        "description": "Unified company intelligence — ZoomInfo, LeadIQ, Explorium, RocketReach, SICCode",
        "category": "company_intel",
        "type": "toolkit",
        "config_schema": None,
    },
    # ── Data & Analysis ───────────────────────────────────────────────
    {
        "slug": "correlation_analysis",
        "name": "CorrelationAnalysisTool",
        "display_name": "Correlation Analysis",
        "description": "Compute and visualize correlations between variables in a dataset",
        "category": "data_analysis",
        "type": "tool",
        "config_schema": None,
    },
    {
        "slug": "composite_score",
        "name": "CompositeScoreTool",
        "display_name": "Composite Scoring",
        "description": "Build weighted composite scores from multiple metrics",
        "category": "data_analysis",
        "type": "tool",
        "config_schema": None,
    },
    {
        "slug": "statistical_tests",
        "name": "StatisticalTestsTool",
        "display_name": "Statistical Tests",
        "description": "Run hypothesis tests (t-test, chi-square, ANOVA, etc.) on datasets",
        "category": "data_analysis",
        "type": "tool",
        "config_schema": None,
    },
]


@is_authenticated()
@user_session()
class CrewToolCatalogHandler(BaseView):
    """Returns the curated tool catalog for the crew builder UI."""

    _logger_name: str = "Parrot.CrewToolCatalogHandler"

    def post_init(self, *args, **kwargs) -> None:
        self.logger = logging.getLogger(self._logger_name)

    async def get(self) -> Any:
        """Return the curated crew tool catalog as a JSON array."""
        return self.json_response(CREW_TOOL_CATALOG)
