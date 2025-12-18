"""SiteSearch package for site-specific crawling with preset support."""
from .tool import SiteSearch, SiteSearchArgs
from .toolkit import SiteSearchToolkit
from .presets import SITE_PRESETS

__all__ = ["SiteSearch", "SiteSearchArgs", "SiteSearchToolkit", "SITE_PRESETS"]
