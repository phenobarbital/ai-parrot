from typing import Any, Type
from pydantic import Field
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema
from parrot.interfaces.rss_content import RSSContentInterface


class CoinTelegraphToolArgsSchema(AbstractToolArgsSchema):
    """Schema for CoinTelegraph tool arguments."""
    limit: int = Field(
        default=10,
        description="Maximum number of news items to return.",
        ge=1,
        le=50
    )
    max_chars: int = Field(
        default=1000,
        description="Maximum characters for content summary (approximately 1 paragraph).",
        ge=100,
        le=5000
    )
    output_format: str = Field(
        default="dict",
        description="Output format: 'dict', 'markdown', or 'yaml'."
    )


class CoinTelegraphTool(AbstractTool):
    """
    Tool for fetching cryptocurrency news from CoinTelegraph RSS feed with content summaries.
    
    Fetches RSS entries and extracts main content from linked pages to provide
    plain-text summaries of each article.
    """
    name: str = "cointelegraph_news"
    description: str = "Fetches the latest cryptocurrency news from CoinTelegraph RSS feed with content summaries extracted from article pages."
    args_schema: Type[AbstractToolArgsSchema] = CoinTelegraphToolArgsSchema
    
    RSS_URL: str = "https://cointelegraph.com/rss"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.rss = RSSContentInterface()

    async def _execute(
        self,
        limit: int = 10,
        max_chars: int = 1000,
        output_format: str = "dict",
        **kwargs
    ) -> Any:
        """
        Execute the CoinTelegraph tool.

        :param limit: The number of items to return.
        :param max_chars: Maximum characters for content summary.
        :param output_format: Output format ('dict', 'markdown', 'yaml').
        :return: A dictionary containing the feed data with content summaries.
        """
        try:
            result = await self.rss.read_rss_with_content(
                url=self.RSS_URL,
                limit=limit,
                max_chars=max_chars,
                output_format=output_format
            )
            
            # If RSS Interface returns empty list or None handling
            if not result:
                return {
                    "feed": "CoinTelegraph",
                    "count": 0,
                    "items": [],
                    "message": "Failed to fetch or parse the feed."
                }

            # For dict format, add metadata
            if output_format.lower() == 'dict':
                return {
                    "feed": "CoinTelegraph",
                    "title": result.get('title', 'CoinTelegraph News'),
                    "url": self.RSS_URL,
                    "count": len(result.get('items', [])),
                    "items": result.get('items', [])
                }
            
            # For markdown/yaml, return as-is
            return result

        except Exception as e:
            self.logger.error(f"Error in CoinTelegraphTool: {e}")
            raise e
