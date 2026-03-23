"""
Bing Search Tool implementation for the ai-parrot framework.
"""
from typing import Optional
import os
import httpx
from pydantic import BaseModel, Field
from navconfig import config
from parrot.tools.abstract import AbstractTool, ToolResult


class BingSearchArgs(BaseModel):
    """Arguments for the Bing Search Tool."""
    query: str = Field(..., description="The search query to execute on Bing.")
    count: Optional[int] = Field(default=10, description="The number of search results to return.")
    offset: Optional[int] = Field(default=0, description="The zero-based offset that indicates the number of search results to skip before returning results.")
    mkt: Optional[str] = Field(default="en-US", description="The market where the results come from. Typically, mkt is the country where the user is making the request from.")
    safeSearch: Optional[str] = Field(default="Moderate", description="Filter search results for adult content (Off, Moderate, Strict).")


class BingSearchTool(AbstractTool):
    """
    Tool to execute web searches using the Bing Search API.
    """
    name: str = "BingSearch"
    description: str = "Perform a web search using Microsoft Bing. Useful for finding up-to-date information on the internet."
    args_schema = BingSearchArgs

    async def _execute(
        self,
        query: str,
        count: int = 10,
        offset: int = 0,
        mkt: str = "en-US",
        safeSearch: str = "Moderate",
        **kwargs
    ) -> ToolResult:
        """
        Executes the Bing search.
        """
        # Load credentials from environment
        bing_subscription_key = config.get("BING_SUBSCRIPTION_KEY")
        
        # Determine the endpoint URL
        bing_search_url = config.get("BING_SEARCH_URL", "https://api.bing.microsoft.com/v7.0/search")

        if not bing_subscription_key:
            return ToolResult(
                success=False,
                status="error",
                result=None,
                error="BING_SUBSCRIPTION_KEY environment variable is missing for BingSearchTool."
            )

        headers = {
            "Ocp-Apim-Subscription-Key": bing_subscription_key
        }
        
        # Some custom APIs might require the subscription ID
        bing_subscription_id = os.environ.get("BING_SUBSCRIPTION_ID")
        if bing_subscription_id:
            headers["X-BingApis-SDK-Client-ID"] = bing_subscription_id # or custom header based on setup

        params = {
            "q": query,
            "count": count,
            "offset": offset,
            "mkt": mkt,
            "safeSearch": safeSearch
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    bing_search_url,
                    headers=headers,
                    params=params,
                    timeout=15.0
                )
                response.raise_for_status()
                data = response.json()

                # Extract concise results for LLM
                snippets = []
                if "webPages" in data and "value" in data["webPages"]:
                    for item in data["webPages"]["value"]:
                        snippets.append({
                            "title": item.get("name", ""),
                            "url": item.get("url", ""),
                            "snippet": item.get("snippet", "")
                        })

                if not snippets:
                    return ToolResult(
                        success=True,
                        status="success",
                        result="No results found.",
                        metadata={"raw_data": data}
                    )

                return ToolResult(
                    success=True,
                    status="success",
                    result=snippets,
                    metadata={"query": query, "total_estimated": data.get("webPages", {}).get("totalEstimatedMatches", 0)}
                )

        except httpx.HTTPError as e:
            self.logger.error(f"HTTP error occurred while calling Bing API: {e}")
            return ToolResult(
                success=False,
                status="error",
                result=None,
                error=f"Bing API request failed: {str(e)}"
            )
        except Exception as e:
            self.logger.error(f"Unexpected error in BingSearchTool: {e}")
            return ToolResult(
                success=False,
                status="error",
                result=None,
                error=f"Unexpected error: {str(e)}"
            )
