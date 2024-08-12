from typing import Any
from pydantic import PrivateAttr
from langchain_community.tools.ddg_search.tool import (
    DuckDuckGoSearchResults,
    DuckDuckGoSearchAPIWrapper
)
from duckduckgo_search import DDGS
from langchain.tools import BaseTool


class DuckDuckGoSearchTool(BaseTool):
    """Web Search tool using Duck Duck Go API."""
    name: str = "DuckDuckGo Web Search"
    description: str = "Search the web using DuckDuckGo Search API"
    source: Any = None
    max_results: int = 5
    region: str = None

    def __init__(self, source: str = "news", results: int = 5, region: str = 'wt-wt', **kwargs: Any):
        super().__init__(**kwargs)
        self.source = source
        self.max_results = results
        self.region = region

    def _run(self, query: str) -> dict:
        """Run the DuckDuckGo Search Tool."""
        wrapper = DuckDuckGoSearchAPIWrapper(
            region=self.region,
            time="y",
            max_results=self.max_results
        )
        search = DuckDuckGoSearchResults(
            api_wrapper=wrapper,
            source=self.source
        )
        return search.run(query)

class DuckDuckGoRelevantSearch(BaseTool):
    """Web Search tool using Duck Duck Go API."""
    name: str = "DuckDuckGo Relevant Search"
    description: str = "Search the web using DuckDuckGo Search API"
    _max_results: PrivateAttr
    _region: PrivateAttr

    def __init__(self, results: int = 5, region: str = 'wt-wt', **kwargs: Any):
        super().__init__(**kwargs)
        self._max_results = results
        self._region = region

    def _run(
		self,
        query: str,
		**kwargs: Any,
	) -> Any:
        """Search Internet for relevant information based on a query."""
        search = DDGS()
        return search.text(
            keywords=query,
            region=self._region,
            safesearch='moderate',
            max_results=self._max_results
        )
