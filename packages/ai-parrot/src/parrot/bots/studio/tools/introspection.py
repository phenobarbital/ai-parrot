"""Read-only introspection tools (no confirmation)."""

from __future__ import annotations

from parrot.tools import tool

from ._context import _require_app, _studio_caller, _studio_partition_and_services


@tool(
    name="list_agent_base_classes",
    description="List available agent base classes (name, module, " "docstring, configurable constructor params).",
)
async def list_agent_base_classes() -> list:
    """List agent base classes via the Studio catalog (TASK-2519)."""
    from parrot.handlers.studio.catalog import _build_base_classes_catalog

    return _build_base_classes_catalog()


@tool(
    name="list_available_tools",
    description="List available tools/toolkits from the framework's tool registry.",
)
async def list_available_tools() -> list:
    """List the tool catalog via the existing tools_catalog registry."""
    from parrot.handlers.tools_catalog import _build_catalog, filter_catalog_for
    from parrot.tools.scope import current_tool_scope
    from parrot.tools.tooling_policy import ToolingSubject
    from parrot.utils.helpers import current_context

    from parrot.handlers.scope import has_installed_resolver

    catalog = _build_catalog()
    scope = current_tool_scope()
    ctx = current_context()
    app = getattr(ctx, "app", None) or {}
    if scope is None:
        # An opted-in (tenant-aware) host with no resolved caller scope: fail closed, never the full catalogue.
        return [] if has_installed_resolver(app) else catalog
    # A bound caller scope: list only what the tenant tooling policy permits (no app => fail closed: deny_all).
    subject = ToolingSubject(tenant=scope.caller.tenant, agent_id=None, actor=scope.caller.user_id, phase="attach")
    return filter_catalog_for(app, subject, catalog)


@tool(
    name="list_existing_agents",
    description="List agents already registered in the live AgentRegistry.",
)
async def list_existing_agents() -> list:
    """List registered agent names (registry-origin only)."""
    app = _require_app()
    caller = _studio_caller()
    if caller is not None:   # a bound scope: the Studio rows the caller can see in ITS partition, nothing global
        return await _visible_studio_agents(app, caller)
    from parrot.handlers.scope import has_installed_resolver  # lazy: server satellite

    if has_installed_resolver(app):   # opted-in host, no scope bound: fail closed, never the global registry
        return []
    manager = app.get("bot_manager")
    if manager is None or manager.registry is None:
        return []
    return [meta.name for meta in manager.registry.list_agents()]


async def _visible_studio_agents(app, caller) -> list:
    """Names of the agents of the caller's partition that the access rule lets it see (fail closed: ``[]``)."""
    from parrot.handlers.studio.access import StudioAccess, _store_record  # lazy: server satellite

    ps = await _studio_partition_and_services(app)
    if ps is None or isinstance(ps, dict):
        return []
    part, services = ps
    access = StudioAccess(caller, opted_in=True)
    return [rec.name for rec in await services.agents.list(part) if access.can_see(_store_record("agent", rec.agent_id, rec))]
