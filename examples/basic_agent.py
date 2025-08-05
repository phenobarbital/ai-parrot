import asyncio
from parrot.bots.agent import BasicAgent

async def get_agent(question):
    agent = BasicAgent(name='HelperAgent',)
    await agent.configure()
    answer, response = await agent.invoke(question)
    return answer, response


if __name__ == '__main__':
    answer, response = asyncio.run(get_agent(
        "What is the capital of France?"
    ))
    print(answer)
