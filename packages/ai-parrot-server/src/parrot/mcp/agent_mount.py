"""`AgentMCPMount` — per-agent Streamable HTTP endpoints (FEAT-477, Module 2).

Builds one :class:`~parrot.mcp.transports.streamable_http.StreamableHttpMCPServer`
per exposed agent at ``{base_path}/{agent_name}``, mirroring the mount pattern
``A2AServer.setup()`` already proves (``a2a/server.py:231``). Each per-agent
server is registered with that agent's exposure set (FEAT-477 TASK-2600) plus
its own ``tool_manager`` tools, minus internal plumbing.

Optionally publishes an aggregate ``/mcp`` endpoint (spec §2 Overview #2)
exposing every agent's tools as ``{agent}__{tool}``. Both name forms resolve
to the same canonical PBAC resource, ``mcp:agent:{name}:tool:{tool}`` — the
aggregate is naming sugar, never its own authorization path (OQ2-adjacent
invariant; PBAC enforcement itself is TASK-2604/2605's job).

**OQ5 — agent reload.** Agents are held **by name only** and resolved through
``BotManager.get_bots()`` on every ``tools/list``/``tools/call``. When
``BotManager.reload_agent()`` swaps an agent's instance, the next call
rebuilds that agent's tool registrations rather than serving the exposure
set of a garbage-collected instance.
"""
import logging
from typing import Any

from aiohttp import web
from parrot.mcp.agent_tools import build_exposure_set
from parrot.mcp.config import AgentMCPMountConfig, MCPServerConfig
from parrot.mcp.transports.streamable_http import StreamableHttpMCPServer

#: Internal plumbing tools that must never be surfaced over MCP, mirroring
#: ``A2AServer._INTERNAL_TOOL_NAMES`` (``a2a/server.py:398``) — they clutter
#: the tool catalog and their auto-generated schema can trip strict clients.
_INTERNAL_TOOL_NAMES = frozenset({"to_json"})

#: Fixed path for the optional aggregate endpoint (spec §2 Overview #2:
#: "an optional aggregate `/mcp`"). Not derived from `AgentMCPMountConfig.
#: base_path` — it is a distinct, well-known mount point that happens to
#: coincide with the tool-level `MCPServerConfig` default, which is exactly
#: why a base_path collision must be rejected when both are active.
_AGGREGATE_BASE_PATH = "/mcp"

#: Reserved key for the aggregate server in `AgentMCPMount._servers`. Not a
#: valid agent name (agent names are validated against containing "__", so
#: this can never collide with a real per-agent entry).
_AGGREGATE_KEY = "__aggregate__"


class _AggregateToolProxy:
    """Read-only proxy that renames a tool for the aggregate endpoint.

    Delegates every attribute *except* ``name`` to the wrapped tool, so
    ``MCPToolAdapter``/``RemoteMCPServerBase.register_tool`` see a tool
    identical to the original except for its MCP-visible name. Both the
    per-agent name and this aggregate name resolve to the same canonical
    PBAC resource (see :meth:`AgentMCPMount.canonical_resource`).
    """

    def __init__(self, tool: Any, aggregate_name: str) -> None:
        self._tool = tool
        self.name = aggregate_name

    def __getattr__(self, item: str) -> Any:
        return getattr(self._tool, item)


class _AgentBoundMCPServer(StreamableHttpMCPServer):
    """Per-agent server that re-resolves its agent before every dispatch.

    Overrides the two JSON-RPC handlers that enumerate/execute tools so
    that a stale exposure set (bound, via `AgentMethodTool`'s weak
    reference, to an agent instance `reload_agent()` already cleaned up)
    is rebuilt against the live instance first (OQ5).
    """

    def __init__(
        self,
        config: MCPServerConfig,
        mount: "AgentMCPMount",
        agent_name: str,
        parent_app: web.Application | None = None,
    ) -> None:
        super().__init__(config, parent_app=parent_app)
        self._mount = mount
        self._agent_name = agent_name

    async def handle_tools_list(self, params: dict[str, Any]) -> dict[str, Any]:
        self._mount._ensure_current(self._agent_name)
        return await super().handle_tools_list(params)

    async def handle_tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
        self._mount._ensure_current(self._agent_name)
        return await super().handle_tools_call(params)


