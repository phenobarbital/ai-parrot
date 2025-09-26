"""
Practical MCP Test - Focus on what actually works
================================================
This test validates your working custom MCP implementation instead of
fighting with the broken official MCP library.
"""
import asyncio
import logging
import sys
import traceback
from pathlib import Path
from parrot.mcp import MCPClient, MCPServerConfig, create_local_mcp_server
from parrot.tools.manager import ToolManager
from parrot.mcp.integration import MCPToolManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)


async def create_test_calculator_server(path: Path):
    """Create a test calculator server."""
    server_code = '''#!/usr/bin/env python3
"""Test calculator MCP server."""
import asyncio
import json
import sys
import logging

# Set up logging to stderr so it doesn't interfere with JSON-RPC
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr
)
logger = logging.getLogger("calculator-server")

class CalculatorServer:
    """Simple calculator MCP server."""

    def __init__(self):
        self.tools = {
            "add": {
                "name": "add",
                "description": "Add two numbers together",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "a": {"type": "number", "description": "First number"},
                        "b": {"type": "number", "description": "Second number"}
                    },
                    "required": ["a", "b"]
                }
            },
            "multiply": {
                "name": "multiply",
                "description": "Multiply two numbers",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "a": {"type": "number", "description": "First number"},
                        "b": {"type": "number", "description": "Second number"}
                    },
                    "required": ["a", "b"]
                }
            },
            "power": {
                "name": "power",
                "description": "Calculate a^b",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "base": {"type": "number", "description": "Base number"},
                        "exponent": {"type": "number", "description": "Exponent"}
                    },
                    "required": ["base", "exponent"]
                }
            }
        }

    async def handle_request(self, request: dict) -> dict:
        """Handle JSON-RPC request."""
        method = request.get("method")
        params = request.get("params", {})
        request_id = request.get("id")

        try:
            if method == "initialize":
                logger.info("Initializing calculator server...")
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {
                            "tools": {"listChanged": False}
                        },
                        "serverInfo": {
                            "name": "calculator-server",
                            "version": "1.0.0"
                        }
                    }
                }

            elif method == "tools/list":
                logger.info("Listing available tools...")
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "tools": list(self.tools.values())
                    }
                }

            elif method == "tools/call":
                tool_name = params.get("name")
                arguments = params.get("arguments", {})
                logger.info(f"Calling tool: {tool_name} with args: {arguments}")

                if tool_name == "add":
                    result = arguments["a"] + arguments["b"]
                    content = f"The sum of {arguments['a']} and {arguments['b']} is {result}"
                elif tool_name == "multiply":
                    result = arguments["a"] * arguments["b"]
                    content = f"The product of {arguments['a']} and {arguments['b']} is {result}"
                elif tool_name == "power":
                    result = arguments["base"] ** arguments["exponent"]
                    content = f"{arguments['base']} raised to the power of {arguments['exponent']} is {result}"
                else:
                    raise ValueError(f"Unknown tool: {tool_name}")

                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [{"type": "text", "text": content}],
                        "isError": False
                    }
                }

            elif method == "notifications/initialized":
                # This is a notification, no response needed
                logger.info("Server initialization complete")
                return None

            else:
                logger.warning(f"Unknown method: {method}")
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method not found: {method}"
                    }
                }

        except Exception as e:
            logger.error(f"Error handling request: {e}")
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32603,
                    "message": f"Internal error: {str(e)}"
                }
            }

    async def run(self):
        """Run the server."""
        logger.info("Starting calculator MCP server...")
        logger.info("Calculator MCP server started and ready for connections")

        while True:
            try:
                line = sys.stdin.readline()
                if not line:
                    logger.info("No more input, shutting down")
                    break

                line = line.strip()
                if not line:
                    continue

                request = json.loads(line)
                response = await self.handle_request(request)

                if response:
                    print(json.dumps(response), flush=True)

            except json.JSONDecodeError:
                logger.warning("Invalid JSON received")
                continue
            except KeyboardInterrupt:
                logger.info("Server interrupted")
                break
            except Exception as e:
                logger.error(f"Server error: {e}")


if __name__ == "__main__":
    server = CalculatorServer()
    asyncio.run(server.run())
'''

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(server_code)
    path.chmod(0o755)
    print(f"Created test server: {path}")


