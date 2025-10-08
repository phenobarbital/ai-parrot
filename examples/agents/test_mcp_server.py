"""
Practical Examples - Expose Your AI-Parrot Tools via MCP Server
==============================================================
These examples show how to create MCP servers with your actual tools.
"""
import sys
import asyncio
from pathlib import Path
import json
from parrot.conf import OPENWEATHER_APPID
# Your existing AI-Parrot tools
from parrot.tools.openweather import OpenWeatherTool
from parrot.tools.databasequery import DatabaseQueryTool
from parrot.tools.google import GoogleLocationTool, GoogleSearchTool
from parrot.tools.pythonpandas import PythonPandasTool
from parrot.tools.pdfprint import PDFPrintTool

# The MCP server implementation
from parrot.mcp.server import (
    MCPServer,
    create_stdio_mcp_server,
    create_http_mcp_server,
    MCPServerConfig
)


async def create_weather_tools_server():
    """Create an MCP server with weather and location tools."""
    print("=== Weather & Location Tools MCP Server ===")

    # Initialize your tools
    weather_tool = OpenWeatherTool(
        api_key=OPENWEATHER_APPID,  # Replace with actual key
        default_units="metric"
    )

    location_tool = GoogleLocationTool()
    search_tool = GoogleSearchTool()

    # Create MCP server
    server = create_stdio_mcp_server(
        name="weather-location-tools",
        tools=[weather_tool, location_tool, search_tool],
        description="Weather and location services via MCP",
        allowed_tools=["openweather_tool", "google_location", "google_search"]  # Optional filtering
    )

    print("Weather tools MCP server created")
    print("Tools available: openweather_tool, google_location, google_search")
    print("Run with: python -m parrot.mcp.weather_server")

    return server


async def create_data_analysis_server():
    """Create an MCP server with data analysis tools."""
    print("=== Data Analysis Tools MCP Server ===")

    # Initialize data analysis tools
    db_tool = DatabaseQueryTool()

    pandas_tool = PythonPandasTool()

    # Create HTTP MCP server for data analysis
    server = create_http_mcp_server(
        name="data-analysis-tools",
        host="localhost",
        port=8081,
        tools=[db_tool, pandas_tool],
        description="Database queries and data analysis via MCP"
    )

    print("Data analysis MCP server created")
    print("Tools available: database_query, python_pandas")
    print("Will run at: http://localhost:8081/mcp")

    return server


async def create_comprehensive_tools_server():
    """Create an MCP server with multiple tool types."""
    print("=== Comprehensive AI-Parrot Tools Server ===")

    # Initialize various tools
    tools = [
        OpenWeatherTool(api_key=OPENWEATHER_APPID),
        DatabaseQueryTool(),
        GoogleLocationTool(),
        GoogleSearchTool(),
        PythonPandasTool(),
        PDFPrintTool()
    ]

    # Create server with custom configuration
    config = MCPServerConfig(
        name="ai-parrot-comprehensive",
        version="1.0.0",
        description="Comprehensive AI-Parrot tool suite via MCP",
        transport="stdio",
        log_level="INFO",
        # You could filter tools if needed
        # allowed_tools=["openweather_tool", "database_query"],
        # blocked_tools=["python_pandas"]  # Block potentially dangerous tools
    )

    server = MCPServer(config)
    server.register_tools(tools)

    print(f"Comprehensive MCP server created with {len(tools)} tools")
    print("Available tools:")
    for tool in tools:
        print(f"  - {tool.name}: {tool.description[:50]}...")

    return server


async def create_secure_http_server():
    """Create an HTTP MCP server with tool filtering for security."""
    print("=== Secure HTTP MCP Server ===")

    # Only expose safe, read-only tools
    safe_tools = [
        OpenWeatherTool(api_key=OPENWEATHER_APPID),
        GoogleLocationTool(),
        DatabaseQueryTool(),
    ]

    server = create_http_mcp_server(
        name="secure-ai-parrot-tools",
        host="0.0.0.0",  # Allow external connections
        port=8082,
        tools=safe_tools,
        description="Secure AI-Parrot tools (read-only operations)",
        allowed_tools=["openweather_tool", "google_location"],
        blocked_tools=["database_query", "python_pandas"]  # Block risky tools
    )

    print("Secure HTTP MCP server created")
    print("Only safe, read-only tools exposed")
    print("Will run at: http://0.0.0.0:8082/mcp")

    return server


