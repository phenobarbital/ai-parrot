"""Pydantic request/response models for the Scraping HTTP API.

These models define the data contract between the navigator-frontend-next
ScrapingToolkit Svelte UI and the scraping handler endpoints at /api/v1/scraping/.
"""
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class PlanCreateRequest(BaseModel):
    """Request body for POST /api/v1/scraping/plans (create a new plan via LLM)."""

    url: str = Field(..., description="Target URL for the scraping plan")
    objective: str = Field(..., description="What data to extract from the page")
    hints: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional hints for the LLM plan generator (e.g. pagination, auth)",
    )
    force_regenerate: bool = Field(
        default=False,
        description="Force plan regeneration even if a cached plan exists",
    )
    save: bool = Field(
        default=False,
        description="Persist the generated plan to disk immediately",
    )


class ScrapeRequest(BaseModel):
    """Request body for POST /api/v1/scraping/scrape."""

    url: str = Field(..., description="URL to scrape")
    plan_name: Optional[str] = Field(
        default=None,
        description="Name of a saved plan to use",
    )
    plan: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Inline plan definition (overrides plan_name)",
    )
    objective: Optional[str] = Field(
        default=None,
        description="Objective for auto-generating a plan if no plan is provided",
    )
    steps: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Raw action steps for ad-hoc execution (bypasses plan resolution)",
    )
    selectors: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="CSS/XPath selectors to apply after step execution",
    )
    save_plan: bool = Field(
        default=False,
        description="Save the resolved plan after successful execution",
    )
    browser_config_override: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Override default DriverConfig settings for this request",
    )


class CrawlRequest(BaseModel):
    """Request body for POST /api/v1/scraping/crawl."""

    start_url: str = Field(..., description="Starting URL for the crawl")
    depth: int = Field(default=1, ge=0, description="Maximum crawl depth")
    max_pages: Optional[int] = Field(
        default=None,
        ge=1,
        description="Maximum number of pages to crawl",
    )
    follow_selector: Optional[str] = Field(
        default=None,
        description="CSS selector for links to follow",
    )
    follow_pattern: Optional[str] = Field(
        default=None,
        description="Regex pattern for URLs to follow",
    )
    plan_name: Optional[str] = Field(
        default=None,
        description="Name of a saved plan to apply to each crawled page",
    )
    plan: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Inline plan definition to apply to each crawled page",
    )
    objective: Optional[str] = Field(
        default=None,
        description="Objective for auto-generating a plan if no plan is provided",
    )
    save_plan: bool = Field(
        default=False,
        description="Save the resolved plan after successful execution",
    )
    strategy: Literal["bfs", "dfs"] = Field(
        default="bfs",
        description="Crawl traversal strategy",
    )
    concurrency: int = Field(
        default=1,
        ge=1,
        description="Number of concurrent scraping workers",
    )


class PlanSaveRequest(BaseModel):
    """Request body for PUT /api/v1/scraping/plans/{name} (save/update a plan)."""

    plan: Dict[str, Any] = Field(
        ...,
        description="Full plan data to save",
    )
    overwrite: bool = Field(
        default=False,
        description="Overwrite existing plan with same fingerprint",
    )


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class ActionInfo(BaseModel):
    """Description of a single browser action type for the UI."""

    name: str = Field(..., description="Action identifier (e.g. 'click', 'navigate')")
    description: str = Field(default="", description="Human-readable description from docstring")
    fields: Dict[str, Any] = Field(
        default_factory=dict,
        description="JSON schema of action parameters",
    )
    required: List[str] = Field(
        default_factory=list,
        description="List of required field names",
    )


class DriverTypeInfo(BaseModel):
    """Available driver type and its supported browsers."""

    name: str = Field(..., description="Driver type identifier (e.g. 'selenium', 'playwright')")
    browsers: List[str] = Field(
        default_factory=list,
        description="List of supported browser names",
    )


class StrategyInfo(BaseModel):
    """Crawl strategy description for the UI."""

    name: str = Field(..., description="Strategy identifier (e.g. 'bfs', 'dfs')")
    description: str = Field(default="", description="Human-readable description")
