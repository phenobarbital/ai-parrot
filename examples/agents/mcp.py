"""
MCP Usage Examples - All Transport Types and Authentication Methods
=================================================================
"""
import asyncio
import logging
from parrot.mcp.integration import (
    MCPEnabledMixin,
    MCPServerConfig,
    create_local_mcp_server,
    create_http_mcp_server,
    create_fireflies_mcp_server,
    create_api_key_mcp_server
)
from parrot.bots.agent import BasicAgent

logging.basicConfig(level=logging.INFO)


class CompleteMCPAgent(MCPEnabledMixin, BasicAgent):
    """Agent with complete MCP capabilities."""
    pass


async def example_local_stdio_server():
    """Example: Local stdio server (your working calculator example)."""
    print("=== Local Stdio MCP Server ===")

    agent = CompleteMCPAgent(name="Local Agent", llm="openai")

    try:
        # Add local calculator server
        tools = await agent.add_local_mcp_server(
            name="calculator",
            script_path="./test_calc_server.py",
            timeout=10.0,
            allowed_tools=["add", "multiply"]  # Filter tools
        )

        print(f"Registered tools: {tools}")

        response = await agent.conversation(
            "What's 25 times 8?",
            user_id="local_user"
        )

        print(f"Response: {response.message}")

    finally:
        await agent.shutdown()


async def example_http_with_api_key():
    """Example: HTTP MCP server with API key authentication."""
    print("=== HTTP MCP Server with API Key ===")

    agent = CompleteMCPAgent(name="API Agent", llm="openai")

    try:
        # Add HTTP server with API key auth
        tools = await agent.add_http_mcp_server(
            name="weather_api",
            url="https://api.example.com/mcp",
            auth_type="api_key",
            auth_config={
                "api_key": "your-api-key-here",
                "header_name": "X-API-Key"
            },
            headers={
                "Content-Type": "application/json",
                "User-Agent": "AI-Parrot-Client/1.0"
            },
            timeout=15.0
        )

        print(f"Registered HTTP tools: {tools}")

        # Or use the convenience function
        # tools = await agent.add_mcp_server(create_api_key_mcp_server(
        #     name="weather_api",
        #     url="https://api.example.com/mcp",
        #     api_key="your-api-key-here"
        # ))

    except Exception as e:
        print(f"HTTP server example failed (expected): {e}")
    finally:
        await agent.shutdown()


async def example_oauth_bearer_token():
    """Example: OAuth/Bearer token authentication."""
    print("=== OAuth Bearer Token MCP Server ===")

    agent = CompleteMCPAgent(name="OAuth Agent", llm="anthropic")

    try:
        # Add server with Bearer token
        config = MCPServerConfig(
            name="oauth_service",
            url="https://api.service.com/mcp",
            transport="http",
            auth_type="bearer",
            auth_config={
                "access_token": "your-oauth-access-token-here"
            },
            headers={
                "Accept": "application/json",
                "User-Agent": "AI-Parrot/1.0"
            },
            timeout=20.0,
            allowed_tools=["search", "analyze"],  # Only allow specific tools
            blocked_tools=["delete", "modify"]   # Block dangerous tools
        )

        tools = await agent.add_mcp_server(config)
        print(f"OAuth tools: {tools}")

    except Exception as e:
        print(f"OAuth example failed (expected): {e}")
    finally:
        await agent.shutdown()


async def example_fireflies_integration():
    """Example: Fireflies.ai MCP server (if it existed)."""
    print("=== Fireflies.ai MCP Integration ===")

    agent = CompleteMCPAgent(name="Fireflies Agent", llm="openai")

    try:
        # Add Fireflies server using convenience function
        tools = await agent.add_fireflies_mcp_server(
            access_token="your-fireflies-access-token",
            server_name="fireflies_meeting"
        )

        print(f"Fireflies tools: {tools}")

        response = await agent.conversation(
            "Get my recent meeting transcripts",
            user_id="meeting_user"
        )

        print(f"Fireflies response: {response.message}")

    except Exception as e:
        print(f"Fireflies example failed (expected): {e}")
    finally:
        await agent.shutdown()


async def example_basic_auth():
    """Example: HTTP Basic authentication."""
    print("=== HTTP Basic Authentication ===")

    agent = CompleteMCPAgent(name="Basic Auth Agent", llm="openai")

    try:
        config = MCPServerConfig(
            name="basic_auth_server",
            url="https://secure-api.example.com/mcp",
            transport="http",
            auth_type="basic",
            auth_config={
                "username": "your-username",
                "password": "your-password"
            },
            timeout=10.0
        )

        tools = await agent.add_mcp_server(config)
        print(f"Basic auth tools: {tools}")

    except Exception as e:
        print(f"Basic auth example failed (expected): {e}")
    finally:
        await agent.shutdown()


