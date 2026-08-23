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
    """Return the catalog of tools a builder may reference by name.

    Two sources, merged:

    * ``discover_from_registry()`` — the declarative ``TOOL_REGISTRY`` maps
      published by installed packages (``parrot_tools`` and friends). Read
      without importing anything, so the full catalog is cheap.
    * the ``@tool``-decorated functions re-exported at the ``parrot.tools``
      top level, which carry a human-written description.

    The registry is the reason this is not just the second source: scanning
    ``dir(parrot.tools)`` alone sees only what happens to be re-exported
    there, which is a small fraction of the registry — so a builder was
    being shown a catalog that omitted most installed tools and then
    (correctly) refused to use them.

    (This function previously opened with ``from parrot.tools import
    _imports``, a module that does not exist, so every call raised
    ``ImportError`` before reaching the scan.)

    Returns:
        Name-sorted entries of ``{name, description, kind, dotted_path}``.
        ``description`` is empty for a registry entry that was not imported;
        resolving it would mean importing every tool in the catalog.
    """
    from parrot.tools.discovery import discover_from_registry  # noqa: PLC0415

    import parrot.tools as parrot_tools

    merged: Dict[str, Dict[str, str]] = {}

    for name, dotted_path in discover_from_registry().items():
        merged[name] = {
            "name": name,
            "description": "",
            "kind": "toolkit" if "toolkit" in dotted_path.lower() else "tool",
            "dotted_path": dotted_path,
        }

    for attr in dir(parrot_tools):
        obj = getattr(parrot_tools, attr, None)
        meta = getattr(obj, "_tool_metadata", None)
        if meta is None:
            continue
        name = meta.get("name", attr)
        entry = merged.setdefault(
            name, {"name": name, "description": "", "kind": "tool", "dotted_path": ""}
        )
        # The decorator's description is authored; never let the registry's
        # blank placeholder overwrite it.
        entry["description"] = (meta.get("description") or "").strip()

    return sorted(merged.values(), key=lambda item: item["name"])


async def list_registered_agents() -> List[Dict[str, Any]]:
    """List agents currently known to ``AgentRegistry`` (YAML + decorator)."""
    agents: List[Dict[str, Any]] = []
    for meta in agent_registry.list_agents():
        cfg = meta.bot_config
        agents.append(
            {
                "name": meta.name,
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
    meta = agent_registry.get_metadata(name)
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
      description="List every tool a definition may reference by name — the "
                  "declarative TOOL_REGISTRY of installed packages plus the "
                  "standalone @tool functions in parrot.tools.")
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
