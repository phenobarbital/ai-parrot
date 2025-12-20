import asyncio
import os
import sys

# Ensure parrot package is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from parrot.bots.agent import BasicAgent

async def main():
    print("Initializing Agent...")
    # Initialize agent with Google LLM (default)
    agent = BasicAgent(
        name="ChromeDevToolsAgent",
        agent_id="chrome_tester",
        use_llm="google"
    )
    import logging
    logging.getLogger("MCPClient.chrome-devtools").setLevel(logging.INFO)
    
    print("Connecting to Chrome DevTools MCP...")
    # NOTE: Chrome must be running with --remote-debugging-port=9222
    # e.g. google-chrome --headless --remote-debugging-port=9222
    
    try:
        # Connect to Chrome DevTools MCP
        # This will use 'npx' to install/run @modelcontextprotocol/server-chrome-devtools
        # aka chrome-devtools-mcp
        tools = await agent.add_chrome_devtools_mcp_server(
            browser_url="http://127.0.0.1:9222"
        )
        print(f"Successfully connected to Chrome DevTools MCP.")
        print(f"Registered tools: {len(tools)}")
        for tool in tools:
            print(f" - {tool}")
            
        print("-" * 50)
        prompt = "Check the performance of url=https://navigator.trocglobal.com"
        print(f"Sending prompt: {prompt}")

        await agent.configure()

        async with agent:
            response = await agent.ask(prompt)
        
        print("\nResponse:")
        print(response.content)
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
