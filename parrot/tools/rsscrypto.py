from typing import Any, Type
from pydantic import Field
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema
from parrot.interfaces.rss import RSSInterface


class RSSCryptoToolArgsSchema(AbstractToolArgsSchema):
    """Schema for RSSCrypto tool arguments."""
    limit: int = Field(
        default=10,
        description="Maximum number of news items to return.",
        ge=1,
        le=50
    )


class RSSCryptoTool(AbstractTool):
    """Tool for fetching aggregated cryptocurrency news from rsscrypto.com RSS feed."""
    name: str = "rsscrypto"
    description: str = (
        "Fetches the latest aggregated cryptocurrency news from multiple sources "
        "via the rsscrypto.com RSS feed."
    )
    args_schema: Type[AbstractToolArgsSchema] = RSSCryptoToolArgsSchema

    RSS_CRYPTO_URL: str = "https://www.rsscrypto.com/rss"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.rss = RSSInterface()

    async def _execute(
        self,
        limit: int = 10,
        **kwargs
    ) -> Any:
        """Execute the RSSCrypto tool.

        :param limit: The number of items to return.
        :return: A dictionary containing the feed data.
        """
        try:
            result = await self.rss.read_rss(
                url=self.RSS_CRYPTO_URL,
                limit=limit,
                output_format='dict'
            )

            if not result:
                return {
                    "feed": "rsscrypto",
                    "count": 0,
                    "items": [],
                    "message": "Failed to fetch or parse the feed."
                }

            return {
                "feed": "rsscrypto",
                "title": result.get('title', 'RSS Cryptocurrency News'),
                "count": len(result.get('items', [])),
                "items": result.get('items', [])
            }

        except Exception as e:
            self.logger.error(f"Error in RSSCryptoTool: {e}")
            raise e
