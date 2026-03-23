from typing import Any, Type, Dict
from pydantic import Field
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema
from parrot.interfaces.rss import RSSInterface


class BloombergToolArgsSchema(AbstractToolArgsSchema):
    """Schema for Bloomberg tool arguments."""
    category: str = Field(
        default="markets",
        description="Bloomberg news category. Options: 'economics', 'industries', 'green', 'markets', 'politics', 'technology', 'wealth'."
    )
    limit: int = Field(
        default=5,
        description="Maximum number of news items to return.",
        ge=1,
        le=50
    )


class BloombergTool(AbstractTool):
    """Tool for fetching news from Bloomberg RSS feeds."""
    name: str = "bloomberg_news"
    description: str = "Fetches the latest news from Bloomberg RSS feeds by category (economics, industries, green, markets, politics, technology, wealth)."
    args_schema: Type[AbstractToolArgsSchema] = BloombergToolArgsSchema

    FEED_URLS: Dict[str, str] = {
        "economics": "https://feeds.bloomberg.com/economics/news.rss",
        "industries": "https://feeds.bloomberg.com/industries/news.rss",
        "green": "https://feeds.bloomberg.com/green/news.rss",
        "markets": "https://feeds.bloomberg.com/markets/news.rss",
        "politics": "https://feeds.bloomberg.com/politics/news.rss",
        "technology": "https://feeds.bloomberg.com/technology/news.rss",
        "wealth": "https://feeds.bloomberg.com/wealth/news.rss",
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.rss = RSSInterface()

    async def _execute(
        self,
        category: str = "markets",
        limit: int = 5,
        **kwargs
    ) -> Any:
        """
        Execute the Bloomberg tool.

        :param category: The news category to fetch.
        :param limit: The number of items to return.
        :return: A dictionary containing the feed data.
        """
        try:
            category_key = category.lower()
            if category_key not in self.FEED_URLS:
                valid_keys = ", ".join(self.FEED_URLS.keys())
                raise ValueError(f"Invalid category '{category}'. Valid options are: {valid_keys}")

            url = self.FEED_URLS[category_key]

            result = await self.rss.read_rss(
                url=url,
                limit=limit,
                output_format='dict'
            )

            if not result:
                return {
                    "category": category,
                    "count": 0,
                    "items": [],
                    "message": "Failed to fetch or parse the feed."
                }

            return {
                "category": category,
                "title": result.get('title', 'Bloomberg News'),
                "count": len(result.get('items', [])),
                "items": result.get('items', [])
            }

        except Exception as e:
            self.logger.error(f"Error in BloombergTool: {e}")
            raise e
