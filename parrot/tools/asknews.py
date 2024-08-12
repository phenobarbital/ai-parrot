from typing import Any
import os
from navconfig import config
from langchain_community.tools.asknews import AskNewsSearch
from langchain.tools import BaseTool

class AskNewsTool(BaseTool):
    """Tool that searches the AskNews API."""
    name: str = "asknews_search"
    description: str = (
        "This tool allows you to perform a search on up-to-date news and historical "
        "news. If you needs news from more than 48 hours ago, you can estimate the "
        "number of hours back to search."
    )
    search: Any = None

    def __init__(self, max_results: int = 5, **kwargs):
        super().__init__(**kwargs)
        os.environ["ASKNEWS_CLIENT_ID"] = config.get('ASKNEWS_CLIENT_ID')
        os.environ["ASKNEWS_CLIENT_SECRET"] = config.get('ASKNEWS_CLIENT_SECRET')
        self.search = AskNewsSearch(max_results=5)

    def _run(
        self,
        query: str
    ) -> str:
        """Use the Wikipedia tool."""
        return self.search.invoke(
            {
                "query": query,
            }
        )
