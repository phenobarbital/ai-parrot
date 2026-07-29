"""Pydantic schema for the declarative compressor TOML manifest.

A manifest maps tool-name patterns (exact name, glob, or ``"*"``) to a
:class:`CompressorEntry` describing which codec to run, at what
:class:`~parrot.tools.compression.levels.FilterLevel`, whether to tee the
original payload to working memory, and codec-specific parameters.
"""
from typing import Any

from pydantic import BaseModel, Field

from .levels import FilterLevel


class CompressorEntry(BaseModel):
    """A single compressor configuration entry.

    Attributes:
        codec: Name of the codec to dispatch to. Must be a name registered
            via :func:`~parrot.tools.compression.register_codec` — validated
            at :meth:`CompressorRegistry.load` time, not at first tool call.
        level: The configured :class:`FilterLevel` for this entry.
        tee: Whether lossy/error payloads for this entry should be teed to
            working memory. Codecs that report ``lossy=True`` always require
            a tee regardless of this flag (G3); this flag is preserved for
            forward-compatible explicit opt-in.
        params: Codec-specific parameters (e.g. ``min_rows`` for the
            columnar codec).
    """

    codec: str
    level: FilterLevel = FilterLevel.MINIMAL
    tee: bool = False
    params: dict[str, Any] = Field(default_factory=dict)


class CompressorConfig(BaseModel):
    """Parsed shape of a single ``compressors.toml`` manifest.

    Attributes:
        compressor: Mapping of tool-name pattern (exact name, glob, or
            ``"*"``) to its :class:`CompressorEntry`.
    """

    compressor: dict[str, CompressorEntry] = Field(default_factory=dict)