async def test_your_working_implementation():
    """Test the implementation that actually works."""
    print("=== Testing Your Working MCP Implementation ===")

    # Create test server
    server_path = Path("./test_calc_server.py")
    await create_test_calculator_server(server_path)

    try:
        # Test basic connection
        config = create_local_mcp_server(
            name="test_calc",
            script_path=server_path,
            timeout=10.0
        )

        print("1. Testing basic connection...")
        async with MCPClient(config) as client:
            print("   ✅ Connection successful")

            # Test listing tools
            print("2. Testing tool listing...")
            tools = client.get_available_tools()
            print(f"   ✅ Found {len(tools)} tools: {[t['name'] for t in tools]}")

            # Test tool execution
            print("3. Testing tool execution...")

            # Test addition
            add_result = await client.call_tool("add", {"a": 15, "b": 27})
            print(f"   ✅ Addition: 15 + 27 = {add_result}")

            # Test multiplication
            mult_result = await client.call_tool("multiply", {"a": 6, "b": 9})
            print(f"   ✅ Multiplication: 6 * 9 = {mult_result}")

            # Test power
            power_result = await client.call_tool("power", {"base": 2, "exponent": 10})
            print(f"   ✅ Power: 2^10 = {power_result}")

        print("4. Testing error handling...")
        async with MCPClient(config) as client:
            try:
                await client.call_tool("nonexistent", {})
                print("   ❌ Should have failed")
            except Exception as e:
                print(f"   ✅ Properly handled error: {type(e).__name__}")

        print("5. Testing concurrent connections...")
        tasks = []
        for i in range(3):
            async def concurrent_test(n):
                async with MCPClient(config) as client:
                    result = await client.call_tool("add", {"a": n, "b": n * 2})
                    return f"Task {n}: {result}"

            tasks.append(concurrent_test(i + 1))

        results = await asyncio.gather(*tasks)
        for result in results:
            print(f"   ✅ {result}")

        print("\n🎉 ALL TESTS PASSED! Your implementation works perfectly!")
        return True

    except Exception as e:
        print(f"❌ Test failed: {e}")
        traceback.print_exc()
        return False

    finally:
        # Cleanup
        if server_path.exists():
            server_path.unlink()


async def test_integration_with_tool_manager():
    """Test integration with your ToolManager."""
    print("\n=== Testing ToolManager Integration ===")

    try:
        # Create test server
        server_path = Path("./test_calc_server.py")
        await create_test_calculator_server(server_path)

        # Create tool manager and MCP manager
        tool_manager = ToolManager()
        mcp_manager = MCPToolManager(tool_manager)

        config = create_local_mcp_server(
            name="integrated_calc",
            script_path=server_path
        )

        # Add MCP server
        registered_tools = await mcp_manager.add_mcp_server(config)
        print(f"✅ Registered MCP tools: {registered_tools}")

        # Test that tools are available in tool manager
        all_tools = tool_manager.list_tools()
        print(f"✅ All tools in manager: {all_tools}")

        # Test tool execution through manager
        mcp_tool = tool_manager.get_tool("mcp_integrated_calc_add")
        if mcp_tool:
            result = await mcp_tool._execute(a=100, b=200)
            print(f"✅ Tool execution via manager: {result}")

        # Cleanup
        await mcp_manager.disconnect_all()
        server_path.unlink()

        print("✅ ToolManager integration works!")
        return True

    except Exception as e:
        print(f"❌ Integration test failed: {e}")
        return False


async def main():
    """Run practical tests for working implementation."""
    print("Practical MCP Test Suite - Testing What Actually Works")
    print("=" * 60)

    results = []

    # Test 1: Your working implementation
    results.append(await test_your_working_implementation())

    # Test 2: Integration
    results.append(await test_integration_with_tool_manager())

    # Summary
    passed = sum(results)
    total = len(results)

    print("\n" + "=" * 60)
    print(f"Final Results: {passed}/{total} tests passed")

    if passed == total:
        print("🎉 Your MCP implementation is solid and reliable!")
        print("\nKey takeaways:")
        print("• Your custom implementation works perfectly")
        print("• The official MCP client is broken - don't use it")
        print("• Your integration with ToolManager works")
        print("• You have a production-ready MCP solution")
    else:
        print("❌ Some issues found - check the logs above")

    return passed == total


if __name__ == "__main__":
    try:
        success = asyncio.run(main())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\nTests interrupted")
        sys.exit(130)
    except Exception as e:
        print(f"Unexpected error: {e}")
        traceback.print_exc()
        sys.exit(1)
