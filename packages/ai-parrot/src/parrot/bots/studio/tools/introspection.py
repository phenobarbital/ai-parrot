"""Read-only introspection tools (no confirmation)."""

from __future__ import annotations

from parrot.tools import tool

from ._context import _require_app


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
    from parrot.handlers.tools_catalog import _build_catalog

    return _build_catalog()


@tool(
    name="list_existing_agents",
    description="List agents already registered in the live AgentRegistry.",
)
async def list_existing_agents() -> list:
    """List registered agent names (registry-origin only)."""
    app = _require_app()
    manager = app.get("bot_manager")
    if manager is None or manager.registry is None:
        return []
    return [meta.name for meta in manager.registry.list_agents()]
