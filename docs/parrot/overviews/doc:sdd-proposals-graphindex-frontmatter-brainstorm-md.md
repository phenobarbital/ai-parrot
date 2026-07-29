---
type: Wiki Overview
title: 'Brainstorm: GraphIndex OKF Frontmatter Projection'
id: doc:sdd-proposals-graphindex-frontmatter-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: FEAT-238 (OKF Knowledge Layer) made PageIndex sidecars **self-describing**
  by
relates_to:
- concept: mod:parrot.knowledge.graphindex
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.projection
  rel: mentions
- concept: mod:parrot.knowledge.okf
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.okf
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Brainstorm: GraphIndex OKF Frontmatter Projection

**Date**: 2026-06-16
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: Option A

---

## Problem Statement

FEAT-238 (OKF Knowledge Layer) made PageIndex sidecars **self-describing** by
projecting deterministic YAML frontmatter onto every `.md` document. Each PageIndex
node now carries `type`, `title`, `id`, `resource`, `summary`, `relates_to`, and
`source` in its frontmatter — fully compatible with OKF v0.1 and Karpathy's LLM-Wiki
pattern.

**GraphIndex has no equivalent.** Its only markdown output is `GRAPH_REPORT.md`
(analytics summary), which has no frontmatter. The rich `UniversalNode` data
(6 node kinds, 5 edge kinds, signal relevance scores, community membership) lives
exclusively in ArangoDB and is invisible to agents or tools that consume plain
markdown files.

This creates three problems:

1. **GraphIndex output is not OKF-compatible.** An agent reading `GRAPH_REPORT.md`
   gets a bare markdown table — no structured metadata, no type, no resource URI.
2. **No node-level markdown export.** Unlike PageIndex (which projects per-node
   `.md` sidecars), GraphIndex cannot export its nodes as self-describing documents.
   An LLM navigating the knowledge base sees PageIndex nodes but not GraphIndex nodes.
3. **Cross-index discovery is fractured.** PageIndex uses `pageindex://` URIs,
   GraphIndex uses ArangoDB `_key` references. There is no unified addressing scheme
   for cross-index linking.

**Who is affected**: LLM agents (cannot consume graph knowledge as markdown), RAG
pipelines (miss graph-enriched context), developers building knowledge-aware
applications.

**Why now**: FEAT-238 just landed (2026-06-15). The OKF projection pattern is fresh,
tested, and proven. Extending it to GraphIndex while the design is in working memory
avoids drift. FEAT-215 (LLM-Wiki roadmap) identifies OKF bundle export as gap G4 —
this feature is the prerequisite.

## Constraints & Requirements

- **Reuse PageIndex OKF schema**: `ConceptFrontmatter`, `ConceptType`, `RelationType`
  from `pageindex/okf/` must be reused, not forked. Single vocabulary.
- **Extend ConceptType**: Add graph-native types (`SYMBOL`, `RATIONALE`, `SKILL`,
  `CONCEPT`, `DOCUMENT`) to the existing enum.
- **Dual-write at build time**: `.md` sidecars written alongside ArangoDB persistence
  during `build_graph()`, following the PageIndex pattern.
- **Unified URI scheme**: `knowledge://<index_type>/<id>` for cross-index references.
- **Byte-determinism**: Same graph data must produce identical output files (FEAT-238
  invariant D1).
- **JSON authoritative**: Frontmatter is a projection, never the source of truth.
- **No breaking changes**: Existing GraphIndex APIs, ArangoDB schema, and PageIndex
  OKF layer must remain backwards-compatible.
- **Frontmatter on GRAPH_REPORT.md**: The analytics report must also gain OKF
  frontmatter for discoverability.

---

## Options Explored

### Option A: Shared OKF Core Module + GraphIndex Projection

Extract the OKF type vocabulary and frontmatter engine into a shared
`parrot/knowledge/okf/` module. Both PageIndex and GraphIndex import from there.
GraphIndex adds its own `projection.py` that maps `UniversalNode` → `ConceptFrontmatter`
→ `.md` sidecar.

