"""Utilities for starting the MCP server inside the aiohttp application."""
from __future__ import annotations
from typing import Dict, List, Optional, Union
import asyncio
import contextlib
import inspect
from importlib import import_module
from aiohttp import web
from navconfig.logging import logging
from ...conf import (
    MCP_SERVER_DESCRIPTION,
    MCP_SERVER_HOST,
    MCP_SERVER_LOG_LEVEL,
    MCP_SERVER_NAME,
    MCP_SERVER_PORT,
    MCP_SERVER_TRANSPORT,
    MCP_STARTED_TOOLS,
)
from ...mcp.server import MCPServer, MCPServerConfig, HttpMCPServer, SseMCPServer
from ...tools.abstract import AbstractTool
from ...tools.toolkit import AbstractToolkit
from .config import TransportConfig


class ParrotMCPServer:
    """Manage lifecycle of multiple MCP servers (multi-transport) attached to an aiohttp app."""

    def __init__(
        self,
        *,
        transports: Optional[Union[str, List[str], Dict[str, TransportConfig]]] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        tools: Optional[Dict[str, str]] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        log_level: Optional[str] = None,
        allow_anonymous: bool = True,
    ) -> None:
        self.name = name or MCP_SERVER_NAME
        self.description = description or MCP_SERVER_DESCRIPTION
        self.log_level = log_level or MCP_SERVER_LOG_LEVEL
        self.tools_config = tools if isinstance(tools, dict) else MCP_STARTED_TOOLS
        self.toolkit_instance = tools if isinstance(tools, AbstractToolkit) else None
        self.allow_anonymous = allow_anonymous
        # Parse transport configuration
        self.transport_configs = self._parse_transports(
            transports, host, port
        )
        # Multiple servers, one per transport
        self.servers: Dict[str, MCPServer] = {}
        self._server_tasks: Dict[str, asyncio.Task] = {}
        self.logger = logging.getLogger("Parrot.MCPServer")
        self.app: Optional[web.Application] = None

        # Multiple servers, one per transport
        self.servers: Dict[str, MCPServer] = {}
        self._server_tasks: Dict[str, asyncio.Task] = {}

    def _parse_transports(
        self,
        transports: Optional[Union[str, List[str], Dict[str, TransportConfig]]],
        default_host: Optional[str],
        default_port: Optional[int],
    ) -> Dict[str, TransportConfig]:
        """Parse transport configuration into normalized format."""
        if transports is None:
            # Default: HTTP only
            transports = MCP_SERVER_TRANSPORT or "http"

        configs = {}

        if isinstance(transports, str):
            # Single transport string: "stdio" or "http"
            transport = transports.lower()
            host = default_host or MCP_SERVER_HOST if transport in {"http", "sse"} else None
            port = default_port or MCP_SERVER_PORT if transport in {"http", "sse"} else None
            configs[transport] = TransportConfig(
                transport=transport,
                host=host,
                port=port,
            )

        elif isinstance(transports, list):
            # List of transport names: ["stdio", "http"]
            for i, transport in enumerate(transports):
                transport = transport.lower()
                is_http_like = transport in {"http", "sse"}
                port = ((default_port or MCP_SERVER_PORT) + i) if is_http_like else None
                configs[transport] = TransportConfig(
                    transport=transport,
                    host=(default_host or MCP_SERVER_HOST) if is_http_like else None,
                    port=port,
                    name_suffix=f"{i}" if len(transports) > 1 else None,
                )

        elif isinstance(transports, dict):
            # Full control: {"stdio": TransportConfig(...), "http": TransportConfig(...)}
            configs = transports

        return configs

    def setup(self, app: web.Application) -> None:
        """Register lifecycle hooks inside the aiohttp application."""
        self.app = app
        app["parrot_mcp_server"] = self
        app.on_startup.append(self.on_startup)
        app.on_shutdown.append(self.on_shutdown)
        self.logger.notice(
            ":: ParrotMCPServer registered for aiohttp app lifecycle management"
        )

    async def on_startup(self, app: web.Application) -> None:  # pylint: disable=unused-argument
        """Start the MCP server once aiohttp finishes bootstrapping."""
        tools = await self._load_configured_tools()
        if not tools:
            self.logger.info("No MCP tools configured to start")
            return

        # Start a server for each enabled transport
        for transport_key, config in self.transport_configs.items():
            if not config.enabled:
                continue

            server_name = self.name
            if config.name_suffix:
                server_name = f"{self.name}-{config.name_suffix}"

            mcp_config = MCPServerConfig(
                name=server_name,
                description=self.description,
                transport=config.transport,
                host=config.host,
                port=config.port,
                log_level=self.log_level,
            )

            # Ensure MCP endpoints bypass the auth middleware (uses AuthHandler.exclude_list)
            self._add_auth_exclusions(
                [
                    mcp_config.base_path,
                    f"{mcp_config.base_path.rstrip('/')}/events",
                    f"{mcp_config.base_path.rstrip('/')}/.well-known/oauth-authorization-server",
                    f"{mcp_config.base_path.rstrip('/')}/oauth/register",
                    f"{mcp_config.base_path.rstrip('/')}/oauth/authorize",
                    f"{mcp_config.base_path.rstrip('/')}/oauth/token",
                ]
            )

            if config.transport == "stdio":
                server = MCPServer(mcp_config)
                server.register_tools(tools)
                self.servers[transport_key] = server

                start_coro = server.start()
                self._server_tasks[transport_key] = asyncio.create_task(start_coro)
                self.logger.info(f"Spawned stdio MCP server task: {server_name}")

            elif config.transport in {"http", "sse"}:
                # Launch HTTP/SSE MCP server using existing aiohttp app
                if config.transport == "sse":
                    server = SseMCPServer(mcp_config, parent_app=app)
                else:
                    server = HttpMCPServer(mcp_config, parent_app=app)
                server.register_tools(tools)
                self.servers[transport_key] = server

                # Solo registra rutas, no crea nueva app
                await server.start()

                self.logger.info(
                    f"MCP server '{server_name}' routes registered on existing app"
                )

    async def on_shutdown(self, app: web.Application) -> None:  # pylint: disable=unused-argument
        """Stop the MCP server when aiohttp starts shutting down."""
        shutdown_errors = []

        # Stop all servers
        for transport_key, server in self.servers.items():
            try:
                await server.stop()
                self.logger.info(f"Stopped MCP server: {transport_key}")
            except Exception as exc:
                shutdown_errors.append((transport_key, exc))
                self.logger.error(f"Failed stopping MCP server {transport_key}: {exc}")

        # Cancel stdio tasks
        for transport_key, task in self._server_tasks.items():
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

        self._server_tasks.clear()
        self.servers.clear()

        if shutdown_errors:
            self.logger.warning(
                f"Shutdown completed with {len(shutdown_errors)} errors"
            )
        else:
            self.logger.info("All MCP servers shutdown complete")

    def _add_auth_exclusions(self, paths: List[str]) -> None:
        """Register paths that should bypass the Auth middleware (if present)."""
        if not self.allow_anonymous:
            return

        if not self.app:
            return

        auth_handler = self.app.get("auth")
        if not auth_handler:
            self.logger.debug("Auth handler not found; skipping auth exclusions for MCP")
            return

        for path in paths:
            auth_handler.add_exclude_list(path)
            # Also add glob-style pattern to cover subpaths
            if not path.endswith("*"):
                auth_handler.add_exclude_list(f"{path}*")
        self.logger.info("Registered MCP paths as auth exclusions: %s", paths)

    async def _load_configured_tools(self) -> List[AbstractTool]:
        """Instantiate every tool declared in configuration."""
        loaded: List[AbstractTool] = []

        if not self.tools_config:
            return loaded

        for class_name, module_path in self.tools_config.items():
            if isinstance(module_path, (AbstractTool)):
                loaded.append(module_path)
                continue
            elif isinstance(module_path, AbstractToolkit):
                toolkit = module_path
                await self._maybe_start_toolkit(toolkit, class_name)
                loaded.extend(toolkit.get_tools())
                continue
            try:
                module = import_module(module_path)
                tool_cls = getattr(module, class_name)
            except (ImportError, AttributeError) as exc:
                self.logger.error(
                    "Unable to import MCP tool %s from %s: %s",
                    class_name,
                    module_path,
                    exc,
                )
                continue

            instances = await self._initialize_tool(tool_cls, class_name)
            if not instances:
                continue

            loaded.extend(instances)

        self.logger.info("Loaded %s MCP tools", len(loaded))
        return loaded

    async def _initialize_tool(
        self,
        tool_cls,
        class_name: str,
    ) -> List[AbstractTool]:
        """Instantiate either a toolkit or an individual AbstractTool."""
        try:
            instance = tool_cls()
        except Exception as exc:
            self.logger.error("Unable to instantiate %s: %s", class_name, exc)
            return []

        if isinstance(instance, AbstractToolkit):
            await self._maybe_start_toolkit(instance, class_name)
            return list(instance.get_tools())

        if isinstance(instance, AbstractTool):
            return [instance]

        self.logger.warning(
            "Configured MCP entry %s is neither an AbstractTool nor AbstractToolkit",
            class_name,
        )
        return []

    async def _maybe_start_toolkit(self, toolkit: AbstractToolkit, class_name: str) -> None:
        """Call toolkit.start() when available."""
        try:
            result = toolkit.start()
            if inspect.isawaitable(result):
                await result
            self.logger.debug("Toolkit %s started", class_name)
        except Exception as exc:  # pragma: no cover - logging path
            self.logger.error("Toolkit %s failed during startup: %s", class_name, exc)
