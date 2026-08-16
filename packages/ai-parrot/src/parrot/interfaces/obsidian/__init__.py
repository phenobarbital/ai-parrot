"""Shared Obsidian vault interface (FEAT-392 + shared-interface work).

One vault-access + parsing core reused by:

* ``parrot.tools.obsidian.ObsidianToolkit`` — agent-facing tools
* ``parrot.loaders.obsidian`` — PageIndex/GraphIndex vault ingestion
* ``parrot.knowledge.wiki.vault_scan`` — wikitoolkit vault build mode

Two backends implement :class:`ObsidianVaultInterface`:
:class:`LocalVaultBackend` (direct filesystem, primary) and
:class:`RestVaultBackend` (Obsidian Local REST API plugin, optional).
"""
from typing import Any, Literal

from .abstract import ObsidianVaultInterface, VaultAccessError
from .index import VaultIndex
from .local import LocalVaultBackend
from .models import (
    CANVAS_SUFFIX,
    DEFAULT_SKIP_PATTERNS,
    NOTE_SUFFIX,
    ExtractionGranularity,
    ObsidianCanvas,
    ObsidianCanvasCard,
    ObsidianLink,
    ObsidianNote,
    VaultFileInfo,
    VaultIngestConfig,
    VaultIngestReport,
    VaultSearchHit,
)
from .okf import (
    OKF_KEY,
    apply_okf,
    normalize_relates_target,
    project_okf_block,
    read_okf,
    validate_okf,
)
from .parser import ObsidianNoteParser, parse_canvas
from .rest import RestVaultBackend

__all__ = (
    "CANVAS_SUFFIX",
    "DEFAULT_SKIP_PATTERNS",
    "NOTE_SUFFIX",
    "OKF_KEY",
    "ExtractionGranularity",
    "LocalVaultBackend",
    "ObsidianCanvas",
    "ObsidianCanvasCard",
    "ObsidianLink",
    "ObsidianNote",
    "ObsidianNoteParser",
    "ObsidianVaultInterface",
    "RestVaultBackend",
    "VaultAccessError",
    "VaultFileInfo",
    "VaultIndex",
    "VaultIngestConfig",
    "VaultIngestReport",
    "VaultSearchHit",
    "apply_okf",
    "create_vault_backend",
    "normalize_relates_target",
    "parse_canvas",
    "project_okf_block",
    "read_okf",
    "validate_okf",
)


def create_vault_backend(
    backend: Literal["local", "rest"] = "local", **kwargs: Any
) -> ObsidianVaultInterface:
    """Factory for vault backends.

    Args:
        backend: ``"local"`` (filesystem, requires ``vault_path``) or
            ``"rest"`` (Local REST API plugin, accepts ``base_url``,
            ``api_key``, ``verify_ssl``, ``timeout``).
        **kwargs: Forwarded to the backend constructor.

    Returns:
        A configured, unopened backend instance.

    Raises:
        ValueError: For an unknown backend name.
    """
    if backend == "local":
        return LocalVaultBackend(**kwargs)
    if backend == "rest":
        return RestVaultBackend(**kwargs)
    raise ValueError(
        f"Unknown Obsidian backend {backend!r} — expected 'local' or 'rest'"
    )