**Architecture**:
```
parrot/knowledge/okf/          ← NEW shared module
├── ontology.py               (ConceptType + new graph types, RelationType + new edge kinds)
├── frontmatter.py            (ConceptFrontmatter, project_frontmatter, parse_frontmatter)
└── uri.py                    (knowledge:// URI builder/parser)

parrot/knowledge/pageindex/okf/
├── projection.py             (unchanged — imports from knowledge.okf)
├── concept_id.py             (unchanged)
├── graph.py                  (unchanged)
└── ...                       (re-exports from knowledge.okf for backwards compat)

parrot/knowledge/graphindex/
├── projection.py             ← NEW
│   (project_graph_sidecars, project_node_sidecar, project_report_frontmatter)
└── ...
```

**Key change**: `ConceptType` gains 5 new members: `SYMBOL`, `RATIONALE`, `SKILL`,
`CONCEPT_NODE`, `DOCUMENT_NODE`. `RelationType` gains 3: `DEFINES`, `MENTIONS`,
`EXPLAINS`. These directly mirror `NodeKind` and `EdgeKind` values.

The `UniversalNode → ConceptFrontmatter` mapping is a pure function:
- `kind` → `ConceptType` (direct enum mapping)
- `node_id` → `id`
- `title` → `title`
- `summary` → `summary`
- `domain_tags.get("categories", [])` → `tags`
- `source_uri` → `source.document`
- Edges from `UniversalEdge` → `relates_to` (via `EdgeKind → RelationType`)
- `knowledge://graphindex/<node_id>` → `resource`

`GraphIndexBuilder.build()` gains a Stage 6.5 (after analytics, before return) that
calls `project_graph_sidecars()` to write `.md` files to `output_dir/nodes/`.

`generate_report()` is updated to prepend OKF frontmatter to `GRAPH_REPORT.md`.

✅ **Pros:**
- Single vocabulary — no type confusion between indexes
- Clean dependency graph — shared module, no cross-index imports
- Forwards-compatible with FEAT-215 G4 (OKF bundle export)
- Backwards-compatible via re-exports in `pageindex/okf/__init__.py`
- Enables future `knowledge://` cross-index linking

❌ **Cons:**
- Requires extracting shared code from `pageindex/okf/` (moderate refactor)
- PageIndex must update imports (mitigated by re-exports)
- Two new enum values per type could surprise consumers expecting only PageIndex types

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pyyaml` | YAML serialization for frontmatter | Already a dependency |
| `pydantic` | ConceptFrontmatter model | Already used throughout |

🔗 **Existing Code to Reuse:**
- `pageindex/okf/ontology.py` — ConceptType, RelationType, RelatesTo, SourceProvenance
- `pageindex/okf/frontmatter.py` — ConceptFrontmatter, project_frontmatter, parse_frontmatter
- `pageindex/okf/projection.py` — project_sidecar pattern (frontmatter + body assembly)
- `graphindex/analytics.py` — generate_report, _render_report (add frontmatter header)
- `graphindex/builder.py` — build() pipeline (insert projection stage)

---

### Option B: Import Directly from PageIndex OKF (Thin Adapter)

Keep all OKF code in `pageindex/okf/` as-is. GraphIndex imports directly from
`parrot.knowledge.pageindex.okf` and adds a thin adapter layer in
`graphindex/okf_adapter.py` that converts `UniversalNode` into the dict format
expected by `project_frontmatter()`.

**Architecture**:
```
parrot/knowledge/graphindex/
├── okf_adapter.py            ← NEW (node_to_frontmatter_dict, edge_to_relates_to)
├── projection.py             ← NEW (project_graph_sidecars)
└── ...

parrot/knowledge/pageindex/okf/
└── (unchanged — ConceptType extended in place)
```

✅ **Pros:**
- Minimal refactoring — no file moves
- Fast to implement — just adapter + projection
- ConceptType extended in its current home

❌ **Cons:**
- GraphIndex depends on PageIndex (inverted dependency — graph should not import page)
- If PageIndex is not installed, GraphIndex frontmatter breaks
- Harder to reason about: "why does the graph index import from page index?"

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pyyaml` | YAML serialization | Already a dependency |

🔗 **Existing Code to Reuse:**
- `pageindex/okf/frontmatter.py` — project_frontmatter (called directly)
- `pageindex/okf/ontology.py` — ConceptType (extended in place)

---

