---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: LLM Wiki Obsidian Plugin — Vault Ingestion into AI-Parrot

**Date**: 2026-07-30
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: Option A

---

## Problem Statement

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

## Constraints & Requirements

- Must preserve all Obsidian-specific rich structures: `[[wikilinks]]`, `![[embeds]]`,
  YAML frontmatter, `#tags`, aliases, callouts, canvas files (`.canvas`),
  dataview queries, and folder hierarchy.
- Two-phase pipeline: fast raw ingest (Phase 1) + LLM entity/concept extraction
  (Phase 2), separated so users can load quickly and extract later.
- Both full vault ingest and incremental updates (detect changed/new/deleted files).
- Configurable granularity for entity extraction (Minimal → Fine).
- Must work with both a running AI-Parrot server (HTTP API) and local installation
  (direct Python).
- Vault access by mounting/pointing at a directory (no client-side push needed).
- Obsidian `[[wikilinks]]` must be imported as GraphIndex edges.
- Connector to existing LLM Wiki infrastructure — reuses PageIndex, GraphIndex,
  WikiIngestOrchestrator, SourceCollectionManager.

---

## Options Explored

### Option A: ObsidianVaultLoader + WikiIngestOrchestrator Integration

Build an `ObsidianVaultLoader` module in `parrot.loaders` that parses Obsidian
vault structure, then wire it into the existing `WikiIngestOrchestrator` pipeline
for entity extraction. The loader handles Phase 1 (raw ingest with Obsidian-aware
parsing), and the orchestrator handles Phase 2 (entity/concept extraction via
TwoStepIngester).

The loader produces `Document` objects with rich metadata preserving all Obsidian
structures (frontmatter, tags, aliases, links). A separate `ObsidianGraphBridge`
component converts the vault's `[[wikilink]]` graph into GraphIndex nodes and edges.

For incremental updates, reuse `SourceCollectionManager` (hash + mtime staleness
detection) which already supports the exact pattern needed.

✅ **Pros:**
- Reuses maximum existing infrastructure (WikiIngestOrchestrator, SourceCollectionManager,
  PageIndexToolkit, GraphIndexToolkit).
- Familiar pattern for AI-Parrot developers — follows the established loader convention.
- Clean two-phase separation: loader is fast/offline, extraction is LLM-dependent.
- Incremental updates come "free" from SourceCollectionManager.
- Can be registered as a standard loader and discovered via the loader registry.

❌ **Cons:**
- AbstractLoader was designed for document-level loading; a vault is a collection
  with inter-document relationships (wikilinks). The graph-bridging step is an
  extension beyond the normal loader pattern.
- Requires extending WikiIngestOrchestrator to handle batch ingestion (it currently
  processes one source at a time).

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `python-frontmatter` | Parse YAML frontmatter from markdown | Mature, MIT, v1.1+ |
| `marko` or `markdown-it-py` | Obsidian-flavored markdown parsing (wikilinks, callouts) | Need custom extensions for `[[wikilinks]]` |
| `watchdog` | Filesystem watching for live incremental updates (optional) | BSD, v4.0+ |
| `pydantic` | Vault/note/link models | Already a project dependency |

🔗 **Existing Code to Reuse:**
- `parrot/loaders/abstract.py` — AbstractLoader base class
- `parrot/knowledge/wiki/ingest.py` — WikiIngestOrchestrator pipeline
- `parrot/knowledge/wiki/sources.py` — SourceCollectionManager (staleness detection)
- `parrot/knowledge/pageindex/toolkit.py` — PageIndexToolkit (insert_content, add_node, import_folder)
- `parrot_tools/graphindex/toolkit.py` — GraphIndexToolkit (create_node, link_nodes)
- `examples/knowledge_wiki/wiki.py` — graph_seed_from_tree bridge pattern

---

### Option B: Dedicated `parrot.knowledge.obsidian` Module

Build a self-contained module at `parrot.knowledge.obsidian` that handles the
full Obsidian → LLM Wiki pipeline: vault discovery, markdown parsing, graph
extraction, PageIndex population, and GraphIndex bridging. Does not extend
AbstractLoader — instead provides its own `ObsidianVaultManager` class that
orchestrates the two-phase pipeline internally.

This approach treats an Obsidian vault as a first-class knowledge source with
its own lifecycle, not just another document format to load.

✅ **Pros:**
- Purpose-built for vault-level semantics (collections, inter-document links,
  folder hierarchy) — not shoehorned into a document-level loader abstraction.
- Can model the vault as a persistent, evolving knowledge source with its own
  state tracking.
- Clean API surface: `vault.full_ingest()`, `vault.incremental_update()`,
  `vault.extract_entities(granularity="fine")`.
