"""Utilities for starting the MCP server inside the aiohttp application."""
from __future__ import annotations

import asyncio
import contextlib
import inspect
from importlib import import_module
from typing import Dict, List, Optional

from aiohttp import web
from navconfig.logging import logging

from ..conf import (
    MCP_SERVER_DESCRIPTION,
    MCP_SERVER_HOST,
    MCP_SERVER_LOG_LEVEL,
    MCP_SERVER_NAME,
    MCP_SERVER_PORT,
    MCP_SERVER_TRANSPORT,
    MCP_STARTED_TOOLS,
)
from ..mcp.server import MCPServer, MCPServerConfig
from ..tools.abstract import AbstractTool
from ..tools.toolkit import AbstractToolkit


class ParrotMCPServer:
    """Manage lifecycle of an MCP server attached to an aiohttp app."""

    def __init__(
        self,
        *,
        transport: Optional[str] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        tools: Optional[Dict[str, str]] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        log_level: Optional[str] = None,
    ) -> None:
        self.transport = (transport or MCP_SERVER_TRANSPORT or "http").lower()
        self.host = host or MCP_SERVER_HOST
        self.port = port or MCP_SERVER_PORT
        self.name = name or MCP_SERVER_NAME
        self.description = description or MCP_SERVER_DESCRIPTION
        self.log_level = log_level or MCP_SERVER_LOG_LEVEL
        self.tools_config = tools or MCP_STARTED_TOOLS

        self.logger = logging.getLogger("Parrot.MCPServer")
        self.app: Optional[web.Application] = None
        self.server: Optional[MCPServer] = None
        self._server_task: Optional[asyncio.Task] = None

    def setup(self, app: web.Application) -> None:
        """Register lifecycle hooks inside the aiohttp application."""
        self.app = app
        app["parrot_mcp_server"] = self
        app.on_startup.append(self.on_startup)
        app.on_shutdown.append(self.on_shutdown)
        self.logger.debug("ParrotMCPServer registered on aiohttp signals")

    async def on_startup(self, app: web.Application) -> None:  # pylint: disable=unused-argument
        """Start the MCP server once aiohttp finishes bootstrapping."""
        tools = await self._load_configured_tools()
        if not tools:
            self.logger.info("No MCP tools configured to start")
            return

        config = MCPServerConfig(
            name=self.name,
            description=self.description,
            transport=self.transport,
            host=self.host,
            port=self.port,
            log_level=self.log_level,
        )
        self.server = MCPServer(config)
        self.server.register_tools(tools)

        start_coro = self.server.start()
        if self.transport == "stdio":
            self._server_task = asyncio.create_task(start_coro)
            self.logger.info("Spawned stdio MCP server task")
        else:
            await start_coro
            self.logger.info(
                "MCP server started using %s transport on %s:%s",
                self.transport,
                self.host,
                self.port,
            )

    async def on_shutdown(self, app: web.Application) -> None:  # pylint: disable=unused-argument
        """Stop the MCP server when aiohttp starts shutting down."""
        if not self.server:
            return

        try:
            await self.server.stop()
        except Exception as exc:  # pragma: no cover - logging path
            self.logger.error("Failed stopping MCP server: %s", exc)

        if self._server_task and not self._server_task.done():
            self._server_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._server_task
        self._server_task = None
        self.server = None
        self.logger.info("MCP server shutdown complete")

    async def _load_configured_tools(self) -> List[AbstractTool]:
        """Instantiate every tool declared in configuration."""
        loaded: List[AbstractTool] = []

        if not self.tools_config:
            return loaded

        for class_name, module_path in self.tools_config.items():
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
