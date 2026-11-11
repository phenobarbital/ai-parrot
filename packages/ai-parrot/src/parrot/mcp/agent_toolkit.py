"""Serve a registered agent's own async methods as a local stdio MCP toolkit (FEAT-877).

Only the methods the author wrote on the agent's own class are exposed; every name a
framework class or mixin defines — and ``ask``/``ask_stream`` always — is reserved.
"""

from __future__ import annotations

import difflib
import functools
import importlib
import inspect
import logging
import types
import weakref
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, SkipValidation

from parrot.mcp.agent_tools import MCP_TOOL_ATTR, MCPToolDeclaration
from parrot.mcp.toolkit_config import agent_section_name
from parrot.registry import AgentKind, AgentRegistry, BotMetadata, agent_registry
from parrot.registry.registry import MCPLocalExposure
from parrot.tools.toolkit import AbstractToolkit

logger = logging.getLogger(__name__)

NEVER_EXPOSED: frozenset[str] = frozenset({"ask", "ask_stream"})


class AgentExposureError(ValueError):
    """An agent cannot be exposed as a local MCP toolkit; the message names the fix."""


def framework_agent_bases() -> tuple[type, ...]:
    """Return the generic agent bases, imported lazily.

    Returns:
        ``(AbstractBot, BaseBot, BasicBot, Chatbot, BasicAgent, Agent)``.
    """
    from parrot.bots.abstract import AbstractBot  # noqa: PLC0415
    from parrot.bots.agent import Agent, BasicAgent  # noqa: PLC0415
    from parrot.bots.base import BaseBot  # noqa: PLC0415
    from parrot.bots.basic import BasicBot  # noqa: PLC0415
    from parrot.bots.chatbot import Chatbot  # noqa: PLC0415

    return (AbstractBot, BaseBot, BasicBot, Chatbot, BasicAgent, Agent)


def _framework_classes(agent_cls: type) -> set[type]:
    """Classes whose public names are reserved for ``agent_cls`` (spec §2 step 1)."""
    bases = framework_agent_bases()
    abstract_bot = bases[0]
    framework: set[type] = set()
    for base in bases:
        framework.update(base.__mro__)
    framework.update(klass for klass in agent_cls.__mro__ if not issubclass(klass, abstract_bot))
    return framework


def own_coroutine_methods(agent_cls: type) -> dict[str, Callable[..., Awaitable[Any]]]:
    """Return the exposable candidates of ``agent_cls`` (spec §2 steps 1-4), ordered by name.

    Args:
        agent_cls: An ``AbstractBot`` subclass (never instantiated).

    Returns:
        Method name → the class function (unbound).
    """
    framework = _framework_classes(agent_cls)
    reserved: set[str] = set(NEVER_EXPOSED)
    for klass in framework:
        reserved.update(name for name in vars(klass) if not name.startswith("_"))
    candidates: dict[str, Callable[..., Awaitable[Any]]] = {}
    seen: set[str] = set()
    for klass in agent_cls.__mro__:
        if klass in framework:
            continue
        for name, value in vars(klass).items():
            if name in seen:
                continue
            seen.add(name)
            if (
                not name.startswith("_")
                and name not in reserved
                and isinstance(value, types.FunctionType)
                and inspect.iscoroutinefunction(value)
            ):
                candidates[name] = value
    return dict(sorted(candidates.items()))


def exposed_methods(
    agent_cls: type, exposure: MCPLocalExposure, *, agent_name: str | None = None
) -> dict[str, Callable[..., Awaitable[Any]]]:
    """Apply ``exposure.allow`` to the candidates (spec §2 step 5).

    Args:
        agent_cls: The agent class.
        exposure: The agent's ``mcp_local`` declaration.
        agent_name: Registry name used in error messages (defaults to the class name).

    Returns:
        Exposed method name → class function; allow order when ``allow`` is set, else by name.

    Raises:
        AgentExposureError: An allow entry is not a candidate, or the result is empty.
    """
    label = agent_name or agent_cls.__name__
    candidates = own_coroutine_methods(agent_cls)
    if exposure.allow is None:
        methods = candidates
    else:
        bad = list(dict.fromkeys(name for name in exposure.allow if name not in candidates))
        if bad:
            message = f"Agent '{label}': allow entries are not own-class public async methods: {', '.join(bad)}"
            if any(name in NEVER_EXPOSED for name in bad):
                message += " (ask/ask_stream are never exposed)"
            raise AgentExposureError(message)
        methods = {name: candidates[name] for name in dict.fromkeys(exposure.allow)}
    if not methods:
        raise AgentExposureError(f"Agent '{label}' ({agent_cls.__name__}) defines no exposable methods")
    return methods


