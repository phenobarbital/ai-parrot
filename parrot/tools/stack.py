from langchain.tools import Tool
from langchain.tools import BaseTool
from langchain_community.utilities import StackExchangeAPIWrapper

class StackExchangeTool(BaseTool):
    """Tool that searches the StackExchangeTool API."""
    name: str = "StackExchangeSearch"
    description: str = (
        "A wrapper around StackExchange API. Stack Exchange is a network of question-and-answer (Q&A) websites on topics in diverse fields, each site covering a specific topic."
        "Useful for when you need to answer general questions about different topics when user requested."
    )
    search: Tool = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.search = StackExchangeAPIWrapper(
            query_type='title',
            max_results=5
        )

    def _run(
        self,
        query: dict,
    ) -> dict:
        """Use the StackExchangeSearch tool."""
        return self.search.run(query)
