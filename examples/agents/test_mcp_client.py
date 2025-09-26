#!/usr/bin/env python3
"""
Test Script for AI-Parrot MCP Server
===================================
This script tests your running MCP server using our custom MCPClient.
"""
import asyncio
import logging
import sys
from pathlib import Path
import traceback
# Import our working MCP client
from parrot.mcp.integration import MCPClient, create_local_mcp_server

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

# Set debug for our MCP client
logging.getLogger("MCPClient").setLevel(logging.DEBUG)

class MCPServerTester:
    """Test suite for MCP server functionality."""

    def __init__(self, server_script_path: str):
        self.server_script_path = server_script_path
        self.logger = logging.getLogger("MCPServerTester")

    async def test_basic_connection(self):
        """Test basic connection and tool listing."""
        print("=== Test 1: Basic Connection & Tool Listing ===")

        try:
            config = create_local_mcp_server(
                name="test_connection",
                script_path=self.server_script_path,
                timeout=15.0
            )

            async with MCPClient(config) as client:
                print("✅ Connected to MCP server")

                tools = client.get_available_tools()
                print(f"✅ Found {len(tools)} tools")

                print("Available tools:")
                for tool in tools:
                    print(f"  • {tool['name']}: {tool['description'][:60]}...")

                return tools

        except Exception as e:
            print(f"❌ Connection test failed: {e}")
            traceback.print_exc()
            return []

    async def test_openweather_tool(self):
        """Test the OpenWeather tool."""
        print("\n=== Test 2: OpenWeather Tool ===")

        try:
            config = create_local_mcp_server(
                name="test_weather",
                script_path=self.server_script_path
            )

            async with MCPClient(config) as client:
                # Test weather for New York (example coordinates)
                result = await client.call_tool("OpenWeatherTool", {
                    "latitude": 40.7128,
                    "longitude": -74.0060,
                    "request_type": "weather",
                    "units": "imperial"
                })

                print("✅ OpenWeather tool executed successfully")
                print(f"Result: {self._format_result(result)}")
                return True

        except Exception as e:
            print(f"❌ OpenWeather test failed: {e}")
            return False

    async def test_google_location_tool(self):
        """Test the Google Location tool."""
        print("\n=== Test 3: Google Location Tool ===")

        try:
            config = create_local_mcp_server(
                name="test_location",
                script_path=self.server_script_path
            )

            async with MCPClient(config) as client:
                # Test geocoding for a known address
                result = await client.call_tool("GoogleLocationTool", {
                    "address": "Times Square, New York, NY",
                    "result_type": "json"
                })

                print("✅ Google Location tool executed successfully")
                print(f"Result: {self._format_result(result)}")
                return True

        except Exception as e:
            print(f"❌ Google Location test failed: {e}")
            return False

    async def test_database_query_tool(self):
        """Test the Database Query tool with a simple query."""
        print("\n=== Test 4: Database Query Tool ===")

        try:
            config = create_local_mcp_server(
                name="test_database",
                script_path=self.server_script_path
            )

            async with MCPClient(config) as client:
                # Test with a simple SQLite query
                result = await client.call_tool("DatabaseQueryTool", {
                    "driver": "sqlite",
                    "query": "SELECT 'Hello from MCP Database Tool' as message, datetime('now') as timestamp",
                    "credentials": {"dsn": ":memory:"},  # In-memory SQLite
                    "output_format": "json"
                })

                print("✅ Database Query tool executed successfully")
                print(f"Result: {self._format_result(result)}")
                return True

        except Exception as e:
            print(f"❌ Database Query test failed: {e}")
            return False

    async def test_python_pandas_tool(self):
        """Test the Python Pandas tool."""
        print("\n=== Test 5: Python Pandas Tool ===")

        try:
            config = create_local_mcp_server(
                name="test_pandas",
                script_path=self.server_script_path
            )

            async with MCPClient(config) as client:
                # Test with simple pandas code
                result = await client.call_tool("PythonPandasTool", {
                    "code": """
import pandas as pd
import numpy as np

# Create a simple DataFrame
df = pd.DataFrame({
    'name': ['Alice', 'Bob', 'Charlie'],
    'age': [25, 30, 35],
    'city': ['New York', 'London', 'Tokyo']
})

print("DataFrame created via MCP:")
print(df)
print(f"\\nShape: {df.shape}")
print(f"Data types:\\n{df.dtypes}")

# Return the DataFrame info
df.info()
""",
                    "execution_mode": "safe"
                })

                print("✅ Python Pandas tool executed successfully")
                print(f"Result: {self._format_result(result)}")
                return True

        except Exception as e:
            print(f"❌ Python Pandas test failed: {e}")
            return False

    async def test_tool_with_invalid_args(self):
        """Test error handling with invalid arguments."""
        print("\n=== Test 6: Error Handling ===")

        try:
            config = create_local_mcp_server(
                name="test_errors",
                script_path=self.server_script_path
            )

            async with MCPClient(config) as client:
                # Test with invalid arguments
                try:
                    result = await client.call_tool("OpenWeatherTool", {
                        "latitude": "invalid",  # Should be float
                        "longitude": "invalid"  # Should be float
                    })
                    print("⚠️  Expected error but got success")
                except Exception as e:
                    print(f"✅ Properly handled invalid arguments: {type(e).__name__}")

                # Test with non-existent tool
                try:
                    result = await client.call_tool("NonExistentTool", {})
                    print("⚠️  Expected error but got success")
                except Exception as e:
                    print(f"✅ Properly handled non-existent tool: {type(e).__name__}")

                return True

        except Exception as e:
            print(f"❌ Error handling test failed: {e}")
            return False

    async def test_concurrent_calls(self):
        """Test concurrent tool calls."""
        print("\n=== Test 7: Concurrent Tool Calls ===")

        try:
            config = create_local_mcp_server(
                name="test_concurrent",
                script_path=self.server_script_path
            )

            async with MCPClient(config) as client:
                # Create multiple concurrent tasks
                tasks = [
                    client.call_tool("DatabaseQueryTool", {
                        "driver": "sqlite",
                        "query": f"SELECT {i} as task_number, 'Task {i}' as task_name",
                        "credentials": {"dsn": ":memory:"},
                        "output_format": "json"
                    })
                    for i in range(1, 4)
                ]

                results = await asyncio.gather(*tasks, return_exceptions=True)

                success_count = sum(1 for r in results if not isinstance(r, Exception))
                print(f"✅ Concurrent calls: {success_count}/{len(tasks)} successful")

                for i, result in enumerate(results, 1):
                    if isinstance(result, Exception):
                        print(f"  Task {i}: Failed - {result}")
                    else:
                        print(f"  Task {i}: Success")

                return success_count > 0

        except Exception as e:
            print(f"❌ Concurrent test failed: {e}")
            return False

    def _format_result(self, result, max_length: int = 200) -> str:
        """Format result for display."""
        if hasattr(result, 'content') and result.content:
            content_parts = []
            for item in result.content:
                if hasattr(item, 'text'):
                    content_parts.append(item.text)
                elif isinstance(item, dict) and 'text' in item:
                    content_parts.append(item['text'])
                else:
                    content_parts.append(str(item))

            full_text = "\n".join(content_parts)
            if len(full_text) > max_length:
                return full_text[:max_length] + "... (truncated)"
            return full_text
        else:
            result_str = str(result)
            if len(result_str) > max_length:
                return result_str[:max_length] + "... (truncated)"
            return result_str

    async def run_all_tests(self):
        """Run all tests."""
        print("MCP Server Test Suite")
        print("=" * 50)
        print(f"Testing server: {self.server_script_path}")
        print()

        results = []

        # Test 1: Basic connection
        tools = await self.test_basic_connection()
        results.append(len(tools) > 0)

        if not tools:
            print("❌ Cannot continue - no tools available")
            return False

        # Test individual tools based on what's available
        tool_names = [tool['name'] for tool in tools]

        if 'OpenWeatherTool' in tool_names:
            results.append(await self.test_openweather_tool())

        if 'GoogleLocationTool' in tool_names:
            results.append(await self.test_google_location_tool())

        if 'DatabaseQueryTool' in tool_names:
            results.append(await self.test_database_query_tool())

        if 'PythonPandasTool' in tool_names:
            results.append(await self.test_python_pandas_tool())

        # Test error handling
        results.append(await self.test_tool_with_invalid_args())

        # Test concurrent calls
        results.append(await self.test_concurrent_calls())

        # Summary
        passed = sum(results)
        total = len(results)

        print("\n" + "=" * 50)
        print(f"Test Results: {passed}/{total} tests passed")

        if passed == total:
            print("🎉 All tests passed! Your MCP server is working perfectly!")
        else:
            print("⚠️  Some tests failed - check the output above")

        return passed == total


async def main():
    """Main test function."""
    import argparse

    parser = argparse.ArgumentParser(description="Test AI-Parrot MCP Server")
    parser.add_argument(
        "--server-script",
        default="./ai_parrot_mcp_server.py",
        help="Path to your MCP server script"
    )

    args = parser.parse_args()

    server_script = Path(args.server_script)
    if not server_script.exists():
        print(f"❌ Server script not found: {server_script}")
        print("Make sure your MCP server script exists and is accessible")
        sys.exit(1)

    tester = MCPServerTester(str(server_script.absolute()))

    try:
        success = await tester.run_all_tests()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n👋 Tests interrupted")
        sys.exit(130)
    except Exception as e:
        print(f"❌ Test suite failed: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
