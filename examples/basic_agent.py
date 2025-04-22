import asyncio
from parrot.bots.agent import BasicAgent
from parrot.tools.bby import BestBuyToolkit

async def get_agent(question):
    toolkit = BestBuyToolkit()
    bby = toolkit._get_availability_tool()
    agent = BasicAgent(name='BestBuyAgent', tools=[bby])
    await agent.configure()
    answer, response = await agent.invoke(question)
    return answer


if __name__ == '__main__':
    question = "I need the availability of sku 6428376 for the Store 448 and zipcode 19462"
    answer = asyncio.run(get_agent(
        question
    ))
    print(answer)
