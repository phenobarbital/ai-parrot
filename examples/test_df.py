import asyncio
import pandas as pd
from navconfig import BASE_DIR
from parrot.llms.vertex import VertexLLM
from parrot.bots.data import PandasAgent


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
    file = BASE_DIR.joinpath('documents', 'ga_reporting.xlsx')
    data = pd.read_excel(file)
    agent = asyncio.run(get_agent(data))
    prompt = f"""

    Generate a business-style narrative based on the data provided in the Pandas DataFrame, considering the above description.
    The narrative should include the following sections:

    1.  **Executive Summary:** Provide a brief overview of the key findings and insights derived from the data analysis.
    2.  **Key Trends:** Identify and describe the most significant trends observed in the data. Provide specific examples and supporting data points, examples and supporting data points as most frequently visited stores, visitors with more visits, most frequently asked questions, etc.
    3.  **Outliers:** Highlight any significant outliers or anomalies in the data. Explain their potential impact on the overall analysis.
    4.  **Potential Risks:** Based on the trends and outliers, identify potential risks or challenges that leadership should be aware of.
    5.  **Recommendations:** Provide actionable recommendations for leadership based on the analysis, addressing the identified trends and risks.

    Ensure the narrative is concise, professional, and directly relevant to business decision-making.
    """
    answer = asyncio.run(
        agent.invoke(prompt)
    )
    print(answer)
    # answer, response = agent.invoke("What is the capital of France and calculate 5 * 7.")
