"""CacheableSegment dataclass for provider-agnostic prompt caching.

FEAT-181 — Provider-Agnostic Prompt Caching (Module 1).

A CacheableSegment represents one chunk of the system prompt with a
cache-eligibility flag. The PromptBuilder.build_segments() method produces
a list of these for consumption by AbstractClient._apply_cache_hints().

The ``ttl_hint`` field is reserved for forward-compatibility but is not
translated by any provider in v1.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Literal


@dataclass(frozen=True)
class CacheableSegment:
    """One chunk of the system prompt with a cache-eligibility flag.

    Attributes:
        text: The rendered text of this segment.
        cacheable: Whether this segment is eligible for provider-side caching.
            CONFIGURE-phase layers produce ``cacheable=True`` segments;
            REQUEST-phase layers produce ``cacheable=False`` segments.
        ttl_hint: Reserved for forward-compatibility. Not translated by any
            provider in v1. Use ``'short'`` or ``'long'`` as hints for future
            TTL-aware caching strategies.
    """

    text: str
    cacheable: bool
    ttl_hint: Optional[Literal["short", "long"]] = None
