"""
Simple MCP Server Example for Testing AI-Parrot Integration
==========================================================

This is a basic MCP server that provides calculator functionality.
Use this to test the MCP integration with your AI-Parrot BaseAgent.
"""

import asyncio
import sys
import logging
from typing import Any, Sequence
import json
import math
from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server



# Create MCP server instance
app = Server("calculator-server")


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    """List available calculator tools."""
    return [
        types.Tool(
            name="add",
            description="Add two numbers together",
            inputSchema={
                "type": "object",
                "properties": {
                    "a": {"type": "number", "description": "First number"},
                    "b": {"type": "number", "description": "Second number"}
                },
                "required": ["a", "b"]
            }
        ),
        types.Tool(
            name="multiply",
            description="Multiply two numbers",
            inputSchema={
                "type": "object",
                "properties": {
                    "a": {"type": "number", "description": "First number"},
                    "b": {"type": "number", "description": "Second number"}
                },
                "required": ["a", "b"]
            }
        ),
        types.Tool(
            name="calculate_expression",
            description="Evaluate a mathematical expression safely",
            inputSchema={
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Mathematical expression to evaluate (e.g., '2 + 3 * 4')"
                    }
                },
                "required": ["expression"]
            }
        ),
        types.Tool(
            name="power",
            description="Calculate a number raised to a power",
            inputSchema={
                "type": "object",
                "properties": {
                    "base": {"type": "number", "description": "Base number"},
                    "exponent": {"type": "number", "description": "Exponent"}
                },
                "required": ["base", "exponent"]
            }
        ),
        types.Tool(
            name="square_root",
            description="Calculate the square root of a number",
            inputSchema={
                "type": "object",
                "properties": {
                    "number": {"type": "number", "description": "Number to find square root of"}
                },
                "required": ["number"]
            }
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> Sequence[types.TextContent]:
    """Handle tool calls."""

    try:
        if name == "add":
            a = arguments.get("a")
            b = arguments.get("b")
            if a is None or b is None:
                raise ValueError("Both 'a' and 'b' parameters are required")
            result = a + b
            return [
                types.TextContent(
                    type="text",
                    text=f"The sum of {a} and {b} is {result}"
                )
            ]

        elif name == "multiply":
            a = arguments.get("a")
            b = arguments.get("b")
            if a is None or b is None:
                raise ValueError("Both 'a' and 'b' parameters are required")
            result = a * b
            return [
                types.TextContent(
                    type="text",
                    text=f"The product of {a} and {b} is {result}"
                )
            ]

        elif name == "calculate_expression":
            expression = arguments.get("expression")
            if not expression:
                raise ValueError("Expression parameter is required")

            # Simple safety check - only allow basic mathematical operations
            allowed_chars = set("0123456789+-*/().^ ")
            if not all(c in allowed_chars for c in expression.replace(" ", "")):
                return [
                    types.TextContent(
                        type="text",
                        text=f"Error: Expression contains invalid characters. Only numbers and +, -, *, /, (, ), ^ are allowed."
                    )
                ]

            try:
                # Replace ^ with ** for Python power operator
                safe_expression = expression.replace("^", "**")

                # Use eval with restricted namespace for safety
                allowed_names = {
                    "__builtins__": {},
                    "abs": abs,
                    "min": min,
                    "max": max,
                    "round": round,
                    "pow": pow,
                    "math": math,
                }

                result = eval(safe_expression, allowed_names, {})
                return [
                    types.TextContent(
                        type="text",
                        text=f"The result of '{expression}' is {result}"
                    )
                ]
            except Exception as e:
                return [
                    types.TextContent(
                        type="text",
                        text=f"Error evaluating expression '{expression}': {str(e)}"
                    )
                ]

        elif name == "power":
            base = arguments.get("base")
            exponent = arguments.get("exponent")
            if base is None or exponent is None:
                raise ValueError("Both 'base' and 'exponent' parameters are required")
            result = base ** exponent
            return [
                types.TextContent(
                    type="text",
                    text=f"{base} raised to the power of {exponent} is {result}"
                )
            ]

        elif name == "square_root":
            number = arguments.get("number")
            if number is None:
                raise ValueError("Number parameter is required")
            if number < 0:
                return [
                    types.TextContent(
                        type="text",
                        text=f"Error: Cannot calculate square root of negative number {number}"
                    )
                ]

            result = math.sqrt(number)
            return [
                types.TextContent(
                    type="text",
                    text=f"The square root of {number} is {result}"
                )
            ]

        else:
            return [
                types.TextContent(
                    type="text",
                    text=f"Error: Unknown tool '{name}'"
                )
            ]

    except Exception as e:
        return [
            types.TextContent(
                type="text",
                text=f"Error in tool '{name}': {str(e)}"
            )
        ]


@app.list_resources()
async def list_resources() -> list[types.Resource]:
    """List available resources."""
    return [
        types.Resource(
            uri="calculator://help",
            name="Calculator Help",
            description="Help documentation for the calculator server",
            mimeType="text/plain"
        ),
        types.Resource(
            uri="calculator://operations",
            name="Supported Operations",
            description="List of supported mathematical operations",
            mimeType="application/json"
        )
    ]


@app.read_resource()
async def read_resource(uri: str) -> str:
    """Read resource content."""

    if uri == "calculator://help":
        return """
Calculator MCP Server Help
=========================

This server provides basic mathematical calculation tools.

Available Tools:
- add: Add two numbers
- multiply: Multiply two numbers
- calculate_expression: Evaluate mathematical expressions
- power: Calculate exponentiation
- square_root: Calculate square root

Usage Examples:
- add(5, 3) → "The sum of 5 and 3 is 8"
- multiply(4, 6) → "The product of 4 and 6 is 24"
- calculate_expression("2 + 3 * 4") → "The result of '2 + 3 * 4' is 14"
- power(2, 8) → "2 raised to the power of 8 is 256"
- square_root(16) → "The square root of 16 is 4.0"

Note: Expression evaluation is restricted to basic mathematical operations for security.
        """.strip()

    elif uri == "calculator://operations":
        operations = {
            "basic_operations": ["+", "-", "*", "/"],
            "advanced_operations": ["^", "sqrt", "pow"],
            "supported_functions": ["abs", "min", "max", "round"],
            "constants": {
                "pi": math.pi,
                "e": math.e
            }
        }
        return json.dumps(operations, indent=2)

    else:
        raise ValueError(f"Unknown resource URI: {uri}")


async def main():
    """Run the MCP server."""
    try:
        # Setup logging to stderr so it doesn't interfere with stdio
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            stream=sys.stderr
        )

        logger = logging.getLogger("calculator-server")
        logger.info("Starting calculator MCP server...")

        # Run stdio server
        async with stdio_server() as (read_stream, write_stream):
            logger.info("Calculator MCP server started and ready for connections")
            await app.run(
                read_stream,
                write_stream,
                app.create_initialization_options()
            )
    except Exception as e:
        logging.error(f"Error running MCP server: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
