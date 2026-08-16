"""Obsidian vault ingestion into PageIndex / GraphIndex (FEAT-392).

The parsing core (models, parser, discovery/VaultIndex) lives in the
shared interface package ``parrot.interfaces.obsidian`` — re-exported
here so the FEAT-392 import surface keeps working:

    from parrot.loaders.obsidian import ObsidianVaultLoader, ObsidianNote
"""
from parrot.interfaces.obsidian import (
    ExtractionGranularity,
    ObsidianCanvas,
    ObsidianCanvasCard,
    ObsidianLink,
    ObsidianNote,
    ObsidianNoteParser,
    VaultIndex,
    VaultIngestConfig,
    VaultIngestReport,
    parse_canvas,
)

from .graph_bridge import ObsidianGraphBridge
from .loader import ObsidianLoader, ObsidianVaultLoader

__all__ = (
    "ExtractionGranularity",
    "ObsidianCanvas",
    "ObsidianCanvasCard",
    "ObsidianGraphBridge",
    "ObsidianLink",
    "ObsidianLoader",
    "ObsidianNote",
    "ObsidianNoteParser",
    "ObsidianVaultLoader",
    "VaultIndex",
    "VaultIngestConfig",
    "VaultIngestReport",
    "parse_canvas",
)
