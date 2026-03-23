"""Link discovery for the CrawlEngine.

Extracts and filters links from HTML content, applying domain scoping,
URL pattern filtering, and depth guards before returning normalized URLs.
"""
from __future__ import annotations

import re
from typing import List, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from .url_utils import normalize_url


class LinkDiscoverer:
    """Discovers and filters links from HTML pages.

    Extracts URLs from HTML elements matching a CSS selector, normalizes
    them, and applies domain scoping and regex pattern filters.

    Args:
        follow_selector: CSS selector for elements to extract links from.
        follow_pattern: Optional regex pattern; only URLs matching it are kept.
        base_domain: If set, restricts discovered URLs to this domain
            (unless allow_external is True).
        allow_external: When False (default), URLs outside base_domain
            are discarded.
    """

    def __init__(
        self,
        follow_selector: str = "a[href]",
        follow_pattern: Optional[str] = None,
        base_domain: Optional[str] = None,
        allow_external: bool = False,
    ) -> None:
        self.follow_selector = follow_selector
        self.follow_pattern: Optional[re.Pattern[str]] = (
            re.compile(follow_pattern) if follow_pattern else None
        )
        self.base_domain = base_domain
        self.allow_external = allow_external

    def _strip_www(self, domain: str) -> str:
        """Strip the ``www.`` prefix from a domain for comparison."""
        domain = domain.lower()
        if domain.startswith("www."):
            return domain[4:]
        return domain

    def discover(
        self,
        html: str,
        base_url: str,
        current_depth: int,
        max_depth: int,
    ) -> List[str]:
        """Extract, normalize, and filter links from *html*.

        Args:
            html: Raw HTML content to parse.
            base_url: The URL of the page being parsed (used for resolving
                relative links).
            current_depth: Current crawl depth.
            max_depth: Maximum allowed depth. If ``current_depth >= max_depth``
                no links are returned.

        Returns:
            A deduplicated list of normalized URLs that pass all filters.
        """
        if current_depth >= max_depth:
            return []

        soup = BeautifulSoup(html, "html.parser")
        elements = soup.select(self.follow_selector)

        urls: list[str] = []
        for el in elements:
            href = el.get("href") or el.get("src")
            if not href:
                continue

            normalized = normalize_url(href, base_url)
            if normalized is None:
                continue

            # Domain scoping
            if not self.allow_external and self.base_domain:
                parsed = urlparse(normalized)
                if self._strip_www(parsed.netloc) != self._strip_www(self.base_domain):
                    continue

            # Pattern filtering
            if self.follow_pattern and not self.follow_pattern.search(normalized):
                continue

            urls.append(normalized)

        # Deduplicate preserving order
        return list(dict.fromkeys(urls))