### Option C: Pipeline-Only Projection (No Shared Module)

Instead of extracting a shared module, leverage the existing
`LoaderExtractor → PageIndexToolkit` integration path. Extend it so that ALL
GraphIndex nodes (not just loader-extracted ones) can be projected through
PageIndex's sidecar machinery. GraphIndex delegates frontmatter entirely to
PageIndex — it calls `PageIndexToolkit.insert_markdown()` for each node after
build.

**Architecture**:
```
GraphIndexBuilder.build()
  → Stage 5: persist to ArangoDB
  → Stage 6: analytics + report
  → Stage 6.5 (NEW): for each node, call PageIndexToolkit.insert_markdown()
     → PageIndex handles frontmatter projection via project_sidecars()
```

✅ **Pros:**
- Zero new frontmatter code — reuses PageIndex projection entirely
- Nodes get PageIndex-quality sidecars automatically
- Already partially implemented (LoaderExtractor does this for doc nodes)

❌ **Cons:**
- Tight coupling — GraphIndex requires a running PageIndex to export markdown
- Symbol and rationale nodes don't naturally fit PageIndex's tree model
- Cannot project frontmatter without PageIndex configured (optional dependency becomes mandatory for this feature)
- Does not add frontmatter to GRAPH_REPORT.md (separate problem)

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| (none new) | Reuses PageIndexToolkit | Already optional dependency |

🔗 **Existing Code to Reuse:**
- `graphindex/extractors/loader.py` — `_extract_via_toolkit` pattern
- `pageindex/toolkit.py` — `insert_markdown()`, `_persist()`
- `pageindex/okf/projection.py` — `project_sidecars()`

---

### Option D: Minimal Report-Only Frontmatter (Unconventional)

Skip node-level projection entirely. Only add OKF frontmatter to
`GRAPH_REPORT.md` and any future analytics output files. The report becomes
a self-describing OKF document; individual nodes remain in ArangoDB only.

A separate `graph-export` CLI command could later project nodes on demand (like
`okf-migrate` does for PageIndex), decoupling the write-time concern.

✅ **Pros:**
- Smallest possible scope — one function change
- No new projection machinery
- Validates OKF compatibility with minimal risk
- Export-on-demand avoids disk footprint during build

❌ **Cons:**
- Does not achieve the stated goal (node-level .md projection)
- Agents still cannot navigate graph nodes as markdown
- Defers the hard problem to a future FEAT

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pyyaml` | Frontmatter header | Already a dependency |

🔗 **Existing Code to Reuse:**
- `graphindex/analytics.py` — `_render_report()` (prepend frontmatter)

---

## Recommendation

**Option A** is recommended because:

1. **Clean architecture**: A shared `knowledge/okf/` module is the natural home for
   OKF types that both indexes need. It prevents the inverted dependency of Option B
   (graph importing from page) and the tight coupling of Option C (graph requiring
   PageIndex runtime).

2. **Single vocabulary**: Extending `ConceptType` and `RelationType` in one shared
   location means every knowledge component speaks the same type language. This is
   a prerequisite for FEAT-215 G4 (OKF bundle export) and cross-index `knowledge://`
   linking.

3. **Proven pattern**: The extract-to-shared-module pattern follows the same strategy
   used for `parrot/stores/` (shared models) and `parrot/embeddings/` (base classes
   in core, backends in satellite). It's an established AI-Parrot refactoring idiom.

4. **Backwards-compatible**: Re-exports in `pageindex/okf/__init__.py` mean existing
   imports continue to work. No consumer code changes needed.

**Tradeoff**: Medium effort vs Low for Options B/C/D. The refactoring cost is justified
because it establishes the right dependency direction for all future OKF work, and
the shared module is needed regardless once cross-index features land.

---

## Feature Description

### User-Facing Behavior

After `build_graph()` completes, agents and tools see:

1. **Per-node `.md` sidecars** in `<output_dir>/nodes/<node_id>.md`, each with OKF
   frontmatter:
   ```yaml
   ---
   type: Symbol
   title: "GraphIndexBuilder"
   id: "graphindex-builder"
   node_id: "sym-graphindexbuilder-abc123"
   resource: "knowledge://graphindex/sym-graphindexbuilder-abc123"
   tags: ["python", "builder-pattern"]
   timestamp: "2026-06-16T12:00:00Z"
   summary: "Orchestrates the 6-stage graph build pipeline..."
   relates_to:
     - concept: "graphindex-persistence"
       rel: references
   ---
   ```

