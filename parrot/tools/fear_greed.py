from typing import Any, Dict, List, Optional
from pydantic import Field, BaseModel

from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema
from parrot.interfaces.http import HTTPService


class FearGreedInput(AbstractToolArgsSchema):
    limit: int = Field(
        default=10,
        description="Limit the number of results returned (0 for all, default 10).",
        ge=0
    )

class FearGreedItem(BaseModel):
    value: str
    value_classification: str
    timestamp: str
    time_until_update: Optional[str] = None

class FearGreedData(BaseModel):
    name: str
    data: List[FearGreedItem]
    metadata: Dict[str, Any]


class FearGreedTool(AbstractTool):
    """
    Tool for fetching the Crypto Fear & Greed Index from alternative.me.
    The Fear & Greed Index is a contrarian indicator:
    - Extreme Fear (approx. 0-25) can be a buying opportunity.
    - Extreme Greed (approx. 75-100) suggests the market is due for a correction.
    """
    name: str = "fear_greed_index"
    description: str = "Fetches the Crypto Fear & Greed Index. Useful for analyzing market sentiment."
    args_schema: type[BaseModel] = FearGreedInput

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.base_url = "https://api.alternative.me"
        self.http_service = HTTPService(accept="application/json")

    async def _execute(
        self,
        limit: int = 10,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Execute the Fear & Greed Tool.

        Args:
            limit: Number of results to return.

        Returns:
            Dict containing the Fear & Greed Index data.
        """
        try:
            url = f"{self.base_url}/fng/?limit={limit}"
            
            result, error = await self.http_service.async_request(
                url=url,
                method="GET"
            )

            if error:
                 raise Exception(f"Error fetching Fear & Greed Index: {error}")

            if isinstance(result, str):
                import json
                try:
                    result = json.loads(result)
                except json.JSONDecodeError:
                    pass

            if not isinstance(result, dict):
                 raise ValueError(f"Unexpected response format: {result}")
            
            return result

        except Exception as e:
            self.logger.error(f"Error in FearGreedTool: {e}")
            raise e