async def example_multiple_servers_different_transports():
    """Example: Multiple MCP servers with different transports."""
    print("=== Multiple MCP Servers - Mixed Transports ===")

    agent = CompleteMCPAgent(name="Multi-Transport Agent", llm="openai")

    try:
        # Local stdio server
        local_tools = await agent.add_local_mcp_server(
            name="local_calc",
            script_path="./test_calc_server.py"
        )

        # HTTP server with API key (would fail in real usage without real server)
        # http_tools = await agent.add_http_mcp_server(
        #     name="http_weather",
        #     url="https://api.weather.com/mcp",
        #     auth_type="api_key",
        #     auth_config={"api_key": "weather-key"}
        # )

        # List all connected servers
        servers = agent.list_mcp_servers()
        print(f"Connected servers: {servers}")

        # List all available tools
        all_tools = agent.tool_manager.list_tools()
        mcp_tools = [t for t in all_tools if t.startswith("mcp_")]
        print(f"MCP tools: {mcp_tools}")

        # Use the local calculator
        response = await agent.conversation(
            "Calculate 150 + 250, then multiply by 3",
            user_id="multi_user"
        )

        print(f"Multi-transport response: {response.message}")

    finally:
        await agent.shutdown()


async def example_custom_configuration():
    """Example: Fully custom MCP server configuration."""
    print("=== Custom MCP Server Configuration ===")

    agent = CompleteMCPAgent(name="Custom Agent", llm="anthropic")

    try:
        # Fully customized local server
        custom_config = MCPServerConfig(
            name="custom_python_server",
            command="python",
            args=["-u", "./custom_mcp_server.py", "--verbose"],
            env={
                "PYTHONPATH": "/custom/path",
                "MCP_DEBUG": "true"
            },
            transport="stdio",
            timeout=30.0,
            startup_delay=1.0,
            kill_timeout=10.0,
            retry_count=5,
            allowed_tools=["search", "process", "analyze"],
            blocked_tools=["delete", "destroy", "remove"]
        )

        # Would register if server existed
        # tools = await agent.add_mcp_server(custom_config)
        # print(f"Custom configured tools: {tools}")

        print("Custom configuration created successfully")

    finally:
        await agent.shutdown()


async def example_error_handling_and_recovery():
    """Example: Error handling and connection recovery."""
    print("=== Error Handling and Recovery ===")

    agent = CompleteMCPAgent(name="Resilient Agent", llm="openai")

    try:
        # Try to add a server that doesn't exist
        try:
            await agent.add_http_mcp_server(
                name="nonexistent",
                url="https://does-not-exist.com/mcp",
                timeout=5.0
            )
        except Exception as e:
            print(f"✅ Properly caught connection error: {e}")

        # Add a working server
        working_tools = await agent.add_local_mcp_server(
            name="working_calc",
            script_path="./test_calc_server.py",
            retry_count=3
        )
        print(f"✅ Successfully added working server: {working_tools}")

        # Test server removal
        await agent.remove_mcp_server("working_calc")
        print("✅ Successfully removed server")

        servers = agent.list_mcp_servers()
        print(f"✅ Remaining servers: {servers}")

    finally:
        await agent.shutdown()


async def main():
    """Run all examples."""
    examples = [
        example_local_stdio_server,
        example_http_with_api_key,
        example_oauth_bearer_token,
        example_fireflies_integration,
        example_basic_auth,
        example_multiple_servers_different_transports,
        example_custom_configuration,
        example_error_handling_and_recovery
    ]

    for i, example in enumerate(examples, 1):
        print(f"\n{i}. Running {example.__name__}...")
        try:
            await example()
            print("✅ Example completed")
        except Exception as e:
            print(f"❌ Example failed: {e}")

        print("-" * 50)


if __name__ == "__main__":
    try:
        asyncio.run(main())
        print("\n🎉 All MCP examples completed!")
        print("\nYou now have:")
        print("• Stdio transport (working)")
        print("• HTTP transport with auth (ready for real servers)")
        print("• Multiple authentication types")
        print("• Tool filtering and management")
        print("• Error handling and recovery")
        print("• Production-ready MCP integration")
    except KeyboardInterrupt:
        print("\nExamples interrupted")
    except Exception as e:
        print(f"Error: {e}")
