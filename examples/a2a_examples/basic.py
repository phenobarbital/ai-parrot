# examples/a2a_examples/basic.py
import asyncio
from aiohttp import web
from parrot.bots import Agent
from parrot.a2a import A2AServer

async def main():
    # 1. Create your agent as usual
    agent = Agent(
        name="CustomerSupport",
        llm="anthropic:claude-sonnet-4-20250514",
        role="Customer support specialist",
        goal="Help customers with their inquiries",
        max_tokens=4096,
    )

    # Add tools if needed
    # agent.tool_manager.add_tool(MyCustomTool())

    # Add MCP servers if needed
    # await agent.add_mcp_server(...)

    # 2. Configure the agent (required for LLM initialization)
    await agent.configure()

    # 3. Wrap it with A2A server
    a2a = A2AServer(agent)

    # 4. Mount on aiohttp app
    app = web.Application()
    a2a.setup(app, url="https://customer-support.internal:8181")

    # 5. Run
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8181)
    await site.start()

    print(f"Agent '{agent.name}' running as A2A service")
    print("AgentCard: http://localhost:8181/.well-known/agent.json")
    print("Send message: POST http://localhost:8181/a2a/message/send")

    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
