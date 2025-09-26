"""
MCP Server Implementation - Expose AI-Parrot Tools via MCP Protocol
=================================================================
This creates an MCP server that exposes your existing AbstractTool instances
as MCP tools that can be consumed by any MCP client.
"""
from typing import Dict, List, Any, Optional
from abc import ABC, abstractmethod
import asyncio
import json
import logging
import sys
import argparse
from dataclasses import dataclass
import io
from pathlib import Path
import traceback
import aiohttp
from aiohttp import web
# AI-Parrot imports
from parrot.tools.abstract import AbstractTool, ToolResult

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
    transport: str = "stdio"  # "stdio" or "http"
    host: str = "localhost"
    port: int = 8080

    # Tool filtering
    allowed_tools: Optional[List[str]] = None
    blocked_tools: Optional[List[str]] = None

    # Logging
    log_level: str = "INFO"


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
        # Setup logging to stderr ONLY
        logging.basicConfig(
            level=logging.ERROR,  # Reduce noise
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            stream=sys.stderr,  # Critical: only stderr
            force=True  # Override any existing logging config
        )
        self.logger = logging.getLogger(f"MCPServer.{config.name}")

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
        for adapter in self.tools.values():
            tools.append(adapter.to_mcp_tool_definition())

        return {"tools": tools}

    async def handle_tools_call(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle tools/call request."""
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        self.logger.info(f"Calling tool: {tool_name} with args: {arguments}")

        if tool_name not in self.tools:
            raise Exception(f"Tool not found: {tool_name}")

        adapter = self.tools[tool_name]
        result = await adapter.execute(arguments)

        return result

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
                raise Exception(f"Unknown method: {method}")

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

    def __init__(self, config: MCPServerConfig):
        super().__init__(config)
        self.app = web.Application()
        self.runner = None
        self.site = None

        # Setup routes
        self.app.router.add_post("/mcp", self._handle_http_request)
        self.app.router.add_get("/", self._handle_info)

    async def start(self):
        """Start the HTTP MCP server."""
        self.logger.info(f"Starting HTTP MCP server on {self.config.host}:{self.config.port}")

        self.runner = web.AppRunner(self.app)
        await self.runner.setup()

        self.site = web.TCPSite(
            self.runner,
            self.config.host,
            self.config.port
        )
        await self.site.start()

        self.logger.info(f"HTTP MCP server started at http://{self.config.host}:{self.config.port}")
        self.logger.info(f"MCP endpoint: http://{self.config.host}:{self.config.port}/mcp")

    async def stop(self):
        """Stop the HTTP server."""
        if self.site:
            await self.site.stop()
        if self.runner:
            await self.runner.cleanup()
        self.logger.info("HTTP MCP server stopped")

    async def _handle_http_request(self, request: web.Request) -> web.Response:
        """Handle HTTP JSON-RPC request."""
        try:
            data = await request.json()
            method = data.get("method")
            params = data.get("params", {})
            request_id = data.get("id")

            self.logger.info(f"HTTP request: {method}")

            try:
                if method == "initialize":
                    result = await self.handle_initialize(params)
                elif method == "tools/list":
                    result = await self.handle_tools_list(params)
                elif method == "tools/call":
                    result = await self.handle_tools_call(params)
                else:
                    raise Exception(f"Unknown method: {method}")

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

    async def _handle_info(self, request: web.Request) -> web.Response:
        """Handle info endpoint."""
        info = {
            "name": self.config.name,
            "version": self.config.version,
            "description": self.config.description,
            "transport": "http",
            "endpoint": "/mcp",
            "tools": list(self.tools.keys()),
            "tool_count": len(self.tools)
        }

        return web.json_response(info)


class MCPServer:
    """Main MCP server class that chooses transport."""

    def __init__(self, config: MCPServerConfig):
        self.config = config

        if config.transport == "stdio":
            self.server = StdioMCPServer(config)
        elif config.transport == "http":
            self.server = HttpMCPServer(config)
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

    server = MCPServer(config)

    if tools:
        server.register_tools(tools)

    return server


# CLI support

async def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="AI-Parrot MCP Server"
    )
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio",
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

    # Register example tools (you'd register your actual tools here)
    # server.register_tool(YourOpenWeatherTool())
    # server.register_tool(YourDatabaseQueryTool())

    try:
        if args.transport == "http":
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