- Can implement Obsidian-specific optimizations (e.g., reading `.obsidian/`
  config for resolved aliases, plugin metadata).

❌ **Cons:**
- More code to write — reimplements some patterns already in WikiIngestOrchestrator
  and SourceCollectionManager.
- New module location may confuse developers expecting loaders in `parrot/loaders/`.
- Doesn't benefit from loader registry auto-discovery.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `python-frontmatter` | Parse YAML frontmatter | Mature, MIT |
| `marko` | Obsidian-flavored markdown parsing | Extensible, customizable |
| `watchdog` | Filesystem watching for live sync | BSD, v4.0+ |
| `pydantic` | Models | Already a dependency |

🔗 **Existing Code to Reuse:**
- `parrot/knowledge/pageindex/toolkit.py` — PageIndexToolkit (used as output target)
- `parrot_tools/graphindex/toolkit.py` — GraphIndexToolkit (used as output target)
- `examples/knowledge_wiki/wiki.py` — Patterns for graph seeding and wiki agent wiring

---

### Option C: Hybrid Loader + Obsidian Toolkit

Split the work into two components:
1. An `ObsidianLoader` in `parrot/loaders/` that handles pure file parsing and
   produces `Document` objects (Phase 1 only).
2. An `ObsidianToolkit` in `parrot/tools/` that exposes agent-facing tools for
   vault management: `ingest_vault`, `sync_vault`, `extract_entities`,
   `query_vault_graph`. The toolkit orchestrates the pipeline and wraps the
   loader + PageIndex + GraphIndex interactions.

This gives agents direct programmatic access to vault operations through the
standard tool interface.

✅ **Pros:**
- Agents can manage Obsidian vaults autonomously via toolkit tools.
- Clean separation: loader for parsing, toolkit for orchestration.
- Follows the "tools are the interface" philosophy of AI-Parrot.
- Toolkit can be composed into agent definitions (e.g., an "Obsidian Knowledge Agent").

❌ **Cons:**
- Two new components to maintain (loader + toolkit).
- Toolkit tools may be too coarse-grained for some use cases — users may want
  finer control over the pipeline.
- Agent-facing tools add complexity for the non-agent use case (direct Python API).

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `python-frontmatter` | Parse YAML frontmatter | Mature, MIT |
| `marko` | Markdown parsing with extensions | Extensible |
| `watchdog` | Filesystem watching | BSD, v4.0+ |
| `pydantic` | Models | Already a dependency |

🔗 **Existing Code to Reuse:**
- `parrot/loaders/abstract.py` — AbstractLoader base
- `parrot/tools/toolkit.py` — AbstractToolkit base
- `parrot/knowledge/wiki/ingest.py` — WikiIngestOrchestrator
- `parrot/knowledge/pageindex/toolkit.py` — PageIndexToolkit
- `parrot_tools/graphindex/toolkit.py` — GraphIndexToolkit

---

## Recommendation

**Option A** is recommended because:

- It maximizes reuse of the existing LLM Wiki infrastructure, which was designed
  for exactly this kind of source → pages → graph pipeline.
- The `SourceCollectionManager` already solves incremental updates with hash + mtime
  staleness detection — no need to reinvent it.
- The `WikiIngestOrchestrator` already handles the orchestration of
  PageIndex → GraphIndex → bookkeeping — we just need to feed it Obsidian-parsed
  content instead of raw text.
- The graph-bridging extension (converting `[[wikilinks]]` to GraphIndex edges)
  is a natural addition that follows the pattern in
  `examples/knowledge_wiki/wiki.py::graph_seed_from_tree`.
- Medium effort — the core parsing logic is the main new code; the pipeline
  plumbing already exists.

The main tradeoff is that AbstractLoader is document-oriented, but this is
manageable: the `ObsidianVaultLoader` operates at the vault level, producing
multiple `Document` objects per vault, and the graph bridge is a separate
component that runs after loading. This is consistent with how `import_folder`
already works in PageIndexToolkit.

---

## Feature Description

### User-Facing Behavior

**Phase 1 — Raw Vault Ingest (fast, no LLM):**

```python
from parrot.loaders.obsidian import ObsidianVaultLoader

loader = ObsidianVaultLoader(vault_path="/path/to/my-vault")
# Full ingest: loads all markdown + canvas files into PageIndex
await loader.ingest(pageindex_toolkit, tree_name="my-vault")
# Result: PageIndex tree with one node per note, preserving frontmatter,
# tags, folder hierarchy as metadata. [[wikilinks]] parsed and stored.
```

**Graph Import (no LLM):**

