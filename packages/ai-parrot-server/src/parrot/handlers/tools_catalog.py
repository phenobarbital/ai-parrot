"""Handler for the tool catalog endpoint (FEAT-149 TASK-1039).

Exposes the ToolkitResolver entries (built-ins, ``parrot_tools`` and host toolkits) as a read-only JSON catalog so the
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

import asyncio
import inspect
from typing import Any, Dict, List

from navconfig.logging import logging as nav_logging
from navigator.views import BaseView
from navigator_auth.decorators import is_authenticated, user_session
from parrot.handlers.scope import get_scope_resolver, has_installed_resolver
from parrot.tools.resolver import ToolkitEntry, get_toolkit_resolver
from parrot.tools.toolkit import AbstractToolkit, effective_access
from parrot.tools.tooling_policy import TenantToolingRefused, ToolingSubject, get_tenant_tooling_policy

_logger = nav_logging.getLogger("Parrot.ToolCatalogHandler")

# Cache the enriched catalog after the first build (avoids repeated imports).
_CATALOG_CACHE: List[Dict[str, Any]] | None = None


def _enrich(entry: Dict[str, Any], cls: type) -> None:
    """Add the first docstring line as ``description`` and the ``category`` of ``cls`` to ``entry``."""
    doc = (cls.__doc__ or "").strip()
    if doc:
        # Take only the first non-empty line as the description.
        entry["description"] = doc.split("\n")[0].strip()
    category = getattr(cls, "category", None)
    if category:
        entry["category"] = str(category)


_TOOLKIT_MANAGEMENT = frozenset(
    {"get_tools", "get_tools_filtered", "get_tools_sync", "get_tool", "list_tool_names", "start", "stop", "cleanup",
     "config_schema", "config_options"}
)


def _toolkit_access(cls: type) -> Dict[str, List[str]] | None:
    """``{"read": [...], "write": [...]}`` of a toolkit's public async methods; ``None`` when no access is declared."""
    summary: Dict[str, List[str]] = {"read": [], "write": []}
    excluded = _TOOLKIT_MANAGEMENT | set(getattr(cls, "exclude_tools", ()))
    for name in sorted(dir(cls)):
        if name.startswith("_") or name in excluded or not inspect.iscoroutinefunction(getattr(cls, name, None)):
            continue
        access = effective_access(cls, name)
        if access is not None:
            summary[access].append(name)
    return summary if summary["read"] or summary["write"] else None


def _entry_access(cls: type | None) -> Any:
    """Access of a catalogue class: a toolkit's per-method summary, a tool's ``access``, ``None`` when unknown."""
    if cls is None:
        return None
    if isinstance(cls, type) and issubclass(cls, AbstractToolkit):
        return _toolkit_access(cls)
    return getattr(cls, "access", None)


def _catalog_entry(item: ToolkitEntry, cls: type | None) -> Dict[str, Any]:
    """Build one catalogue dict for a resolver entry; ``cls`` is its resolved class (if any)."""
    dotted_path = item.dotted_path
    if dotted_path is None and cls is not None:
        dotted_path = f"{cls.__module__}.{cls.__qualname__}"
    entry: Dict[str, Any] = {
        "slug": item.slug,
        "dotted_path": dotted_path,
        "source": item.source,
        "access": _entry_access(cls),
    }
    if cls is not None:
        _enrich(entry, cls)
    return entry


def _build_catalog() -> List[Dict[str, Any]]:
    """Build a sorted list of tool entries from the shared ToolkitResolver (FEAT-622 M2).

    Performs a best-effort import of each tool class to extract a
    description from its docstring.  Entries where the class cannot be
    imported still appear in the output — they just lack a ``description``.

    Returns:
        Sorted list of ``{slug, dotted_path, source, access, description?, category?}`` dicts.
    """
    resolver = get_toolkit_resolver()
    entries: List[Dict[str, Any]] = []
    for item in resolver.entries():
        try:
            cls = resolver.resolve(item.slug)
        except Exception:  # noqa: BLE001
            # Never let an import error break the catalog response.
            _logger.debug("Could not enrich tool %r (%s)", item.slug, item.dotted_path)
            cls = None
        entries.append(_catalog_entry(item, cls))
    return entries


def filter_catalog_for(app: Any, subject: ToolingSubject | None, catalog: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Entries the tenant policy permits (unchanged when it does not apply); host ``dotted_path`` is never exposed."""
    return [_redact_host_path(entry) for entry in _permitted(app, subject, catalog)]


def _redact_host_path(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Copy of ``entry`` without the dotted path when it is a host toolkit."""
    if entry.get("source") != "host":
        return entry
    return {**entry, "dotted_path": None}


def _permitted(app: Any, subject: ToolingSubject | None, catalog: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Policy filtering step of :func:`filter_catalog_for`."""
    if subject is None:
        return catalog
    policy = get_tenant_tooling_policy(app)
    if subject.tenant is None and not policy.apply_to_global:
        return catalog
    permitted: List[Dict[str, Any]] = []
    for entry in catalog:
        try:
            policy.check_tool(entry["slug"], subject=subject)
        except TenantToolingRefused:
            continue
        permitted.append(entry)
    return permitted


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
            # FIX-9: run blocking importlib.import_module calls in a thread
            # to avoid blocking the event loop.
            _CATALOG_CACHE = await asyncio.to_thread(_build_catalog)
            self.logger.info("Tool catalog built: %d entries", len(_CATALOG_CACHE))

        app = self.request.app
        tenant = None
        if has_installed_resolver(app):
            scope = await get_scope_resolver(app).resolve(self.request)
            tenant = scope.tenant or None
        subject = ToolingSubject(tenant=tenant, agent_id=None, actor=None, phase="attach")
        return self.json_response(filter_catalog_for(app, subject, _CATALOG_CACHE))
