import asyncio
from parrot.tools.abstract import ToolRegistry
from parrot.tools.math import MathTool

# Test the tool registry:
# Default tool registry instance
default_tool_registry = ToolRegistry()

# Usage examples and testing
async def example_usage():
    """Example of how to use the AbstractTool system."""

    # Create a MathTool instance
    math_tool = MathTool()
    default_tool_registry.register(
        MathTool,
        name=math_tool.name,
    )

    # Get the tool schema
    print("MathTool Schema:")
    print(math_tool.get_tool_schema())

    # Execute some operations
    result1 = await math_tool.execute(a=10, b=5, operation="add")
    print(f"Addition result: {result1}")

    result2 = await math_tool.execute(a=10, b=5, operation="divide")
    print(f"Division result: {result2}")

    # Try an error case
    try:
        result3 = await math_tool.execute(a=10, b=0, operation="divide")
        print(f"Division by zero result: {result3}")
    except Exception as e:
        print(f"Expected error: {e}")

    # Use the tool registry
    print("\nUsing tool registry:")
    registry = default_tool_registry
    print("Available tools:", registry.list_tools())

    # Get a tool from registry
    math_tool_from_registry = registry.get_tool("MathTool")
    result4 = await math_tool_from_registry.execute(a=7, b=3, operation="multiply")
    print(f"Registry tool result: {result4}")


if __name__ == "__main__":
    asyncio.run(example_usage())
