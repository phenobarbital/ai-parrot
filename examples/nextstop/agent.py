# basic requirements:
import os
from typing import Union, List
import asyncio
# Parrot Agent
from parrot.bots.agent import BasicAgent
from parrot.llms.vertex import VertexLLM
from parrot.llms.groq import GroqLLM
from parrot.llms.anthropic import AnthropicLLM
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

claude = AnthropicLLM(
    model="claude-3-5-sonnet-20240620",
    temperature=0.1,
    use_tools=True
)


# Design Tool:
tools = []

async def get_agent(llm):
    agent = BasicAgent(
        name='NextStop Copilot',
        llm=llm,
        tools=tools
    )
    await agent.configure()
    return agent


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    agent = loop.run_until_complete(
        get_agent(llm=vertex)
    )
    query = input(":: Type in your query: \n")
    EXIT_WORDS = ["exit", "quit", "bye"]
    while query not in EXIT_WORDS:
        if query:
            answer, response = loop.run_until_complete(
                agent.invoke(query=query)
            )
            print('::: Response: ', response)
        query = input(
            "Type in your query: \n"
        )
