"""
ScrapingPlan & PlanRegistryEntry Models.

Pydantic v2 models for declarative scraping plans and registry index entries.
ScrapingPlan is a value object — immutable once saved to disk.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, urlunparse

from pydantic import BaseModel, Field, computed_field


def _normalize_url(url: str) -> str:
    """Strip query params and fragments for stable fingerprinting.

    Args:
        url: Raw URL string.

    Returns:
        URL with scheme, netloc, and path only.
    """
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def _compute_fingerprint(normalized_url: str) -> str:
    """Compute a 16-char SHA-256 hex prefix of a normalized URL.

    Note: 16 hex chars = 64 bits. Collision probability is negligible
    for expected plan volumes (~thousands of plans).

    Args:
        normalized_url: URL after normalization (no query/fragment).

    Returns:
        First 16 characters of the SHA-256 hex digest.
    """
    digest = hashlib.sha256(normalized_url.encode("utf-8")).hexdigest()
    return digest[:16]


def _sanitize_domain(domain: str) -> str:
    """Convert a domain into a valid name slug.

    Args:
        domain: Domain string (e.g. 'shop.example.com').

    Returns:
        Sanitized name (e.g. 'shop-example-com').
    """
    return re.sub(r"[^a-zA-Z0-9-]", "-", domain).strip("-")


class ScrapingPlan(BaseModel):
    """Declarative scraping plan — value object, immutable once saved.

    Auto-populates `domain`, `name`, and `fingerprint` from the URL
    in `model_post_init`.
    """

    # Identity
    name: Optional[str] = None
    version: str = "1.0"
    tags: List[str] = Field(default_factory=list)

    # Target
    url: str
    domain: str = ""
    objective: str

    # Execution contract
    steps: List[Dict[str, Any]]
    selectors: Optional[List[Dict[str, Any]]] = None
    browser_config: Optional[Dict[str, Any]] = None

    # Crawl hints
    follow_selector: Optional[str] = None
    follow_pattern: Optional[str] = None
    max_depth: Optional[int] = None

    # Metadata
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: Optional[datetime] = None
    source: str = "llm"
    fingerprint: str = ""

    @computed_field
    @property
    def normalized_url(self) -> str:
        """Strip query params and fragments for stable fingerprinting."""
        return _normalize_url(self.url)

    def model_post_init(self, __context: Any) -> None:
        """Auto-populate domain, name, and fingerprint from URL."""
        parsed = urlparse(self.url)

        if not self.domain:
            self.domain = parsed.netloc

        if self.name is None:
            self.name = _sanitize_domain(self.domain)

        if not self.fingerprint:
            self.fingerprint = _compute_fingerprint(self.normalized_url)


class PlanRegistryEntry(BaseModel):
    """Entry in the PlanRegistry index mapping a plan to its disk location."""

    name: str
    plan_version: str
    url: str
    domain: str
    fingerprint: str = ""
    path: str  # relative to plans_dir
    created_at: datetime
    last_used_at: Optional[datetime] = None
    use_count: int = 0
    tags: List[str] = Field(default_factory=list)