# Standalone server scripts

async def run_weather_server():
    """Standalone weather tools MCP server."""
    weather_tool = OpenWeatherTool(
        api_key="your-openweather-api-key",
        default_units="metric"
    )

    server = create_stdio_mcp_server(
        name="weather-service",
        tools=[weather_tool],
        description="Weather information via OpenWeatherMap API"
    )

    print("Weather MCP server starting...", file=sys.stderr)
    print("Connect with: python -c 'from mcp_client import connect; connect(\"python weather_server.py\")'", file=sys.stderr)

    try:
        await server.start()
    except KeyboardInterrupt:
        print("Weather server shutting down...", file=sys.stderr)
    finally:
        await server.stop()


async def run_database_server():
    """Standalone database tools MCP server."""
    db_tool = DatabaseQueryTool()

    server = create_stdio_mcp_server(
        name="database-service",
        tools=[db_tool],
        description="Database query service via MCP",
        # Security: limit database operations
        allowed_tools=["database_query"]
    )

    print("Database MCP server starting...", file=sys.stderr)

    try:
        await server.start()
    except KeyboardInterrupt:
        print("Database server shutting down...", file=sys.stderr)
    finally:
        await server.stop()


async def run_http_multi_tool_server():
    """Standalone HTTP server with multiple tools."""
    tools = [
        OpenWeatherTool(api_key="demo-key"),
        GoogleLocationTool(),
        PythonPandasTool()
    ]

    server = create_http_mcp_server(
        name="multi-tool-http-service",
        host="localhost",
        port=8080,
        tools=tools,
        description="Multi-tool AI-Parrot service via HTTP"
    )

    try:
        await server.start()
        print(f"Multi-tool HTTP MCP server running at http://localhost:8080")
        print("Available endpoints:")
        print("  - GET  /     : Server info")
        print("  - POST /mcp  : MCP JSON-RPC")
        print("\nPress Ctrl+C to stop")

        # Keep running
        while True:
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        await server.stop()


# Usage with Claude Desktop or other MCP clients

def generate_claude_desktop_config():
    """Generate configuration for Claude Desktop to use your MCP server."""
    config = {
        "mcpServers": {
            "ai-parrot-weather": {
                "command": "python",
                "args": [str(Path.cwd() / "weather_mcp_server.py")],
                "env": {
                    "OPENWEATHER_API_KEY": "your-api-key-here"
                }
            },
            "ai-parrot-database": {
                "command": "python",
                "args": [str(Path.cwd() / "database_mcp_server.py")],
                "env": {
                    "DB_CONNECTION_STRING": "your-db-connection"
                }
            },
            "ai-parrot-http": {
                "url": "http://localhost:8080/mcp",
                "transport": "http"
            }
        }
    }

    print("Claude Desktop MCP Server Configuration:")
    print("Add this to your Claude Desktop config file:")
    print(json.dumps(config, indent=2))

    return config


# Main demo function

async def demo_all_servers():
    """Demo creating different types of MCP servers."""
    print("AI-Parrot MCP Server Examples")
    print("=" * 40)

    # Demo 1: Weather server
    weather_server = await create_weather_tools_server()

    # Demo 2: Data analysis server
    data_server = await create_data_analysis_server()

    # Demo 3: Comprehensive server
    comprehensive_server = await create_comprehensive_tools_server()

    # Demo 4: Secure HTTP server
    secure_server = await create_secure_http_server()

    # Demo 5: Claude Desktop config
    generate_claude_desktop_config()

    print("\n" + "=" * 40)
    print("MCP Server Creation Examples Complete!")
    print("\nTo actually run a server:")
    print("1. Choose one of the server creation functions above")
    print("2. Call server.start() to begin serving")
    print("3. Connect with any MCP client (Claude Desktop, your MCP client, etc.)")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        server_type = sys.argv[1]

        if server_type == "weather":
            asyncio.run(run_weather_server())
        elif server_type == "database":
            asyncio.run(run_database_server())
        elif server_type == "http":
            asyncio.run(run_http_multi_tool_server())
        else:
            print(f"Unknown server type: {server_type}")
            print("Usage: python mcp_server_examples.py [weather|database|http]")
    else:
        # Run demo
        asyncio.run(demo_all_servers())
