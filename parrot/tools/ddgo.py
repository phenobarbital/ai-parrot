"""
DuckDuckGo Search Toolkit for AI-Parrot.

This toolkit provides web search capabilities using the ddgs library directly,
removing all Langchain dependencies and implementing proper backoff retry for rate limiting.
"""
import asyncio
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
import backoff
from ddgs import DDGS
from ddgs.exceptions import (
    DDGSException,
    RatelimitException,
    TimeoutException,
)
from navconfig.logging import logging
from .toolkit import AbstractToolkit
from .abstract import ToolResult



# Pydantic schemas for tool arguments
class WebSearchArgs(BaseModel):
    """Arguments for web search."""
    query: str = Field(description="Search query")
    region: str = Field(default="us-en", description="Search region (e.g., us-en, uk-en, ru-ru)")
    safesearch: str = Field(default="moderate", description="Safe search level: on, moderate, off")
    timelimit: Optional[str] = Field(default=None, description="Time limit: d(day), w(week), m(month), y(year)")
    max_results: int = Field(default=10, description="Maximum number of results to return")
    page: int = Field(default=1, description="Page number for results")


class NewsSearchArgs(BaseModel):
    """Arguments for news search."""
    query: str = Field(description="News search query")
    region: str = Field(default="us-en", description="Search region")
    safesearch: str = Field(default="moderate", description="Safe search level")
    timelimit: Optional[str] = Field(default=None, description="Time limit for news")
    max_results: int = Field(default=10, description="Maximum number of news results")


class ImageSearchArgs(BaseModel):
    """Arguments for image search."""
    query: str = Field(description="Image search query")
    region: str = Field(default="us-en", description="Search region")
    safesearch: str = Field(default="moderate", description="Safe search level")
    size: Optional[str] = Field(default=None, description="Image size filter: Small, Medium, Large, Wallpaper")
    color: Optional[str] = Field(default=None, description="Color filter: color, Monochrome, Red, Orange, etc.")
    type_image: Optional[str] = Field(default=None, description="Image type: photo, clipart, gif, transparent, line")
    layout: Optional[str] = Field(default=None, description="Layout: Square, Tall, Wide")
    license_image: Optional[str] = Field(default=None, description="License: any, Public, Share, ShareCommercially, Modify")
    max_results: int = Field(default=10, description="Maximum number of image results")


class VideoSearchArgs(BaseModel):
    """Arguments for video search."""
    query: str = Field(description="Video search query")
    region: str = Field(default="us-en", description="Search region")
    safesearch: str = Field(default="moderate", description="Safe search level")
    timelimit: Optional[str] = Field(default=None, description="Time limit for videos")
    resolution: Optional[str] = Field(default=None, description="Video resolution: high, standard")
    duration: Optional[str] = Field(default=None, description="Video duration: short, medium, long")
    license_videos: Optional[str] = Field(default=None, description="Video license filter")
    max_results: int = Field(default=10, description="Maximum number of video results")


