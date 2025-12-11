import sys
import os
import asyncio
import json
import logging
from typing import Dict, Any, Optional

from parrot.mcp.config import MCPServerConfig
from parrot.mcp.transports.base import MCPServerBase
from parrot.mcp.client import MCPClientConfig, MCPConnectionError

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


class StdioMCPSession:
    """MCP session for stdio transport."""

    def __init__(self, config: MCPClientConfig, logger):
        self.config = config
        self.logger = logger
        self._request_id = 0
        self._process = None
        self._stdin = None
        self._stdout = None
        self._stderr = None
        self._initialized = False

    async def connect(self):
        """Connect to MCP server via stdio."""
        if self._process:
            await self.disconnect()

        try:
            await self._start_process()
            await self._initialize_session()
            self._initialized = True
            self.logger.info(f"Stdio connection established to {self.config.name}")

        except Exception as e:
            await self.disconnect()
            raise MCPConnectionError(f"Stdio connection failed: {e}") from e

    async def _start_process(self):
        """Start the MCP server process."""
        if not self.config.command:
            raise ValueError("Command required for stdio transport")

        args = self.config.args or []
        env = dict(os.environ)
        if self.config.env:
            env.update(self.config.env)

        self._process = await asyncio.create_subprocess_exec(
            self.config.command,
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env
        )

        self._stdin = self._process.stdin
        self._stdout = self._process.stdout
        self._stderr = self._process.stderr

        await asyncio.sleep(self.config.startup_delay)

        if self._process.returncode is not None:
            stderr_output = ""
            if self._stderr:
                try:
                    stderr_data = await asyncio.wait_for(self._stderr.read(1024), timeout=2.0)
                    stderr_output = stderr_data.decode('utf-8', errors='replace')
                except asyncio.TimeoutError:
                    stderr_output = "No error output available"

            raise RuntimeError(f"Process failed to start: {stderr_output}")

    async def _initialize_session(self):
        """Initialize the MCP session."""
        try:
            await self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "ai-parrot-mcp-client", "version": "1.0.0"}
            })
            await self._send_notification("notifications/initialized")
        except Exception as e:
            raise MCPConnectionError(f"Session initialization failed: {e}") from e

    async def _send_request(self, method: str, params: dict = None) -> dict:
        if not self._process or self._process.returncode is not None:
            raise MCPConnectionError("Process is not running")

        request_id = self._get_next_id()
        request = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params:
            request["params"] = params

        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.config.timeout

        try:
            line = (json.dumps(request) + "\n").encode("utf-8")
            self.logger.debug(f"Stdio sending: {line.decode().strip()}")
            self._stdin.write(line)
            await self._stdin.drain()

            response = None
            while True:
                timeout = max(0.1, deadline - loop.time())
                response_line = await asyncio.wait_for(self._stdout.readline(), timeout=timeout)
                if not response_line:
                    raise MCPConnectionError("Empty response - connection closed")

                response_str = response_line.decode("utf-8", errors="replace").strip()
                if not response_str:
                    continue
                self.logger.debug(f"Stdio received: {response_str}")

                # Skip non-JSON garbage
                try:
                    candidate = json.loads(response_str)
                except json.JSONDecodeError:
                    self.logger.debug(f"Ignoring non-JSON stdout: {response_str!r}")
                    continue

                # Only accept responses with our request id; ignore notifications/others
                if candidate.get("id") != request_id:
                    # could be a notification or another message; ignore
                    continue

                response = candidate
                break

            if "error" in response:
                raise MCPConnectionError(f"Server error: {response['error']}")

            return response.get("result", {})

        except asyncio.TimeoutError:
            raise MCPConnectionError(f"Request timeout after {self.config.timeout} seconds")
        except Exception as e:
            if isinstance(e, MCPConnectionError):
                raise
            raise MCPConnectionError(f"Request failed: {e}") from e

    async def _send_notification(self, method: str, params: dict = None):
        """Send JSON-RPC notification."""
        notification = {"jsonrpc": "2.0", "method": method}
        if params:
            notification["params"] = params

        notification_line = json.dumps(notification) + "\n"
        self.logger.debug(f"Stdio notification: {notification_line.strip()}")

        self._stdin.write(notification_line.encode('utf-8'))
        await self._stdin.drain()

    def _get_next_id(self):
        self._request_id += 1
        return self._request_id

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

        result_obj = type('ToolCallResult', (), {"content": content_items})()
        return result_obj

    async def disconnect(self):
        """Disconnect stdio session."""
        self._initialized = False

        if self._process:
            try:
                if self._stdin and not self._stdin.is_closing():
                    self._stdin.close()
                    await self._stdin.wait_closed()

                if self._process.returncode is None:
                    try:
                        await asyncio.wait_for(
                            self._process.wait(),
                            timeout=self.config.kill_timeout
                        )
                    except asyncio.TimeoutError:
                        self.logger.warning("Process didn't terminate, force killing")
                        self._process.kill()
                        await self._process.wait()

            except Exception as e:
                self.logger.debug(f"Error during disconnect: {e}")
            finally:
                self._process = None
                self._stdin = None
                self._stdout = None
                self._stderr = None