class ResolvedAgent(BaseModel):
    """An agent resolved for exposure, without instantiating it."""

    name: str
    metadata: Annotated[BotMetadata, SkipValidation]
    agent_cls: type
    methods: dict[str, Callable[..., Awaitable[Any]]]

    model_config = ConfigDict(arbitrary_types_allowed=True)


class ExposableAgent(BaseModel):
    """One agent that may be installed with `parrot toolkits install --agent`."""

    name: str
    section_name: str
    class_path: str
    tools: list[str]
    source: str


_DISCOVERED: "weakref.WeakSet[AgentRegistry]" = weakref.WeakSet()


def discover_agents(registry: AgentRegistry | None = None) -> AgentRegistry:
    """Run the sync discovery steps once per registry; experts are not loaded.

    Mirrors ``StandaloneAgentLoader._ensure_discovered`` steps 1-3.
    """
    reg = registry if registry is not None else agent_registry
    if reg in _DISCOVERED:
        return reg
    reg.load_modules_sync()
    reg.discover_config_agents()
    definitions_dir = reg.agents_dir / "agents"
    if definitions_dir.is_dir():
        reg.load_agent_definitions(definitions_dir)
    _DISCOVERED.add(reg)
    return reg


def _tool_names(methods: dict[str, Callable[..., Awaitable[Any]]], agent_name: str) -> dict[str, str]:
    """Map MCP tool names to methods, respecting ``@mcp_tool`` declarations.

    Raises:
        AgentExposureError: If two methods map to the same tool name.
    """
    names: dict[str, str] = {}
    for method_name, func in methods.items():
        declaration: MCPToolDeclaration | None = getattr(func, MCP_TOOL_ATTR, None)
        tool_name = declaration.name if declaration is not None else method_name
        if tool_name in names:
            raise AgentExposureError(
                f"Agent '{agent_name}': methods {names[tool_name]} and {method_name} "
                f"both map to tool name '{tool_name}'"
            )
        names[tool_name] = method_name
    return names


def _agent_class(name: str, metadata: BotMetadata) -> type:
    """Return the agent class without instantiating it.

    Raises:
        AgentExposureError: If a configuration-defined agent class cannot be imported.
    """
    if inspect.isclass(metadata.factory):
        return metadata.factory
    config = metadata.bot_config
    try:
        module = importlib.import_module(config.module)
        return getattr(module, config.class_name)
    except Exception as exc:
        raise AgentExposureError(
            f"Cannot import agent class {config.module}.{config.class_name} for '{name}': {exc}"
        ) from exc


def resolve_exposable_agent(name: str, registry: AgentRegistry | None = None) -> ResolvedAgent:
    """Resolve an enabled local agent's own methods without instantiating it.

    Raises:
        AgentExposureError: If the agent is unknown, not locally exposable, or invalid.
    """
    reg = discover_agents(registry)
    metadata = reg.get_metadata(name)
    if metadata is None:
        suggestions = difflib.get_close_matches(name, reg.list_agent_names(), n=3, cutoff=0.5)
        matches = ", ".join(suggestions) if suggestions else "none"
        raise AgentExposureError(f"Unknown agent '{name}'. Close matches: {matches}")
    if metadata.kind != AgentKind.LOCAL:
        raise AgentExposureError(
            f"Agent '{name}' is a {metadata.kind.value} agent; only local agents can be served over stdio"
        )
    config = metadata.bot_config
    exposure = config.mcp_local if config is not None else None
    if exposure is None or not exposure.enabled:
        raise AgentExposureError(
            f"Agent '{name}' is not declared for local MCP exposure; add 'mcp_local:' to its YAML "
            "or mcp_local=... to @register_agent"
        )
    agent_cls = _agent_class(name, metadata)
    methods = exposed_methods(agent_cls, exposure, agent_name=name)
    _tool_names(methods, name)
    return ResolvedAgent(name=name, metadata=metadata, agent_cls=agent_cls, methods=methods)


