"""Introspection helpers — the catalog the builders show to their LLM.

Every helper has a plain async function (callable from builder code) and a
``@tool``-decorated wrapper of the same name suffix for LLM invocation.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from parrot.registry import agent_registry
from parrot.tools.decorators import tool
from parrot.tools.registry import ToolkitRegistry


async def list_available_toolkits() -> List[Dict[str, str]]:
    """Return the registered toolkit catalog: name + class docstring summary."""
    catalog: List[Dict[str, str]] = []
    for name, cls in ToolkitRegistry.get_registry().items():
        doc = (cls.__doc__ or "").strip().splitlines()
        summary = doc[0] if doc else ""
        catalog.append(
            {
                "name": name,
                "class_name": cls.__name__,
                "module": cls.__module__,
                "summary": summary,
            }
        )
    return sorted(catalog, key=lambda item: item["name"])


async def list_available_tools() -> List[Dict[str, str]]:
    """Return the catalog of standalone ``@tool`` functions discovered.

    The factory currently relies on the toolkit catalog for capability
    discovery; standalone tools surface here so builders can reference them
    by name in ``tools.tools`` of an ``AgentDefinition``.
    """
    from parrot.tools import _imports  # noqa: F401 — triggers @tool registration

    import parrot.tools as parrot_tools

    catalog: List[Dict[str, str]] = []
    for attr in dir(parrot_tools):
        obj = getattr(parrot_tools, attr, None)
        meta = getattr(obj, "_tool_metadata", None)
        if meta is None:
            continue
        catalog.append(
            {
                "name": meta.get("name", attr),
                "description": (meta.get("description") or "").strip(),
            }
        )
    return sorted(catalog, key=lambda item: item["name"])


async def list_registered_agents() -> List[Dict[str, Any]]:
    """List agents currently known to ``AgentRegistry`` (YAML + decorator)."""
    agents: List[Dict[str, Any]] = []
    for name, meta in agent_registry._registered_agents.items():
        cfg = meta.bot_config
        agents.append(
            {
                "name": name,
                "class_name": cfg.class_name if cfg else None,
                "module": cfg.module if cfg else meta.module_path,
                "tags": sorted(cfg.tags) if cfg and cfg.tags else [],
                "has_vector_store": bool(cfg and cfg.vector_store),
                "toolkits": list(cfg.toolkits) if cfg else [],
            }
        )
    return sorted(agents, key=lambda item: item["name"])


async def load_agent_definition(name: str) -> Optional[Dict[str, Any]]:
    """Return the ``BotConfig`` of a registered agent as a dict (for cloning).

    Returns ``None`` if the agent is not registered or has no config (i.e. was
    registered programmatically without YAML metadata).
    """
    meta = agent_registry._registered_agents.get(name)
    if meta is None or meta.bot_config is None:
        return None
    return meta.bot_config.model_dump(mode="json", exclude_none=True)


# --- LLM-facing wrappers -----------------------------------------------------


@tool(name="list_available_toolkits",
      description="List every toolkit registered in the ToolkitRegistry "
                  "(JIRA, GitHub, GoogleSearch, OpenAPI, …). Use this to pick "
                  "toolkits when drafting an agent definition.")
async def _list_available_toolkits_tool() -> List[Dict[str, str]]:
    return await list_available_toolkits()


@tool(name="list_available_tools",
      description="List standalone @tool functions discovered in parrot.tools.")
async def _list_available_tools_tool() -> List[Dict[str, str]]:
    return await list_available_tools()


@tool(name="list_registered_agents",
      description="List agents currently registered in the AgentRegistry. "
                  "Use this when the user asks to clone an existing agent.")
async def _list_registered_agents_tool() -> List[Dict[str, Any]]:
    return await list_registered_agents()


@tool(name="load_agent_definition",
      description="Return the full YAML definition of a registered agent as "
                  "a dict, ready to be mutated for a clone.")
async def _load_agent_definition_tool(name: str) -> Optional[Dict[str, Any]]:
    return await load_agent_definition(name)
