from crewai_tools import WebsiteSearchTool
from crewai_tools import BaseTool


class WebSearchTool(BaseTool):
    """Search on any Website using WebSiteSearch."""
    name: str = "WebSite Search"
    description: str = "Search on a website using WebsiteSearchTool"

    def _run(self, query: str, **kwargs) -> dict:
        """Run the Google Trends Tool."""
        search = WebsiteSearchTool(
            config={
                "llm": {
                    "provider": "google",
                    "config": {
                        "model": "models/gemini-pro",
                        "temperature": 0.4,
                        "top_p": 1,
                        "stream": True
                    }
                },
                "embedder": {
                    "provider": "google",
                    "config": {
                        "model": "models/embedding-001",
                        "task_type": "retrieval_document",
                    }
                }
            }
        )
        return search.run(query, **kwargs)