2. **GRAPH_REPORT.md** gains frontmatter:
   ```yaml
   ---
   type: Document
   title: "Knowledge Graph Report"
   id: "graph-report"
   resource: "knowledge://graphindex/graph-report"
   tags: ["analytics", "graph-report"]
   timestamp: "2026-06-16T12:00:00Z"
   summary: "Analytics report for knowledge graph: N nodes, M edges"
   ---
   ```

3. **Unified `knowledge://` URIs** enable cross-index references:
   - `knowledge://pageindex/controls/nist-800-53/ir-4`
   - `knowledge://graphindex/sym-graphindexbuilder-abc123`

### Internal Behavior

**Stage 6.5 — Projection** (inserted into `GraphIndexBuilder.build()` after analytics):

1. Collect all `UniversalNode` instances from the build.
2. For each node, map `NodeKind → ConceptType`, collect outgoing `UniversalEdge`
   instances, and build a `ConceptFrontmatter` instance.
3. Call `project_frontmatter()` to serialize to YAML.
4. Combine frontmatter + node summary as body → write to
   `<output_dir>/nodes/<flattened_node_id>.md`.
5. Prepend report frontmatter to `GRAPH_REPORT.md`.
6. Return `ProjectionReport` with file counts.

**Shared module extraction** (one-time refactor):

1. Move `ConceptType`, `RelationType`, `RelatesTo`, `SourceProvenance` from
   `pageindex/okf/ontology.py` → `knowledge/okf/ontology.py`.
2. Move `ConceptFrontmatter`, `project_frontmatter`, `parse_frontmatter` from
   `pageindex/okf/frontmatter.py` → `knowledge/okf/frontmatter.py`.
3. Add re-exports in `pageindex/okf/__init__.py` for backwards compatibility.
4. Add new `knowledge/okf/uri.py` for `knowledge://` URI construction/parsing.
5. Extend `ConceptType` with graph-native values.
6. Extend `RelationType` with graph edge kinds.

### Edge Cases & Error Handling

- **Nodes with no summary**: Use `title` as fallback summary text.
- **Nodes with no edges**: `relates_to` is an empty list (valid OKF).
- **Duplicate node_ids**: `flatten_concept_id_for_filename()` handles collisions
  with numeric suffixes (existing pattern).
- **Build without output_dir**: Skip projection stage entirely (matches current
  behavior where `generate_report()` is skipped without output_dir).
- **PageIndex URI migration**: Existing `pageindex://` URIs remain valid. New
  documents use `knowledge://pageindex/...`. A migration helper can update old
  URIs in a future FEAT.
- **ConceptType extension**: Consumers doing `match` on ConceptType must handle
  new variants. Pydantic validation rejects unknown types by default.

---

## Capabilities

### New Capabilities
- `graphindex-frontmatter-projection`: Project UniversalNode data as OKF-compatible
  YAML frontmatter in per-node `.md` sidecars.
- `graphindex-report-frontmatter`: Add OKF frontmatter to GRAPH_REPORT.md.
- `shared-okf-ontology`: Shared type vocabulary for cross-index OKF compatibility.
- `knowledge-uri-scheme`: Unified `knowledge://<index>/<id>` URI addressing.

### Modified Capabilities
- `okf-knowledge-layer` (FEAT-238): ConceptType and RelationType extended with
  graph-native values. Imports redirected through shared module.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `pageindex/okf/ontology.py` | refactors to → `knowledge/okf/ontology.py` | Types move; re-exports maintain compat |
| `pageindex/okf/frontmatter.py` | refactors to → `knowledge/okf/frontmatter.py` | Model + functions move; re-exports maintain compat |
| `pageindex/okf/__init__.py` | modifies | Adds re-exports from `knowledge.okf` |
| `graphindex/builder.py` | extends | New Stage 6.5 for projection |
| `graphindex/analytics.py` | modifies | `generate_report()` adds frontmatter header |
| `graphindex/__init__.py` | extends | Exports new projection functions |
| `ConceptType` enum | extends | +5 graph-native values |
| `RelationType` enum | extends | +3 graph edge kinds |
| Tests (FEAT-238) | modifies | Import paths updated (re-exports ensure no breakage) |

