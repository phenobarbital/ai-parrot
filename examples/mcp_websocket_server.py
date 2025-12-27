#!/usr/bin/env python3
"""
WebSocket MCP Server Example

This script demonstrates how to create and run a WebSocket MCP server
with sample tools for testing the WebSocket transport implementation.

Usage:
    python examples/mcp_websocket_server.py

The server will start on ws://localhost:8766/mcp/ws
"""
import asyncio
import logging
from parrot.mcp.config import MCPServerConfig
from parrot.mcp.transports.websocket import WebSocketMCPServer
from parrot.tools.abstract import AbstractTool, ToolResult

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("WebSocketMCPServerExample")


class CalculatorTool(AbstractTool):
    """Simple calculator tool for testing."""
    
    def __init__(self):
        super().__init__()
        self.name = "calculator"
        self.description = "Perform basic arithmetic operations (add, subtract, multiply, divide)"
        self.input_schema = {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["add", "subtract", "multiply", "divide"],
                    "description": "The operation to perform"
                },
                "a": {
                    "type": "number",
                    "description": "First operand"
                },
                "b": {
                    "type": "number",
                    "description": "Second operand"
                }
            },
            "required": ["operation", "a", "b"]
        }
    
    async def _execute(self, operation: str, a: float, b: float) -> ToolResult:
        """Execute the calculator operation."""
        try:
            if operation == "add":
                result = a + b
            elif operation == "subtract":
                result = a - b
            elif operation == "multiply":
                result = a * b
            elif operation == "divide":
                if b == 0:
                    return ToolResult(
                        status="error",
                        result=None,
                        error="Division by zero"
                    )
                result = a / b
            else:
                return ToolResult(
                    status="error",
                    result=None,
                    error=f"Unknown operation: {operation}"
                )
            
            return ToolResult(
                status="success",
                result=f"{a} {operation} {b} = {result}",
                metadata={"result_value": result}
            )
        except Exception as e:
            return ToolResult(
                status="error",
                result=None,
                error=str(e)
            )


class EchoTool(AbstractTool):
    """Simple echo tool that returns the input message."""
    
    def __init__(self):
        super().__init__()
        self.name = "echo"
        self.description = "Echo back the provided message"
        self.input_schema = {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The message to echo back"
                }
            },
            "required": ["message"]
        }
    
    async def _execute(self, message: str) -> ToolResult:
        """Echo the message back."""
        return ToolResult(
            status="success",
            result=f"Echo: {message}"
        )


class GreetTool(AbstractTool):
    """Greeting tool that says hello."""
    
    def __init__(self):
        super().__init__()
        self.name = "greet"
        self.description = "Greet someone by name"
        self.input_schema = {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "The name of the person to greet"
                }
            },
            "required": ["name"]
        }
    
    async def _execute(self, name: str) -> ToolResult:
        """Greet the person."""
        return ToolResult(
            status="success",
            result=f"Hello, {name}! Welcome to the WebSocket MCP server!"
        )


async def main():
    """Run the WebSocket MCP server."""
    # Create server configuration
    config = MCPServerConfig(
        name="websocket-example-server",
        version="1.0.0",
        description="Example WebSocket MCP server with calculator, echo, and greet tools",
        transport="websocket",
        host="127.0.0.1",
        port=8766,
        base_path="/mcp",
        log_level="INFO"
    )
    
    # Create server
    server = WebSocketMCPServer(config)
    
    # Register tools
    logger.info("Registering tools...")
    server.register_tool(CalculatorTool())
    server.register_tool(EchoTool())
    server.register_tool(GreetTool())
    
    # Start server
    logger.info("Starting WebSocket MCP server...")
    await server.start()
    
    logger.info(f"""
╔══════════════════════════════════════════════════════════════╗
║          WebSocket MCP Server Running                        ║
╠══════════════════════════════════════════════════════════════╣
║  WebSocket Endpoint: ws://127.0.0.1:8766/mcp/ws             ║
║  Info Endpoint:      http://127.0.0.1:8766/                 ║
║                                                              ║
║  Available Tools:                                            ║
║    - calculator: Basic arithmetic operations                 ║
║    - echo:       Echo back a message                         ║
║    - greet:      Greet someone by name                       ║
║                                                              ║
║  Press Ctrl+C to stop the server                            ║
╚══════════════════════════════════════════════════════════════╝
    """)
    
    try:
        # Keep server running
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        logger.info("Shutting down server...")
    finally:
        await server.stop()
        logger.info("Server stopped")


if __name__ == "__main__":
    asyncio.run(main())