class DuckDuckGoToolkit(AbstractToolkit):
    """
    DuckDuckGo Search Toolkit providing comprehensive search capabilities.

    This toolkit uses the ddgs library directly for improved performance and reliability,
    with built-in backoff retry mechanisms for handling rate limits.
    """

    def __init__(self, **kwargs):
        """Initialize the DuckDuckGo toolkit."""
        super().__init__(**kwargs)
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

        # Backoff configuration
        self.max_retries = kwargs.get('max_retries', 3)
        self.backoff_factor = kwargs.get('backoff_factor', 2.0)
        self.max_wait_time = kwargs.get('max_wait_time', 60.0)

    def _get_backoff_decorator(self):
        """Get the backoff decorator for retry logic."""
        return backoff.on_exception(
            backoff.expo,
            (RatelimitException, TimeoutException, DDGSException),
            max_tries=self.max_retries,
            factor=self.backoff_factor,
            max_time=self.max_wait_time,
            logger=self.logger
        )

    async def web_search(
        self,
        query: str,
        region: str = "us-en",
        safesearch: str = "moderate",
        timelimit: Optional[str] = None,
        max_results: int = 10,
        page: int = 1
    ) -> ToolResult:
        """
        Search the web using DuckDuckGo.

        Args:
            query: Search query
            region: Search region (e.g., us-en, uk-en, ru-ru)
            safesearch: Safe search level (on, moderate, off)
            timelimit: Time limit (d, w, m, y)
            max_results: Maximum number of results
            page: Page number for results

        Returns:
            ToolResult containing search results
        """
        try:
            # Create backoff-wrapped search function
            @self._get_backoff_decorator()
            def _search():
                ddgs = DDGS()
                return ddgs.text(
                    query=query,
                    region=region,
                    safesearch=safesearch,
                    timelimit=timelimit,
                    max_results=max_results,
                    page=page,
                    backend="auto"
                )

            # Execute search in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(None, _search)

            return ToolResult(
                status="success",
                result={
                    "query": query,
                    "total_results": len(results),
                    "results": results,
                    "search_type": "web"
                },
                metadata={
                    "region": region,
                    "safesearch": safesearch,
                    "timelimit": timelimit,
                    "page": page
                }
            )

        except Exception as e:
            self.logger.error(f"Web search failed for query '{query}': {str(e)}")
            return ToolResult(
                status="error",
                result=[],
                error=f"Search failed: {str(e)}",
                metadata={"query": query}
            )

    async def news_search(
        self,
        query: str,
        region: str = "us-en",
        safesearch: str = "moderate",
        timelimit: Optional[str] = None,
        max_results: int = 10
    ) -> ToolResult:
        """
        Search for news using DuckDuckGo.

        Args:
            query: News search query
            region: Search region
            safesearch: Safe search level
            timelimit: Time limit for news
            max_results: Maximum number of results

        Returns:
            ToolResult containing news results
        """
        try:
            @self._get_backoff_decorator()
            def _search():
                ddgs = DDGS()
                return ddgs.news(
                    query=query,
                    region=region,
                    safesearch=safesearch,
                    timelimit=timelimit,
                    max_results=max_results
                )

            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(None, _search)

            return ToolResult(
                status="success",
                result={
                    "query": query,
                    "total_results": len(results),
                    "results": results,
                    "search_type": "news"
                },
                metadata={
                    "region": region,
                    "safesearch": safesearch,
                    "timelimit": timelimit
                }
            )

        except Exception as e:
            self.logger.error(f"News search failed for query '{query}': {str(e)}")
            return ToolResult(
                status="error",
                result=[],
                error=f"News search failed: {str(e)}",
                metadata={"query": query}
            )

    async def image_search(
        self,
        query: str,
        region: str = "us-en",
        safesearch: str = "moderate",
        size: Optional[str] = None,
        color: Optional[str] = None,
        type_image: Optional[str] = None,
        layout: Optional[str] = None,
        license_image: Optional[str] = None,
        max_results: int = 10
    ) -> ToolResult:
        """
        Search for images using DuckDuckGo.

        Args:
            query: Image search query
            region: Search region
            safesearch: Safe search level
            size: Image size filter
            color: Color filter
            type_image: Image type filter
            layout: Layout filter
            license_image: License filter
            max_results: Maximum number of results

        Returns:
            ToolResult containing image results
        """
        try:
            @self._get_backoff_decorator()
            def _search():
                ddgs = DDGS()
                return ddgs.images(
                    query=query,
                    region=region,
                    safesearch=safesearch,
                    size=size,
                    color=color,
                    type_image=type_image,
                    layout=layout,
                    license_image=license_image,
                    max_results=max_results
                )

            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(None, _search)

            return ToolResult(
                status="success",
                result={
                    "query": query,
                    "total_results": len(results),
                    "results": results,
                    "search_type": "images"
                },
                metadata={
                    "region": region,
                    "safesearch": safesearch,
                    "size": size,
                    "color": color,
                    "type_image": type_image,
                    "layout": layout,
                    "license_image": license_image
                }
            )

        except Exception as e:
            self.logger.error(f"Image search failed for query '{query}': {str(e)}")
            return ToolResult(
                status="error",
                result=[],
                error=f"Image search failed: {str(e)}",
                metadata={"query": query}
            )

    async def video_search(
        self,
        query: str,
        region: str = "us-en",
        safesearch: str = "moderate",
        timelimit: Optional[str] = None,
        resolution: Optional[str] = None,
        duration: Optional[str] = None,
        license_videos: Optional[str] = None,
        max_results: int = 10
    ) -> ToolResult:
        """
        Search for videos using DuckDuckGo.

        Args:
            query: Video search query
            region: Search region
            safesearch: Safe search level
            timelimit: Time limit for videos
            resolution: Video resolution filter
            duration: Video duration filter
            license_videos: Video license filter
            max_results: Maximum number of results

        Returns:
            ToolResult containing video results
        """
        try:
            @self._get_backoff_decorator()
            def _search():
                ddgs = DDGS()
                return ddgs.videos(
                    query=query,
                    region=region,
                    safesearch=safesearch,
                    timelimit=timelimit,
                    resolution=resolution,
                    duration=duration,
                    license_videos=license_videos,
                    max_results=max_results
                )

            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(None, _search)

            return ToolResult(
                status="success",
                result={
                    "query": query,
                    "total_results": len(results),
                    "results": results,
                    "search_type": "videos"
                },
                metadata={
                    "region": region,
                    "safesearch": safesearch,
                    "timelimit": timelimit,
                    "resolution": resolution,
                    "duration": duration,
                    "license_videos": license_videos
                }
            )

        except Exception as e:
            self.logger.error(f"Video search failed for query '{query}': {str(e)}")
            return ToolResult(
                status="error",
                result=[],
                error=f"Video search failed: {str(e)}",
                metadata={"query": query}
            )