```python
from parrot.loaders.obsidian import ObsidianGraphBridge

bridge = ObsidianGraphBridge(loader)
# Import the [[wikilink]] graph into GraphIndex
nodes, edges = bridge.build_graph()
# Each note → DOCUMENT node, each [[wikilink]] → REFERENCES edge,
# each #tag → CONCEPT node with TAGGED_WITH edges
```

**Phase 2 — Entity/Concept Extraction (LLM-powered, separate step):**

```python
from parrot.knowledge.wiki.ingest import WikiIngestOrchestrator

orchestrator = WikiIngestOrchestrator(pi, gi, source_mgr, bookkeeper)
# Extract entities/concepts from already-ingested pages
await orchestrator.extract_entities(
    tree_name="my-vault",
    granularity="standard",  # minimal | standard | fine | custom
)
```

**Incremental Updates:**

```python
# Detect and ingest only changed/new files since last run
report = await loader.incremental_update(pageindex_toolkit, tree_name="my-vault")
# report.added: 3, report.updated: 7, report.deleted: 1
```

**Server Mode (HTTP API):**

The loader is also exposed via AI-Parrot's HTTP handlers, so a running server
can be pointed at a vault directory:

```
POST /api/v1/wiki/ingest/obsidian
{
  "vault_path": "/path/to/my-vault",
  "tree_name": "my-vault",
  "mode": "incremental",
  "granularity": "standard"
}
```

### Internal Behavior

```
Obsidian Vault Directory
    │
    ├── Phase 1: ObsidianVaultLoader
    │   ├── Discover files (.md, .canvas)
    │   ├── Parse each note:
    │   │   ├── YAML frontmatter → metadata dict
    │   │   ├── [[wikilinks]] → link registry (source→target list)
    │   │   ├── ![[embeds]] → embed registry (transclusion refs)
    │   │   ├── #tags → tag set
    │   │   ├── Callouts → preserved in content
    │   │   └── Dataview queries → stored as metadata
    │   ├── Build vault-level index (note paths, aliases, tags)
    │   ├── Store raw pages in PageIndex (one node per note)
    │   └── Register each file in SourceCollectionManager (hash + mtime)
    │
    ├── Phase 1b: ObsidianGraphBridge
    │   ├── Convert note → DOCUMENT nodes in GraphIndex
    │   ├── Convert [[wikilinks]] → REFERENCES edges
    │   ├── Convert #tags → CONCEPT nodes + TAGGED_WITH edges
    │   ├── Convert folder hierarchy → CONTAINS edges
    │   └── Convert aliases → ALIAS_OF edges
    │
    └── Phase 2: WikiIngestOrchestrator.extract_entities()
        ├── For each page in the tree:
        │   ├── Run TwoStepIngester (CoT analysis → entity extraction)
        │   ├── Create entity/concept sub-nodes in PageIndex
        │   └── Create corresponding GraphIndex nodes + edges
        └── Configurable granularity controls extraction depth
```

### Edge Cases & Error Handling

- **Broken wikilinks**: `[[nonexistent-note]]` → create a placeholder DOCUMENT
  node in GraphIndex with `status: unresolved`. When the target note is later
  created, the placeholder is promoted during incremental update.
- **Circular embeds**: `![[a]]` embeds `![[b]]` which embeds `![[a]]` → detect
  cycles during parsing, embed content up to depth limit (default 3), log warning.
- **Binary files**: Images, PDFs, and other non-text files referenced in embeds →
  create metadata-only nodes (no content extraction in Phase 1; PDF extraction
  can use existing PageIndexToolkit.import_pdf in Phase 2).
- **Large vaults**: 10,000+ files → use async batch processing with configurable
  concurrency. SourceCollectionManager handles incremental updates efficiently.
- **Encoding issues**: Non-UTF-8 files → skip with warning, log the path.
- **`.obsidian/` directory**: Skip (internal Obsidian config), but optionally read
  `app.json` for resolved alias mappings.
- **Conflicting note names**: Multiple notes with the same name in different
  folders → use full path as the node identifier, short name as alias.
- **Vault path does not exist or is empty**: Raise `VaultNotFoundError` or return
  an empty report respectively.
- **Deleted files during incremental update**: SourceCollectionManager detects
  missing files → remove corresponding PageIndex nodes and GraphIndex nodes,
  clean up dangling edges.

---

## Capabilities

### New Capabilities
- `obsidian-vault-loader`: Parse and ingest Obsidian vault directories into
  PageIndex with full structure preservation.
- `obsidian-graph-bridge`: Convert Obsidian `[[wikilink]]` graph into GraphIndex
  nodes and edges.
