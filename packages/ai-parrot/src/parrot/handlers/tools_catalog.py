"""Handler for the tool catalog endpoint (FEAT-149 TASK-1039).

Exposes the ``parrot_tools.TOOL_REGISTRY`` as a read-only JSON catalog so the
frontend can present available tools when configuring an ephemeral user agent.

Route:
    GET /api/v1/tools/catalog

Response::

    [
      {
        "slug": "weather",
        "dotted_path": "parrot_tools.weather.WeatherTool",
        "description": "Get the current weather for a location."
      },
      ...
    ]

Items are sorted by ``slug`` for deterministic responses.
"""
from __future__ import annotations

import importlib
import logging
from typing import Any, Dict, List

from navconfig.logging import logging as nav_logging
from navigator.views import BaseView
from navigator_auth.decorators import is_authenticated, user_session

try:
    from parrot_tools import TOOL_REGISTRY  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover — parrot_tools may not be installed in all envs
    TOOL_REGISTRY: Dict[str, str] = {}

_logger = nav_logging.getLogger("Parrot.ToolCatalogHandler")

# Cache the enriched catalog after the first build (avoids repeated imports).
_CATALOG_CACHE: List[Dict[str, Any]] | None = None


def _build_catalog() -> List[Dict[str, Any]]:
    """Build a sorted list of tool entries from ``TOOL_REGISTRY``.

    Performs a best-effort import of each tool class to extract a
    description from its docstring.  Entries where the class cannot be
    imported still appear in the output — they just lack a ``description``.

    Returns:
        Sorted list of ``{slug, dotted_path, description?, category?}`` dicts.
    """
    entries: List[Dict[str, Any]] = []

    for slug, dotted_path in sorted(TOOL_REGISTRY.items()):
        entry: Dict[str, Any] = {
            "slug": slug,
            "dotted_path": dotted_path,
        }

        # Best-effort: extract docstring / category from the tool class.
        try:
            module_path, class_name = dotted_path.rsplit(".", 1)
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name, None)
            if cls is not None:
                doc = (cls.__doc__ or "").strip()
                if doc:
                    # Take only the first non-empty line as the description.
                    entry["description"] = doc.split("\n")[0].strip()
                category = getattr(cls, "category", None)
                if category:
                    entry["category"] = str(category)
        except Exception:  # noqa: BLE001
            # Never let an import error break the catalog response.
            _logger.debug("Could not enrich tool %r (%s)", slug, dotted_path)

        entries.append(entry)

    return entries


@is_authenticated()
@user_session()
class ToolCatalogHandler(BaseView):
    """Read-only handler that returns the global tool registry as JSON.

    Only ``GET`` is supported.  The catalog is built on the first request
    and cached for the lifetime of the process.
    """

    _logger_name: str = "Parrot.ToolCatalogHandler"

    def post_init(self, *args, **kwargs) -> None:
        """Initialise the instance logger."""
        self.logger = nav_logging.getLogger(self._logger_name)

    async def get(self) -> Any:
        """Return the tool catalog as a JSON array.

        Returns:
            HTTP 200 with a JSON array of ``{slug, dotted_path, description?}``
            entries sorted by slug.
        """
        global _CATALOG_CACHE  # noqa: PLW0603

        if _CATALOG_CACHE is None:
            _CATALOG_CACHE = _build_catalog()
            self.logger.info(
                "Tool catalog built: %d entries", len(_CATALOG_CACHE)
            )

        return self.json_response(_CATALOG_CACHE)
