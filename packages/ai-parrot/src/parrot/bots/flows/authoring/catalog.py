"""The component manifest an authoring model is allowed to reference.

Three registries decide what a workflow can be built from, and each is
enumerated differently:

* node types — ``NODE_REGISTRY`` plus the ``NODE_CONFIG_MODELS`` map that
  says which ones accept a typed ``config`` block;
* agents — ``AgentRegistry.list_agents()``, whose ``BotConfig`` is already a
  JSON-serialisable manifest;
* tools — the declarative ``TOOL_REGISTRY`` maps read by
  ``discover_from_registry()`` (no imports), enriched from a live
  ``ToolManager`` when one is available.

This module merges them into one bounded, JSON-safe object. Two properties
matter more than completeness:

**It is built from the live registries, never hand-written.** The two
existing catalogs (``handlers/crew/tool_catalog.py``,
``handlers/crew/special_nodes.py``) are curated by hand and have already
drifted from the 117-entry registry. A catalog that drifts is worse than no
catalog: it teaches a model to reference things that do not exist.

**It is bounded.** Descriptions are truncated and ``render_for`` emits only
the slice relevant to one node kind, because the whole point of authoring a
workflow node-by-node is that no single prompt carries the entire component
surface. Same discipline, and the same limits, as
``parrot.tools.execution_plan.catalog``.

Building one is not free — three registry walks plus a JSON Schema per node
type — so the plain form is cached per process and invalidated when any
registry gains an entry. See :func:`build_catalog`.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Literal, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field

__all__ = (
    "AgentEntry",
    "ArgSummary",
    "ComponentCatalog",
    "NodeTypeEntry",
    "ToolEntry",
    "build_catalog",
)

logger = logging.getLogger(__name__)

# Bounds so a rendered slice stays prompt-sized. Mirrors the limits in
# parrot.tools.execution_plan.catalog, which solved the same problem.
_MAX_DESCRIPTION_CHARS = 200
_MAX_ARG_DESCRIPTION_CHARS = 120

#: Node types that carry no meaning in a crew: ``AgentCrew`` has no edge
#: conditions and no in-graph decision primitive, so a blueprint using them
#: only compiles to a ``FlowDefinition``.
_FLOW_ONLY_TYPES = frozenset({"decision", "interactive_decision", "synthesis"})

#: Sentinels the compilers emit themselves; a blueprint never declares them.
_SENTINEL_TYPES = frozenset({"start", "end"})


class ArgSummary(BaseModel):
    """Compact rendering of one tool argument — never the full JSON schema."""

    model_config = ConfigDict(extra="forbid")

    name: str
    type: str
    required: bool
    description: str = ""


class NodeTypeEntry(BaseModel):
    """One node type a blueprint may declare.

    Attributes:
        type: The ``NODE_REGISTRY`` key.
        class_name: Implementing ``Node`` subclass.
        module: Where that class lives.
        summary: First docstring line of the class.
        config_schema: JSON Schema of the type's ``config`` block, or
            ``None`` when the type declares no config model.
        requires_agent_ref: Whether ``NodeDefinition.agent_ref`` is
            mandatory for this type.
        engines: Which compile targets accept this type.
    """

    model_config = ConfigDict(extra="forbid")

    type: str
    class_name: str
    module: str
    summary: str = ""
    config_schema: Optional[Dict[str, Any]] = None
    requires_agent_ref: bool = False
    engines: List[Literal["crew", "flow"]] = Field(default_factory=list)


class AgentEntry(BaseModel):
    """One registered agent a blueprint may reference by ``agent_ref``."""

    model_config = ConfigDict(extra="forbid")

    name: str
    class_name: Optional[str] = None
    module: Optional[str] = None
    description: str = ""
    tags: List[str] = Field(default_factory=list)
    toolkits: List[str] = Field(default_factory=list)
    has_vector_store: bool = False


class ToolEntry(BaseModel):
    """One tool or toolkit a blueprint may name.

    ``description`` and ``args_summary`` are populated only when a live
    ``ToolManager`` supplied them; resolving them for the whole registry
    would mean importing every tool in the catalog.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    kind: Literal["tool", "toolkit"] = "tool"
    dotted_path: str = ""
    description: str = ""
    args_summary: List[ArgSummary] = Field(default_factory=list)