---

## Code Context

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/knowledge/graphindex/schema.py:70
class UniversalNode(BaseModel):
    node_id: str                                    # line 71
    kind: NodeKind                                  # line 72
    title: str                                      # line 73
    source_uri: str                                 # line 74
    content_ref: Optional[str] = None               # line 75
    summary: Optional[str] = None                   # line 76
    embedding_ref: Optional[str] = None             # line 77
    domain_tags: dict = Field(default_factory=dict) # line 78
    parent_id: Optional[str] = None                 # line 79
    provenance: Provenance = Provenance.EXTRACTED   # line 80

# From packages/ai-parrot/src/parrot/knowledge/graphindex/schema.py:32
class NodeKind(str, Enum):
    DOCUMENT = "document"   # line 33
    SECTION = "section"     # line 34
    SYMBOL = "symbol"       # line 35
    CONCEPT = "concept"     # line 36
    RATIONALE = "rationale" # line 37
    SKILL = "skill"         # line 38

# From packages/ai-parrot/src/parrot/knowledge/graphindex/schema.py:52
class EdgeKind(str, Enum):
    CONTAINS = "contains"     # line 53
    REFERENCES = "references" # line 54
    DEFINES = "defines"       # line 55
    MENTIONS = "mentions"     # line 56
    EXPLAINS = "explains"     # line 57

# From packages/ai-parrot/src/parrot/knowledge/pageindex/okf/ontology.py:21
class ConceptType(str, Enum):
    SECTION = "Section"         # line 22
    POLICY = "Policy"           # line 23
    CONTROL = "Control"         # line 24
    SAFEGUARD = "Safeguard"     # line 25
    EVIDENCE = "Evidence"       # line 26
    PLAYBOOK = "Playbook"       # line 27
    PROCEDURE = "Procedure"     # line 28
    STANDARD = "Standard"       # line 29
    FRAMEWORK = "Framework"     # line 30
    REGULATION = "Regulation"   # line 31
    GUIDELINE = "Guideline"     # line 32

# From packages/ai-parrot/src/parrot/knowledge/pageindex/okf/ontology.py:40
class RelationType(str, Enum):
    REFERENCES = "references"       # line 41
    MAPS_TO = "maps_to"             # line 42
    SATISFIES = "satisfies"         # line 43
    SATISFIED_BY = "satisfied_by"   # line 44
    SUPERSEDES = "supersedes"       # line 45
    SUPERSEDED_BY = "superseded_by" # line 46
    IMPLEMENTS = "implements"       # line 47
    PART_OF = "part_of"             # line 48

# From packages/ai-parrot/src/parrot/knowledge/pageindex/okf/frontmatter.py:30
class ConceptFrontmatter(BaseModel):
    type: ConceptType              # line 31
    title: str                     # line 32
    id: str                        # line 33
    node_id: str                   # line 34
    resource: str                  # line 35
    tags: list[str]                # line 36
    timestamp: str                 # line 37
    summary: str                   # line 38
    relates_to: list[RelatesTo]    # line 39
    source: Optional[SourceProvenance] = None  # line 40

# From packages/ai-parrot/src/parrot/knowledge/pageindex/okf/projection.py:39
class ProjectionReport(BaseModel):
    tree_name: str                                   # line 40
    nodes_projected: int = 0                         # line 41
    files_written: list[str] = Field(...)            # line 42
    old_files_removed: list[str] = Field(...)        # line 43

# From packages/ai-parrot/src/parrot/knowledge/graphindex/analytics.py:48
@dataclass
class AnalyticsResult:
    god_nodes: list[dict] = field(default_factory=list)           # line 49
    surprising_connections: list[dict] = field(default_factory=list) # line 50
    suggested_questions: list[str] = field(default_factory=list)  # line 51
    communities: Optional["CommunitiesResult"] = None             # line 52

