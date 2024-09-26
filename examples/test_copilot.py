import asyncio
from parrot.chatbots.copilot import CopilotAgent
# importing Tools
from parrot.tools import (
    ZipcodeAPIToolkit,
    WikipediaTool,
    # WikidataTool,
    GoogleSearchTool,
    GoogleLocationFinder,
    BingSearchTool,
    # AskNewsTool,
    DuckDuckGoSearchTool,
    YouTubeSearchTool,
    OpenWeatherMapTool,
    StackExchangeTool,
)

# ZipCode API Toolkit
zpt = ZipcodeAPIToolkit()
zpt_tools = zpt.get_tools()

wk1 = WikipediaTool()
# wk12 = WikidataTool()

g1 = GoogleSearchTool()
g2 = GoogleLocationFinder()

b = BingSearchTool()
d = DuckDuckGoSearchTool()
# ask = AskNewsTool()

yt = YouTubeSearchTool()
stackexchange = StackExchangeTool()
weather = OpenWeatherMapTool()

tools = [
    wk1,
    g1, g2,
    b, d, yt,
    weather,
    stackexchange
] + zpt_tools

async def get_agent():
    agent = CopilotAgent(
        name='T-ROC Copilot',
        llm='vertexai',
        tools=tools
    )
    return agent


if __name__ == "__main__":
    # File:
    agent = asyncio.run(get_agent())
    query = input("Type in your query: \n")
    EXIT_WORDS = ["exit", "quit", "bye"]
    while query not in EXIT_WORDS:
        if query:
            with agent.get_conversation() as conversation:
                response, result = conversation.invoke(query)
                print('::: Response: ', response)
        query = input("Type in your query: \n")
