"""
SerpApi Search Tool implementation for the ai-parrot framework.
"""
from typing import Optional
import os
import httpx
from pydantic import BaseModel, Field
from navconfig import config
from parrot.tools.abstract import AbstractTool, ToolResult


class SerpApiSearchArgs(BaseModel):
    """Arguments for the SerpApi Search Tool."""
    query: str = Field(..., description="The search query to execute via SerpApi.")
    engine: Optional[str] = Field(default="google", description="The search engine to use (e.g., 'google', 'bing', 'baidu', 'yahoo').")
    num: Optional[int] = Field(default=10, description="The number of search results to return.")
    gl: Optional[str] = Field(default="us", description="Country for geolocation.")
    hl: Optional[str] = Field(default="en", description="Language of the search results.")


class SerpApiSearchTool(AbstractTool):
    """
    Tool to execute web searches using SerpApi.
    """
    name: str = "SerpApiSearch"
    description: str = "Perform a web search using SerpApi, enabling access to Google and other search engines. Useful for gathering up-to-date web information."
    args_schema = SerpApiSearchArgs

    async def _execute(
        self,
        query: str,
        engine: str = "google",
        num: int = 10,
        gl: str = "us",
        hl: str = "en",
        **kwargs
    ) -> ToolResult:
        """
        Executes the SerpApi search.
        """
        api_key = config.get("SERPAPI_API_KEY")

        if not api_key:
            return ToolResult(
                success=False,
                status="error",
                result=None,
                error="SERPAPI_API_KEY environment variable is missing for SerpApiSearchTool."
            )

        # SerpApi endpoint
        serpapi_url = "https://serpapi.com/search.json"

        params = {
            "api_key": api_key,
            "q": query,
            "engine": engine,
            "num": num,
            "gl": gl,
            "hl": hl
        }
        
        # Add any other kwargs passed to the API
        params.update(kwargs)

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    serpapi_url,
                    params=params,
                    timeout=20.0
                )
                response.raise_for_status()
                data = response.json()

                # Try to extract organic results as the primary payload
                snippets = []
                if "organic_results" in data:
                    for item in data["organic_results"]:
                        snippets.append({
                            "title": item.get("title", ""),
                            "url": item.get("link", ""),
                            "snippet": item.get("snippet", "")
                        })
                        
                elif "answer_box" in data:
                    # Provide answer box content if organic results are absent but answer box exists
                    snippets.append({
                        "title": "Answer Box",
                        "snippet": data["answer_box"].get("answer", data["answer_box"].get("snippet", "")),
                        "url": data["answer_box"].get("link", "")
                    })

                if not snippets:
                    # If we can't parse known structures, return a portion of the raw data or indicate no results
                    if "error" in data:
                        return ToolResult(
                            success=False,
                            status="error",
                            result=None,
                            error=f"SerpApi Error: {data['error']}"
                        )
                    return ToolResult(
                        success=True,
                        status="success",
                        result="No standard web results found. Please check raw_data metadata.",
                        metadata={"raw_data": data}
                    )

                return ToolResult(
                    success=True,
                    status="success",
                    result=snippets,
                    metadata={"query": query, "engine": engine}
                )

        except httpx.HTTPError as e:
            self.logger.error(f"HTTP error occurred while calling SerpApi: {e}")
            return ToolResult(
                success=False,
                status="error",
                result=None,
                error=f"SerpApi request failed: {str(e)}"
            )
        except Exception as e:
            self.logger.error(f"Unexpected error in SerpApiSearchTool: {e}")
            return ToolResult(
                success=False,
                status="error",
                result=None,
                error=f"Unexpected error: {str(e)}"
            )
