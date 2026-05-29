"""ScrapingInfoHandler — GET-only reference metadata endpoints for the Scraping UI.

Serves browser action catalog, driver types, driver configuration schema,
and crawl strategy definitions. Designed to be consumed by the ScrapingToolkit
Svelte component in navigator-frontend-next for dynamic form rendering.
"""
from typing import Any, Dict, List

from aiohttp import web
from datamodel.parsers.json import json_encoder  # pylint: disable=E0611
from navconfig.logging import logging
from navigator.views import BaseHandler

from parrot.tools.scraping.models import ACTION_MAP
from parrot.tools.scraping.toolkit_models import DriverConfig


# ---------------------------------------------------------------------------
# Driver metadata (static — no runtime introspection needed)
# ---------------------------------------------------------------------------

_DRIVER_TYPES: List[Dict[str, Any]] = [
    {
        "name": "selenium",
        "browsers": ["chrome", "firefox", "edge", "safari", "undetected"],
    },
    {
        "name": "playwright",
        "browsers": ["chromium", "firefox", "webkit"],
    },
]

_STRATEGIES: List[Dict[str, str]] = [
    {
        "name": "bfs",
        "description": (
            "Breadth-first search: visits all pages at depth N before "
            "moving to depth N+1. Best for comprehensive, level-by-level crawling."
        ),
    },
    {
        "name": "dfs",
        "description": (
            "Depth-first search: follows links as deep as possible before "
            "backtracking. Best for drilling into specific content paths."
        ),
    },
]


def _build_action_catalog() -> List[Dict[str, Any]]:
    """Introspect all BrowserAction subclasses to build a UI-friendly catalog."""
    actions: List[Dict[str, Any]] = []
    for action_name, action_class in ACTION_MAP.items():
        schema = action_class.model_json_schema()
        actions.append({
            "name": action_name,
            "description": (action_class.__doc__ or "").strip(),
            "fields": schema.get("properties", {}),
            "required": schema.get("required", []),
        })
    return actions


class ScrapingInfoHandler(BaseHandler):
    """Method-based handler serving reference data for the Scraping UI.

    All endpoints are GET-only and return static/introspected metadata
    about browser actions, driver types, driver configuration, and
    crawl strategies.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger("Parrot.ScrapingInfoHandler")
        # Cache the action catalog since it doesn't change at runtime
        self._action_catalog = _build_action_catalog()

    async def get_actions(self, request: web.Request) -> web.Response:
        """GET /api/v1/scraping/info/actions — list all BrowserAction types.

        Returns a JSON array of action types with name, description,
        field schemas (JSON Schema), and required fields.
        """
        return web.json_response(
            {"actions": self._action_catalog},
            dumps=json_encoder,
        )

    async def get_drivers(self, request: web.Request) -> web.Response:
        """GET /api/v1/scraping/info/drivers — list driver types and browsers.

        Returns available driver types (selenium, playwright) with
        their supported browser names.
        """
        return web.json_response(
            {"drivers": _DRIVER_TYPES},
            dumps=json_encoder,
        )

    async def get_config_schema(self, request: web.Request) -> web.Response:
        """GET /api/v1/scraping/info/config — DriverConfig JSON schema.

        Returns the full JSON Schema for DriverConfig, enabling the UI
        to dynamically render configuration forms.
        """
        schema = DriverConfig.model_json_schema()
        return web.json_response(
            {"schema": schema},
            dumps=json_encoder,
        )

    async def get_strategies(self, request: web.Request) -> web.Response:
        """GET /api/v1/scraping/info/strategies — crawl strategy definitions.

        Returns available crawl strategies (bfs, dfs) with descriptions.
        """
        return web.json_response(
            {"strategies": _STRATEGIES},
            dumps=json_encoder,
        )

    def setup(self, app: web.Application) -> None:
        """Register all info GET routes on the aiohttp application."""
        app.router.add_route(
            "GET", "/api/v1/scraping/info/actions", self.get_actions
        )
        app.router.add_route(
            "GET", "/api/v1/scraping/info/drivers", self.get_drivers
        )
        app.router.add_route(
            "GET", "/api/v1/scraping/info/config", self.get_config_schema
        )
        app.router.add_route(
            "GET", "/api/v1/scraping/info/strategies", self.get_strategies
        )
