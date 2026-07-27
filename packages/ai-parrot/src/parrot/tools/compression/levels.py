"""Compression filter levels for the tool-result compression pipeline.

Defines :class:`FilterLevel`, the ordered set of compression aggressiveness
levels applied to tool results, and a small helper (:func:`cap`) used to
clamp an effective level to a ceiling (e.g. capping lossy levels to
``MINIMAL`` when no :class:`WorkingMemoryToolkit` is available to recover
teed payloads).
"""
from enum import Enum


class FilterLevel(str, Enum):
    """Aggressiveness of tool-result compression.

    Members are ordered from least to most aggressive. ``MINIMAL`` is the
    documented, conservative default (spec G2): only lossless
    transformations are applied when nothing else is configured.
    """

    NONE = "none"
    """Passthrough — no compression is applied."""

    MINIMAL = "minimal"
    """Lossless only: JSON separator compaction, null-key elision, exact
    dedup. This is the default when nothing is configured (G2)."""

    NORMAL = "normal"
    """Bounded lossy transformations: columnarization, grouping, long-field
    clipping with a recovery marker. Activates the working-memory tee."""

    AGGRESSIVE = "aggressive"
    """Structural summary only; the full body lives exclusively in working
    memory."""


_ORDER: dict[FilterLevel, int] = {
    FilterLevel.NONE: 0,
    FilterLevel.MINIMAL: 1,
    FilterLevel.NORMAL: 2,
    FilterLevel.AGGRESSIVE: 3,
}


def cap(level: FilterLevel, ceiling: FilterLevel) -> FilterLevel:
    """Clamp ``level`` so it never exceeds ``ceiling``.

    Args:
        level: The level to clamp.
        ceiling: The maximum allowed level.

    Returns:
        ``level`` unchanged if it does not exceed ``ceiling``; otherwise
        ``ceiling``.
    """
    return level if _ORDER[level] <= _ORDER[ceiling] else ceiling
