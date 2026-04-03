from pydantic import BaseModel, Field
from parrot.tools.abstract import AbstractTool, ToolResult


class WeatherLookupArgs(BaseModel):
    """Arguments for the WeatherLookupTool."""
    city: str = Field(description="The name of the city")


class WeatherLookupTool(AbstractTool):
    """
    Retrieves current weather information for a specific location.
    """
    name = "WeatherLookup"
    description = "Get the current weather for a city."
    args_schema = WeatherLookupArgs

    async def _execute(self, city: str, **kwargs) -> ToolResult:
        """
        Execute the weather lookup.
        
        Args:
            city: The name of the city.
            
        Returns:
            ToolResult containing weather data.
        """
        try:
            # Mock implementation
            result = {
                "temperature": 72,
                "condition": "Sunny",
                "city": city
            }
            
            return ToolResult(
                status="success",
                result=result,
                metadata={
                    "tool": self.name
                }
            )
        except Exception as e:
            return ToolResult(
                status="error",
                error=str(e),
                result=None
            )
