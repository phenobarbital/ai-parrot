"""
MCP Server Implementation - Expose AI-Parrot Tools via MCP Protocol
=================================================================
This creates an MCP server that exposes your existing AbstractTool instances
as MCP tools that can be consumed by any MCP client.
"""
import os
from typing import Dict, List, Any, Optional, Callable
from abc import ABC, abstractmethod
import contextlib
import asyncio
import json
import logging
import sys
import argparse
import signal
from dataclasses import dataclass
import io
from pathlib import Path
import traceback
import uuid
import aiohttp
from aiohttp import web
# AI-Parrot imports
from parrot.tools.abstract import AbstractTool, ToolResult
from .oauth import OAuthAuthorizationServer

# Suppress noisy loggers
logging.getLogger('matplotlib').setLevel(logging.ERROR)
logging.getLogger('PIL').setLevel(logging.ERROR)
logging.getLogger('urllib3').setLevel(logging.ERROR)
logging.getLogger('requests').setLevel(logging.ERROR)

@dataclass
class MCPServerConfig:
    """Configuration for MCP server."""
    name: str = "ai-parrot-mcp-server"
    version: str = "1.0.0"
    description: str = "AI-Parrot Tools via MCP Protocol"

    # Server settings
    transport: str = "stdio"  # "stdio" or "http" or "unix"
    host: str = "localhost"
    port: int = 8080
    socket_path: Optional[str] = None  # For UNIX socket transport

    # Tool filtering
    allowed_tools: Optional[List[str]] = None
    blocked_tools: Optional[List[str]] = None

    # Logging
    log_level: str = "INFO"

    # OAuth / Authorization
    enable_oauth: bool = False
    oauth_scopes: Optional[List[str]] = None
    oauth_token_ttl: int = 3600
    oauth_code_ttl: int = 600
    oauth_allow_dynamic_registration: bool = True

    # base path for HTTP transport
    base_path: str = "/mcp"
    events_path: str = "/mcp/events"


