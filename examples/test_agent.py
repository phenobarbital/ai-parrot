import asyncio
from parrot.bots.agent import BasicAgent
from parrot.tools.bby import BestBuyToolkit


async def create_agent():
    toolkit = BestBuyToolkit()
    bby = toolkit._get_availability_tool()
    agent = BasicAgent(name='BestBuyAgent', tools=[bby])
    await agent.configure()
    return agent


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    agent = loop.run_until_complete(create_agent())
    query = input("Type in your query: \n")
    EXIT_WORDS = ["exit", "quit", "bye"]
    while query not in EXIT_WORDS:
        if query:
            answer, response = loop.run_until_complete(
                agent.invoke(query=query)
            )
            print('::: Response: ', response)
        query = input("Type in your query: \n")
