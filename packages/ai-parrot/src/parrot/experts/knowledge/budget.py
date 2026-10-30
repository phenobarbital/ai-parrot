"""Knowledge budget and revision helpers (FEAT-778 M4, §8 Q1)."""

from __future__ import annotations

import hashlib
from typing import Final

from parrot.memory.compaction.budget import resolve_window

KNOWLEDGE_FRACTION: Final[float] = 0.15


def knowledge_budget(model: str | None, *, fraction: float = KNOWLEDGE_FRACTION) -> int:
    """Return the single knowledge-token pool for a model.

    Args:
        model: Model name whose context window determines the pool.
        fraction: Portion of the context window reserved for knowledge.

    Returns:
        The truncated knowledge-token budget.
    """
    return int(resolve_window(model) * fraction)


def sha256_revision(data: bytes) -> str:
    """Return the hexadecimal SHA-256 revision for file-backed content.

    Args:
        data: Exact source bytes.

    Returns:
        The hexadecimal SHA-256 digest.
    """
    return hashlib.sha256(data).hexdigest()
