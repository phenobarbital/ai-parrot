import asyncio
import pandas as pd
from navconfig import BASE_DIR
from parrot.llms.vertex import VertexLLM
from parrot.llms.groq import GroqLLM
from parrot.llms.anthropic import AnthropicLLM
from parrot.llms.openai import OpenAILLM
from parrot.bots.data import PandasAgent


vertex = VertexLLM(
    # model="gemini-2.0-flash",
    model="gemini-1.5-pro",
    preset="analytical",
    use_chat=True
)

vertex_pro = VertexLLM(
    model="gemini-2.5-pro-preview-05-06",
    preset="concise",
    use_chat=True
)

gemma = GroqLLM(
    model="gemma2-9b-it",
    preset="concise",
    max_tokens=1024
)

groq = GroqLLM(
    model="mistral-saba-24b",
    preset="analytical",
    max_tokens=2048,
    use_chat=True
)

openai = OpenAILLM(
    model="gpt-4.1",
    temperature=0.1,
    preset="concise",
    max_tokens=2048,
    use_chat=True
)

claude = AnthropicLLM(
    model="claude-3-5-sonnet-20240620",
    temperature=0,
    use_tools=True
)

async def get_agent(llm):
    data = await PandasAgent.gen_data(agent_name='RevenueBot', query="troc_revenue_projections")
    agent = PandasAgent(
        name='RevenueBot',
        llm=llm,
        df=data
    )
    await agent.configure()
    return agent


if __name__ == '__main__':
    agent = asyncio.run(get_agent(openai))
    # prompt = f"""

    # Generate a business-style narrative based on the data provided in the Pandas DataFrame, considering the above description.
    # The narrative should include the following sections:

    # 1.  **Executive Summary:** Provide a brief overview of the key findings and insights derived from the data analysis.
    # 2.  **Key Trends:** Identify and describe the most significant trends observed in the data. Provide specific examples and supporting data points, examples and supporting data points as most frequently visited stores, visitors with more visits, most frequently asked questions, etc.
    # 3.  **Outliers:** Highlight any significant outliers or anomalies in the data. Explain their potential impact on the overall analysis.
    # 4.  **Potential Risks:** Based on the trends and outliers, identify potential risks or challenges that leadership should be aware of.
    # 5.  **Recommendations:** Provide actionable recommendations for leadership based on the analysis, addressing the identified trends and risks.

    # Ensure the narrative is concise, professional, and directly relevant to business decision-making.
    # """
    prompt = """Return the total rows and list of columns in provided dataframe."""
    answer, response = asyncio.run(
        agent.invoke(prompt)
    )
    print(response.output)
