#!/usr/bin/env python3
"""
Ready-to-Use AI-Parrot MCP Server
================================
This script creates an MCP server that exposes your AI-Parrot tools
to any MCP client (Claude Desktop, other AI systems, etc.).

Usage:
  python ai_parrot_mcp_server.py                    # stdio server
  python ai_parrot_mcp_server.py --http             # HTTP server
  python ai_parrot_mcp_server.py --port 8080        # Custom port
"""
import os
import asyncio
import sys
import argparse
import logging
from pathlib import Path
# Import the MCP server implementation (from previous artifact)
from parrot.mcp.server import MCPServer, MCPServerConfig
# Import your existing AI-Parrot tools
try:
    from parrot.tools.openweather import OpenWeatherTool
    OPENWEATHER_AVAILABLE = True
except ImportError:
    OPENWEATHER_AVAILABLE = False

try:
    from parrot.tools.asdb import DatabaseQueryTool
    DATABASE_AVAILABLE = True
except ImportError:
    DATABASE_AVAILABLE = False

try:
    from parrot.tools.google import GoogleLocationTool, GoogleSearchTool
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False

try:
    from parrot.tools.pythonpandas import PythonPandasTool
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False


def setup_logging(level: str = "INFO"):
    """Setup logging configuration."""
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        stream=sys.stderr  # Important: log to stderr for stdio servers
    )


def create_available_tools(safe_mode: bool = False) -> list:
    """Create list of available tools based on imports and configuration."""
    tools = []

    # Weather tool
    if OPENWEATHER_AVAILABLE:
        api_key = os.getenv('OPENWEATHER_APPID') or os.getenv('OPENWEATHER_API_KEY')
        if api_key:
            weather_tool = OpenWeatherTool(
                api_key=api_key,
                default_units='metric'
            )
            tools.append(weather_tool)
            print(f"✅ Added OpenWeatherTool", file=sys.stderr)
        else:
            print(f"⚠️  OpenWeatherTool available but no API key (set OPENWEATHER_API_KEY)", file=sys.stderr)

    # Google tools
    if GOOGLE_AVAILABLE:
        try:
            location_tool = GoogleLocationTool()
            tools.append(location_tool)
            print(f"✅ Added GoogleLocationTool", file=sys.stderr)
        except Exception as e:
            print(f"⚠️  GoogleLocationTool failed to initialize: {e}", file=sys.stderr)

    # Database tool (only in non-safe mode)
    if DATABASE_AVAILABLE and not safe_mode:
        db_tool = DatabaseQueryTool()
        tools.append(db_tool)
        print(f"✅ Added DatabaseQueryTool", file=sys.stderr)
    elif DATABASE_AVAILABLE and safe_mode:
        print(f"⚠️  DatabaseQueryTool skipped in safe mode", file=sys.stderr)

    # Python/Pandas tool (only in non-safe mode)
    if PANDAS_AVAILABLE and not safe_mode:
        pandas_tool = PythonPandasTool()
        tools.append(pandas_tool)
        print(f"✅ Added PythonPandasTool", file=sys.stderr)
    elif PANDAS_AVAILABLE and safe_mode:
        print(f"⚠️  PythonPandasTool skipped in safe mode", file=sys.stderr)

    if not tools:
        print(f"❌ No tools available! Check your imports and API keys.", file=sys.stderr)
        sys.exit(1)

    return tools


async def run_stdio_server(tools: list, server_name: str):
    """Run stdio MCP server."""
    config = MCPServerConfig(
        name=server_name,
        transport="stdio",
        description=f"AI-Parrot tools via MCP ({len(tools)} tools available)"
    )

    server = MCPServer(config)
    server.register_tools(tools)

    print(f"Starting stdio MCP server with {len(tools)} tools...", file=sys.stderr)
    print(f"Server name: {server_name}", file=sys.stderr)
    print(f"Tools: {[tool.name for tool in tools]}", file=sys.stderr)
    print("Ready for MCP client connections...", file=sys.stderr)

    try:
        await server.start()
    except KeyboardInterrupt:
        print("Server shutting down...", file=sys.stderr)
    finally:
        await server.stop()


