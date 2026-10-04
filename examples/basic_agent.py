import asyncio
from parrot.bots.agent import BasicAgent


async def get_agent(question):
    agent = BasicAgent(name='HelperAgent')
    await agent.configure()
    # invoke() returns a single AIMessage (parrot.bots.base.BaseBot.invoke ->
    # AIMessage), not a (answer, response) tuple. issue:00fa8af416fe.
    answer = await agent.invoke(question)
    return answer


if __name__ == '__main__':
    answer = asyncio.run(get_agent("What is the capital of France?"))
    print(answer.output)