class ComponentCatalog(BaseModel):
    """Everything an authoring model is allowed to reference."""

    model_config = ConfigDict(extra="forbid")

    node_types: List[NodeTypeEntry] = Field(default_factory=list)
    agents: List[AgentEntry] = Field(default_factory=list)
    tools: List[ToolEntry] = Field(default_factory=list)

    # ── lookups ──────────────────────────────────────────────────────────

    def tool_names(self) -> set[str]:
        """Names a blueprint may put in ``tools`` / ``tool``."""
        return {entry.name for entry in self.tools}

    def agent_names(self) -> set[str]:
        """Names a blueprint may put in ``agent_ref``."""
        return {entry.name for entry in self.agents}

    def node_type_names(self) -> set[str]:
        """Registered node types, sentinels included."""
        return {entry.type for entry in self.node_types}

    def node_type(self, type_name: str) -> Optional[NodeTypeEntry]:
        """Return one node-type entry, or ``None`` when unregistered."""
        for entry in self.node_types:
            if entry.type == type_name:
                return entry
        return None

    def kinds_for(self, engine: str) -> List[str]:
        """Declarable node types for ``engine``, sentinels excluded.

        Args:
            engine: ``"crew"`` or ``"flow"``.

        Returns:
            Sorted type names a blueprint may declare for that engine.
        """
        return sorted(
            entry.type
            for entry in self.node_types
            if engine in entry.engines and entry.type not in _SENTINEL_TYPES
        )

    # ── rendering ────────────────────────────────────────────────────────

    def render_tools(self, limit: Optional[int] = None) -> str:
        """Render the tool catalog as one line per tool.

        Args:
            limit: Maximum entries to render. ``None`` renders all; the
                count of anything dropped is stated in the output, because a
                silently truncated catalog reads as "these are all the tools
                there are".

        Returns:
            A newline-joined listing, or a clear placeholder when empty.
        """
        if not self.tools:
            return "(no tools available)"
        entries = self.tools if limit is None else self.tools[:limit]
        lines = []
        for entry in entries:
            args = ", ".join(
                f"{arg.name}:{arg.type}{'' if arg.required else '?'}"
                for arg in entry.args_summary
            )
            suffix = f": {entry.description}" if entry.description else ""
            lines.append(f"- {entry.name}({args}) [{entry.kind}]{suffix}")
        dropped = len(self.tools) - len(entries)
        if dropped > 0:
            lines.append(f"- … and {dropped} more not shown")
        return "\n".join(lines)

    def render_agents(self) -> str:
        """Render the registered-agent catalog, one line per agent."""
        if not self.agents:
            return "(no registered agents — use engine='crew' to define agents inline)"
        return "\n".join(
            f"- {entry.name} ({entry.class_name or '?'})"
            + (f": {entry.description}" if entry.description else "")
            for entry in self.agents
        )

    def render_for(self, kind: str, *, engine: str = "flow") -> str:
        """Render only the catalog slice a node of ``kind`` needs.

        This is the mechanism that keeps per-node authoring calls bounded: an
        ``agent`` node needs the tool and agent catalogs, a ``tool`` node
        needs only the tools, and a ``decision`` node needs neither — just
        its own config schema.

        Args:
            kind: The blueprint node kind being authored.
            engine: Compile target, which decides whether ``agent_ref``
                candidates are relevant at all.

        Returns:
            The prompt-ready slice for that node kind.
        """
        blocks: List[str] = []
        if kind == "agent":
            blocks.append(f"Tools available:\n{self.render_tools()}")
            if engine == "flow":
                blocks.append(f"Registered agents (agent_ref):\n{self.render_agents()}")
        elif kind == "tool":
            blocks.append(f"Tools available:\n{self.render_tools()}")

        entry = self.node_type(kind)
        if entry is not None and entry.config_schema:
            import json  # noqa: PLC0415 — only needed on this branch

            blocks.append(
                f"config JSON Schema for node type {kind!r}:\n"
                f"{json.dumps(entry.config_schema)}"
            )
        return "\n\n".join(blocks) if blocks else "(no catalog needed for this node)"


