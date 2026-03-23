"""Preset configurations for site-specific searches."""
from typing import Any, Dict, List, TypedDict


class PresetConfig(TypedDict, total=False):
    """Type definition for preset configuration."""
    url: str
    selectors: List[str]
    description: str


SITE_PRESETS: Dict[str, PresetConfig] = {
    "best_buy_deals": {
        "url": "https://www.bestbuy.com/home?intl=nosplash",
        "selectors": [
            "div#trending_deals_story-ProductCard-Carousel-ID ul li"
        ],
        "description": "Trending deals from Best Buy homepage"
    },
}


__all__ = ["SITE_PRESETS", "PresetConfig"]
