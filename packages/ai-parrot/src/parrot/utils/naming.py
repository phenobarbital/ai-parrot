"""Name normalization utilities for bot/agent creation.

Provides slug generation and de-duplication for agent names used in
URLs and database identifiers.
"""
import re
from typing import Awaitable, Callable, Optional

# Match anything that is NOT alphanumeric or a hyphen
_NON_SLUG_RE = re.compile(r'[^a-z0-9-]+')
# Match two or more consecutive hyphens
_MULTI_HYPHEN_RE = re.compile(r'-{2,}')


def slugify_name(name: str) -> str:
    """Convert a user-provided name into a URL-safe slug.

    Strips whitespace, lowercases, replaces non-alphanumeric characters
    with hyphens, collapses consecutive hyphens, and strips leading/trailing
    hyphens.

    Args:
        name: The raw name string from user input.

    Returns:
        A lowercase, hyphen-separated slug (e.g. ``"my-cool-bot"``).

    Raises:
        ValueError: If the result is empty after normalization.
    """
    slug = name.strip().lower()
    slug = _NON_SLUG_RE.sub('-', slug)
    slug = _MULTI_HYPHEN_RE.sub('-', slug)
    slug = slug.strip('-')
    if not slug:
        raise ValueError(
            "Name produces an empty slug after normalization"
        )
    return slug


async def deduplicate_name(
    slug: str,
    exists_fn: Callable[[str], Awaitable[Optional[str]]],
) -> str:
    """Find a unique name by appending a numeric suffix if needed.

    Calls *exists_fn* to check whether a candidate name is already taken.
    If the base slug is free, it is returned as-is.  Otherwise suffixes
    ``-2`` through ``-99`` are tried.

    Args:
        slug: The base slug to check (output of :func:`slugify_name`).
        exists_fn: An async callable that receives a candidate name and
            returns a non-``None`` value (e.g. ``"database"``) when the
            name is taken, or ``None`` when it is available.

    Returns:
        The first available candidate name.

    Raises:
        ValueError: If all suffixes up to ``-99`` are exhausted.
    """
    if await exists_fn(slug) is None:
        return slug

    for i in range(2, 100):
        candidate = f"{slug}-{i}"
        if await exists_fn(candidate) is None:
            return candidate

    raise ValueError(
        f"Cannot deduplicate '{slug}': all suffixes up to -99 are taken"
    )
