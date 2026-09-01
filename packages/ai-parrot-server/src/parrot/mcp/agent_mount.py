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

**Identity + PBAC wiring (FEAT-477 TASK-2610).** TASK-2604/2605 built
principal resolution and PBAC filtering/re-verification (``PBACGuard``,
``resolve_principal``) as standalone, importable pieces, but no task ever
connected them to a live per-agent server — this module is where that
happens: ``_AgentBoundMCPServer`` overrides ``_guard()`` to resolve the
caller into a ``PermissionContext`` and publish it on ``_pctx_var`` (the
same mechanism ``DatasetManager`` uses), then routes ``tools/list``/
``tools/call`` through a ``PBACGuard`` built once per mounted agent.
``AgentMCPMount`` accepts a ``pbac_resolver``/``audit_sink`` (mirroring
TASK-2603's ``policy_filter`` seam) and an ``auth_template`` — an
``MCPServerConfig`` whose auth fields (``auth_method``, ``oauth2_*``,
``api_key_store``) are copied onto every per-agent config, since nothing
upstream of this task ever gave a mount a way to require authentication at
all. ``oauth2_resource_server_url`` is always taken from the mount's own
``AgentMCPMountConfig.resource_server_url`` (RFC 8707 audience scoping is a
*mount*-level concept per the spec's data model) even when the template
carries no OAuth settings of its own.
"""
import logging
from dataclasses import replace
from typing import Any

from aiohttp import web
from parrot.auth.context import _pctx_var
from parrot.mcp.agent_resources import ToolPolicyFilter, register_agent_resources
from parrot.mcp.agent_tools import build_exposure_set
from parrot.mcp.config import AgentMCPMountConfig, MCPServerConfig
from parrot.mcp.principal_guard import (
    AuditSink,
    PBACGuard,
    PBACResolver,
    resolve_principal,
)
from parrot.mcp.server_base import MCPServerBase as _CoreMCPServerBase
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


class _CoreDispatchProxy:
    """Exposes a server's `.tools` + the CORE, un-overridden `handle_tools_call`.

    `PBACGuard.tools_call()` invokes `server.handle_tools_call(params)` to
    actually run a permitted call. If `PBACGuard` were built with
    `server=<the _AgentBoundMCPServer instance>` directly, that call would
    re-enter `_AgentBoundMCPServer.handle_tools_call` — which itself
    delegates to the same `PBACGuard` — recursing forever. This proxy
    gives `PBACGuard` the `.tools` dict it needs to filter/re-verify
    against, plus a `handle_tools_call` bound to
    `parrot.mcp.server_base.MCPServerBase`'s core implementation
    (`adapter = self.tools[name]; return await adapter.execute(...)`),
    bypassing any subclass override.
    """

    def __init__(self, server: StreamableHttpMCPServer) -> None:
        self._server = server

    @property
    def tools(self) -> dict[str, Any]:
        return self._server.tools

    async def handle_tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
        return await _CoreMCPServerBase.handle_tools_call(self._server, params)


class _AgentBoundMCPServer(StreamableHttpMCPServer):
    """Per-agent server that re-resolves its agent before every dispatch.

    Overrides the two JSON-RPC handlers that enumerate/execute tools so
    that a stale exposure set (bound, via `AgentMethodTool`'s weak
    reference, to an agent instance `reload_agent()` already cleaned up)
    is rebuilt against the live instance first (OQ5). Also resolves the
    caller's identity in `_guard()` and routes both handlers through a
    `PBACGuard` (TASK-2610 wiring — see module docstring).
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
        self._pbac_guard = PBACGuard(
            agent_name,
            _CoreDispatchProxy(self),
            resolver=mount._pbac_resolver,
            audit_sink=mount._audit_sink,
            mount_config=mount._config,
        )

    async def _guard(self, request: web.Request) -> web.Response | None:
        """Auth (inherited) + principal resolution, published on `_pctx_var`.

        Publishes for the remainder of this request's dispatch tree —
        `asyncio.create_task()` (used by `_track()` for JSON-RPC dispatch)
        copies the current `contextvars.Context` at creation time, so
        `handle_tools_list`/`handle_tools_call` (invoked from tasks spawned
        after this returns) see the published `PermissionContext` without
        any signature changes down that call chain. Not reset in a
        `finally` here: aiohttp handles each inbound request as its own
        task with a fresh copy of the app-level context, so there is no
        request-to-request leakage to guard against.
        """
        error = await super()._guard(request)
        if error:
            return error
        resolved = await resolve_principal(
            request, self._mount._config, audit_hook=self._mount._audit_sink
        )
        if isinstance(resolved, web.Response):
            return resolved
        _pctx_var.set(resolved)
        return None

    async def handle_tools_list(self, params: dict[str, Any]) -> dict[str, Any]:
        self._mount._ensure_current(self._agent_name)
        pctx = _pctx_var.get()
        if pctx is None:
            # No principal published — deny-by-default rather than fall
            # through to the unfiltered core listing.
            return {"tools": []}
        return await self._pbac_guard.tools_list(params, pctx)

    async def handle_tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
        self._mount._ensure_current(self._agent_name)
        pctx = _pctx_var.get()
        if pctx is None:
            return {
                "content": [
                    {"type": "text", "text": "No authenticated principal for this call"}
                ],
                "isError": True,
            }
        return await self._pbac_guard.tools_call(params, pctx)


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
        policy_filter: Optional `(agent_name, tool_name) -> bool` (or
            awaitable) hook used to filter the per-agent tool-catalog
            resource (TASK-2603) by the calling principal's policy — the
            same decision path as `tools/list`. `None` (default) means
            everything is visible.
        pbac_resolver: Optional `(pctx, resource, required_permissions) ->
            bool` PBAC resolver (the `PBACPermissionResolver.can_execute`
            shape) enforcing `tools/list`/`tools/call` (TASK-2605). `None`
            (default) denies every call (deny-by-default).
        audit_sink: Optional callback invoked with every `tools/call`
            decision and every principal-resolution failure. `None`
            (default) only logs.
        auth_template: Optional `MCPServerConfig` whose auth-related
            fields (`auth_method`, `oauth2_*`, `api_key_store`,
            `api_key_header`) are copied onto every per-agent
            `MCPServerConfig` this mount builds — nothing upstream of this
            mount otherwise has a way to require authentication on it.
            `oauth2_resource_server_url` is always taken from `config
            .resource_server_url` regardless (RFC 8707 audience scoping
            is mount-level, not template-level). `None` (default) mounts
            with `AuthMethod.NONE`, matching `MCPServerConfig`'s own
            default.
    """

    def __init__(
        self,
        bot_manager: Any,
        config: AgentMCPMountConfig,
        policy_filter: ToolPolicyFilter | None = None,
        pbac_resolver: PBACResolver | None = None,
        audit_sink: AuditSink | None = None,
        auth_template: MCPServerConfig | None = None,
    ) -> None:
        self._bots = bot_manager
        self._config = config
        self._policy_filter = policy_filter
        self._pbac_resolver = pbac_resolver
        self._audit_sink = audit_sink
        self._auth_template = auth_template
        self._servers: dict[str, StreamableHttpMCPServer] = {}
        #: Last-seen `id()` of each agent instance, used to detect a
        #: `reload_agent()` swap without holding a strong reference to the
        #: agent (OQ5 — "never hold the agent object across calls").
        self._last_agent_id: dict[str, int] = {}
        self.logger = logging.getLogger("Parrot.MCP.AgentMount")

    def _build_server_config(self, name: str, path: str) -> MCPServerConfig:
        """Build the per-agent `MCPServerConfig` for `name` at `path`.

        Copies auth fields from `self._auth_template` (if given) so the
        mount can actually require authentication, then overrides
        `oauth2_resource_server_url` with this mount's own
        `resource_server_url` — audience scoping is mount-level (spec §2
        Data Models), never inherited from a shared template.

        Args:
            name: Configured agent name.
            path: The full route path this agent's server answers on.

        Returns:
            The `MCPServerConfig` for that agent's `_AgentBoundMCPServer`.
        """
        base = self._auth_template or MCPServerConfig()
        return replace(
            base,
            name=f"agent-mcp-mount-{name}",
            base_path=path,
            oauth2_resource_server_url=self._config.resource_server_url,
        )

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
            server_config = self._build_server_config(name, path)
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
        exposure_set = build_exposure_set(agent)
        for tool in exposure_set:
            server.register_tool(tool)
        tool_manager = getattr(agent, "tool_manager", None)
        if tool_manager is not None:
            for tool_name in tool_manager.list_tools():
                if tool_name in _INTERNAL_TOOL_NAMES:
                    continue
                own_tool = tool_manager.get_tool(tool_name)
                if own_tool is not None:
                    server.register_tool(own_tool)
        # FEAT-477 TASK-2603: identity card, tool catalog, KB descriptors.
        # Re-registering overwrites the same three URIs with handlers
        # closing over the (possibly new, post-OQ5-rebuild) `agent`.
        register_agent_resources(
            server,
            name,
            agent,
            exposure_names=[tool.name for tool in exposure_set],
            policy_filter=self._policy_filter,
        )

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
