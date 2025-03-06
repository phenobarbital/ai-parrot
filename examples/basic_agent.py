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
    question = "I need the availability of sku 6428376 for the Store 767 and zipcode 33928"
    answer = asyncio.run(get_agent(
        question
    ))
    print(answer)
    # answer, response = agent.invoke("is Gene Hackman alive?, based on recent news was found dead in his house.")
    # print('===== ')
    # print(agent.prompt)
    # print('===== ')
    # response = agent.invoke("What Country wins the Olympic Games 2024 in Paris?")
    # print(response)
    # answer, response = agent.invoke("Who is the current Prime Minister of France?")
    # print(response)
    # answer, response = agent.invoke("What is the capital of France and calculate 5 * 7.")
