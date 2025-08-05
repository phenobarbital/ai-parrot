# basic requirements:
import os
from typing import Union, List
import asyncio
# Parrot Agent
from parrot.bots.data import PandasAgent
from parrot.llms.vertex import VertexLLM
from parrot.llms.groq import GroqLLM
# from parrot.llms.anthropic import AnthropicLLM
# from parrot.llms.google import GoogleGenAI
from parrot.llms.openai import OpenAILLM

# Function: Agent Creation:
# If use LLama4 with Groq (fastest model)
vertex = VertexLLM(
    model="gemini-2.0-flash-001",
    preset="analytical",
    use_chat=True
)

groq = GroqLLM(
    model="llama-3.1-8b-instant",
    max_tokens=2048
)

openai = OpenAILLM(
    model="gpt-4.1",
    temperature=0.1,
    max_tokens=2048,
    use_chat=True
)


# This is for getting the dataframes from query-slugs
async def create_agent(llm, backstory = '', capabilities = ''):
    dfs = await PandasAgent.gen_data(
        query={
            "queries": {
                "att_stores": {
                    "slug": "placerai_stores",
                    "fields": ["store_number", "store_name", "city", "zipcode", "zcta", "state_code"],
                    "filter": {
                        "account_name": ["Walmart", "Target", "AT&T", "BJ's Wholesale Club"],
                    }
                },
                # "att_sales": {
                #     "slug": "at&t_worked_hours_sales_ai"
                # },
                "att_traffic": {
                    "slug": "att_weekly_stores_traffic"
                },
                "dp05": {
                    "slug": "census_demographics_2023"
                },
                "dp03": {
                    "slug": "census_economic_2023"
                },
                "dp02": {
                    "slug": "census_social_2023"
                },
                "dp04": {
                    "slug": "census_housing_2023"
                }
            }
        },
        agent_name="att_activities",
        refresh=True,
        no_cache=True
    )
    agent = PandasAgent(
        name="att_activities",
        llm=llm,
        df=dfs,
        backstory=backstory,
        capabilities=capabilities
    )
    await agent.configure()
    return agent

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    agent = loop.run_until_complete(
        create_agent(llm=openai)
    )
    query = input("Type in your query: \n")
    EXIT_WORDS = ["exit", "quit", "bye"]
    while query not in EXIT_WORDS:
        if query:
            answer, response = loop.run_until_complete(
                agent.invoke(query=query)
            )
            print('::: Response: ', response)
        query = input("Type in your query: \n")