- `obsidian-incremental-sync`: Detect changed/new/deleted files and update the
  ingested data incrementally.
- `obsidian-entity-extraction`: Configurable LLM-powered entity/concept
  extraction from vault notes (extends WikiIngestOrchestrator).

### Modified Capabilities
- `wiki-ingest-orchestrator`: Extended with batch ingest support and
  `extract_entities()` method for Phase 2 separation.
- `source-collection-manager`: May need minor extensions for vault-level
  operations (bulk staleness check, bulk deletion).

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/loaders/` | extends | New `obsidian.py` module with ObsidianVaultLoader |
| `parrot/knowledge/wiki/ingest.py` | modifies | Add batch ingest + extract_entities method |
| `parrot/knowledge/wiki/sources.py` | modifies | Minor: bulk operations for vault-level sync |
| `parrot/knowledge/pageindex/toolkit.py` | depends on | Used as storage target (no changes) |
| `parrot_tools/graphindex/toolkit.py` | depends on | Used for graph import (no changes) |
| `examples/knowledge_wiki/` | extends | New example: `obsidian_wiki_agent.py` |
| `parrot/handlers/` | extends | New HTTP endpoint for server-mode vault ingest |

---

## Code Context

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
# - Lint health scan + Smart Fix All
# - Content-hash dedup for identical files
```

### Verified Codebase References

#### Classes & Signatures
```python
# From parrot/loaders/abstract.py (wiki entity verified)
class AbstractLoader(ABC):
    async def load(self, source, split_documents=True, ...) -> List[Document]
    async def from_path(self, path, recursive=False, **kwargs) -> List[asyncio.Task]
    def create_document(self, content, path, metadata=None, **kwargs) -> Document
    def create_metadata(self, path, doctype='document', ...) -> dict

# From parrot/knowledge/wiki/ingest.py (wiki page verified)
class WikiIngestOrchestrator:
    def __init__(self, pageindex_toolkit, graphindex_toolkit,
                 source_manager, bookkeeper, store=None, sync_graph=False)
    async def ingest(self, source_path, wiki_config) -> IngestReport

class IngestReport(BaseModel):
    source_id: str
    source_uri: str
    pages_created: int
    pages_updated: int
    graph_nodes_created: int
    duration_ms: float
    status: str
    error: Optional[str]

# From parrot/knowledge/wiki/sources.py (wiki entity verified)
class SourceCollectionManager:
    def add_source(self, path: Path) -> SourceManifestEntry
    def is_stale(self, source_id: str) -> bool
    def mark_ingested(self, source_id, pages_generated, status='ingested')
    def remove_source(self, source_id: str) -> bool
    def find_by_uri(self, source_uri: str) -> Optional[str]
    def list_sources(self) -> list[SourceManifestEntry]

# From parrot/knowledge/pageindex/toolkit.py (wiki page verified)
class PageIndexToolkit(AbstractToolkit):
    name = "pageindex"
    async def create_tree(self, tree_name, doc_name=None) -> dict
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

# From parrot_tools/graphindex/toolkit.py (wiki entity verified)
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
```

#### Verified Imports
```python
# These imports have been confirmed to work:
from parrot.loaders.abstract import AbstractLoader  # parrot/loaders/abstract.py
from parrot.stores.models import Document  # parrot/stores/models.py
from parrot.knowledge.wiki.ingest import WikiIngestOrchestrator, IngestReport
from parrot.knowledge.wiki.sources import SourceCollectionManager
from parrot.knowledge.wiki.models import WikiConfig
from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper
from parrot.knowledge.wiki.store import WikiPageRecord, WikiStore
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit
from parrot.knowledge.graphindex.schema import (
    EdgeKind, NodeKind, UniversalEdge, UniversalNode,
)
# GraphIndexToolkit is in the separate parrot_tools package:
# from parrot_tools.graphindex.toolkit import GraphIndexToolkit
```

#### Key Attributes & Constants
- `PageIndexToolkit.name` → `"pageindex"` (parrot/knowledge/pageindex/toolkit.py)
- `GraphIndexToolkit` write tools: `create_concept`, `create_node`, `link_nodes`,
  `unlink_nodes`, `attach_summary`, `tag_node`, `merge_nodes`
