"""
DuckDuckGo Search Tool for AI-Parrot.
"""
from typing import Any, Type
import logging
from pydantic import BaseModel
from .abstract import AbstractTool
from .ddgo import DuckDuckGoToolkit, WebSearchArgs

# Reduce verbosity of internal libraries used by ddgs
logging.getLogger("rquest").setLevel(logging.WARNING)
logging.getLogger("primp").setLevel(logging.WARNING)
logging.getLogger("cookie_store").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


class DdgSearchTool(AbstractTool):
    """
    Tool for performing web searches using DuckDuckGo.
    This tool allows agents to search the web for information.
    """
    name: str = "ddg_search"
    description: str = "Search the web using DuckDuckGo to find information about any topic."
    args_schema: Type[BaseModel] = WebSearchArgs

    def __init__(self, **kwargs):
        """Initialize the DdgSearchTool."""
        super().__init__(**kwargs)
        self.toolkit = DuckDuckGoToolkit()

    async def _execute(self, **kwargs) -> Any:
        """
        Execute the web search.

        Args:
            **kwargs: Arguments matching WebSearchArgs schema

        Returns:
            Search results
        """
        # Extract arguments
        query = kwargs.get("query")
        region = kwargs.get("region", "us-en")
        safesearch = kwargs.get("safesearch", "moderate")
        timelimit = kwargs.get("timelimit")
        max_results = kwargs.get("max_results", 10)
        page = kwargs.get("page", 1)

        # Delegate execution to the toolkit
        return await self.toolkit.web_search(
            query=query,
            region=region,
            safesearch=safesearch,
            timelimit=timelimit,
            max_results=max_results,
            page=page
        )