def list_exposable_agents(registry: AgentRegistry | None = None) -> list[ExposableAgent]:
    """List every enabled local agent that can resolve for local MCP exposure."""
    reg = discover_agents(registry)
    result: list[ExposableAgent] = []
    for name in reg.list_agent_names():
        metadata = reg.get_metadata(name)
        if metadata is None or metadata.kind != AgentKind.LOCAL:
            continue
        config = metadata.bot_config
        if config is None or config.mcp_local is None or not config.mcp_local.enabled:
            continue
        try:
            resolved = resolve_exposable_agent(name, reg)
            tool_names = _tool_names(resolved.methods, name)
            result.append(
                ExposableAgent(
                    name=name,
                    section_name=agent_section_name(name),
                    class_path=f"{resolved.agent_cls.__module__}.{resolved.agent_cls.__qualname__}",
                    tools=list(tool_names),
                    source=str(metadata.file_path),
                )
            )
        except (AgentExposureError, ValueError) as exc:
            logger.warning("agent %s not exposable: %s", name, exc)
    return result


def _has_parameters(func: Callable[..., Any]) -> bool:
    """True when ``func`` takes an argument besides ``self`` (``*args``/``**kwargs`` ignored)."""
    params = list(inspect.signature(func).parameters.values())[1:]
    return any(param.kind not in (param.VAR_POSITIONAL, param.VAR_KEYWORD) for param in params)


class AgentToolkit(AbstractToolkit):
    """Serve one registered agent's own async methods as MCP tools (FEAT-877).

    Tools are built from the agent class; the agent is instantiated and configured on the
    first tool call (``auto_open``) and released by ``_close()``. All calls share one instance.
    """

    auto_open: bool = True

    def __init__(self, agent: str, *, registry: AgentRegistry | None = None, **kwargs: Any) -> None:
        """Resolve ``agent`` without instantiating it.

        Raises:
            AgentExposureError: The agent cannot be exposed (see resolve_exposable_agent).
        """
        super().__init__(**kwargs)
        self._registry = discover_agents(registry)
        self._resolved: ResolvedAgent = resolve_exposable_agent(agent, self._registry)
        self._agent_name = agent
        self._agent: Any = None

    def _proxy(self, method_name: str, func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        """Return ``func``'s signature bound to this toolkit, forwarding to the live agent."""

        @functools.wraps(func)
        async def proxy(toolkit_self: AgentToolkit, *args: Any, **kwargs: Any) -> Any:
            return await getattr(toolkit_self._agent, method_name)(*args, **kwargs)

        declaration: MCPToolDeclaration | None = getattr(func, MCP_TOOL_ATTR, None)
        if declaration is not None:
            proxy.__doc__ = declaration.description
            proxy._args_schema = declaration.args_schema  # type: ignore[attr-defined]
        return types.MethodType(proxy, self)

    def _generate_tools(self) -> None:
        """Create one ToolkitTool per exposed method, named by ``_tool_names``."""
        if self._tools_generated:
            return
        for tool_name, method_name in _tool_names(self._resolved.methods, self._agent_name).items():
            func = self._resolved.methods[method_name]
            tool = self._create_tool_from_method(tool_name, self._proxy(method_name, func))
            tool._method_name = method_name
            declaration: MCPToolDeclaration | None = getattr(func, MCP_TOOL_ATTR, None)
            if declaration is None and _has_parameters(func) and not tool.args_schema.model_fields:
                raise AgentExposureError(
                    f"Agent '{self._agent_name}': could not build the argument schema for {method_name}"
                )
            if declaration is not None and declaration.requires_confirmation:
                tool.routing_meta["requires_confirmation"] = True
            self._tool_cache[tool_name] = tool
        self._tools_generated = True

    async def _open(self) -> None:
        """Instantiate and configure the agent on the first tool call."""
        instance = await self._registry.get_instance(self._agent_name)
        if instance is None:
            raise RuntimeError(f"Agent '{self._agent_name}' could not be instantiated; see the server's stderr log")
        if self._resolved.metadata.at_startup:
            await instance.configure()
        self._agent = instance

    async def _close(self) -> None:
        """Run the agent's shutdown and cleanup hooks, then drop its instance."""
        agent, self._agent = self._agent, None
        if agent is not None:
            try:
                await agent.shutdown()
            except Exception:  # noqa: BLE001 -- cleanup must still run
                self.logger.exception("Error shutting down agent %s", self._agent_name)
            try:
                await agent.cleanup()
            except Exception:  # noqa: BLE001 -- lifecycle cleanup is isolated
                self.logger.exception("Error cleaning up agent %s", self._agent_name)
        await super()._close()

    async def _post_execute(self, tool_name: str, result: Any, /, **kwargs: Any) -> Any:
        """Return Pydantic results as JSON-compatible dictionaries."""
        if isinstance(result, BaseModel):
            return result.model_dump(mode="json")
        if isinstance(result, (list, tuple)) and all(isinstance(item, BaseModel) for item in result):
            return [item.model_dump(mode="json") for item in result]
        return result
