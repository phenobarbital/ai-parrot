from typing import Any, Dict, List, Optional, Union
from datetime import datetime, timedelta
from pydantic import BaseModel, Field
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema
from parrot.interfaces.http import HTTPService


class CNNFearGreedInput(AbstractToolArgsSchema):
    full_dataset: bool = Field(
        default=False,
        description="If True, returns the full historical dataset. If False, returns only the latest score."
    )
    start_date: Optional[str] = Field(
        default=None,
        description="Start date for historical data (YYYY-MM-DD). Defaults to 1 week ago."
    )
    end_date: Optional[str] = Field(
        default=None,
        description="End date for historical data (YYYY-MM-DD). Defaults to today."
    )

class CNNFearGreedScore(BaseModel):
    score: float
    rating: str
    timestamp: datetime
    previous_close: float
    previous_1_week: float
    previous_1_month: float
    previous_1_year: float

class CNNFearGreedDataPoint(BaseModel):
    date: datetime
    score: float
    rating: str

class CNNFearGreedHistory(BaseModel):
    current_score: CNNFearGreedScore
    history: List[CNNFearGreedDataPoint]


class CNNFearGreedTool(AbstractTool):
    """
    Tool for fetching the CNN Fear & Greed Index.
    This index is based on 7 indicators:
    - Market Momentum
    - Stock Price Strength
    - Stock Price Breadth
    - Put and Call Options
    - Junk Bond Demand
    - Market Volatility
    - Safe Heaven Demand
    """
    name: str = "cnn_fear_greed"
    description: str = "Fetches the CNN Fear & Greed Index and historical data."
    args_schema: type[BaseModel] = CNNFearGreedInput
    
    BASE_URL: str = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # HTTPService with rotate_ua=True to avoid bot detection
        self.http_service = HTTPService(
            rotate_ua=True,
            accept="application/json",
            headers={
                "Referer": "https://edition.cnn.com/",
                "Origin": "https://edition.cnn.com"
            }
        )

    async def _execute(
        self,
        full_dataset: bool = False,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        **kwargs
    ) -> Union[CNNFearGreedScore, CNNFearGreedHistory]:
        """
        Execute the CNN Fear & Greed Tool.
        """
        # Date logic
        if not end_date:
            end_date_dt = datetime.now()
            end_date = end_date_dt.strftime('%Y-%m-%d')
        else:
            end_date_dt = datetime.strptime(end_date, '%Y-%m-%d')
            
        if not start_date:
            # Default to 1 week ago
            start_date_dt = end_date_dt - timedelta(days=7)
            start_date = start_date_dt.strftime('%Y-%m-%d')
        
        # Construct URL
        # The endpoint expects the start date in the path
        url = f"{self.BASE_URL}/{start_date}"
        
        try:
            result, error = await self.http_service.async_request(
                url=url,
                method="GET"
            )
            
            if error:
                 raise Exception(f"Error fetching data from CNN: {error}")

            if not isinstance(result, dict):
                 # Try parsing if it's a string (though HTTPService usually does this)
                 if isinstance(result, str):
                     import json
                     try:
                         result = json.loads(result)
                     except json.JSONDecodeError:
                         raise ValueError(f"Invalid JSON response: {result}")
                 else:
                     raise ValueError(f"Unexpected response type: {type(result)}")

            # Extract data
            fng_data = result.get('fear_and_greed', {})
            hist_data = result.get('fear_and_greed_historical', {}).get('data', [])
            
            # Helper to safely get float
            def get_score(val):
                try:
                    return float(val)
                except (ValueError, TypeError):
                    return 0.0

            # Current Score
            current_score_val = get_score(fng_data.get('score'))
            rating = fng_data.get('rating', 'neutral')
            timestamp_str = fng_data.get('timestamp')
            
            # Parse timestamp (format: 2023-10-27T14:15:20+00:00)
            if timestamp_str:
                try:
                     timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                except ValueError:
                     timestamp = datetime.now() # Fallback
            else:
                timestamp = datetime.now()

            score_obj = CNNFearGreedScore(
                score=current_score_val,
                rating=rating,
                timestamp=timestamp,
                previous_close=get_score(fng_data.get('previous_close')),
                previous_1_week=get_score(fng_data.get('previous_1_week')),
                previous_1_month=get_score(fng_data.get('previous_1_month')),
                previous_1_year=get_score(fng_data.get('previous_1_year'))
            )

            if not full_dataset:
                return score_obj

            # Process historical data
            history_points = []
            for item in hist_data:
                # 'x' is timestamp in ms, 'y' is score
                ts_ms = item.get('x')
                val = item.get('y')
                rating_hist = item.get('rating', 'unknown')
                
                if ts_ms is not None:
                    dt = datetime.fromtimestamp(ts_ms / 1000.0)
                    # Filter by requested date range (though API does some of this)
                    # self.BASE_URL/START_DATE gets from START_DATE to today generally
                    # We might want to clamp if end_date was specific
                    # But usually API returns everything from start_date
                    
                    history_points.append(CNNFearGreedDataPoint(
                        date=dt,
                        score=get_score(val),
                        rating=rating_hist
                    ))
            
            # Sort by date
            history_points.sort(key=lambda x: x.date)

            return CNNFearGreedHistory(
                current_score=score_obj,
                history=history_points
            )

        except Exception as e:
            self.logger.error(f"Error in CNNFearGreedTool: {e}")
            raise e
