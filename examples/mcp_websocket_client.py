#!/usr/bin/env python3
"""
WebSocket MCP Client Example

This script demonstrates how to connect to a WebSocket MCP server
and interact with its tools.

Usage:
    # First, start the server in another terminal:
    python examples/mcp_websocket_server.py
    
    # Then run this client:
    python examples/mcp_websocket_client.py

The client will connect to ws://localhost:8766/mcp/ws
"""
import asyncio
import logging
from parrot.mcp.integration import MCPClient, create_websocket_mcp_server

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("WebSocketMCPClientExample")


async def main():
    """Run the WebSocket MCP client example."""
    logger.info("Creating WebSocket MCP client...")
    
    # Create client configuration
    config = create_websocket_mcp_server(
        name="websocket-example-client",
        url="ws://127.0.0.1:8766/mcp/ws"
    )
    
    # Connect to server
    async with MCPClient(config) as client:
        logger.info("Connected to WebSocket MCP server!")
        
        # List available tools
        logger.info("\n" + "="*60)
        logger.info("Available Tools:")
        logger.info("="*60)
        
        tools = client.get_available_tools()
        for tool in tools:
            logger.info(f"\n📦 {tool['name']}")
            logger.info(f"   Description: {tool['description']}")
            if 'inputSchema' in tool and 'properties' in tool['inputSchema']:
                logger.info(f"   Parameters:")
                for param_name, param_info in tool['inputSchema']['properties'].items():
                    required = "(required)" if param_name in tool['inputSchema'].get('required', []) else "(optional)"
                    logger.info(f"     - {param_name}: {param_info.get('description', 'N/A')} {required}")
        
        # Test calculator tool
        logger.info("\n" + "="*60)
        logger.info("Testing Calculator Tool")
        logger.info("="*60)
        
        test_cases = [
            {"operation": "add", "a": 10, "b": 5},
            {"operation": "subtract", "a": 20, "b": 8},
            {"operation": "multiply", "a": 6, "b": 7},
            {"operation": "divide", "a": 100, "b": 4},
        ]
        
        for test_args in test_cases:
            try:
                logger.info(f"\n➤ Calling calculator with: {test_args}")
                result = await client.call_tool("calculator", test_args)
                
                # Extract result text
                if hasattr(result, 'content') and result.content:
                    for item in result.content:
                        if hasattr(item, 'text'):
                            logger.info(f"  ✓ Result: {item.text}")
                else:
                    logger.info(f"  ✓ Result: {result}")
                    
            except Exception as e:
                logger.error(f"  ✗ Error: {e}")
        
        # Test echo tool
        logger.info("\n" + "="*60)
        logger.info("Testing Echo Tool")
        logger.info("="*60)
        
        try:
            logger.info("\n➤ Calling echo with message: 'Hello WebSocket MCP!'")
            result = await client.call_tool("echo", {
                "message": "Hello WebSocket MCP!"
            })
            
            if hasattr(result, 'content') and result.content:
                for item in result.content:
                    if hasattr(item, 'text'):
                        logger.info(f"  ✓ Result: {item.text}")
            else:
                logger.info(f"  ✓ Result: {result}")
                
        except Exception as e:
            logger.error(f"  ✗ Error: {e}")
        
        # Test greet tool
        logger.info("\n" + "="*60)
        logger.info("Testing Greet Tool")
        logger.info("="*60)
        
        try:
            logger.info("\n➤ Calling greet with name: 'Android Developer'")
            result = await client.call_tool("greet", {
                "name": "Android Developer"
            })
            
            if hasattr(result, 'content') and result.content:
                for item in result.content:
                    if hasattr(item, 'text'):
                        logger.info(f"  ✓ Result: {item.text}")
            else:
                logger.info(f"  ✓ Result: {result}")
                
        except Exception as e:
            logger.error(f"  ✗ Error: {e}")
        
        logger.info("\n" + "="*60)
        logger.info("✅ All tests completed!")
        logger.info("="*60)
        
        # Keep connection alive for a moment to test persistence
        logger.info("\n⏳ Keeping connection alive for 5 seconds...")
        await asyncio.sleep(5)
        
        logger.info("👋 Disconnecting from server...")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n👋 Client stopped by user")
    except Exception as e:
        logger.error(f"❌ Client error: {e}")
