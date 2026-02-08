from typing import Any, Type
from pydantic import Field
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema
from parrot.interfaces.rss import RSSInterface


class TradingSimToolArgsSchema(AbstractToolArgsSchema):
    """Schema for TradingSim tool arguments."""
    limit: int = Field(
        default=10,
        description="Maximum number of blog posts to return.",
        ge=1,
        le=50
    )


class TradingSimTool(AbstractTool):
    """Tool for fetching trading education and market analysis from TradingSim blog RSS feed."""
    name: str = "tradingsim"
    description: str = "Fetches the latest trading education articles, market analysis, and trading strategies from the TradingSim blog."
    args_schema: Type[AbstractToolArgsSchema] = TradingSimToolArgsSchema

    FEED_URL: str = "https://www.tradingsim.com/blog/rss.xml"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.rss = RSSInterface()

    async def _execute(
        self,
        limit: int = 10,
        **kwargs
    ) -> Any:
        """
        Execute the TradingSim tool.

        :param limit: The number of items to return.
        :return: A dictionary containing the feed data.
        """
        try:
            result = await self.rss.read_rss(
                url=self.FEED_URL,
                limit=limit,
                output_format='dict'
            )

            if not result:
                return {
                    "feed": "tradingsim",
                    "count": 0,
                    "items": [],
                    "message": "Failed to fetch or parse the feed."
                }

            return {
                "feed": "tradingsim",
                "title": result.get('title', 'TradingSim Blog'),
                "count": len(result.get('items', [])),
                "items": result.get('items', [])
            }

        except Exception as e:
            self.logger.error(f"Error in TradingSimTool: {e}")
            raise e
