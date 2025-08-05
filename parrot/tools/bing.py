from langchain_community.utilities.bing_search import BingSearchAPIWrapper
from langchain.tools import BaseTool


class BingSearchTool(BaseTool):
    """Microsoft Bing Search Tool."""
    name: str = "Bing Search"
    description: str = "Search the web using Microsoft Bing Search, conduct searches using Bing for alternative perspectives and sources."

    def _run(self, query: str) -> dict:
        """Run the Bing Search Tool."""
        bing = BingSearchAPIWrapper(k=5)
        return bing.results(query=query, num_results=5)
