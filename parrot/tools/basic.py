from langchain.tools import Tool
# Tools:
from langchain.utilities import SerpAPIWrapper
from langchain.chains.llm_math.base import LLMMathChain
from langchain_groq import ChatGroq
from ..conf import (
    SERPAPI_API_KEY,
    GROQ_API_KEY
)

class SearchTool:
    """Search Tool."""
    def __new__(cls, *args, **kwargs):
        search = SerpAPIWrapper(
            serpapi_api_key=kwargs.get('serpapi_api_key', SERPAPI_API_KEY)
        )
        return Tool(
            name="Search",
            func=search.run,
            description="""
            useful for when you need to answer questions about current events or general knowledge. Input should be a search query.
            """,
        )


class MathTool:
    """Math Tool."""
    def __new__(cls, *args, **kwargs):
        groq = ChatGroq(
            model="llama-3.3-70b-versatile",
            temperature=0.1,
            api_key=kwargs.get('GROQ_API_KEY', GROQ_API_KEY)
        )
        llm = kwargs.get('llm', groq)
        math_chain = LLMMathChain(llm=llm, verbose=True)
        return Tool(
            name="Math",
            func=math_chain.run,
            description="""
            useful for when you need to solve math problems or perform mathematical calculations. Input should be a math equation or a mathematical expression.
            """,
        )
