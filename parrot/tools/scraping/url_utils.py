"""URL normalization utilities for the CrawlEngine.

Provides consistent URL normalization for deduplication across
crawl sessions. All discovered URLs pass through normalize_url()
before being added to the visited set or frontier queue.
"""
from __future__ import annotations

from typing import Optional
from urllib.parse import urljoin, urlparse, urlunparse


_ALLOWED_SCHEMES = frozenset(("http", "https"))


def normalize_url(url: str, base: str = "") -> Optional[str]:
    """Normalize a URL for deduplication.

    Applies the following transformations:
      1. Resolve relative URLs against *base*.
      2. Convert scheme to lowercase.
      3. Remove ``www.`` prefix from the domain.
      4. Strip query string and fragment.
      5. Remove trailing slash (except for root path ``/``).
      6. Reject non-HTTP(S) schemes (``mailto:``, ``javascript:``, etc.).

    Args:
        url: The URL to normalize (absolute or relative).
        base: Base URL used to resolve relative references.

    Returns:
        The normalized URL string, or ``None`` if the URL should be
        discarded (empty, malformed, or non-HTTP scheme).
    """
    if not url or not url.strip():
        return None

    url = url.strip()

    # Resolve relative URLs against base
    if base:
        absolute = urljoin(base, url)
    else:
        absolute = url

    try:
        parsed = urlparse(absolute)
    except Exception:
        return None

    # Reject non-HTTP(S) schemes
    scheme = (parsed.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        return None

    # Reject URLs without a netloc (e.g. malformed)
    if not parsed.netloc:
        return None

    # Normalize domain: lowercase and strip www. prefix
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]

    # Normalize path: remove trailing slash (preserve root "/")
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    # Rebuild without query and fragment
    return urlunparse((scheme, netloc, path, "", "", ""))
