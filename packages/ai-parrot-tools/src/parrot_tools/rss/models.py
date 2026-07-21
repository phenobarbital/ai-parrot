"""
Pydantic models and internal data structures for the RSS Feed Reader Toolkit.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional, Union
from urllib.parse import urlparse

from pydantic import BaseModel, Field

MAX_SLUG_LENGTH = 60
SUMMARY_MAX_CHARS = 500

_ITEM_ID_RE = re.compile(r"^[0-9a-f]{16}$")


def make_item_id(link: str) -> str:
    """Derive a stable item identifier from an article link.

    Args:
        link: Article URL as found in the feed entry.

    Returns:
        First 16 hex chars of the SHA-256 digest of the link.
    """
    return hashlib.sha256(link.encode("utf-8")).hexdigest()[:16]


def is_item_id(value: str) -> bool:
    """Check whether a string looks like an item id produced by :func:`make_item_id`.

    Args:
        value: Candidate string.

    Returns:
        True when the value is exactly 16 lowercase hex characters.
    """
    return bool(_ITEM_ID_RE.match(value))


def _slugify(value: str) -> str:
    """Turn an arbitrary string into a filesystem-safe slug.

    Args:
        value: Raw string (feed name or URL fragment).

    Returns:
        Lowercase slug with non-alphanumeric runs collapsed to ``-``,
        capped at :data:`MAX_SLUG_LENGTH` characters.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:MAX_SLUG_LENGTH] or "feed"


class FeedSite(BaseModel):
    """A configured RSS/Atom feed source.

    Attributes:
        url: Feed URL (RSS or Atom XML endpoint).
        name: Optional human-friendly name; used to derive the storage slug.
        max_items: Optional per-site cap on items processed per read.
        use_browser: When True, article pages for this site are always
            fetched with the Selenium browser instead of aiohttp.
    """

    url: str = Field(..., description="RSS/Atom feed URL")
    name: Optional[str] = Field(default=None, description="Human-friendly feed name")
    max_items: Optional[int] = Field(
        default=None, ge=1, description="Per-site cap on items processed per read"
    )
    use_browser: bool = Field(
        default=False,
        description="Always fetch article pages with the browser (JS-heavy sites)",
    )

    @classmethod
    def from_config(cls, item: Union[str, Dict[str, Any], "FeedSite"]) -> "FeedSite":
        """Coerce a feed configuration entry into a :class:`FeedSite`.

        Args:
            item: A plain URL string, a dict of ``FeedSite`` fields, or an
                already-built ``FeedSite``.

        Returns:
            A ``FeedSite`` instance.

        Raises:
            TypeError: If the entry is not a supported type.
        """
        if isinstance(item, FeedSite):
            return item
        if isinstance(item, str):
            return cls(url=item)
        if isinstance(item, dict):
            return cls(**item)
        raise TypeError(f"Unsupported feed config entry: {type(item)!r}")

    @property
    def slug(self) -> str:
        """Filesystem-safe identifier for this feed (name or URL host+path)."""
        if self.name:
            return _slugify(self.name)
        parsed = urlparse(self.url)
        return _slugify(f"{parsed.netloc}{parsed.path}")


class FeedItemMetadata(BaseModel):
    """LLM-facing record for a retrieved feed item.

    This is the ONLY thing returned to the LLM by ``read_feeds`` — it carries
    metadata plus the paths of the archived content, never the content itself.

    Attributes:
        item_id: Stable id (sha256(link)[:16]) usable with ``get_content``.
        feed: Slug of the feed the item came from.
        feed_url: URL of the feed the item came from.
        title: Item title.
        link: Article URL.
        published: Publication timestamp (ISO-8601) when available.
        summary: Feed-provided summary, truncated to 500 chars.
        author: Item author when available.
        html_path: Absolute path of the saved raw HTML page.
        text_path: Absolute path of the saved extracted text.
        fetch_method: How the page was retrieved.
        fetch_status: Outcome of the retrieval.
        error: Error detail when the fetch failed or degraded.
    """

    item_id: str
    feed: str
    feed_url: str
    title: str = ""
    link: str = ""
    published: Optional[str] = None
    summary: Optional[str] = None
    author: Optional[str] = None
    html_path: Optional[str] = None
    text_path: Optional[str] = None
    fetch_method: Literal["aiohttp", "selenium", "none"] = "none"
    fetch_status: Literal["fetched", "cached", "failed"] = "failed"
    error: Optional[str] = None

    def to_llm_dict(self) -> Dict[str, Any]:
        """Serialize for the LLM, dropping empty fields to save tokens."""
        return self.model_dump(exclude_none=True)


@dataclass
class FetchedPage:
    """Internal result of a single article-page fetch attempt.

    Attributes:
        html: Raw page HTML ('' when nothing was retrieved).
        text: Extracted main text ('' when extraction produced nothing).
        method: Mechanism that produced the html.
        status_code: HTTP status code (aiohttp path only).
        error: Error message when the fetch failed or degraded.
        thin: True when the extracted text is below the minimum length.
    """

    html: str = ""
    text: str = ""
    method: Literal["aiohttp", "selenium", "none"] = "none"
    status_code: Optional[int] = None
    error: Optional[str] = None
    thin: bool = False


class GetContentInput(BaseModel):
    """Input schema for ``rss_get_content``."""

    item: str = Field(
        ...,
        description=(
            "Item to read: either the 16-char item_id returned by "
            "rss_read_feeds, or a saved html_path/text_path"
        ),
    )
    format: Literal["text", "html"] = Field(
        default="text",
        description="Which archived representation to return",
    )
    max_chars: int = Field(
        default=20000,
        ge=100,
        description="Maximum number of characters to return",
    )
