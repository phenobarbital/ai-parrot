"""Pydantic data models for the shared Obsidian vault interface.

These models are the single source of truth for Obsidian structures across
the framework: the ``ObsidianToolkit`` (parrot.tools.obsidian), the vault
loader/graph bridge (parrot.loaders.obsidian, FEAT-392) and the wikitoolkit
vault scanner (parrot.knowledge.wiki.vault_scan) all consume them.

The core note/canvas models follow the approved FEAT-392 spec
(``sdd/specs/llmwiki-obsidian-plugin.spec.md`` §2) verbatim; the
``VaultFileInfo``/``VaultSearchHit`` models belong to the backend access
layer added by the shared-interface work.
"""
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field


class ExtractionGranularity(str, Enum):
    """Granularity for Phase-2 LLM entity extraction (FEAT-392)."""

    MINIMAL = "minimal"
    STANDARD = "standard"
    FINE = "fine"
    CUSTOM = "custom"


class ObsidianLink(BaseModel):
    """A single ``[[wikilink]]`` or ``![[embed]]`` reference."""

    target: str = Field(..., description="Target note name or path")
    alias: Optional[str] = Field(default=None, description="Display text |alias")
    is_embed: bool = Field(default=False, description="True if ![[embed]]")
    heading: Optional[str] = Field(default=None, description="#heading fragment")


class ObsidianNote(BaseModel):
    """Parsed representation of a single Obsidian markdown note."""

    path: Path = Field(..., description="Relative path within the vault")
    title: str = Field(..., description="Note title (filename stem or frontmatter)")
    content: str = Field(..., description="Raw markdown body (frontmatter stripped)")
    frontmatter: dict = Field(default_factory=dict, description="YAML frontmatter")
    links: list[ObsidianLink] = Field(default_factory=list)
    tags: set[str] = Field(default_factory=set, description="Inline and frontmatter #tags")
    aliases: list[str] = Field(default_factory=list, description="From frontmatter")
    dataview_queries: list[str] = Field(default_factory=list, description="Raw DQL")


class ObsidianCanvasCard(BaseModel):
    """A single card in a ``.canvas`` file."""

    card_id: str
    card_type: str = Field(description="'text' | 'file' | 'link' | 'group'")
    file_path: Optional[str] = None
    text: Optional[str] = None
    url: Optional[str] = None


class ObsidianCanvas(BaseModel):
    """Parsed representation of a ``.canvas`` file."""

    path: Path
    title: str
    cards: list[ObsidianCanvasCard] = Field(default_factory=list)
    connections: list[tuple[str, str]] = Field(
        default_factory=list, description="(from_card_id, to_card_id) pairs"
    )


class VaultIngestConfig(BaseModel):
    """Configuration for an Obsidian vault ingest operation (FEAT-392)."""

    vault_path: Path
    tree_name: str
    wiki_config: Any = None
    skip_patterns: list[str] = Field(
        default_factory=lambda: [".obsidian", ".trash", ".git"],
        description="Directory names to skip during vault discovery",
    )
    embed_depth_limit: int = Field(default=3, description="Max transclusion depth")
    concurrency: int = Field(default=8, ge=1, le=32, description="Async batch size")
    granularity: ExtractionGranularity = Field(
        default=ExtractionGranularity.STANDARD,
        description="Entity extraction granularity (Phase 2 only)",
    )


class VaultIngestReport(BaseModel):
    """Result of a vault ingest operation (FEAT-392)."""

    vault_path: str
    tree_name: str
    phase: str = Field(
        description="'raw_ingest' | 'graph_bridge' | 'entity_extraction'"
    )
    notes_processed: int = 0
    canvas_processed: int = 0
    nodes_created: int = 0
    edges_created: int = 0
    files_added: int = 0
    files_updated: int = 0
    files_deleted: int = 0
    files_skipped: int = 0
    errors: list[str] = Field(default_factory=list)
    duration_ms: float = 0.0


class VaultFileInfo(BaseModel):
    """Lightweight file descriptor returned by vault backends."""

    path: str = Field(..., description="Vault-relative POSIX path")
    name: str = Field(..., description="File name including extension")
    size: Optional[int] = Field(default=None, description="Size in bytes when known")
    mtime: Optional[float] = Field(
        default=None, description="POSIX mtime when known (REST backend may omit)"
    )
    is_note: bool = Field(default=False, description="True for .md files")
    is_canvas: bool = Field(default=False, description="True for .canvas files")


class VaultSearchHit(BaseModel):
    """One search result from a vault backend's search primitive."""

    path: str = Field(..., description="Vault-relative POSIX path of the note")
    score: float = Field(default=0.0, description="Backend-specific relevance score")
    snippet: Optional[str] = Field(
        default=None, description="Matching context excerpt when available"
    )
    matches: list[str] = Field(
        default_factory=list, description="Which fields matched (title/tag/alias/body)"
    )


#: Directory names never traversed by vault backends.
DEFAULT_SKIP_PATTERNS: frozenset[str] = frozenset({".obsidian", ".trash", ".git"})

#: Suffix of Obsidian markdown notes.
NOTE_SUFFIX = ".md"

#: Suffix of Obsidian canvas files.
CANVAS_SUFFIX = ".canvas"
