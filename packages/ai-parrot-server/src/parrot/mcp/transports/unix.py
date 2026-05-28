import os
import signal
import asyncio
import contextlib
import json
import logging
from typing import Dict, Any, Optional, Callable
from pathlib import Path

from parrot.mcp.config import MCPServerConfig
from parrot.mcp.transports.base import MCPServerBase
from parrot.mcp.client import MCPClientConfig, MCPConnectionError

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


class UnixMCPSession:
    """MCP session for Unix socket transport."""

    def __init__(self, config: MCPClientConfig, logger):
        self.config = config
        self.logger = logger
        self._request_id = 0
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._initialized = False
        self._response_futures: Dict[int, asyncio.Future] = {}
        self._read_task: Optional[asyncio.Task] = None

    async def connect(self):
        """Connect to MCP server via Unix socket."""
        try:
            self.logger.info(f"Connecting to Unix socket: {self.config.socket_path}")

            if not self.config.socket_path:
                raise ValueError("socket_path is required for unix transport")

            if not os.path.exists(self.config.socket_path):
                raise MCPConnectionError(
                    f"Unix socket does not exist: {self.config.socket_path}"
                )

            # Connect to Unix socket
            self._reader, self._writer = await asyncio.open_unix_connection(
                path=self.config.socket_path
            )

            # Start background task to read responses
            self._read_task = asyncio.create_task(self._read_responses())

            # Initialize MCP session
            await self._initialize_session()
            self._initialized = True

            self.logger.info(f"Unix socket connection established to {self.config.name}")

        except Exception as e:
            await self.disconnect()
            raise MCPConnectionError(f"Unix socket connection failed: {e}") from e

    async def _read_responses(self):
        """Background task to read responses from server."""
        try:
            while True:
                if not self._reader:
                    break

                line = await self._reader.readline()
                if not line:
                    self.logger.warning("Server closed connection")
                    break

                try:
                    response = json.loads(line.decode('utf-8').strip())
                    request_id = response.get('id')

                    if request_id and request_id in self._response_futures:
                        future = self._response_futures.pop(request_id)
                        if 'error' in response:
                            future.set_exception(
                                MCPConnectionError(f"MCP Error: {response['error']}")
                            )
                        else:
                            future.set_result(response.get('result'))
                    else:
                        # Notification or unsolicited message
                        self.logger.debug(f"Received message without pending request: {response}")

                except json.JSONDecodeError as e:
                    self.logger.warning(f"Invalid JSON from server: {e}")
                except Exception as e:
                    self.logger.error(f"Error processing response: {e}")

        except asyncio.CancelledError:
            self.logger.debug("Read task cancelled")
        except Exception as e:
            self.logger.error(f"Error in read loop: {e}")

    async def _initialize_session(self):
        """Initialize MCP session over Unix socket."""
        try:
            init_result = await self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "ai-parrot-mcp-client", "version": "1.0.0"}
            })

            # Send initialized notification
            await self._send_notification("notifications/initialized")

        except Exception as e:
            raise MCPConnectionError(f"Unix socket session initialization failed: {e}") from e

    async def _send_request(self, method: str, params: dict = None) -> dict:
        """Send JSON-RPC request via Unix socket."""
        if not self._writer:
            raise MCPConnectionError("Not connected")

        self._request_id += 1
        request_id = self._request_id

        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params is not None:
            request["params"] = params

        # Create future for response
        future = asyncio.Future()
        self._response_futures[request_id] = future

        # Send request
        request_line = json.dumps(request) + "\n"
        self._writer.write(request_line.encode('utf-8'))
        await self._writer.drain()

        self.logger.debug(f"Sent request: {method} (id={request_id})")

        # Wait for response with timeout
        try:
            return await asyncio.wait_for(
                future,
                timeout=self.config.timeout
            )
        except asyncio.TimeoutError:
            self._response_futures.pop(request_id, None)
            raise MCPConnectionError(f"Request timeout: {method}")

    async def _send_notification(self, method: str, params: dict = None):
        """Send JSON-RPC notification (no response expected)."""
        if not self._writer:
            raise MCPConnectionError("Not connected")

        notification = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            notification["params"] = params

        notification_line = json.dumps(notification) + "\n"
        self._writer.write(notification_line.encode('utf-8'))
        await self._writer.drain()

        self.logger.debug(f"Sent notification: {method}")

    async def list_tools(self):
        """List available tools."""
        if not self._initialized:
            raise MCPConnectionError("Session not initialized")

        result = await self._send_request("tools/list")
        tools = result.get("tools", [])

        tool_objects = []
        for tool_dict in tools:
            tool_obj = type('MCPTool', (), tool_dict)()
            tool_objects.append(tool_obj)

        return tool_objects

    async def call_tool(self, tool_name: str, arguments: dict):
        """Call a tool."""
        if not self._initialized:
            raise MCPConnectionError("Session not initialized")

        result = await self._send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments
        })

        content_items = []
        if "content" in result:
            for item in result["content"]:
                content_obj = type('ContentItem', (), item)()
                content_items.append(content_obj)

        return type('ToolCallResult', (), {"content": content_items})()

    async def disconnect(self):
        """Disconnect Unix socket session."""
        self._initialized = False

        # Cancel read task
        if self._read_task and not self._read_task.done():
            self._read_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._read_task
            self._read_task = None

        # Cancel pending requests
        for future in self._response_futures.values():
            if not future.done():
                future.cancel()
        self._response_futures.clear()

        # Close connection
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception as e:
                self.logger.debug(f"Error closing writer: {e}")
            finally:
                self._writer = None
                self._reader = None

        self.logger.info("Unix socket disconnected")
