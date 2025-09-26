import asyncio
from parrot.bots.mcp import MCPAgent
from parrot.tools import MathTool, PythonREPLTool
from parrot.mcp.integration import MCPClient, MCPServerConfig

async def test():
    config = MCPServerConfig(
        name="direct_test",
        command="python",
        args=["./mcp_servers/calculator_server.py"],
        transport="stdio",
        timeout=10.0
    )
    async with MCPClient(config) as client:
        print("✅ Connected to MCP server directly")

        # List available tools
        tools = client.get_available_tools()
        print(f"✅ Available tools: {[t['name'] for t in tools]}")

        # Test a simple calculation
        result = await client.call_tool("add", {"a": 5, "b": 3})
        print(f"✅ Direct tool call result: {result}")
        assert result == 8, "Addition tool failed"

    print("✅ Direct MCP test completed successfully")

async def test_mcp_agent_initialization():
    agent = MCPAgent(
        name="TestMCPAgent",
        llm='openai',
        model="gpt-4.1",
        enable_tools=True
    )

    # Add existing tools
    agent.register_tool(MathTool())
    agent.register_tool(PythonREPLTool())

    # Add a local calculator MCP server
    config = MCPServerConfig(
        name="calculator",
        command="python",
        args=["./mcp_servers/calculator_server.py"],
        env={"PYTHONPATH": "."},  # Custom environment variables
        allowed_tools=["add", "multiply", "calculate_expression"]
    )
    tools = await agent.add_mcp_server(config)
    print(f"Calculator tools available: {tools}")


    await agent.configure()


    # Agent still works with other tools
    response = await agent.conversation(
        question="What tools do I have available?",
        session_id="resilient_session",
        user_id="user_000"
    )

    print(f"Available tools: {response.output}")

    # Test calculation
    response = await agent.conversation(
        question="What is 15 * 23 + 47?",
        session_id="test_session",
        user_id="user_123"
    )

    print(response.output)

    # Test: Mixed tools (traditional + MCP)
    print("\n--- Testing mixed tools usage ---")
    response = await agent.conversation(
        question="""
        First, use the calculator to multiply 12 and 8.
        Then, use Python to create a list of the first 5 multiples of that result.
        """,
        session_id="test_mixed_session",
        user_id="user_202"
    )
    print(f"Mixed tools response: {response.output}")

    await agent.shutdown()


if __name__ == "__main__":
    # asyncio.run(test())
    asyncio.run(test_mcp_agent_initialization())