# From packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py:54
class GraphIndexBuilder:
    def __init__(self, persistence, embedder, output_dir, ...)  # line 94
    async def build(self, sources: SourceConfig, ctx: TenantContext) -> BuildResult:  # line 122
    async def ingest_document(self, uri: str, ctx: TenantContext) -> IngestResult:    # line 245
    async def regenerate_report(self, ctx: TenantContext) -> Path:                    # line 304
```

#### Verified Imports
```python
# These imports have been confirmed to work:
from parrot.knowledge.pageindex.okf import ConceptType           # pageindex/okf/__init__.py
from parrot.knowledge.pageindex.okf import RelationType          # pageindex/okf/__init__.py
from parrot.knowledge.pageindex.okf import ConceptFrontmatter    # pageindex/okf/__init__.py
from parrot.knowledge.pageindex.okf import project_frontmatter   # pageindex/okf/__init__.py
from parrot.knowledge.pageindex.okf import parse_frontmatter     # pageindex/okf/__init__.py
from parrot.knowledge.pageindex.okf import RelatesTo             # pageindex/okf/__init__.py
from parrot.knowledge.pageindex.okf import SourceProvenance      # pageindex/okf/__init__.py
from parrot.knowledge.pageindex.okf import project_sidecars      # pageindex/okf/__init__.py
from parrot.knowledge.pageindex.okf import ProjectionReport      # pageindex/okf/__init__.py
from parrot.knowledge.graphindex import UniversalNode            # graphindex/__init__.py
from parrot.knowledge.graphindex import UniversalEdge            # graphindex/__init__.py
from parrot.knowledge.graphindex import NodeKind                 # graphindex/__init__.py
from parrot.knowledge.graphindex import EdgeKind                 # graphindex/__init__.py
from parrot.knowledge.graphindex import BuildResult              # graphindex/__init__.py
from parrot.knowledge.graphindex import GraphIndexLoader         # graphindex/__init__.py
```

#### Key Attributes & Constants
- `analytics.REPORT_FILENAME` → `"GRAPH_REPORT.md"` (analytics.py:40)
- `GraphIndexBuilder.output_dir` → `Path` (builder.py:103)
- `UniversalNode.domain_tags` → `dict` (schema.py:78)
- `UniversalNode.content_ref` → `Optional[str]` (schema.py:75)
- `ConceptFrontmatter.resource` → `str` (frontmatter.py:35)

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.knowledge.okf`~~ — shared OKF module does not exist yet (to be created)
- ~~`parrot.knowledge.graphindex.okf`~~ — no graphindex/okf/ directory exists
- ~~`parrot.knowledge.graphindex.projection`~~ — no projection module in graphindex
- ~~`ConceptType.SYMBOL`~~ — graph-native types not yet in ConceptType
- ~~`RelationType.DEFINES`~~ — graph edge kinds not yet in RelationType
- ~~`knowledge://` URI scheme~~ — not implemented anywhere; only `pageindex://` exists
- ~~`GraphIndexBuilder.project_sidecars()`~~ — no such method exists

---

## Parallelism Assessment

- **Internal parallelism**: Yes — tasks decompose into independent tracks:
  (1) shared module extraction + type extension, (2) GraphIndex projection layer,
  (3) report frontmatter, (4) URI scheme. Tracks 2-4 depend on track 1.
- **Cross-feature independence**: Touches `pageindex/okf/` (FEAT-238 complete) and
  `graphindex/builder.py` (no in-flight specs). Low conflict risk. FEAT-215 is
  discussion-only and not blocking.
- **Recommended isolation**: per-spec (all tasks sequential in one worktree)
- **Rationale**: Track 1 (shared module extraction) modifies the same files that
  tracks 2-4 consume. Sequential execution in one worktree avoids merge conflicts
  on the shared ontology module.

---

## Open Questions

- [ ] Should `pageindex://` URIs in existing FEAT-238 documents be migrated to
  `knowledge://pageindex/...` in this FEAT, or deferred to a migration FEAT? — *Owner: Jesus*
- [ ] Should the projected `.md` sidecars include the full node body text (from
  `content_ref` / `NodeContentStore`) or just frontmatter + summary? Full body
  would require loading from PageIndex storage. — *Owner: Jesus*
- [ ] Should `ConceptType` extension be additive-only (new values) or also rename
  existing values for consistency (e.g., `SECTION` exists in both NodeKind and

…(truncated)…
