import asyncio
from parrot.bots.sassie import SassieAgent

async def get_agent():
    agent = SassieAgent(
        llm='openai',
        model='gpt-4o',
        temperature=0
        # model='gemini-2.5-pro'
    )
    await agent.configure()
    return agent

async def create_report():
    """Create a report for the agent."""
    # This method can be implemented to generate a report based on the agent's interactions or data.
    agent = await get_agent()
    async with agent:
        try:
            response, response_data = await agent.multi_report(
                program='google'
            )
            if response is None:  # Error occurred
                print(f"Error generating report: {response_data.output}")
            else:
                print(f"Report generated successfully: {response_data.output}")
        except Exception as e:
            print(f"Unexpected error: {e}")

async def create_retailer_report():
    """Create a retailer-specific report for the agent."""
    agent = await get_agent()
    async with agent:
        try:
            response, response_data = await agent.retailer_report(
                program='google'
            )
            print(f"Retailer Report generated successfully")
        except Exception as e:
            print(f"Unexpected error generating retailer report: {e}")

if __name__ == "__main__":
    # asyncio.run(create_report())
    asyncio.run(create_retailer_report())