class MCPToolAdapter:
    """Adapts AI-Parrot AbstractTool to MCP tool format."""

    def __init__(self, tool: AbstractTool):
        self.tool = tool
        self.logger = logging.getLogger(f"MCPToolAdapter.{tool.name}")

    def to_mcp_tool_definition(self) -> Dict[str, Any]:
        """Convert AbstractTool to MCP tool definition."""
        # Extract schema from the tool's args_schema
        input_schema = {}
        if hasattr(self.tool, 'args_schema') and self.tool.args_schema:
            try:
                # Get the JSON schema from the Pydantic model
                input_schema = self.tool.args_schema.model_json_schema()
            except Exception as e:
                self.logger.warning(f"Could not extract schema for {self.tool.name}: {e}")
                input_schema = {"type": "object", "properties": {}}

        return {
            "name": self.tool.name or "unknown_tool",
            "description": self.tool.description or f"Tool: {self.tool.name}",
            "inputSchema": input_schema
        }

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the AI-Parrot tool and convert result to MCP format."""
        try:
            # Execute the tool
            result = await self.tool._execute(**arguments)

            # Convert ToolResult to MCP response format
            if isinstance(result, ToolResult):
                return self._toolresult_to_mcp(result)
            else:
                # Handle direct results (for backward compatibility)
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": str(result)
                        }
                    ],
                    "isError": False
                }

        except Exception as e:
            self.logger.error(f"Tool execution failed: {e}")
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Error executing tool: {str(e)}"
                    }
                ],
                "isError": True
            }

    def _toolresult_to_mcp(self, result: ToolResult) -> Dict[str, Any]:
        """Convert ToolResult to MCP response format."""
        content_items = []

        if result.status == "success":
            # Handle different result types
            if isinstance(result.result, str):
                content_items.append({
                    "type": "text",
                    "text": result.result
                })
            elif isinstance(result.result, dict):
                content_items.append({
                    "type": "text",
                    "text": json.dumps(result.result, indent=2, default=str)
                })
            else:
                content_items.append({
                    "type": "text",
                    "text": str(result.result)
                })

            # Add metadata if present
            if result.metadata:
                content_items.append({
                    "type": "text",
                    "text": f"\nMetadata: {json.dumps(result.metadata, indent=2, default=str)}"
                })

        else:
            # Handle error case
            error_text = result.error or "Unknown error occurred"
            content_items.append({
                "type": "text",
                "text": f"Error: {error_text}"
            })

        return {
            "content": content_items,
            "isError": result.status != "success"
        }


class MCPServerBase(ABC):
    """Base class for MCP servers."""

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self.tools: Dict[str, MCPToolAdapter] = {}
        self.logger = logging.getLogger(f"MCPServer.{config.name}")
        log_level = getattr(logging, config.log_level.upper(), logging.WARNING)
        self.logger.setLevel(log_level)
        self.oauth_server: Optional[OAuthAuthorizationServer] = None
        if self.config.enable_oauth:
            self.oauth_server = OAuthAuthorizationServer(
                default_scopes=self.config.oauth_scopes,
                allow_dynamic_registration=self.config.oauth_allow_dynamic_registration,
                token_ttl=self.config.oauth_token_ttl,
                code_ttl=self.config.oauth_code_ttl,
            )

    def register_tool(self, tool: AbstractTool):
        """Register an AI-Parrot tool with the MCP server."""
        tool_name = tool.name

        # Apply filtering
        if self.config.allowed_tools and tool_name not in self.config.allowed_tools:
            self.logger.info(f"Skipping tool {tool_name} (not in allowed_tools)")
            return

        if self.config.blocked_tools and tool_name in self.config.blocked_tools:
            self.logger.info(f"Skipping tool {tool_name} (in blocked_tools)")
            return

        adapter = MCPToolAdapter(tool)
        self.tools[tool_name] = adapter
        self.logger.info(f"Registered tool: {tool_name}")

    def register_tools(self, tools: List[AbstractTool]):
        """Register multiple tools."""
        for tool in tools:
            self.register_tool(tool)

    def _authenticate_request(self, request: web.Request) -> Optional[web.Response]:
        """Validate OAuth access token when OAuth is enabled."""
        if not self.oauth_server:
            return None

        token = self.oauth_server.bearer_token_from_header(
            request.headers.get("Authorization")
        )
        if not self.oauth_server.is_token_valid(token):
            return web.json_response(
                {
                    "error": "unauthorized",
                    "error_description": "Valid Bearer token is required",
                },
                status=401,
            )
        return None

    async def handle_initialize(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle MCP initialize request."""
        self.logger.info("Initializing MCP server...")

        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {
                    "listChanged": False
                }
            },
            "serverInfo": {
                "name": self.config.name,
                "version": self.config.version,
                "description": self.config.description
            }
        }

    async def handle_tools_list(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle tools/list request."""
        self.logger.info(f"Listing {len(self.tools)} available tools")

        tools = []
        tools.extend(
            adapter.to_mcp_tool_definition() for adapter in self.tools.values()
        )

        return {"tools": tools}

    async def handle_tools_call(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle tools/call request."""
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        self.logger.info(f"Calling tool: {tool_name} with args: {arguments}")

        if tool_name not in self.tools:
            raise RuntimeError(
                f"Tool not found: {tool_name}"
            )

        adapter = self.tools[tool_name]
        return await adapter.execute(arguments)

    @abstractmethod
    async def start(self):
        """Start the MCP server."""
        pass

    @abstractmethod
    async def stop(self):
        """Stop the MCP server."""
        pass


class StdioMCPServer(MCPServerBase):
    """MCP server using stdio transport."""

    def __init__(self, config: MCPServerConfig):
        super().__init__(config)
        self._request_id = 0
        self._running = False

    async def start(self):
        """Start the stdio MCP server."""
        self.logger.info(f"Starting stdio MCP server with {len(self.tools)} tools...")
        self._running = True

        while self._running:
            try:
                # Read line from stdin
                line = sys.stdin.readline()
                if not line:
                    break

                line = line.strip()
                if not line:
                    continue

                # Parse JSON-RPC request
                try:
                    request = json.loads(line)
                    response = await self._handle_request(request)

                    if response:
                        print(json.dumps(response), flush=True)

                except json.JSONDecodeError as e:
                    self.logger.warning(f"Invalid JSON received: {e}")
                    continue

            except KeyboardInterrupt:
                break
            except Exception as e:
                self.logger.error(f"Error in main loop: {e}")
                continue

        self.logger.info("Stdio MCP server stopped")

    async def stop(self):
        """Stop the stdio server."""
        self._running = False

    async def _handle_request(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Handle a JSON-RPC request."""
        method = request.get("method")
        params = request.get("params", {})
        request_id = request.get("id")

        try:
            if method == "initialize":
                result = await self.handle_initialize(params)
            elif method == "tools/list":
                result = await self.handle_tools_list(params)
            elif method == "tools/call":
                result = await self.handle_tools_call(params)
            elif method == "notifications/initialized":
                # This is a notification, no response needed
                self.logger.info("Client initialization complete")
                return None
            else:
                raise RuntimeError(f"Unknown method: {method}")

            # Return success response
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result
            }

        except Exception as e:
            self.logger.error(f"Error handling {method}: {e}")
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32603,
                    "message": str(e)
                }
            }


class HttpMCPServer(MCPServerBase):
    """MCP server using HTTP transport."""

    def __init__(self, config: MCPServerConfig, parent_app: Optional[web.Application] = None):
        super().__init__(config)
        self.app = parent_app or web.Application()
        self.base_path = config.base_path or '/mcp'
        self.runner = None
        self.site = None
        # define if parent_app is given, we assume setup will be called externally
        self._external_setup = parent_app is not None

        # Setup routes
        self.app.router.add_post(self.base_path, self._handle_http_request)
        self.app.router.add_get("/", self._handle_info)
        if self.oauth_server:
            self.oauth_server.register_routes(self.app)

    async def start(self):
        """Start the HTTP MCP server."""
        self.logger.info(
            f"Starting HTTP MCP server on {self.config.host}:{self.config.port}"
        )

        if not self._external_setup:

            self.runner = web.AppRunner(self.app)
            await self.runner.setup()

            self.site = web.TCPSite(
                self.runner,
                self.config.host,
                self.config.port
            )
            await self.site.start()
        else:
            # Register routes in the parent app
            self.app.router.add_post(self.base_path, self._handle_http_request)
            self.app.router.add_get(f"{self.base_path}/info", self._handle_info)

            self.logger.info(
                f"HTTP MCP routes registered at {self.base_path}"
            )


        self.logger.info(
            f"HTTP MCP server started at http://{self.config.host}:{self.config.port}"
        )
        self.logger.info(
            f"MCP endpoint: http://{self.config.host}:{self.config.port}/mcp"
        )

    async def stop(self):
        """Stop the HTTP server."""
        if self.site:
            await self.site.stop()
        if self.runner:
            await self.runner.cleanup()
        self.logger.info("HTTP MCP server stopped")

    async def _handle_http_request(self, request: web.Request) -> web.Response:
        """Handle HTTP JSON-RPC request with Anthropic compatibility."""
        try:
            auth_response = self._authenticate_request(request)
            if auth_response:
                return auth_response

            data = await request.json()
            method = data.get("method")
            params = data.get("params", {})
            request_id = data.get("id", None)

            self.logger.debug(f"Received HTTP MCP request: {data}")

            # Detect Anthropic mode
            anthropic_mode = request.headers.get("anthropic-beta") == "mcp-client-2025-04-04"

            self.logger.info(
                f"HTTP request: {method} (anthropic_mode={anthropic_mode})"
            )

            try:
                if method == "initialize":
                    result = await self.handle_initialize(params)
                elif method == "tools/list":
                    result = await self.handle_tools_list(params)
                    # Convert to Anthropic format if requested
                    if anthropic_mode:
                        result = self._convert_tools_to_anthropic(result)
                elif method == "tools/call":
                    result = await self.handle_tools_call(params)
                elif method == "notifications/initialized":
                    # This is a notification, no response needed
                    self.logger.info("Client initialization complete")
                    return web.Response(status=204)  # No Content
                else:
                    raise RuntimeError(
                        f"Unknown method: {method}"
                    )

                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": result
                }

            except Exception as e:
                self.logger.error(f"Error handling {method}: {e}")
                # Only send error response if this was a request (has id)
                if request_id is not None:
                    response = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {
                            "code": -32603,
                            "message": str(e)
                        }
                    }
                else:
                    # It's a notification that failed, just log it
                    return web.Response(status=500, text=str(e))

            return web.json_response(response)

        except Exception as e:
            self.logger.error(f"HTTP request error: {e}")
            return web.json_response(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32700,
                        "message": "Parse error"
                    }
                },
                status=400
            )

    def _convert_tools_to_anthropic(self, mcp_result: Dict[str, Any]) -> Dict[str, Any]:
        """Convert MCP tools/list result to Anthropic format.

        MCP format:
            {"tools": [{"name": "...", "description": "...", "inputSchema": {...}}]}

        Anthropic format:
            {"tools": [{"name": "...", "description": "...", "input_schema": {...}}]}
        """
        if "tools" not in mcp_result:
            return mcp_result

        converted_tools = []
        for tool in mcp_result["tools"]:
            converted_tools.append({
                "name": tool["name"],
                "description": tool["description"],
                "input_schema": tool["inputSchema"]  # camelCase -> snake_case
            })

        return {"tools": converted_tools}

    async def _handle_info(self, request: web.Request) -> web.Response:
        """Handle info endpoint."""
        auth_response = self._authenticate_request(request)
        if auth_response:
            return auth_response

        info = {
            "name": self.config.name,
            "version": self.config.version,
            "description": self.config.description,
            "transport": "http",
            "endpoint": self.config.base_path,
            "tools": list(self.tools.keys()),
            "tool_count": len(self.tools)
        }

        return web.json_response(info)

class UnixMCPServer(MCPServerBase):
    """MCP server using Unix socket transport."""

    def __init__(self, config: MCPServerConfig):
        super().__init__(config)
        self.socket_path = config.socket_path
        if not self.socket_path:
            # Fallback to PID-based naming
            toolkit_name = config.name.replace(" ", "-").lower()
            self.socket_path = f"/tmp/parrot-mcp-{toolkit_name}-{os.getpid()}.sock"

        self.server = None
        self._shutdown_handlers: list[Callable] = []
        self._serve_task: Optional[asyncio.Task] = None
        self._setup_signal_handlers()

    def _setup_signal_handlers(self):
        """Setup graceful shutdown on SIGTERM/SIGINT."""
        def signal_handler(signum, frame):
            self.logger.info(f"Received signal {signum}, initiating shutdown...")
            asyncio.create_task(self.stop())

        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)

    def add_shutdown_handler(self, handler: Callable):
        """Register user-defined shutdown handler."""
        self._shutdown_handlers.append(handler)

    async def start(self):
        """Start Unix socket server."""
        # Cleanup old socket if exists
        if os.path.exists(self.socket_path):
            self.logger.warning(f"Removing existing socket: {self.socket_path}")
            os.unlink(self.socket_path)

        # Ensure parent directory exists
        socket_dir = Path(self.socket_path).parent
        socket_dir.mkdir(parents=True, exist_ok=True)

        self.logger.info(f"Starting Unix socket MCP server at {self.socket_path}")

        # Use asyncio.start_unix_server (menos conflicto con aiohttp)
        self.server = await asyncio.start_unix_server(
            self._handle_connection,
            path=self.socket_path
        )

        # Set socket permissions (readable/writable by owner and group)
        os.chmod(self.socket_path, 0o660)

        self.logger.info(f"Unix MCP server listening on {self.socket_path}")
        self.logger.info(f"Registered {len(self.tools)} tools")

        # Keep server running until stop() cancels the task
        self._serve_task = asyncio.create_task(self.server.serve_forever())
        try:
            await self._serve_task
        except asyncio.CancelledError:
            self.logger.debug("Unix MCP server serve loop cancelled")

    async def _handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle a client connection."""
        addr = writer.get_extra_info('peername', 'unknown')
        self.logger.info(f"New connection from {addr}")

        try:
            while True:
                # Read JSON-RPC message (newline-delimited)
                line = await reader.readline()
                if not line:
                    break

                line = line.decode('utf-8').strip()
                if not line:
                    continue

                try:
                    request = json.loads(line)
                    response = await self._handle_request(request)

                    if response:
                        response_line = json.dumps(response) + "\n"
                        writer.write(response_line.encode('utf-8'))
                        await writer.drain()

                except json.JSONDecodeError as e:
                    self.logger.warning(f"Invalid JSON: {e}")
                    continue

        except asyncio.CancelledError:
            self.logger.info("Connection cancelled")
        except Exception as e:
            self.logger.error(f"Connection error: {e}")
        finally:
            writer.close()
            await writer.wait_closed()
            self.logger.info(f"Connection closed: {addr}")

    async def _handle_request(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Handle JSON-RPC request (same as stdio)."""
        method = request.get("method")
        params = request.get("params", {})
        request_id = request.get("id")

        try:
            if method == "initialize":
                result = await self.handle_initialize(params)
            elif method == "tools/list":
                result = await self.handle_tools_list(params)
            elif method == "tools/call":
                result = await self.handle_tools_call(params)
            elif method == "notifications/initialized":
                self.logger.info("Client initialization complete")
                return None
            else:
                raise RuntimeError(f"Unknown method: {method}")

            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result
            }

        except Exception as e:
            self.logger.error(f"Error handling {method}: {e}")
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32603,
                    "message": str(e)
                }
            }

    async def stop(self):
        """Stop the server and cleanup."""
        self.logger.info("Shutting down Unix MCP server...")

        # Call user shutdown handlers
        for handler in self._shutdown_handlers:
            try:
                result = handler()
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                self.logger.error(f"Error in shutdown handler: {e}")

        # Cancel serve loop first
        if self._serve_task and not self._serve_task.done():
            self._serve_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._serve_task

        # Close server
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.server = None

        # Remove socket file
        if os.path.exists(self.socket_path):
            self.logger.info(f"Removing socket: {self.socket_path}")
            os.unlink(self.socket_path)

        self.logger.info("Shutdown complete")

class SseMCPServer(MCPServerBase):
    """MCP server using SSE transport compatible with ChatGPT and OpenAI MCP clients."""

    def __init__(self, config: MCPServerConfig, parent_app: Optional[web.Application] = None):
        super().__init__(config)
        self.app = parent_app or web.Application()
        self.base_path = config.base_path or "/mcp"
        self.events_path = config.events_path or f"{self.base_path.rstrip('/')}/events"
        self.runner = None
        self.site = None
        self.sessions: Dict[str, asyncio.Queue] = {}
        self._external_setup = parent_app is not None
        self.app.router.add_post(self.base_path, self._handle_http_request)
        # Alias GET on base path to the SSE stream for clients that connect at /mcp
        self.app.router.add_get(self.base_path, self._handle_sse, allow_head=True)
        self.app.router.add_get(self.events_path, self._handle_sse, allow_head=True)
        self.app.router.add_get("/", self._handle_info, allow_head=True)
        if self.oauth_server:
            self.oauth_server.register_routes(self.app)

    async def start(self):
        """Start the SSE MCP server."""
        if self._external_setup:
            self.logger.info("SSE MCP server using existing aiohttp application")
            return

        self.logger.info(
            f"Starting SSE MCP server on {self.config.host}:{self.config.port}"
        )

        self.runner = web.AppRunner(self.app)
        await self.runner.setup()

        self.site = web.TCPSite(
            self.runner,
            self.config.host,
            self.config.port
        )
        await self.site.start()

        self.logger.info(f"SSE MCP server started at http://{self.config.host}:{self.config.port}")
        self.logger.info(
            "MCP endpoints: "
            f"events at http://{self.config.host}:{self.config.port}{self.events_path}, "
            f"requests at http://{self.config.host}:{self.config.port}{self.base_path}"
        )

    async def stop(self):
        """Stop the SSE server."""
        if not self._external_setup:
            if self.site:
                await self.site.stop()
            if self.runner:
                await self.runner.cleanup()

        # Clear any pending sessions
        for session_id, queue in list(self.sessions.items()):
            with contextlib.suppress(Exception):
                queue.put_nowait(None)
            self.sessions.pop(session_id, None)

        self.logger.info("SSE MCP server stopped")

    async def _handle_info(self, request: web.Request) -> web.Response:
        auth_response = self._authenticate_request(request)
        if auth_response:
            return auth_response

        info = {
            "name": self.config.name,
            "version": self.config.version,
            "description": self.config.description,
            "transport": "sse",
            "endpoint": self.events_path,
            "tools": list(self.tools.keys()),
            "tool_count": len(self.tools)
        }
        return web.json_response(info)

    def _get_session_id(self, request: web.Request) -> str:
        return request.headers.get("X-Session-Id") or request.query.get("session") or str(uuid.uuid4())

    async def _handle_sse(self, request: web.Request) -> web.StreamResponse:
        auth_response = self._authenticate_request(request)
        if auth_response:
            return auth_response

        session_id = self._get_session_id(request)
        queue: asyncio.Queue = asyncio.Queue()
        self.sessions[session_id] = queue
        self.logger.info(f"SSE client connected: {session_id}")

        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Session-Id": session_id,
            },
        )

        await response.prepare(request)
        await response.write(self._format_sse_event({"type": "connected", "session": session_id}, event="connection"))

        try:
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=15)
                    if message is None:
                        break
                    await response.write(self._format_sse_event(message))
                except asyncio.TimeoutError:
                    await response.write(b": keep-alive\n\n")
        except asyncio.CancelledError:
            self.logger.info(f"SSE client disconnected: {session_id}")
        finally:
            self.sessions.pop(session_id, None)
            with contextlib.suppress(Exception):
                await response.write_eof()

        return response

    def _format_sse_event(self, payload: Any, event: str = "message") -> bytes:
        data = json.dumps(payload)
        return f"event: {event}\ndata: {data}\n\n".encode("utf-8")

    async def _push_to_session(self, session_id: Optional[str], message: Dict[str, Any]):
        if not session_id:
            return
        if queue := self.sessions.get(session_id):
            try:
                queue.put_nowait(message)
            except Exception as e:
                self.logger.warning(f"Failed to enqueue SSE message for {session_id}: {e}")

    async def _handle_http_request(self, request: web.Request) -> web.Response:
        try:
            auth_response = self._authenticate_request(request)
            if auth_response:
                return auth_response

            data = await request.json()
            method = data.get("method")
            params = data.get("params", {})
            request_id = data.get("id")
            session_id = request.headers.get("X-Session-Id") or request.query.get("session")

            self.logger.info(f"SSE HTTP request: {method} (session {session_id or 'none'})")

            try:
                if method == "initialize":
                    result = await self.handle_initialize(params)
                elif method == "tools/list":
                    result = await self.handle_tools_list(params)
                elif method == "notifications/initialized":
                    # This is a notification, no response needed
                    self.logger.info("Client initialization complete")
                    return web.Response(status=204)  # No Content
                elif method == "tools/call":
                    result = await self.handle_tools_call(params)
                else:
                    raise RuntimeError(
                        f"Unknown method: {method}"
                    )

                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": result
                }

            except Exception as e:
                self.logger.error(f"Error handling {method}: {e}")
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32603,
                        "message": str(e)
                    }
                }

            await self._push_to_session(session_id, response)
            return web.json_response(response)

        except Exception as e:
            self.logger.error(f"SSE HTTP request error: {e}")
            return web.json_response(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32700,
                        "message": "Parse error",
                    }
                },
                status=400
            )


class MCPServer:
    """Main MCP server class that chooses transport."""

    def __init__(self, config: MCPServerConfig, parent_app: Optional[web.Application] = None):
        self.config = config

        if config.transport == "stdio":
            self.server = StdioMCPServer(config)
        elif config.transport == "http":
            self.server = HttpMCPServer(config, parent_app=parent_app)
        elif config.transport == "sse":
            self.server = SseMCPServer(config, parent_app=parent_app)
        elif config.transport == "unix":
            self.server = UnixMCPServer(config)
        else:
            raise ValueError(
                f"Unsupported transport: {config.transport}"
            )

    def register_tool(self, tool: AbstractTool):
        """Register a tool."""
        self.server.register_tool(tool)

    def register_tools(self, tools: List[AbstractTool]):
        """Register multiple tools."""
        self.server.register_tools(tools)

    async def start(self):
        """Start the server."""
        await self.server.start()

    async def stop(self):
        """Stop the server."""
        await self.server.stop()

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()


# Convenience functions

def create_stdio_mcp_server(
    name: str = "ai-parrot-tools",
    tools: Optional[List[AbstractTool]] = None,
    **kwargs
) -> MCPServer:
    """Create a stdio MCP server."""
    config = MCPServerConfig(
        name=name,
        transport="stdio",
        **kwargs
    )

    server = MCPServer(config)

    if tools:
        server.register_tools(tools)

    return server


def create_http_mcp_server(
    name: str = "ai-parrot-tools",
    host: str = "localhost",
    port: int = 8080,
    tools: Optional[List[AbstractTool]] = None,
    parent_app: Optional[web.Application] = None,
    **kwargs
) -> MCPServer:
    """Create an HTTP MCP server."""
    config = MCPServerConfig(
        name=name,
        transport="http",
        host=host,
        port=port,
        **kwargs
    )

    server = HttpMCPServer(
        config,
        parent_app=parent_app
    )

    if tools:
        server.register_tools(tools)

    return server

def create_sse_mcp_server(
    name: str = "ai-parrot-tools",
    host: str = "localhost",
    port: int = 8080,
    tools: Optional[List[AbstractTool]] = None,
    parent_app: Optional[web.Application] = None,
    **kwargs,
) -> MCPServer:
    """Create an SSE MCP server."""
    config = MCPServerConfig(
        name=name,
        transport="sse",
        host=host,
        port=port,
        **kwargs,
    )

    server = MCPServer(config, parent_app=parent_app)
    if tools:
        server.register_tools(tools)

    return server



# CLI support

async def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="AI-Parrot MCP Server"
    )
    parser.add_argument("--transport", choices=["stdio", "http", "sse"], default="stdio",
                        help="Transport type")
    parser.add_argument("--host", default="localhost",
                        help="Host for HTTP server")
    parser.add_argument("--port", type=int, default=8080,
                        help="Port for HTTP server")
    parser.add_argument("--name", default="ai-parrot-tools",
                        help="Server name")
    parser.add_argument("--log-level", default="INFO",
                        help="Log level")

    args = parser.parse_args()

    # Create server config
    config = MCPServerConfig(
        name=args.name,
        transport=args.transport,
        host=args.host,
        port=args.port,
        log_level=args.log_level
    )

    # Create server
    server = MCPServer(config)

    # Register example tools:
    # server.register_tool(YourOpenWeatherTool())
    # server.register_tool(YourDatabaseQueryTool())

    try:
        if args.transport in {"http", "sse"}:
            await server.start()
            print(f"Server running at http://{args.host}:{args.port}")
            print("Press Ctrl+C to stop")

            # Keep running
            while True:
                await asyncio.sleep(1)
        else:
            # For stdio, just start and let it handle stdin
            await server.start()

    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        await server.stop()


if __name__ == "__main__":
    asyncio.run(main())