- `NodeKind.DOCUMENT`, `NodeKind.CONCEPT` — graph node types
- `EdgeKind.CONTAINS`, `EdgeKind.REFERENCES` — graph edge types

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.loaders.obsidian`~~ — does not exist yet (this is what we're building)
- ~~`parrot.loaders.ObsidianVaultLoader`~~ — does not exist
- ~~`ObsidianGraphBridge`~~ — does not exist
- ~~`WikiIngestOrchestrator.extract_entities()`~~ — method does not exist yet
  (currently only has `ingest()`)
- ~~`WikiIngestOrchestrator.batch_ingest()`~~ — method does not exist
- ~~`SourceCollectionManager.bulk_staleness_check()`~~ — method does not exist
- ~~`parrot.knowledge.obsidian`~~ — module does not exist
- ~~`EdgeKind.TAGGED_WITH`~~ — not verified to exist as a built-in edge kind;
  may need to be added or use a custom string
- ~~`EdgeKind.ALIAS_OF`~~ — not verified to exist; may need custom string
- ~~`NodeKind.TAG`~~ — not verified to exist; may need custom string

---

## Parallelism Assessment

- **Internal parallelism**: Yes — the feature decomposes cleanly:
  - Obsidian markdown parser (standalone, no dependencies on other tasks)
  - Graph bridge component (depends on parser models, but not implementation)
  - WikiIngestOrchestrator extensions (independent of parser)
  - HTTP handler (depends on loader being done)
  - Example script (depends on all above)
- **Cross-feature independence**: Low conflict. Only touches the wiki ingest
  module (`parrot/knowledge/wiki/ingest.py`) which is not currently under active
  development. No conflict with in-flight specs.
- **Recommended isolation**: `per-spec` — tasks are sequential enough that a
  single worktree is cleaner. The parser and graph bridge share Pydantic models
  that benefit from co-development.
- **Rationale**: While the parser and orchestrator extensions could theoretically
  be parallelized, they share data models (vault note representation, link
  registry) that would cause merge conflicts if developed in separate worktrees.

---

## Open Questions

- [x] Should canvas files (`.canvas`) be treated as first-class documents with
  their own node type, or as metadata on the notes they reference? — *Owner: Jesus*:
  First-class documents. Each canvas becomes a `NodeKind.DOCUMENT` node with
  `domain_tags: {"obsidian_type": "canvas"}`. Canvas card→note references become
  `EdgeKind.REFERENCES` edges; canvas connections between cards become additional
  `REFERENCES` edges. No new `NodeKind` needed.
- [x] Which markdown parser to use? `marko` is more extensible for custom syntax
  (wikilinks), `markdown-it-py` is faster. `python-frontmatter` handles YAML
  frontmatter but not the full markdown AST. — *Owner: Jesus*:
  Use `python-frontmatter` (v1.3.0, installed) for YAML frontmatter extraction
  as a pre-processing step, then `marko` (v2.2.3, installed) for body parsing.
  `marko`'s extensible renderer/parser architecture makes adding custom
  `[[wikilink]]` and `![[embed]]` inline elements clean. Both are already
  project dependencies.
- [x] Should `EdgeKind` and `NodeKind` be extended with Obsidian-specific types
  (`TAGGED_WITH`, `ALIAS_OF`, `EMBEDS`, `TAG`, `FOLDER`) or should we use
  generic string-based kinds? — *Owner: Jesus*:
  Use existing enums + `domain_tags` for Obsidian-specific semantics. Mapping:
  note → `NodeKind.DOCUMENT`, `[[wikilink]]` → `EdgeKind.REFERENCES`,
  `![[embed]]` → `EdgeKind.REFERENCES` + `domain_tags: {"embed": true}`,
  `#tag` → `NodeKind.CONCEPT` + `domain_tags: {"obsidian_type": "tag"}`,
  folder → `NodeKind.DOCUMENT` + `domain_tags: {"obsidian_type": "folder"}`,
  folder→note → `EdgeKind.CONTAINS`, aliases → stored as
  `domain_tags: {"aliases": [...]}` on the note node. Avoids coupling the
  core schema to a specific integration.
- [x] For the server-mode HTTP API, should vault access be restricted to
  pre-configured directories (security), or can the API accept any path? —
  *Owner: Jesus*:
  Restricted to pre-configured directories. The HTTP API only accepts paths
  under directories listed in server config (`allowed_vault_dirs` in
  `parrot.conf` or environment variable). Arbitrary path access is a
  path-traversal vulnerability. The local Python API (direct usage) does not
  need this restriction.
- [x] Should dataview queries be evaluated (requires a dataview parser) or just
  stored as raw text in note metadata? — *Owner: Jesus*:
  Store as raw text in metadata (`metadata: {"dataview_queries": [...]}`).
  Mark the content region as `[dataview-query]` in parsed output so downstream
  consumers know it's a query, not content. Evaluating Dataview queries would
  require reimplementing the DQL parser — massive scope expansion with
  questionable value. Raw queries are preserved for future evaluation if needed.
