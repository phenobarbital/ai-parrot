from typing import Any, Type
from pydantic import Field
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema
from parrot.interfaces.rss import RSSInterface

class CoindeskToolArgsSchema(AbstractToolArgsSchema):
    """Schema for Coindesk tool arguments."""
    limit: int = Field(
        default=10,
        description="Maximum number of news items to return.",
        ge=1,
        le=50
    )

class CoindeskTool(AbstractTool):
    """
    Tool for fetching cryptocurrency news from Coindesk RSS feed.
    """
    name: str = "coindesk"
    description: str = "Fetches the latest cryptocurrency news and updates from Coindesk RSS feed."
    args_schema: Type[AbstractToolArgsSchema] = CoindeskToolArgsSchema
    
    COINDESK_RSS_URL: str = "https://www.coindesk.com/arc/outboundfeeds/rss"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.rss = RSSInterface()

    async def _execute(
        self,
        limit: int = 10,
        **kwargs
    ) -> Any:
        """
        Execute the Coindesk tool.

        :param limit: The number of items to return.
        :return: A dictionary containing the feed data.
        """
        try:
            result = await self.rss.read_rss(
                url=self.COINDESK_RSS_URL,
                limit=limit,
                output_format='dict'
            )
            
            # If RSS Interface returns empty list or None handling
            if not result:
                 return {
                     "feed": "coindesk",
                     "count": 0,
                     "items": [],
                     "message": "Failed to fetch or parse the feed."
                 }

            return {
                "feed": "coindesk",
                "title": result.get('title', 'Coindesk'),
                "count": len(result.get('items', [])),
                "items": result.get('items', [])
            }

        except Exception as e:
            self.logger.error(f"Error in CoindeskTool: {e}")
            raise e
