---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: LLM Wiki Obsidian Plugin — Vault Ingestion into AI-Parrot

**Feature ID**: FEAT-392
**Date**: 2026-07-30
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.x

---

## 1. Motivation & Business Requirements

> Ingest Obsidian vaults into AI-Parrot's LLM Wiki infrastructure, preserving
> the vault's rich structure and hand-curated link graph.

### Problem Statement

Obsidian is one of the most popular knowledge management tools, with vaults
containing rich, interlinked markdown notes that represent a user's curated
knowledge graph. Currently, there is no way to ingest an Obsidian vault into
AI-Parrot's LLM Wiki infrastructure (PageIndex + GraphIndex + Ontology).

Users who maintain knowledge in Obsidian want to:
1. Make their vault queryable through AI-Parrot agents (grounded, cited answers).
2. Extract structured entities and concepts from their notes (like the
   obsidian-llm-wiki plugin does, but backed by AI-Parrot's infrastructure).
3. Preserve the hand-curated `[[wikilink]]` graph as high-quality edges in
   GraphIndex — these are human-verified "related" signals that outperform
   embedding-based similarity.
4. Keep the ingested data in sync as the vault evolves (incremental updates).

This affects both end-users who want AI-powered access to their Obsidian knowledge
and developers building agents backed by personal/team knowledge bases.

### Goals
- Parse and ingest Obsidian vault directories into PageIndex with full structure
  preservation (`[[wikilinks]]`, `![[embeds]]`, YAML frontmatter, `#tags`,
  aliases, callouts, canvas files, dataview queries, folder hierarchy).
- Two-phase pipeline: Phase 1 (fast raw ingest, no LLM) + Phase 2 (LLM-powered
  entity/concept extraction), separated so users can load quickly and extract later.
- Import the vault's `[[wikilink]]` graph into GraphIndex as pre-curated edges.
- Support both full vault ingest and incremental updates (detect changed/new/deleted
  files via SourceCollectionManager).
- Configurable granularity for entity extraction (Minimal / Standard / Fine / Custom).
- Work with both a running AI-Parrot server (HTTP API) and local Python installation.

### Non-Goals (explicitly out of scope)
- Building a TypeScript Obsidian plugin that runs inside Obsidian — this is a
  Python-side loader/connector only.
- Evaluating Dataview queries (would require reimplementing the DQL parser) —
  queries are stored as raw text in metadata.
- Real-time sync via filesystem watching (watchdog) — this is a future enhancement;
  the current scope covers on-demand full and incremental ingest.
- Modifying the GraphIndex `EdgeKind`/`NodeKind` enums — Obsidian-specific semantics
  use existing enum values plus `domain_tags`.

---

## 2. Architectural Design

### Overview

The solution follows **Option A** from the brainstorm: an `ObsidianVaultLoader`
module in `parrot/loaders/` wired into the existing `WikiIngestOrchestrator`
pipeline. The architecture has three components:

1. **ObsidianVaultLoader** (`parrot/loaders/obsidian/`) — Parses the vault directory,
   extracts all Obsidian-specific structures, and stores raw pages into PageIndex
   via `PageIndexToolkit.add_node()`. Uses `python-frontmatter` for YAML frontmatter
   extraction and `marko` for markdown body parsing with custom extensions for
   `[[wikilinks]]` and `![[embeds]]`. Registers each file in `SourceCollectionManager`
   for staleness tracking.

2. **ObsidianGraphBridge** (`parrot/loaders/obsidian/graph_bridge.py`) — Converts the
   vault's link graph into GraphIndex nodes and edges. Notes → `NodeKind.DOCUMENT`
   nodes, `[[wikilinks]]` → `EdgeKind.REFERENCES` edges, `#tags` → `NodeKind.CONCEPT`
   nodes with `EdgeKind.REFERENCES` edges, folder hierarchy → `EdgeKind.CONTAINS`
   edges. All Obsidian-specific semantics are expressed via `domain_tags` on existing
   node/edge kinds.

3. **WikiIngestOrchestrator extension** — A new `extract_entities()` method on the
   existing orchestrator for Phase 2 (LLM-powered entity/concept extraction from
   already-ingested pages), with configurable granularity.

### Component Diagram
```
Obsidian Vault Directory
    │
    ├── Phase 1: ObsidianVaultLoader
    │   ├── ObsidianVaultDiscovery  ─── scan .md / .canvas files
    │   ├── ObsidianNoteParser      ─── frontmatter + marko + wikilink extensions
    │   ├── ObsidianCanvasParser    ─── .canvas JSON parsing
    │   ├── VaultIndex              ─── in-memory note path/alias/tag index
    │   │
    │   ├──→ PageIndexToolkit.add_node()      (one node per note)
    │   └──→ SourceCollectionManager          (hash + mtime tracking)
    │
    ├── Phase 1b: ObsidianGraphBridge
    │   ├──→ GraphIndexToolkit.create_node()  (notes, tags, folders)
    │   └──→ GraphIndexToolkit.link_nodes()   (wikilinks, contains, embeds)
    │
    └── Phase 2: WikiIngestOrchestrator.extract_entities()
        ├──→ TwoStepIngester (CoT analysis → entity extraction)
        ├──→ PageIndexToolkit (entity/concept sub-nodes)
        └──→ GraphIndexToolkit (entity graph nodes + edges)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `PageIndexToolkit` | uses | `add_node()`, `create_tree()`, `tag_node()` — storage target for raw pages |
| `GraphIndexToolkit` | uses | `create_node()`, `link_nodes()`, `create_concept()` — graph import target |
| `WikiIngestOrchestrator` | extends | New `extract_entities()` method for Phase 2 |
| `SourceCollectionManager` | uses | `add_source()`, `is_stale()`, `mark_ingested()`, `remove_source()` — staleness tracking |
| `LLMWikiToolkit` | extends | New `ingest_obsidian_vault()` tool method wrapping the loader |
| `WikiConfig` | uses | Configuration for wiki name, storage dir, model, etc. |

### Data Models
```python
from pydantic import BaseModel, Field
from pathlib import Path
from enum import Enum


class ExtractionGranularity(str, Enum):
    MINIMAL = "minimal"
    STANDARD = "standard"
    FINE = "fine"
    CUSTOM = "custom"


class ObsidianLink(BaseModel):
    """A single [[wikilink]] or ![[embed]] reference."""
    target: str = Field(..., description="Target note name or path")
    alias: str | None = Field(default=None, description="Display text |alias")
    is_embed: bool = Field(default=False, description="True if ![[embed]]")
    heading: str | None = Field(default=None, description="#heading fragment")


class ObsidianNote(BaseModel):
    """Parsed representation of a single Obsidian markdown note."""
    path: Path = Field(..., description="Relative path within the vault")
    title: str = Field(..., description="Note title (filename stem or frontmatter)")
    content: str = Field(..., description="Raw markdown body (frontmatter stripped)")
    frontmatter: dict = Field(default_factory=dict, description="YAML frontmatter")
    links: list[ObsidianLink] = Field(default_factory=list)
    tags: set[str] = Field(default_factory=set, description="Inline #tags")
    aliases: list[str] = Field(default_factory=list, description="From frontmatter")
    dataview_queries: list[str] = Field(default_factory=list, description="Raw DQL")


class ObsidianCanvasCard(BaseModel):
    """A single card in a .canvas file."""
    card_id: str
    card_type: str = Field(description="'text' | 'file' | 'link' | 'group'")
    file_path: str | None = None
    text: str | None = None
    url: str | None = None


class ObsidianCanvas(BaseModel):
    """Parsed representation of a .canvas file."""
    path: Path
    title: str
    cards: list[ObsidianCanvasCard] = Field(default_factory=list)
    connections: list[tuple[str, str]] = Field(
        default_factory=list, description="(from_card_id, to_card_id) pairs"
    )


class VaultIngestConfig(BaseModel):
    """Configuration for an Obsidian vault ingest operation."""
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
    """Result of a vault ingest operation."""
    vault_path: str
    tree_name: str
    phase: str = Field(description="'raw_ingest' | 'graph_bridge' | 'entity_extraction'")
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
```

### New Public Interfaces
```python
class ObsidianVaultLoader:
    """Parse and ingest Obsidian vault directories into PageIndex."""

    def __init__(self, vault_path: str | Path) -> None: ...

    async def discover(self) -> tuple[list[ObsidianNote], list[ObsidianCanvas]]:
        """Scan the vault and parse all notes and canvas files."""
        ...

    async def ingest(
        self,
        pageindex_toolkit: PageIndexToolkit,
        tree_name: str,
        source_manager: SourceCollectionManager,
        config: VaultIngestConfig | None = None,
    ) -> VaultIngestReport:
        """Phase 1: Full vault ingest into PageIndex (no LLM)."""
        ...

    async def incremental_update(
        self,
        pageindex_toolkit: PageIndexToolkit,
        tree_name: str,
        source_manager: SourceCollectionManager,
        config: VaultIngestConfig | None = None,
    ) -> VaultIngestReport:
        """Detect changed/new/deleted files and update PageIndex."""
        ...


class ObsidianGraphBridge:
    """Convert Obsidian link graph into GraphIndex nodes and edges."""

    def __init__(
        self,
        notes: list[ObsidianNote],
        canvases: list[ObsidianCanvas],
    ) -> None: ...

    def build_graph(self) -> tuple[list[UniversalNode], list[UniversalEdge]]:
        """Convert vault structure into GraphIndex-compatible nodes/edges."""
        ...


# Extension on existing class:
class WikiIngestOrchestrator:
    async def extract_entities(
        self,
        tree_name: str,
        wiki_config: WikiConfig,
        granularity: ExtractionGranularity = ExtractionGranularity.STANDARD,
    ) -> IngestReport:
        """Phase 2: LLM-powered entity/concept extraction from ingested pages."""
        ...
```

---

## 3. Module Breakdown

### Module 1: Obsidian Markdown Parser
- **Path**: `packages/ai-parrot/src/parrot/loaders/obsidian/parser.py`
- **Responsibility**: Parse Obsidian-flavored markdown into `ObsidianNote` models.
  Uses `python-frontmatter` for YAML extraction and `marko` with custom inline
  elements for `[[wikilinks]]`, `![[embeds]]`, `#tags`, and callouts. Extracts
  dataview queries as raw text into metadata.
- **Depends on**: `python-frontmatter`, `marko`, Pydantic models (Module 2)

### Module 2: Data Models
- **Path**: `packages/ai-parrot/src/parrot/loaders/obsidian/models.py`
- **Responsibility**: Pydantic models for `ObsidianNote`, `ObsidianCanvas`,
  `ObsidianLink`, `ObsidianCanvasCard`, `VaultIngestConfig`, `VaultIngestReport`,
  `ExtractionGranularity`.
- **Depends on**: `pydantic`

### Module 3: Vault Discovery & Canvas Parser
- **Path**: `packages/ai-parrot/src/parrot/loaders/obsidian/discovery.py`
- **Responsibility**: Scan vault directory for `.md` and `.canvas` files,
  respecting skip patterns (`.obsidian`, `.trash`, `.git`). Parse `.canvas`
  JSON files into `ObsidianCanvas` models. Build the `VaultIndex` — an in-memory
  index of note paths, aliases, and tags for resolving `[[wikilinks]]` during
  graph bridging.
- **Depends on**: Module 2

### Module 4: ObsidianVaultLoader
- **Path**: `packages/ai-parrot/src/parrot/loaders/obsidian/loader.py`
- **Responsibility**: Orchestrates Phase 1 (raw vault ingest). Uses Module 3
  for discovery, Module 1 for parsing, then stores each note as a PageIndex node
  via `PageIndexToolkit.add_node()`. Registers files in `SourceCollectionManager`.
  Supports both full ingest and incremental update (staleness detection via
  `SourceCollectionManager.is_stale()`). Handles encoding errors, empty files,
  and broken embeds gracefully.
- **Depends on**: Module 1, Module 2, Module 3, `PageIndexToolkit`, `SourceCollectionManager`

### Module 5: ObsidianGraphBridge
- **Path**: `packages/ai-parrot/src/parrot/loaders/obsidian/graph_bridge.py`
- **Responsibility**: Converts parsed vault structure into GraphIndex nodes and
  edges. Mapping: notes → `NodeKind.DOCUMENT`, `[[wikilinks]]` →
  `EdgeKind.REFERENCES`, `![[embeds]]` → `EdgeKind.REFERENCES` +
  `domain_tags: {"embed": true}`, `#tags` → `NodeKind.CONCEPT` +
  `domain_tags: {"obsidian_type": "tag"}`, folders → `NodeKind.DOCUMENT` +
  `domain_tags: {"obsidian_type": "folder"}`, folder→note → `EdgeKind.CONTAINS`,
  canvas → `NodeKind.DOCUMENT` + `domain_tags: {"obsidian_type": "canvas"}`.
  Broken wikilinks create placeholder nodes with `domain_tags: {"status": "unresolved"}`.
- **Depends on**: Module 2, Module 3, `GraphIndexToolkit`, `UniversalNode`, `UniversalEdge`

### Module 6: WikiIngestOrchestrator Extension
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/ingest.py` (modification)
- **Responsibility**: Add `extract_entities()` method to the existing
  `WikiIngestOrchestrator`. Iterates over pages in a PageIndex tree, runs
  `TwoStepIngester` on each page's content, creates entity/concept sub-nodes,
  and syncs them to GraphIndex. Configurable granularity controls extraction depth.
- **Depends on**: `PageIndexToolkit`, `GraphIndexToolkit`, `TwoStepIngester`

### Module 7: Package Init & Registration
- **Path**: `packages/ai-parrot/src/parrot/loaders/obsidian/__init__.py`
- **Responsibility**: Package init exposing `ObsidianVaultLoader`,
  `ObsidianGraphBridge`, and key models. Registration as a discoverable loader.
- **Depends on**: Module 4, Module 5

### Module 8: Tests
- **Path**: `packages/ai-parrot/tests/loaders/obsidian/`
- **Responsibility**: Unit tests for parser, discovery, loader, graph bridge.
  Integration test for the full Phase 1 + Phase 1b pipeline using a fixture vault.
  Test fixtures: a small Obsidian vault directory with representative note types,
  wikilinks, embeds, tags, frontmatter, canvas files, and edge cases (broken links,
  circular embeds, non-UTF-8 files).
- **Depends on**: All modules

### Module 9: Example Script
- **Path**: `examples/knowledge_wiki/obsidian_wiki_agent.py`
- **Responsibility**: End-to-end example demonstrating Obsidian vault ingest into
  the LLM Wiki. Shows Phase 1 (raw ingest), Phase 1b (graph bridge), Phase 2
  (entity extraction), and querying the resulting wiki.
- **Depends on**: All modules, `examples/knowledge_wiki/wiki.py`

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_parse_wikilink` | Module 1 | Parses `[[target]]`, `[[target\|alias]]`, `[[target#heading]]` |
| `test_parse_embed` | Module 1 | Parses `![[note]]`, `![[image.png]]` |
| `test_parse_frontmatter` | Module 1 | Extracts YAML frontmatter including aliases and tags |
| `test_parse_tags` | Module 1 | Extracts inline `#tag` and `#nested/tag` |
| `test_parse_callouts` | Module 1 | Preserves `> [!note]` callout blocks in content |
| `test_parse_dataview` | Module 1 | Extracts dataview queries as raw text in metadata |
| `test_discover_vault` | Module 3 | Scans fixture vault, finds .md and .canvas files |
| `test_skip_patterns` | Module 3 | Skips `.obsidian/`, `.trash/`, `.git/` |
| `test_parse_canvas` | Module 3 | Parses `.canvas` JSON into `ObsidianCanvas` model |
| `test_vault_index` | Module 3 | Resolves wikilinks by name, path, and alias |
| `test_full_ingest` | Module 4 | Ingests fixture vault into PageIndex |
| `test_incremental_add` | Module 4 | Detects new files and ingests them |
| `test_incremental_update` | Module 4 | Detects modified files and re-ingests |
| `test_incremental_delete` | Module 4 | Detects deleted files and removes nodes |
| `test_encoding_error` | Module 4 | Skips non-UTF-8 files with warning |
| `test_graph_notes` | Module 5 | Creates DOCUMENT nodes for each note |
| `test_graph_wikilinks` | Module 5 | Creates REFERENCES edges for `[[wikilinks]]` |
| `test_graph_embeds` | Module 5 | Creates REFERENCES edges with embed domain_tag |
| `test_graph_tags` | Module 5 | Creates CONCEPT nodes for `#tags` |
| `test_graph_folders` | Module 5 | Creates CONTAINS edges for folder hierarchy |
| `test_graph_canvas` | Module 5 | Creates DOCUMENT nodes for canvas files |
| `test_graph_broken_links` | Module 5 | Creates unresolved placeholder nodes |
| `test_circular_embeds` | Module 4 | Detects cycles, limits depth, logs warning |

### Integration Tests
| Test | Description |
|---|---|
| `test_vault_to_wiki_pipeline` | Full Phase 1 + Phase 1b: fixture vault → PageIndex + GraphIndex |
| `test_incremental_pipeline` | Modify fixture vault → incremental update → verify PageIndex/GraphIndex state |

### Test Data / Fixtures
```python
@pytest.fixture
def fixture_vault(tmp_path):
    """Create a small Obsidian vault with representative content."""
    # notes/
    #   daily/2026-07-30.md  — frontmatter + wikilinks
    #   projects/ai-parrot.md — tags, aliases, embeds
    #   concepts/machine-learning.md — nested tags, callouts
    #   orphan.md — no links to/from
    # assets/
    #   diagram.png — binary file (referenced by embed)
    # canvas/
    #   overview.canvas — JSON canvas with card refs
    # broken-link-note.md — [[nonexistent-target]]
    # non-utf8.md — binary content (should be skipped)
    ...
    return tmp_path
```

---

## 5. Acceptance Criteria

- [ ] `ObsidianVaultLoader` parses all Obsidian structures: `[[wikilinks]]`,
  `![[embeds]]`, YAML frontmatter, `#tags`, aliases, callouts, `.canvas` files,
  dataview queries, and folder hierarchy.
- [ ] Phase 1 (raw ingest) runs without an LLM — no API key required.
- [ ] Phase 2 (entity extraction) is a separate method with configurable
  granularity: `minimal`, `standard`, `fine`, `custom`.
- [ ] `[[wikilinks]]` are imported as `EdgeKind.REFERENCES` edges in GraphIndex.
- [ ] `![[embeds]]` are imported as `EdgeKind.REFERENCES` edges with
  `domain_tags: {"embed": true}`.
- [ ] `#tags` are imported as `NodeKind.CONCEPT` nodes with
  `domain_tags: {"obsidian_type": "tag"}`.
- [ ] Canvas files are imported as `NodeKind.DOCUMENT` nodes with
  `domain_tags: {"obsidian_type": "canvas"}`.
- [ ] Folder hierarchy is represented via `EdgeKind.CONTAINS` edges.
- [ ] Aliases are stored as `domain_tags: {"aliases": [...]}` on note nodes.
- [ ] Dataview queries are stored as raw text in note metadata
  (`metadata: {"dataview_queries": [...]}`).
- [ ] Incremental updates detect added, modified, and deleted files via
  `SourceCollectionManager` (hash + mtime staleness).
- [ ] Broken `[[wikilinks]]` create placeholder nodes with
  `domain_tags: {"status": "unresolved"}`.
- [ ] Circular `![[embeds]]` are detected with depth limit (default 3).
- [ ] Non-UTF-8 files are skipped with a logged warning.
- [ ] `.obsidian/`, `.trash/`, `.git/` directories are skipped.
- [ ] All unit tests pass: `pytest packages/ai-parrot/tests/loaders/obsidian/ -v`
- [ ] Integration test passes: full vault → PageIndex + GraphIndex pipeline.
- [ ] No breaking changes to existing `WikiIngestOrchestrator.ingest()` API.
- [ ] Works with both local Python installation and server-mode (via
  `LLMWikiToolkit` integration).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### User-Provided Code
```
# Source: user-provided (reference repository)
# https://github.com/green-dalii/obsidian-llm-wiki
# TypeScript Obsidian plugin — used as conceptual reference only.
# Key architecture insights:
# - Entity & concept extraction from markdown notes
# - Zero-embedding graph retrieval via Personalized PageRank
# - 5-stage seed-selection cascade (lex → LLM keyword → substring → LLM KB → PPR)
# - Configurable granularity (Minimal → Fine + Custom)
# - Content-hash dedup for identical files
```

### Verified Imports
```python
# Base classes and models — verified in current codebase:
from parrot.loaders.abstract import AbstractLoader       # parrot/loaders/abstract.py
from parrot.stores.models import Document                # parrot/stores/models.py

# Wiki infrastructure:
from parrot.knowledge.wiki.ingest import (               # parrot/knowledge/wiki/ingest.py
    WikiIngestOrchestrator, IngestReport,
)
from parrot.knowledge.wiki.sources import (              # parrot/knowledge/wiki/sources.py
    SourceCollectionManager,
)
from parrot.knowledge.wiki.models import WikiConfig      # parrot/knowledge/wiki/models.py
from parrot.knowledge.wiki.bookkeeper import (           # parrot/knowledge/wiki/bookkeeper.py
    WikiBookkeeper,
)
from parrot.knowledge.wiki.store import (                # parrot/knowledge/wiki/store.py
    WikiPageRecord, WikiStore, estimate_tokens,
)
from parrot.knowledge.wiki.toolkit import LLMWikiToolkit # parrot/knowledge/wiki/toolkit.py

# PageIndex:
from parrot.knowledge.pageindex.toolkit import (         # parrot/knowledge/pageindex/toolkit.py
    PageIndexToolkit,
)
from parrot.knowledge.pageindex.ingest import (          # parrot/knowledge/pageindex/ingest.py
    TwoStepIngester,
)

# GraphIndex schema:
from parrot.knowledge.graphindex.schema import (         # parrot/knowledge/graphindex/schema.py
    EdgeKind, NodeKind, UniversalEdge, UniversalNode,
)

# GraphIndexToolkit is in the separate parrot_tools package:
# from parrot_tools.graphindex.toolkit import GraphIndexToolkit

# Toolkit base class:
from parrot.tools.toolkit import AbstractToolkit         # parrot/tools/toolkit.py

# External libraries (all installed):
import frontmatter      # python-frontmatter v1.3.0
import marko             # marko v2.2.3
```

### Existing Class Signatures
```python
# parrot/loaders/abstract.py
class AbstractLoader(ABC):
    async def load(self, source=None, split_documents=True, ...) -> List[Document]
    async def from_path(self, path, recursive=False, **kwargs) -> List[asyncio.Task]
    def create_document(self, content, path, metadata=None, **kwargs) -> Document
    def create_metadata(self, path, doctype='document', ...) -> dict

# parrot/knowledge/wiki/ingest.py
class WikiIngestOrchestrator:
    def __init__(self, pageindex_toolkit, graphindex_toolkit,
                 source_manager, bookkeeper, store=None, sync_graph=False)
    async def ingest(self, source_path: str, wiki_config: WikiConfig) -> IngestReport
    # NOTE: extract_entities() does NOT exist yet — Module 6 adds it.

class IngestReport(BaseModel):
    source_id: str
    source_uri: str
    pages_created: int = 0
    pages_updated: int = 0
    graph_nodes_created: int = 0
    duration_ms: float = 0.0
    status: str = "ok"
    error: Optional[str] = None

# parrot/knowledge/wiki/sources.py
class SourceCollectionManager:
    def add_source(self, path: Path) -> SourceManifestEntry
    def list_sources(self) -> list[SourceManifestEntry]
    def get_source(self, source_id: str) -> Optional[SourceManifestEntry]
    def is_stale(self, source_id: str) -> bool
    def mark_ingested(self, source_id: str, pages_generated: list[str],
                      status: str = 'ingested') -> Optional[SourceManifestEntry]
    def remove_source(self, source_id: str) -> bool
    def find_by_uri(self, source_uri: str) -> Optional[str]

# parrot/knowledge/wiki/models.py
class WikiConfig(BaseModel):
    wiki_name: str
    storage_dir: Path
    source_dir: Optional[Path] = None
    page_categories: list = ...
    search_weights: dict[str, float] = ...
    lightweight_model: Optional[str] = None
    model: Optional[str] = None
    sync_graph: bool = False
    storage_backend: str = "sqlite"

# parrot/knowledge/pageindex/toolkit.py
class PageIndexToolkit(AbstractToolkit):
    name = "pageindex"
    async def create_tree(self, tree_name, doc_name=None) -> dict
    async def get_tree(self, tree_name) -> dict
    async def add_node(self, tree_name, title, body, parent_node_id=None,
                       summary=None, categories=None, metadata=None) -> dict
    async def insert_content(self, tree_name, content, parent_node_id=None,
                             hint=None) -> dict
    async def import_file(self, tree_name, file_path, parent_node_id=None) -> dict
    async def import_folder(self, tree_name, folder_path, recursive=False,
                            glob_pattern=None, parent_node_id=None) -> dict
    async def search(self, tree_name, query, top_k=10, use_bm25=True,
                     use_llm_walk=True, rerank=False, ...) -> list
    async def tag_node(self, tree_name, node_id, categories=None, metadata=None)
    async def delete_node(self, tree_name, node_id) -> dict

# parrot/knowledge/graphindex/schema.py
class NodeKind(str, Enum):
    DOCUMENT = "document"
    SECTION = "section"
    SYMBOL = "symbol"
    CONCEPT = "concept"
    RATIONALE = "rationale"
    SKILL = "skill"

class EdgeKind(str, Enum):
    CONTAINS = "contains"
    REFERENCES = "references"
    DEFINES = "defines"
    MENTIONS = "mentions"
    EXPLAINS = "explains"

class UniversalNode(BaseModel):
    node_id: str
    kind: NodeKind
    title: str
    source_uri: Optional[str] = None
    summary: Optional[str] = None
    domain_tags: dict = {}
    ...

class UniversalEdge(BaseModel):
    source_id: str
    target_id: str
    kind: EdgeKind
    confidence: Optional[float] = None
    ...

# parrot_tools/graphindex/toolkit.py
class GraphIndexToolkit(AbstractToolkit):
    async def create_concept(self, title, summary, source_uri=None,
                             categories=None) -> dict
    async def create_node(self, kind, title, summary=None, source_uri=None,
                          parent_id=None, domain_tags=None) -> dict
    async def link_nodes(self, source_id, target_id, kind,
                         confidence=None) -> dict
    async def unlink_nodes(self, source_id, target_id, kind=None) -> dict
    async def find_node(self, query) -> dict
    async def search_hybrid(self, query, top_k=10) -> list[dict]
    async def merge_nodes(self, canonical_id, duplicate_id) -> dict
    async def attach_summary(self, node_id, summary) -> dict
    async def tag_node(self, node_id, key, value) -> dict

# parrot/knowledge/wiki/toolkit.py
class LLMWikiToolkit(AbstractToolkit):
    tool_prefix = "wiki"
    def __init__(self, pageindex_toolkit, graphindex_toolkit, okf_toolkit,
                 config: WikiConfig, agent_id="agent")
    async def ingest_source(self, wiki_name, source_path, source_type=None) -> dict
    async def query(self, wiki_name, question, file_answer=False, mode="combined") -> dict
    async def lint(self, wiki_name, fix=False) -> dict
    # NOTE: ingest_obsidian_vault() does NOT exist yet — to be added.
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `ObsidianVaultLoader.ingest()` | `PageIndexToolkit.add_node()` | method call | `pageindex/toolkit.py` |
| `ObsidianVaultLoader.ingest()` | `SourceCollectionManager.add_source()` | method call | `wiki/sources.py` |
| `ObsidianVaultLoader.incremental_update()` | `SourceCollectionManager.is_stale()` | method call | `wiki/sources.py` |
| `ObsidianGraphBridge.build_graph()` | `UniversalNode`, `UniversalEdge` | data model | `graphindex/schema.py` |
| `WikiIngestOrchestrator.extract_entities()` | `TwoStepIngester` | internal class | `pageindex/ingest.py` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.loaders.obsidian`~~ — does not exist (this spec creates it)
- ~~`ObsidianVaultLoader`~~ — does not exist (Module 4 creates it)
- ~~`ObsidianGraphBridge`~~ — does not exist (Module 5 creates it)
- ~~`WikiIngestOrchestrator.extract_entities()`~~ — does not exist (Module 6 creates it)
- ~~`WikiIngestOrchestrator.batch_ingest()`~~ — does not exist
- ~~`SourceCollectionManager.bulk_staleness_check()`~~ — does not exist; use
  `is_stale()` per source in a loop
- ~~`LLMWikiToolkit.ingest_obsidian_vault()`~~ — does not exist (to be added)
- ~~`EdgeKind.TAGGED_WITH`~~ — does not exist; use `EdgeKind.REFERENCES` +
  `domain_tags: {"obsidian_type": "tag_link"}`
- ~~`EdgeKind.ALIAS_OF`~~ — does not exist; aliases are stored as
  `domain_tags: {"aliases": [...]}` on the note node
- ~~`EdgeKind.EMBEDS`~~ — does not exist; use `EdgeKind.REFERENCES` +
  `domain_tags: {"embed": true}`
- ~~`NodeKind.TAG`~~ — does not exist; use `NodeKind.CONCEPT` +
  `domain_tags: {"obsidian_type": "tag"}`
- ~~`NodeKind.FOLDER`~~ — does not exist; use `NodeKind.DOCUMENT` +
  `domain_tags: {"obsidian_type": "folder"}`
- ~~`NodeKind.CANVAS`~~ — does not exist; use `NodeKind.DOCUMENT` +
  `domain_tags: {"obsidian_type": "canvas"}`

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Use `asyncio.to_thread()` for all file I/O (consistent with
  `WikiIngestOrchestrator._load_source()`).
- Use `asyncio.Semaphore` for concurrency control during batch processing
  (consistent with `PageIndexToolkit._folder_concurrency`).
- Pydantic models for all structured data.
- Logging with `logging.getLogger(__name__)` — no print statements.
- Follow the existing `examples/knowledge_wiki/wiki.py` patterns for graph
  seeding (`graph_seed_from_tree`) and toolkit wiring (`build_graphindex_toolkit`).

### Obsidian-Specific Parsing Details

**Wikilink syntax variants** (all must be handled):
- `[[note]]` — basic link
- `[[note|display text]]` — aliased link
- `[[note#heading]]` — heading link
- `[[note#heading|display]]` — heading + alias
- `[[folder/note]]` — path-qualified link

**Embed syntax**: `![[note]]`, `![[image.png]]`, `![[note#heading]]`

**Tag syntax**: `#tag`, `#nested/tag`, frontmatter `tags: [tag1, tag2]`

**Canvas JSON structure** (`.canvas`):
```json
{
  "nodes": [
    {"id": "abc", "type": "file", "file": "notes/my-note.md", ...},
    {"id": "def", "type": "text", "text": "Some text", ...}
  ],
  "edges": [
    {"fromNode": "abc", "toNode": "def", ...}
  ]
}
```

### Node ID Convention
Use deterministic node IDs based on vault-relative paths:
- Notes: `obsidian::vault-name::path/to/note` (no `.md` extension)
- Tags: `obsidian::vault-name::tag::tag-name`
- Folders: `obsidian::vault-name::folder::path/to/folder`
- Canvas: `obsidian::vault-name::canvas::path/to/file` (no `.canvas` extension)

### Known Risks / Gotchas
- **Large vaults (10,000+ files)**: Batch processing with configurable concurrency
  mitigates. `SourceCollectionManager` is file-based — very large vaults may
  benefit from the `sqlite` backend.
- **Wikilink resolution ambiguity**: Obsidian resolves `[[note]]` by searching
  the entire vault for a file named `note.md`. If multiple files have the same
  name in different folders, Obsidian uses the shortest path. The `VaultIndex`
  must replicate this resolution logic.
- **Frontmatter edge cases**: Some notes have invalid YAML frontmatter. Use
  `python-frontmatter`'s error handling — skip frontmatter on parse failure,
  treat entire content as body.
- **Circular embeds**: `![[a]]` → `![[b]]` → `![[a]]` — enforce depth limit
  (default 3), log a warning, stop recursion.
- **Empty notes**: Notes with only frontmatter and no body — create metadata-only
  nodes (no content to store, but preserve frontmatter as tags/metadata).

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `python-frontmatter` | `>=1.0` | YAML frontmatter extraction from markdown (already installed v1.3.0) |
| `marko` | `>=2.0` | Extensible markdown parsing with custom `[[wikilink]]` elements (already installed v2.2.3) |
| `pydantic` | `>=2.0` | Data models (already a project dependency) |

---

## Worktree Strategy

- **Isolation unit**: `per-spec` — all tasks run sequentially in one worktree.
- **Rationale**: Modules share Pydantic data models (Module 2) and the parser
  (Module 1) is consumed by both the loader (Module 4) and graph bridge (Module 5).
  Co-development in a single worktree avoids merge conflicts on shared models.
- **Cross-feature dependencies**: None. The wiki infrastructure modules
  (`parrot/knowledge/wiki/`) are not under active development by other specs.

---

## 8. Open Questions

- [x] Should canvas files be treated as first-class documents or metadata? —
  *Resolved in brainstorm*: First-class documents. Each canvas becomes a
  `NodeKind.DOCUMENT` node with `domain_tags: {"obsidian_type": "canvas"}`.
  Canvas card→note references become `EdgeKind.REFERENCES` edges.
- [x] Which markdown parser to use? — *Resolved in brainstorm*:
  `python-frontmatter` (v1.3.0) for YAML frontmatter + `marko` (v2.2.3) for
  body parsing with custom `[[wikilink]]`/`![[embed]]` extensions.
- [x] Should EdgeKind/NodeKind be extended with Obsidian-specific types? —
  *Resolved in brainstorm*: No. Use existing enums + `domain_tags` for
  Obsidian-specific semantics.
- [x] Should server-mode vault access be restricted? — *Resolved in brainstorm*:
  Yes. HTTP API only accepts paths under pre-configured `allowed_vault_dirs`.
  Local Python API has no restriction.
- [x] Should dataview queries be evaluated or stored as raw text? —
  *Resolved in brainstorm*: Store as raw text in metadata
  (`metadata: {"dataview_queries": [...]}`). Evaluation deferred to future work.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-30 | Jesus Lara | Initial draft from brainstorm |