# ─── construction ────────────────────────────────────────────────────────────


def _summary_of(cls: Any) -> str:
    """First docstring line of ``cls``, bounded."""
    doc = (getattr(cls, "__doc__", "") or "").strip().splitlines()
    return doc[0][:_MAX_DESCRIPTION_CHARS] if doc else ""


def _build_node_types() -> List[NodeTypeEntry]:
    """Reflect ``NODE_REGISTRY`` into catalog entries.

    Returns:
        One entry per registered type, sorted by type name.
    """
    from parrot.bots.flows.flow.flow import (  # noqa: PLC0415
        NODE_CONFIG_MODELS,
        NODE_REGISTRY,
    )

    entries: List[NodeTypeEntry] = []
    for type_name, node_cls in NODE_REGISTRY.items():
        config_model = NODE_CONFIG_MODELS.get(type_name)
        config_schema: Optional[Dict[str, Any]] = None
        if config_model is not None:
            try:
                config_schema = config_model.model_json_schema()
            except Exception:  # pragma: no cover - defensive
                logger.warning(
                    "Could not build JSON Schema for node type %r", type_name,
                    exc_info=True,
                )

        engines: List[Literal["crew", "flow"]] = ["flow"]
        if type_name not in _FLOW_ONLY_TYPES and type_name not in _SENTINEL_TYPES:
            engines.append("crew")

        entries.append(
            NodeTypeEntry(
                type=type_name,
                class_name=node_cls.__name__,
                module=node_cls.__module__,
                summary=_summary_of(node_cls),
                config_schema=config_schema,
                requires_agent_ref=(type_name == "agent"),
                engines=engines,
            )
        )

    if not any(entry.type == "tool" for entry in entries):
        # Deterministic tool nodes are supported by both engines, but neither
        # path goes through a NODE_REGISTRY entry that exists at catalog-build
        # time: a crew compiles them to ToolNodeDefinition (never a registered
        # node type at all), and a flow's "tool" type is registered lazily by
        # ensure_tool_node_registered(). Advertising the kind here — rather
        # than importing the plan package for its registration side effect —
        # keeps the catalog read-only.
        entries.append(
            NodeTypeEntry(
                type="tool",
                class_name="ToolNode",
                module="parrot.bots.flows.crew.tool_node",
                summary=(
                    "Executes a catalog tool directly with declared args — no "
                    "LLM tokens spent."
                ),
                config_schema=None,
                requires_agent_ref=False,
                engines=["crew", "flow"],
            )
        )

    return sorted(entries, key=lambda entry: entry.type)


def _build_agents() -> List[AgentEntry]:
    """Reflect the ``AgentRegistry`` into catalog entries."""
    from parrot.registry import agent_registry  # noqa: PLC0415

    entries: List[AgentEntry] = []
    for meta in agent_registry.list_agents():
        cfg = meta.bot_config
        description = ""
        if cfg is not None:
            description = (getattr(cfg, "description", None) or "")[
                :_MAX_DESCRIPTION_CHARS
            ]
        entries.append(
            AgentEntry(
                name=meta.name,
                class_name=cfg.class_name if cfg else None,
                module=cfg.module if cfg else meta.module_path,
                description=description,
                tags=sorted(cfg.tags) if cfg and cfg.tags else [],
                toolkits=list(cfg.toolkits) if cfg and cfg.toolkits else [],
                has_vector_store=bool(cfg and cfg.vector_store),
            )
        )
    return entries


def _args_summary(args_schema: Any) -> List[ArgSummary]:
    """Summarise a Pydantic args schema into per-argument lines."""
    if args_schema is None:
        return []
    try:
        schema = args_schema.model_json_schema()
    except Exception:  # pragma: no cover - defensive
        return []

    required = set(schema.get("required") or ())
    summaries: List[ArgSummary] = []
    for name, spec in (schema.get("properties") or {}).items():
        summaries.append(
            ArgSummary(
                name=name,
                type=str(spec.get("type", "any")),
                required=name in required,
                description=(spec.get("description") or "")[
                    :_MAX_ARG_DESCRIPTION_CHARS
                ],
            )
        )
    return summaries


