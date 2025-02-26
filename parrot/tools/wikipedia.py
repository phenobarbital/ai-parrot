from typing import Optional, Any
from langchain_core.callbacks import CallbackManagerForToolRun
from langchain_community.tools import WikipediaQueryRun
from langchain_community.utilities import WikipediaAPIWrapper
from langchain_community.tools.wikidata.tool import WikidataAPIWrapper, WikidataQueryRun
from langchain.tools import BaseTool


class WikipediaTool(BaseTool):
    """Tool that searches the Wikipedia API."""
    name = "Wikipedia"
    description: str = (
        "Access detailed and verified information from Wikipedia. "
        "Useful for searching Wikipedia for general information. "
        "Useful for when you need to answer general questions about "
        "people, places, companies, facts, historical events, or other subjects. "
        "Input should be a search query."
    )
    search: Any = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.search = WikipediaQueryRun(
            api_wrapper=WikipediaAPIWrapper()
        )

    def _run(
        self,
        query: str,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        """Use the Wikipedia tool."""
        return self.search.run(query)

class WikidataTool(BaseTool):
    """Tool that searches the Wikidata API."""
    name: str = "Wikidata"
    description: str = (
        "Fetch structured data from WikiData for precise and factual details. "
        "Useful for when you need to answer general questions about "
        "people, places, companies, facts, historical events, or other subjects. "
        "Input should be the exact name of the item you want information about or a Wikidata QID."
    )
    search: Any = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.search = WikidataQueryRun(
            api_wrapper=WikidataAPIWrapper()
        )

    def _run(
        self,
        query: str,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        """Use the Wikidata tool."""
        return self.search.run(query)
