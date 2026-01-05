
import asyncio
import logging
from parrot.bots.agent import BasicAgent
from navconfig import config

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("GenMediaExample")

async def main():
    # Initialize the agent
    agent = BasicAgent(
        name="GenMediaArtist",
        agent_id="genmedia_artist",
        use_llm="google",
        model="gemini-2.5-flash",
        max_tokens=16000,
        human_prompt="You are a creative artist. Use the available tools to generate media as requested."
    )

    # Add GenMedia MCP servers
    logger.info("Adding GenMedia MCP servers...")
    # This assumes PROJECT_ID and LOCATION are set in navconfig/env
    if not config.get('PROJECT_ID'):
        logger.error("PROJECT_ID is missing in configuration. Please set it in .env or navconfig.")
        return

    mcp_results = await agent.add_genmedia_mcp_servers()
    
    for server, tools in mcp_results.items():
        if tools:
            logger.info(
                f"✅ Server '{server}' registered with tools: {tools}"
            )
        else:
            logger.warning(
                f"⚠️ Server '{server}' failed or has no tools."
            )

    # Define the prompt
    prompt = "generate a image of a chubbly tuxedo cat resting on a chair moving the tail."
    
    logger.info(f"🎨 Sending prompt to agent: '{prompt}'")
    
    try:
        await agent.configure()
        async with agent:
            # Invoke the agent
            response = await agent.ask(prompt)
            
            logger.info("✨ Agent Response:")
            print(response.content)
            
            if response.data:
                logger.info(f"📦 Data: {response.data}")

            print(response)            
    except Exception as e:
        logger.error(f"❌ Error during execution: {e}", exc_info=True)
    finally:
        await agent.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
