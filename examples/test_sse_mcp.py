
import asyncio
import logging
import sys
from aiohttp import web
from parrot.mcp.transports.sse import SseMCPServer
from parrot.mcp.client import MCPClientConfig, MCPAuthHandler
from parrot.mcp.integration import MCPClient
from parrot.mcp.config import MCPServerConfig

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

from parrot.tools.abstract import AbstractTool, ToolResult

# Mock Tool Implementation
class SimpleTool(AbstractTool):
    def __init__(self):
        self.name = "hello"
        self.description = "Say hello"
        self.input_schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"}
            },
            "required": ["name"]
        }
        
    async def _execute(self, name: str) -> ToolResult:
        return ToolResult(
            status="success",
            result=[{"type": "text", "text": f"Hello, {name} from SSE!"}]
        )

async def run_server_and_client():
    # 1. Setup Server
    config = MCPServerConfig(
        name="test-sse-server",
        host="127.0.0.1",
        port=8899,
        base_path="/mcp"
    )
    server = SseMCPServer(config)
    server.register_tool(SimpleTool())
    
    # Run server in background
    runner = web.AppRunner(server.app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 8899)
    await site.start()
    print("Server started on http://127.0.0.1:8899")

    # 2. Setup Client
    client_config = MCPClientConfig(
        name="test-sse-client",
        url="http://127.0.0.1:8899/mcp",
        transport="sse",
        timeout=5.0
    )
    
    print("Connecting client...")
    async with MCPClient(client_config) as client:
        print("Client connected!")
        
        # List tools
        tools = await client._session.list_tools()
        print(f"Tools found: {[t.name for t in tools]}")
        
        # Call tool
        print("Calling tool 'hello'...")
        result = await client.call_tool("hello", {"name": "User"})
        print(f"Tool result: {result.content[0].text}")
        
    # Cleanup
    await site.stop()
    await runner.cleanup()

if __name__ == "__main__":
    try:
        asyncio.run(run_server_and_client())
    except KeyboardInterrupt:
        pass
