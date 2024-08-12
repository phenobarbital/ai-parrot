from langchain_community.tools.google_trends import GoogleTrendsQueryRun
from langchain_community.utilities.google_trends import GoogleTrendsAPIWrapper
from crewai_tools import BaseTool


class GoogleTrendsTool(BaseTool):
    """Google Trends Tool."""
    name: str = "Google Trends"
    description: str = "Search the web using Google Trends API"

    def _run(self, query: str) -> dict:
        """Run the Google Trends Tool."""
        google_trends = GoogleTrendsQueryRun(
            api_wrapper=GoogleTrendsAPIWrapper()
        )
        return google_trends.run(query)
