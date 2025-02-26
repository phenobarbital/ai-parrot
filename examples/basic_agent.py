import asyncio
from parrot.bots.agent import BasicAgent


async def get_agent():
    agent = BasicAgent()
    await agent.configure()
    return agent


if __name__ == '__main__':
    agent = asyncio.run(get_agent())
    print('===== ')
    print(agent.prompt)
    print('===== ')
    response = agent.invoke("What Country wins the Olympic Games 2024 in Paris?")
    print(response)
    response = agent.invoke("Who is the current Prime Minister of France?")
    print(response)
    response = agent.invoke("What is the capital of France and calculate 5 * 7.")
    print(response)