class _AggregateMCPServer(StreamableHttpMCPServer):
    """Aggregate server publishing every configured agent's tools.

    Rebuilds its full tool set (across all configured agents) before every
    dispatch — the multi-agent analogue of `_AgentBoundMCPServer`'s OQ5
    rebuild, since the aggregate has no single owning agent to diff against.
    """

    def __init__(
        self,
        config: MCPServerConfig,
        mount: "AgentMCPMount",
        parent_app: web.Application | None = None,
    ) -> None:
        super().__init__(config, parent_app=parent_app)
        self._mount = mount

    async def handle_tools_list(self, params: dict[str, Any]) -> dict[str, Any]:
        self._mount._rebuild_aggregate(self)
        return await super().handle_tools_list(params)

    async def handle_tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
        self._mount._rebuild_aggregate(self)
        return await super().handle_tools_call(params)


class AgentMCPMount:
    """Mounts one MCP endpoint per configured agent on a shared aiohttp app.

    Args:
        bot_manager: The `BotManager` whose agents are exposed. Held by
            reference and queried by name on every call (`get_bots()`) —
            never a cached agent instance (OQ5).
        config: The `AgentMCPMountConfig` describing which agents to mount,
            under which base path, and whether the aggregate is enabled.
    """

    def __init__(self, bot_manager: Any, config: AgentMCPMountConfig) -> None:
        self._bots = bot_manager
        self._config = config
        self._servers: dict[str, StreamableHttpMCPServer] = {}
        #: Last-seen `id()` of each agent instance, used to detect a
        #: `reload_agent()` swap without holding a strong reference to the
        #: agent (OQ5 — "never hold the agent object across calls").
        self._last_agent_id: dict[str, int] = {}
        self.logger = logging.getLogger("Parrot.MCP.AgentMount")

    def setup(self, app: web.Application) -> web.Application:
        """Register one endpoint per configured agent (plus the optional
        aggregate) on `app`.

        Args:
            app: The shared aiohttp application to mount onto.

        Returns:
            The same `app`, for chaining (matches `BotManager.setup()`'s
            own return convention).

        Raises:
            ValueError: If an agent name contains the aggregate separator
                `__`, or if a mount's base path collides with an already
                registered route/transport.
        """
        for name in self._config.agents:
            if "__" in name:
                raise ValueError(
                    f"agent name {name!r} contains the aggregate separator "
                    "'__'"
                )
            path = f"{self._config.base_path}/{name}"
            self._reject_if_path_claimed(app, path)
            server_config = MCPServerConfig(
                name=f"agent-mcp-mount-{name}",
                base_path=path,
            )
            server = _AgentBoundMCPServer(
                server_config, mount=self, agent_name=name, parent_app=app
            )
            self._register_agent_tools(server, name)
            self._last_agent_id[name] = id(self._bots.get_bots()[name])
            server._register_routes(app.router, path)
            self._servers[name] = server

        if self._config.aggregate_enabled:
            self._reject_if_path_claimed(app, _AGGREGATE_BASE_PATH)
            agg_config = MCPServerConfig(
                name="agent-mcp-mount-aggregate",
                base_path=_AGGREGATE_BASE_PATH,
            )
            aggregate = _AggregateMCPServer(agg_config, mount=self, parent_app=app)
            self._rebuild_aggregate(aggregate)
            aggregate._register_routes(app.router, _AGGREGATE_BASE_PATH)
            self._servers[_AGGREGATE_KEY] = aggregate

        return app

    def _resolve(self, name: str) -> Any:
        """Resolve `name` to its live agent instance (OQ5 — never cached).

        Args:
            name: Configured agent name.

        Returns:
            The current agent instance from `BotManager.get_bots()`.
        """
        return self._ensure_current(name)

    def _ensure_current(self, name: str) -> Any:
        """Resolve `name` and rebuild its registrations if it changed.

        Args:
            name: Configured agent name.

        Returns:
            The current agent instance.
        """
        agent = self._bots.get_bots()[name]
        if self._last_agent_id.get(name) != id(agent):
            server = self._servers.get(name)
            if server is not None:
                self._register_agent_tools(server, name, agent=agent)
            self._last_agent_id[name] = id(agent)
        return agent

    def _register_agent_tools(
        self, server: StreamableHttpMCPServer, name: str, agent: Any = None
    ) -> None:
        """(Re)register `name`'s exposure set plus its own tools onto `server`.

        Args:
            server: The per-agent `StreamableHttpMCPServer` to populate.
            name: Configured agent name.
            agent: The already-resolved agent instance, if the caller has
                one; resolved from `BotManager.get_bots()` otherwise.
        """
        if agent is None:
            agent = self._bots.get_bots()[name]
        server.tools.clear()
        for tool in build_exposure_set(agent):
            server.register_tool(tool)
        tool_manager = getattr(agent, "tool_manager", None)
        if tool_manager is not None:
            for tool_name in tool_manager.list_tools():
                if tool_name in _INTERNAL_TOOL_NAMES:
                    continue
                own_tool = tool_manager.get_tool(tool_name)
                if own_tool is not None:
                    server.register_tool(own_tool)

    def _rebuild_aggregate(self, server: StreamableHttpMCPServer) -> None:
        """Rebuild the aggregate server's tool set from every configured agent.

        Args:
            server: The aggregate `StreamableHttpMCPServer`.
        """
        server.tools.clear()
        for name in self._config.agents:
            agent = self._ensure_current(name)
            for tool in build_exposure_set(agent):
                server.register_tool(_AggregateToolProxy(tool, f"{name}__{tool.name}"))
            tool_manager = getattr(agent, "tool_manager", None)
            if tool_manager is not None:
                for tool_name in tool_manager.list_tools():
                    if tool_name in _INTERNAL_TOOL_NAMES:
                        continue
                    own_tool = tool_manager.get_tool(tool_name)
                    if own_tool is not None:
                        server.register_tool(
                            _AggregateToolProxy(own_tool, f"{name}__{tool_name}")
                        )

    def canonical_resource(self, agent_name: str, tool_name: str) -> str:
        """Build the canonical PBAC resource string for `agent_name`/`tool_name`.

        Args:
            agent_name: Configured agent name.
            tool_name: Tool name as registered (per-agent form).

        Returns:
            The canonical resource string, `mcp:agent:{name}:tool:{tool}`.
        """
        return f"mcp:agent:{agent_name}:tool:{tool_name}"

    def canonical_resource_from_aggregate(self, aggregate_name: str) -> str:
        """Resolve an aggregate `{agent}__{tool}` name to its canonical resource.

        Args:
            aggregate_name: A name published on the aggregate endpoint, of
                the form `{agent}__{tool}`.

        Returns:
            The same canonical resource string `canonical_resource` would
            produce for the equivalent per-agent name — both forms are
            naming sugar over one authorization path.

        Raises:
            ValueError: If `aggregate_name` does not contain the `__`
                separator.
        """
        agent_name, sep, tool_name = aggregate_name.partition("__")
        if not sep:
            raise ValueError(
                f"{aggregate_name!r} is not an aggregate name "
                "('{agent}__{tool}' expected)"
            )
        return self.canonical_resource(agent_name, tool_name)

    def _reject_if_path_claimed(self, app: web.Application, path: str) -> None:
        """Raise if `path` is already claimed by an existing route/transport.

        Checks both routes already registered on `app.router` (e.g. an
        `A2AServer` or an already-started transport) and, when present,
        `app["parrot_mcp_server"]`'s configured (not-yet-started)
        transports — `ParrotMCPServer.setup()` defers its own route
        registration to `on_startup`, so a not-yet-started conflicting
        transport would otherwise go undetected (`parrot_server.py:121`,
        `_check_base_path_conflicts`).

        Args:
            path: The full route path this mount is about to claim.

        Raises:
            ValueError: If `path` collides with an existing or configured
                route.
        """
        claimed = {
            route.resource.canonical
            for route in app.router.routes()
            if route.resource is not None
        }
        parrot_mcp_server = app.get("parrot_mcp_server")
        if parrot_mcp_server is not None:
            default_base_path = MCPServerConfig().base_path
            for transport_config in getattr(
                parrot_mcp_server, "transport_configs", {}
            ).values():
                if not getattr(transport_config, "enabled", True):
                    continue
                claimed.add(transport_config.base_path or default_base_path)
        if path in claimed:
            raise ValueError(
                f"agent mount path {path!r} collides with an existing MCP "
                "route or transport; give the mount a distinct base_path"
            )


__all__ = ["AgentMCPMount"]