async def run_http_server(tools: list, host: str, port: int, server_name: str):
    """Run HTTP MCP server."""
    config = MCPServerConfig(
        name=server_name,
        transport="http",
        host=host,
        port=port,
        description=f"AI-Parrot tools via MCP HTTP ({len(tools)} tools available)"
    )

    server = MCPServer(config)
    server.register_tools(tools)

    try:
        await server.start()
        print(f"🚀 MCP Server running at http://{host}:{port}", file=sys.stderr)
        print(f"📡 MCP endpoint: http://{host}:{port}/mcp", file=sys.stderr)
        print(f"ℹ️  Server info: http://{host}:{port}/", file=sys.stderr)
        print(f"🛠️  Tools available: {len(tools)}", file=sys.stderr)
        print(f"📋 Tool names: {[tool.name for tool in tools]}", file=sys.stderr)
        print("Press Ctrl+C to stop", file=sys.stderr)

        # Keep running
        while True:
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        print("\nShutting down HTTP server...", file=sys.stderr)
    finally:
        await server.stop()


def print_usage_examples(server_name: str, tools: list):
    """Print usage examples for the server."""
    print(f"\n{'='*50}", file=sys.stderr)
    print(f"MCP Server Ready: {server_name}", file=sys.stderr)
    print(f"Tools available: {len(tools)}", file=sys.stderr)
    print(f"{'='*50}", file=sys.stderr)

    print(f"\n📖 Usage Examples:", file=sys.stderr)

    # Claude Desktop configuration
    print(f"\n1️⃣ Claude Desktop Configuration:", file=sys.stderr)
    print(f"Add this to your Claude Desktop MCP config:", file=sys.stderr)
    print(f'''{{
  "mcpServers": {{
    "{server_name}": {{
      "command": "python",
      "args": ["{Path(__file__).absolute()}"],
      "env": {{
        "OPENWEATHER_API_KEY": "your-api-key-here"
      }}
    }}
  }}
}}''', file=sys.stderr)

    # Direct MCP client usage
    print(f"\n2️⃣ With Your MCP Client:", file=sys.stderr)
    print(f"config = create_local_mcp_server(", file=sys.stderr)
    print(f'    name="{server_name}",', file=sys.stderr)
    print(f'    script_path="{Path(__file__).absolute()}"', file=sys.stderr)
    print(f")", file=sys.stderr)

    # Tool list
    print(f"\n3️⃣ Available Tools:", file=sys.stderr)
    for tool in tools:
        print(f"  • {tool.name}: {tool.description[:60]}...", file=sys.stderr)

    print(f"\n{'='*50}", file=sys.stderr)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="AI-Parrot MCP Server - Expose your tools via MCP protocol"
    )
    parser.add_argument(
        "--http",
        action="store_true",
        help="Run HTTP server instead of stdio"
    )
    parser.add_argument(
        "--host",
        default="localhost",
        help="Host for HTTP server (default: localhost)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port for HTTP server (default: 8080)"
    )
    parser.add_argument(
        "--name",
        default="ai-parrot-tools",
        help="Server name (default: ai-parrot-tools)"
    )
    parser.add_argument(
        "--safe-mode",
        action="store_true",
        help="Run in safe mode (exclude potentially risky tools like database/python)"
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level (default: INFO)"
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(args.log_level)

    # Create available tools
    tools = create_available_tools(safe_mode=args.safe_mode)

    # Print usage examples
    print_usage_examples(args.name, tools)

    # Run appropriate server
    try:
        if args.http:
            asyncio.run(run_http_server(tools, args.host, args.port, args.name))
        else:
            asyncio.run(run_stdio_server(tools, args.name))
    except KeyboardInterrupt:
        print("\n👋 Goodbye!", file=sys.stderr)
    except Exception as e:
        print(f"❌ Server error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
