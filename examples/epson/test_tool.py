import asyncio
from querysource.conf import default_dsn
from parrot.tools.epson import EpsonProductToolkit

async def test_tool():
    toolkit = EpsonProductToolkit(dsn=default_dsn, program="epson", agent_id="epson_concierge")
    # Get all tools (automatic)
    tools = toolkit.get_tools()
    print(
        f"Available tools: {[tool.name for tool in tools]}"
    )
    # List tool names
    tool_names = toolkit.list_tool_names()
    print(f"Tool names: {tool_names}")

    print('Testing get_product_information tool...')
    # Use tools directly
    product_info = await toolkit.get_product_information("V11HA73020")
    print(product_info)


if __name__ == "__main__":
    asyncio.run(test_tool())
    # This will run the test_tool function to demonstrate the toolkit functionality.
