from typing import Any, Type, Dict
from pydantic import Field
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema
from parrot.interfaces.rss import RSSInterface

class MarketNewsToolArgsSchema(AbstractToolArgsSchema):
    """Schema for MarketNews tool arguments."""
    feed: str = Field(
        default="top_stories",
        description="Name of the news feed to fetch. Options: 'top_stories', 'real_time', 'breaking_news', 'market_pulse'."
    )
    limit: int = Field(
        default=10,
        description="Maximum number of news items to return.",
        ge=1,
        le=50
    )

class MarketNewsTool(AbstractTool):
    """
    Tool for fetching financial news from MarketWatch/Dow Jones RSS feeds.
    """
    name: str = "market_news"
    description: str = "Fetches the latest financial news and market updates from MarketWatch RSS feeds."
    args_schema: Type[AbstractToolArgsSchema] = MarketNewsToolArgsSchema
    
    FEED_URLS: Dict[str, str] = {
        "top_stories": "https://feeds.content.dowjones.io/public/rss/mw_topstories",
        "real_time": "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines",
        "breaking_news": "https://feeds.content.dowjones.io/public/rss/mw_bulletins",
        "market_pulse": "https://feeds.content.dowjones.io/public/rss/mw_marketpulse"
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.rss = RSSInterface()

    async def _execute(
        self,
        feed: str = "top_stories",
        limit: int = 10,
        **kwargs
    ) -> Any:
        """
        Execute the MarketNews tool.

        :param feed: The name of the feed to fetch.
        :param limit: The number of items to return.
        :return: A dictionary containing the feed data.
        """
        try:
            feed_key = feed.lower()
            if feed_key not in self.FEED_URLS:
                 # Try to find a partial match or fallback
                 valid_keys = ", ".join(self.FEED_URLS.keys())
                 raise ValueError(f"Invalid feed name '{feed}'. Valid options are: {valid_keys}")

            url = self.FEED_URLS[feed_key]
            
            result = await self.rss.read_rss(
                url=url,
                limit=limit,
                output_format='dict'
            )
            
            # If RSS Interface returns empty list or None handling
            if not result:
                 return {
                     "feed": feed,
                     "count": 0,
                     "items": [],
                     "message": "Failed to fetch or parse the feed."
                 }

            return {
                "feed": feed,
                "title": result.get('title', 'Market News'),
                "count": len(result.get('items', [])),
                "items": result.get('items', [])
            }

        except Exception as e:
            self.logger.error(f"Error in MarketNewsTool: {e}")
            raise e
