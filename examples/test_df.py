import asyncio
import pandas as pd
from parrot.llms.vertex import VertexLLM
from parrot.bots.pd import PandasAgent


async def get_agent(data):
    llm = VertexLLM(
        model='gemini-pro-2.0',
        temperature=0,
        top_k=30,
        Top_p=0.5,
    )
    agent = PandasAgent(
        name='PandasAgent',
        llm=llm,
        df=data
    )
    await agent.configure()
    return agent


if __name__ == '__main__':
    data = pd.DataFrame({
        'name': ['Alice', 'Bob', 'Charlie'],
        'age': [25, 30, 35],
        'city': ['New York', 'Los Angeles', 'Chicago']
    })

    agent = asyncio.run(get_agent(data))
    answer = asyncio.run(agent.invoke("What is the average age of the people in the dataset?"))
    print(answer)
    # answer, response = agent.invoke("What is the capital of France and calculate 5 * 7.")
