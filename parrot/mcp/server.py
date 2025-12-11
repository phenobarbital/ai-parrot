"""
MCP Server Implementation - Expose AI-Parrot Tools via MCP Protocol
=================================================================
This creates an MCP server that exposes your existing AbstractTool instances
as MCP tools that can be consumed by any MCP client.
"""
import logging
import asyncio
import argparse
from typing import List, Optional
from aiohttp import web

# AI-Parrot imports
from parrot.tools.abstract import AbstractTool

# Config
from parrot.mcp.config import MCPServerConfig

# Transports
from parrot.mcp.transports.stdio import StdioMCPServer
from parrot.mcp.transports.http import HttpMCPServer
from parrot.mcp.transports.sse import SseMCPServer
from parrot.mcp.transports.unix import UnixMCPServer
from parrot.mcp.transports.quic import QuicMCPServer

# Suppress noisy loggers
logging.getLogger('matplotlib').setLevel(logging.ERROR)
logging.getLogger('PIL').setLevel(logging.ERROR)
logging.getLogger('urllib3').setLevel(logging.ERROR)
logging.getLogger('requests').setLevel(logging.ERROR)


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
        elif config.transport == "quic":
            self.server = QuicMCPServer(config)
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
        """Start the server."""
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

def create_unix_mcp_server(
    name: str = "ai-parrot-tools",
    socket_path: Optional[str] = None,
    tools: Optional[List[AbstractTool]] = None,
    **kwargs,
) -> MCPServer:
    """Create an Unix MCP server."""
    config = MCPServerConfig(
        name=name,
        transport="unix",
        socket_path=socket_path,
        **kwargs,
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
