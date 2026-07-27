"""Tool-result compression pipeline (FEAT-380).

Public surface for the compression contract primitives: :class:`FilterLevel`,
:class:`CompressionOutcome`, the :class:`ResultCompressor` Protocol, and the
codec-class registry.

This package deliberately has NO dependency on ``parrot.tools.manager`` or
``parrot.tools.abstract`` — importing it must never pull in
``parrot.tools.manager`` (avoids an import cycle with ``parrot.tools.__init__``).
"""
from .budget import BudgetRouter, Route
from .config import CompressorConfig, CompressorEntry
from .levels import FilterLevel, cap
from .protocol import (
    CompressionOutcome,
    ResultCompressor,
    get_codec,
    known_codecs,
    register_codec,
)
from .registry import CompressorRegistry

__all__ = [
    "FilterLevel",
    "cap",
    "CompressionOutcome",
    "ResultCompressor",
    "register_codec",
    "get_codec",
    "known_codecs",
    "CompressorEntry",
    "CompressorConfig",
    "CompressorRegistry",
    "Route",
    "BudgetRouter",
]
