from langchain.tools import Tool
# Tools:
from langchain.chains.llm_math.base import LLMMathChain
from langchain_community.utilities import SerpAPIWrapper
from langchain_groq import ChatGroq
from ..conf import (
    SERPAPI_API_KEY,
    GROQ_API_KEY
)

class SearchTool:
    """Search Tool."""
    name: str = "web_search"
    def __new__(cls, *args, **kwargs):
        search = SerpAPIWrapper(
            serpapi_api_key=kwargs.get('serpapi_api_key', SERPAPI_API_KEY)
        )
        tool = Tool(
            name="Web Search",
            func=search.run,
            description="""
            useful for when you need to answer questions about current events or general knowledge. Input should be a search query.
            """,
            coroutine=search.arun
        )
        tool.name = "Web Search"
        return tool


class MathTool:
    """Math Tool."""
    def __new__(cls, *args, **kwargs):
        groq = ChatGroq(
            model="llama-3.1-8b-instant",
            temperature=0.1,
            api_key=kwargs.get('GROQ_API_KEY', GROQ_API_KEY)
        )
        llm = kwargs.get('llm', groq)
        math_chain = LLMMathChain.from_llm(
            llm=llm,
            verbose=True
        )
        tool = Tool(
            name="math_calculator",
            func=math_chain.run,
            description="""
            useful for when you need to solve math problems or perform mathematical calculations. Input should be a math equation or a mathematical expression.
            """,
            coroutine=math_chain.arun
        )
        return tool
