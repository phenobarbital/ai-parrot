from langchain_community.utilities.bing_search import BingSearchAPIWrapper
from crewai_tools import BaseTool


class BingSearchTool(BaseTool):
    """Microsoft Bing Search Tool."""
    name: str = "Microsoft Bing Search"
    description: str = "Search the web using Microsoft Bing Search API"

    def _run(self, query: str) -> dict:
        """Run the Bing Search Tool."""
        bing = BingSearchAPIWrapper(k=5)
        return bing.results(query=query, num_results=5)
