"""SiteSearchToolkit for site-specific searches with preset support."""
from typing import Any, Dict, List

from ..toolkit import AbstractToolkit
from .presets import SITE_PRESETS


class SiteSearchToolkit(AbstractToolkit):
    """
    Toolkit for site-specific web searches with preset configurations.

    Provides two tools:
    - site_presets_list: Discover available preset configurations
    - site_search: Perform site-specific searches with optional preset support
    """

    async def site_presets_list(self) -> Dict[str, Any]:
        """
        List available preset configurations for site search.

        Returns a list of available presets with their names and descriptions.
        Use this to discover which presets can be used with the site_search tool.
        """
        presets_info = [
            {
                "name": name,
                "description": preset.get("description", ""),
                "url": preset.get("url", ""),
            }
            for name, preset in SITE_PRESETS.items()
        ]

        return {
            "available_presets": presets_info,
            "usage_hint": (
                "Pass the preset 'name' to the site_search tool's 'preset' parameter "
                "to use predefined URL and selectors for that site."
            ),
        }

    async def site_search(
        self,
        url: str = None,
        query: str = None,
        preset: str = None,
        selectors: List[str] = None,
        max_results: int = 3,
    ) -> Dict[str, Any]:
        """
        Search within a given site and return fully-rendered page content as markdown.

        Supports presets for common searches (e.g., 'best_buy_deals' for trending Best Buy deals).
        Use 'site_presets_list' tool first to discover available presets.

        Args:
            url: Base URL of the site to explore. Required if preset is not provided.
            query: Terms to search for within the provided site.
            preset: Preset name for predefined search configurations.
                    If provided, url and selectors will be taken from preset.
            selectors: Optional CSS selectors to extract specific page areas.
            max_results: Maximum number of search results to process (1-10).

        Returns:
            Dictionary with search results including rendered markdown content.
        """
        # Import here to avoid circular imports
        from .tool import SiteSearch

        tool = SiteSearch()
        return await tool._execute(
            url=url,
            query=query,
            preset=preset,
            selectors=selectors,
            max_results=max_results,
        )


__all__ = ["SiteSearchToolkit"]
