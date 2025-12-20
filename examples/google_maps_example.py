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
        name="GoogleMapsAgent",
        agent_id="google_maps_tester",
        use_llm="google"
    )
    
    print("Connecting to Google Maps MCP...")
    
    try:
        # Connect to Google Maps MCP
        # This will use 'npx' to install/run @googlemaps/code-assist-mcp
        tools = await agent.add_google_maps_mcp_server()
            
        print(f"Successfully connected to Google Maps MCP.")
        print(f"Registered tools: {len(tools)}")
        for tool in tools:
            print(f" - {tool}")
            
        print("-" * 50)
        
        # NOTE: To actually use the tools, one might need a valid Google Maps API Key
        # and likely some environment setup, but this verifies the connection/installation.
        
        await agent.configure()

        # Just verify we can start the agent session
        async with agent:
            print("Agent session started successfully.")
            # We don't necessarily need to send a prompt if we just want to verify connection
            # But let's ask something simple if we wanted to test.
            response = await agent.ask("What tools do you have available?")
            print(response.content)
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