def _build_tools(
    tool_manager: Any = None,
    allowed_tools: Optional[Sequence[str]] = None,
) -> List[ToolEntry]:
    """Merge the declarative tool registry with a live manager's schemas.

    Args:
        tool_manager: Optional live ``ToolManager``. When given, its tools
            contribute real descriptions and argument summaries.
        allowed_tools: Optional allowlist. Entries outside it are dropped,
            which is what keeps a generated workflow inside a caller's
            security boundary.

    Returns:
        Name-sorted tool entries.
    """
    from parrot.tools.discovery import discover_from_registry  # noqa: PLC0415

    merged: Dict[str, ToolEntry] = {}

    try:
        declared = discover_from_registry()
    except Exception:  # pragma: no cover - defensive
        logger.warning("Tool registry discovery failed", exc_info=True)
        declared = {}

    for name, dotted_path in declared.items():
        merged[name] = ToolEntry(
            name=name,
            kind="toolkit" if "toolkit" in dotted_path.lower() else "tool",
            dotted_path=dotted_path,
        )

    if tool_manager is not None:
        for name in list(tool_manager.list_tools() or []):
            tool = tool_manager.get_tool(name)
            entry = merged.get(name) or ToolEntry(name=name)
            entry.description = (getattr(tool, "description", None) or "")[
                :_MAX_DESCRIPTION_CHARS
            ]
            entry.args_summary = _args_summary(getattr(tool, "args_schema", None))
            merged[name] = entry

    if allowed_tools is not None:
        allow = set(allowed_tools)
        merged = {name: entry for name, entry in merged.items() if name in allow}

    return sorted(merged.values(), key=lambda entry: entry.name)


#: Process-wide cache for the unrestricted, manager-less catalog.
#:
#: Building one walks three registries and generates a JSON Schema per node
#: type, which is wasted work on an endpoint that answers "what components
#: exist?" on every request. The key is the registry sizes: they change only
#: when something registers, which is exactly when the catalog is stale.
#: Variants (an allowlist, or a live ``ToolManager``) are request-specific
#: and deliberately not cached.
_CATALOG_CACHE: Dict[Any, ComponentCatalog] = {}


def _cache_key() -> tuple:
    """Return a key that changes whenever a registry gains an entry."""
    from parrot.bots.flows.flow.flow import NODE_REGISTRY  # noqa: PLC0415
    from parrot.registry import agent_registry  # noqa: PLC0415

    try:
        from parrot.tools.discovery import discover_from_registry  # noqa: PLC0415

        tool_count = len(discover_from_registry())
    except Exception:  # pragma: no cover - defensive
        tool_count = -1
    return (len(NODE_REGISTRY), len(agent_registry.list_agents()), tool_count)


def build_catalog(
    *,
    tool_manager: Any = None,
    allowed_tools: Optional[Sequence[str]] = None,
    include_agents: bool = True,
    use_cache: bool = True,
) -> ComponentCatalog:
    """Build the component catalog from the live registries.

    Args:
        tool_manager: Optional live ``ToolManager``; supplies descriptions
            and argument summaries the declarative registry cannot.
        allowed_tools: Optional allowlist restricting the tool catalog. A
            model can only reference what the catalog lists, so this is the
            authoring layer's security boundary — same role ``allowed_tools``
            plays for ``ExecutionPlan``.
        include_agents: Set ``False`` to skip agent enumeration when only the
            node/tool surface is needed.
        use_cache: Reuse a cached catalog when the registries have not grown.
            Only the plain form (no ``tool_manager``, no ``allowed_tools``,
            agents included) is ever cached.

    Returns:
        A fully populated :class:`ComponentCatalog`.
    """
    cacheable = (
        use_cache
        and tool_manager is None
        and allowed_tools is None
        and include_agents
    )
    if cacheable:
        key = _cache_key()
        cached = _CATALOG_CACHE.get(key)
        if cached is not None:
            return cached

    catalog = ComponentCatalog(
        node_types=_build_node_types(),
        agents=_build_agents() if include_agents else [],
        tools=_build_tools(tool_manager=tool_manager, allowed_tools=allowed_tools),
    )

    if cacheable:
        _CATALOG_CACHE.clear()  # only the current registry state is useful
        _CATALOG_CACHE[key] = catalog
    return catalog
