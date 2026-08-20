from __future__ import annotations

import asyncio
import contextlib
import json
import socket
from dataclasses import dataclass
from typing import Any, Optional

import uvicorn
from mcp import types
from mcp.server.fastmcp.server import StreamableHTTPASGIApp
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from navconfig.logging import logging
from starlette.applications import Starlette
from starlette.routing import Route

from parrot.tools.abstract import ToolResult
from parrot.tools.manager import ToolFormat, ToolManager


@dataclass(slots=True)
class CodexMCPBridgeConfig:
    """Runtime details for the ephemeral ai-parrot MCP bridge."""

    name: str
    url: str

    def to_codex_config_args(self) -> list[str]:
        """Return Codex CLI ``-c`` overrides for this streamable HTTP server."""
        return [
            "-c",
            f"mcp_servers.{self.name}.url={json.dumps(self.url)}",
        ]


class CodexToolBridge:
    """Expose a live :class:`ToolManager` as a temporary MCP server for Codex.

    Tool calls intentionally go through ``ToolManager.execute_tool()`` so
    guardrails, grants, confirmation, compression, and credential broker logic
    stay on the same path as native ai-parrot tool execution.
    """

    def __init__(
        self,
        tool_manager: ToolManager,
        *,
        permission_context: Optional[Any] = None,
        host: str = "127.0.0.1",
        port: int = 0,
        path: str = "/mcp",
        name: str = "ai_parrot",
        max_tools: Optional[int] = None,
        tool_names: Optional[list[str]] = None,
    ) -> None:
        self.tool_manager = tool_manager
        self.permission_context = permission_context
        self.host = host
        self.port = port
        self.path = path
        self.name = name
        self.max_tools = max_tools
        self.tool_names = set(tool_names or [])
        self.logger = logging.getLogger(self.__class__.__name__)
        self._server: Optional[uvicorn.Server] = None
        self._task: Optional[asyncio.Task[Any]] = None
        self._config: Optional[CodexMCPBridgeConfig] = None

    @property
    def config(self) -> CodexMCPBridgeConfig:
        if self._config is None:
            raise RuntimeError("CodexToolBridge has not been started")
        return self._config

    async def __aenter__(self) -> "CodexToolBridge":
        await self.start()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.stop()

    async def start(self) -> CodexMCPBridgeConfig:
        """Start the streamable HTTP MCP server in the current event loop."""
        if self._config is not None:
            return self._config

        port = self.port or self._reserve_port()
        mcp_server = self._build_mcp_server()
        session_manager = StreamableHTTPSessionManager(
            app=mcp_server,
            json_response=True,
            stateless=True,
        )

        @contextlib.asynccontextmanager
        async def lifespan(_: Starlette):
            async with session_manager.run():
                yield

        app = Starlette(
            routes=[
                Route(
                    self.path,
                    endpoint=StreamableHTTPASGIApp(session_manager),
                )
            ],
            lifespan=lifespan,
        )
        self._server = uvicorn.Server(
            uvicorn.Config(
                app,
                host=self.host,
                port=port,
                log_level="warning",
                access_log=False,
            )
        )
        self._task = asyncio.create_task(self._server.serve())
        await self._wait_started()
        self._config = CodexMCPBridgeConfig(
            name=self.name,
            url=f"http://{self.host}:{port}{self.path}",
        )
        return self._config

    async def stop(self) -> None:
        """Stop the bridge server if it is running."""
        if self._server is not None:
            self._server.should_exit = True
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except asyncio.TimeoutError:  # pragma: no cover - defensive stop
                self._task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._task
        self._server = None
        self._task = None
        self._config = None

    def list_mcp_tools(self) -> list[types.Tool]:
        """Return MCP tool definitions for currently registered tools."""
        tools: list[types.Tool] = []
        allowed = self.tool_names
        for schema in self.tool_manager.get_tool_schemas(ToolFormat.GENERIC):
            name = schema.get("name")
            if not name or (allowed and name not in allowed):
                continue
            parameters = schema.get("parameters") or schema.get("input_schema") or {}
            tools.append(
                types.Tool(
                    name=name,
                    description=schema.get("description") or f"Tool: {name}",
                    inputSchema=parameters,
                )
            )
            if self.max_tools is not None and len(tools) >= self.max_tools:
                break
        return tools

    async def execute_mcp_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> types.CallToolResult:
        """Execute one MCP tool through ``ToolManager.execute_tool()``."""
        try:
            result = await self.tool_manager.execute_tool(
                tool_name,
                arguments,
                permission_context=self.permission_context,
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.exception("Codex MCP tool execution failed: %s", tool_name)
            return self._error_result(f"Error executing {tool_name}: {exc}")

        if isinstance(result, ToolResult):
            return self._tool_result_to_mcp(result)
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=str(result))],
            isError=False,
        )

    def _build_mcp_server(self) -> Server:
        server = Server(self.name)

        @server.list_tools()
        async def list_tools() -> list[types.Tool]:
            return self.list_mcp_tools()

        @server.call_tool(validate_input=True)
        async def call_tool(
            tool_name: str,
            arguments: dict[str, Any],
        ) -> types.CallToolResult:
            return await self.execute_mcp_tool(tool_name, arguments)

        return server

    def _tool_result_to_mcp(self, result: ToolResult) -> types.CallToolResult:
        text = self._result_text(result)
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=text)],
            isError=result.status != "success",
        )

    @staticmethod
    def _result_text(result: ToolResult) -> str:
        if result.status != "success":
            return f"Error: {result.error or 'Unknown error'}"
        if isinstance(result.result, str):
            text = result.result
        elif isinstance(result.result, (dict, list)):
            text = json.dumps(result.result, indent=2, default=str)
        else:
            text = str(result.result)
        if result.metadata:
            metadata = json.dumps(result.metadata, indent=2, default=str)
            text = f"{text}\n\nMetadata: {metadata}"
        return text

    @staticmethod
    def _error_result(message: str) -> types.CallToolResult:
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=message)],
            isError=True,
        )

    @staticmethod
    def _reserve_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    async def _wait_started(self) -> None:
        assert self._server is not None
        assert self._task is not None
        for _ in range(100):
            if self._task.done():
                exc = self._task.exception()
                if exc is not None:
                    raise exc
                raise RuntimeError("Codex MCP bridge stopped during startup")
            if self._server.started:
                return
            await asyncio.sleep(0.05)
        raise TimeoutError("Timed out starting Codex MCP bridge")
