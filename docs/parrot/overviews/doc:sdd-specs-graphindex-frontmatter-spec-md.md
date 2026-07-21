---
type: Wiki Overview
title: 'Feature Specification: GraphIndex OKF Frontmatter Projection'
id: doc:sdd-specs-graphindex-frontmatter-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: FEAT-238 (OKF Knowledge Layer) made PageIndex sidecars self-describing by
relates_to:
- concept: mod:parrot.knowledge.graphindex
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.projection
  rel: mentions
- concept: mod:parrot.knowledge.okf
  rel: mentions
- concept: mod:parrot.knowledge.okf.ontology
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.okf
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: GraphIndex OKF Frontmatter Projection

**Feature ID**: FEAT-239
**Date**: 2026-06-16
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.next
**Brainstorm**: `sdd/proposals/graphindex-frontmatter.brainstorm.md`

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-238 (OKF Knowledge Layer) made PageIndex sidecars self-describing by
projecting deterministic YAML frontmatter onto every `.md` document. Each
PageIndex node now carries `type`, `title`, `id`, `resource`, `summary`,
`relates_to`, and `source` in its frontmatter — fully compatible with OKF v0.1
and the LLM-Wiki pattern (Karpathy).

GraphIndex has no equivalent. Its only markdown output is `GRAPH_REPORT.md`
(analytics summary), which has no frontmatter. The rich `UniversalNode` data
(6 node kinds, 5 edge kinds, signal relevance scores, community membership)
lives exclusively in ArangoDB and is invisible to agents or tools that consume
plain markdown files.

Three consequences:

1. **GraphIndex output is not OKF-compatible.** An agent reading
   `GRAPH_REPORT.md` gets a bare markdown table — no structured metadata,
   no type, no resource URI.
2. **No node-level markdown export.** Unlike PageIndex (which projects
   per-node `.md` sidecars), GraphIndex cannot export its nodes as
   self-describing documents.
3. **Cross-index discovery is fractured.** PageIndex uses `pageindex://`
   URIs, GraphIndex uses ArangoDB `_key` references. There is no unified
   addressing scheme for cross-index linking.

### Goals

- G1: Project every `UniversalNode` as an OKF-compatible `.md` sidecar with
  YAML frontmatter during `build_graph()`.
- G2: Add OKF frontmatter to `GRAPH_REPORT.md`.
- G3: Extract shared OKF type vocabulary into `parrot/knowledge/okf/` so
  both PageIndex and GraphIndex import from one source.
- G4: Extend `ConceptType` with graph-native types and unify the shared
  `SECTION` value with aliases.
- G5: Introduce a `knowledge://<index>/<id>` URI scheme for cross-index
  references.
- G6: When a node has a `content_ref` pointing to PageIndex storage, include
  the full body text in the sidecar (not just the summary).

### Non-Goals (explicitly out of scope)

- Migrating existing `pageindex://` URIs to `knowledge://` — deferred to
  a future FEAT.
- OKF bundle export (tarball/directory interchange) — covered by FEAT-215 G4.
- Runtime fallback-on-failure was rejected in brainstorm — see
  `proposals/graphindex-frontmatter.brainstorm.md` Option C.
- Formal RFC registration of the `knowledge://` URI scheme — project-internal
  convention is sufficient for now.

---

## 2. Architectural Design

### Overview

**Selected approach**: Option A from the brainstorm — Shared OKF Core Module
+ GraphIndex Projection.

Extract the OKF type vocabulary (`ConceptType`, `RelationType`, `RelatesTo`,
`SourceProvenance`) and frontmatter engine (`ConceptFrontmatter`,
`project_frontmatter`, `parse_frontmatter`) into a new shared module at
`parrot/knowledge/okf/`. Both PageIndex and GraphIndex import from there.
GraphIndex adds its own `projection.py` that maps `UniversalNode` →
`ConceptFrontmatter` → `.md` sidecar.

`ConceptType` is extended with 5 graph-native values: `SYMBOL`, `RATIONALE`,
`SKILL`, `CONCEPT_NODE`, `DOCUMENT_NODE`. The shared `SECTION` value is
unified via aliases so `NodeKind.SECTION` and `ConceptType.SECTION` resolve
identically. `RelationType` gains 3 graph edge kinds: `DEFINES`, `MENTIONS`,
`EXPLAINS`.

A new `knowledge://` URI module provides `build_uri(index, id)` and
`parse_uri(uri)` for cross-index addressing.

Sidecars include the full node body when a `content_ref` resolves to PageIndex
storage. If content_ref is absent or unresolvable, the body falls back to the
node summary.

### Component Diagram

```
parrot/knowledge/okf/                    ← NEW shared module
├── __init__.py
├── ontology.py                          ← ConceptType (extended), RelationType (extended),
│                                           RelatesTo, SourceProvenance
├── frontmatter.py                       ← ConceptFrontmatter, project_frontmatter,
│                                           parse_frontmatter (moved from pageindex/okf/)
└── uri.py                               ← build_uri(), parse_uri()

parrot/knowledge/pageindex/okf/
├── __init__.py                          ← re-exports from knowledge.okf for backwards compat
├── ontology.py                          ← THIN: imports + re-exports from knowledge.okf
├── frontmatter.py                       ← THIN: imports + re-exports from knowledge.okf
├── concept_id.py                        (unchanged)
├── projection.py                        (unchanged — imports updated to knowledge.okf)
├── graph.py                             (unchanged)
├── tools.py                             (unchanged)
└── migrate.py                           (unchanged)

parrot/knowledge/graphindex/
├── projection.py                        ← NEW: project_graph_sidecars(),
│                                           project_node_sidecar(),
│                                           project_report_frontmatter(),
│                                           node_to_frontmatter_dict()
├── builder.py                           ← MODIFIED: Stage 6.5 calls projection
├── analytics.py                         ← MODIFIED: generate_report() prepends frontmatter
└── (rest unchanged)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `pageindex/okf/ontology.py` | refactors → `knowledge/okf/ontology.py` | Types move; thin re-export shim stays |
| `pageindex/okf/frontmatter.py` | refactors → `knowledge/okf/frontmatter.py` | Model + functions move; thin re-export shim stays |
| `pageindex/okf/__init__.py` | modifies | Adds re-exports from `knowledge.okf` |
| `graphindex/builder.py` | extends | New Stage 6.5 for projection |
| `graphindex/analytics.py` | modifies | `generate_report()` prepends frontmatter |
| `graphindex/__init__.py` | extends | Exports projection functions |
| `pageindex/okf/projection.py` | modifies (imports only) | Update import paths to `knowledge.okf` |
| FEAT-238 tests | modifies (imports only) | Re-exports ensure no breakage |

### Data Models

#### ConceptType (extended)

```python
# parrot/knowledge/okf/ontology.py
class ConceptType(str, Enum):
    # --- Existing PageIndex types (unchanged values) ---
    SECTION = "Section"
    POLICY = "Policy"
    CONTROL = "Control"
    SAFEGUARD = "Safeguard"
    EVIDENCE = "Evidence"
    PLAYBOOK = "Playbook"
    PROCEDURE = "Procedure"
    STANDARD = "Standard"
    FRAMEWORK = "Framework"
    REGULATION = "Regulation"
    GUIDELINE = "Guideline"
    # --- New graph-native types ---
    SYMBOL = "Symbol"
    RATIONALE = "Rationale"
    SKILL = "Skill"
    CONCEPT_NODE = "Concept"
    DOCUMENT_NODE = "Document"
```

The shared `SECTION` value is the same enum member used by both NodeKind
and ConceptType contexts — no alias needed since both sides already use
`SECTION`.

#### RelationType (extended)

```python
# parrot/knowledge/okf/ontology.py
class RelationType(str, Enum):
    # --- Existing ---
    REFERENCES = "references"
    MAPS_TO = "maps_to"
    SATISFIES = "satisfies"
    SATISFIED_BY = "satisfied_by"
    SUPERSEDES = "supersedes"
    SUPERSEDED_BY = "superseded_by"
    IMPLEMENTS = "implements"
    PART_OF = "part_of"
    # --- New graph edge kinds ---
    DEFINES = "defines"
    MENTIONS = "mentions"
    EXPLAINS = "explains"
    CONTAINS = "contains"
```

#### NodeKind → ConceptType Mapping

```python
# parrot/knowledge/graphindex/projection.py
NODE_KIND_TO_CONCEPT_TYPE: dict[NodeKind, ConceptType] = {
    NodeKind.DOCUMENT: ConceptType.DOCUMENT_NODE,
    NodeKind.SECTION: ConceptType.SECTION,        # shared value — direct mapping
    NodeKind.SYMBOL: ConceptType.SYMBOL,
    NodeKind.CONCEPT: ConceptType.CONCEPT_NODE,
    NodeKind.RATIONALE: ConceptType.RATIONALE,
    NodeKind.SKILL: ConceptType.SKILL,
}
```

#### EdgeKind → RelationType Mapping

```python
# parrot/knowledge/graphindex/projection.py
EDGE_KIND_TO_RELATION_TYPE: dict[EdgeKind, RelationType] = {
    EdgeKind.CONTAINS: RelationType.CONTAINS,
    EdgeKind.REFERENCES: RelationType.REFERENCES,  # shared value
    EdgeKind.DEFINES: RelationType.DEFINES,
    EdgeKind.MENTIONS: RelationType.MENTIONS,
    EdgeKind.EXPLAINS: RelationType.EXPLAINS,
}
```

#### knowledge:// URI Functions

```python
# parrot/knowledge/okf/uri.py
def build_uri(index_type: str, identifier: str) -> str:
    """Build a knowledge:// URI. E.g. build_uri("graphindex", "node-123")
    → "knowledge://graphindex/node-123"."""

def parse_uri(uri: str) -> tuple[str, str]:
    """Parse a knowledge:// URI into (index_type, identifier).
    Also accepts legacy pageindex:// URIs (maps to index_type="pageindex").
    Raises ValueError for unrecognised schemes."""
```

#### GraphProjectionReport

```python
# parrot/knowledge/graphindex/projection.py
class GraphProjectionReport(BaseModel):
    output_dir: str
    nodes_projected: int = 0
    files_written: list[str] = Field(default_factory=list)
    report_frontmatter_added: bool = False
```

### New Public Interfaces

```python
# parrot/knowledge/graphindex/projection.py

def node_to_frontmatter_dict(
    node: UniversalNode,
    edges: list[UniversalEdge],
) -> dict:
    """Convert a UniversalNode + its outgoing edges into the dict format
    expected by project_frontmatter(). Pure function, no I/O."""

def project_node_sidecar(
    node: UniversalNode,
    edges: list[UniversalEdge],
    body: str,
) -> str:
    """Return the complete sidecar text: frontmatter + body."""

async def project_graph_sidecars(
    nodes: list[UniversalNode],
    edges: list[UniversalEdge],
    output_dir: Path,
    content_store: Optional[NodeContentStore] = None,
    pageindex_toolkit: Optional[PageIndexToolkit] = None,
) -> GraphProjectionReport:
    """Write per-node .md sidecars to output_dir/nodes/. If content_store
    or pageindex_toolkit is available, resolve content_ref to full body."""

def project_report_frontmatter(
    analytics: AnalyticsResult,
    tenant_id: str,
) -> str:
    """Return frontmatter YAML string for GRAPH_REPORT.md."""
```

```python
# parrot/knowledge/okf/uri.py

def build_uri(index_type: str, identifier: str) -> str: ...
def parse_uri(uri: str) -> tuple[str, str]: ...
```

---

## 3. Module Breakdown

### Module 1: Shared OKF Ontology (`knowledge/okf/ontology.py`)

- **Path**: `packages/ai-parrot/src/parrot/knowledge/okf/ontology.py`
- **Responsibility**: Single source of truth for OKF type vocabulary.
  Contains `ConceptType` (16 values), `RelationType` (12 values),
  `RelatesTo`, `SourceProvenance`. Moved from `pageindex/okf/ontology.py`
  and extended with graph-native types.
- **Depends on**: nothing (leaf module)

### Module 2: Shared OKF Frontmatter (`knowledge/okf/frontmatter.py`)

- **Path**: `packages/ai-parrot/src/parrot/knowledge/okf/frontmatter.py`
- **Responsibility**: `ConceptFrontmatter` model, `project_frontmatter()`,
  `parse_frontmatter()`. Moved from `pageindex/okf/frontmatter.py`. No
  changes to logic — only import paths updated.
- **Depends on**: Module 1

### Module 3: Knowledge URI Scheme (`knowledge/okf/uri.py`)

- **Path**: `packages/ai-parrot/src/parrot/knowledge/okf/uri.py`
- **Responsibility**: `build_uri()` and `parse_uri()` for
  `knowledge://<index>/<id>` URIs. Also parses legacy `pageindex://` URIs.
- **Depends on**: nothing (leaf module)

### Module 4: PageIndex OKF Re-export Shims

- **Paths**:
  - `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/__init__.py`
  - `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/ontology.py`
  - `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/frontmatter.py`
- **Responsibility**: Backwards-compatible re-exports from `knowledge.okf`.
  Existing consumers (`from parrot.knowledge.pageindex.okf import
  ConceptType`) continue to work unchanged.
- **Depends on**: Modules 1, 2

### Module 5: GraphIndex Projection (`graphindex/projection.py`)

- **Path**: `packages/ai-parrot/src/parrot/knowledge/graphindex/projection.py`
- **Responsibility**: `node_to_frontmatter_dict()`,
  `project_node_sidecar()`, `project_graph_sidecars()`,
  `project_report_frontmatter()`, `GraphProjectionReport`.
  Maps `UniversalNode` → `ConceptFrontmatter` → `.md` sidecar.
  Resolves `content_ref` to full body when possible.
- **Depends on**: Modules 1, 2, 3

### Module 6: Builder + Analytics Integration

- **Paths**:
  - `packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py`
  - `packages/ai-parrot/src/parrot/knowledge/graphindex/analytics.py`
- **Responsibility**: Insert Stage 6.5 (projection) into
  `GraphIndexBuilder.build()`. Update `generate_report()` to prepend
  frontmatter via `project_report_frontmatter()`.
- **Depends on**: Module 5

### Module 7: Tests

- **Paths**:
  - `packages/ai-parrot/tests/knowledge/graphindex/test_projection.py`
  - `packages/ai-parrot/tests/knowledge/okf/test_ontology.py`
  - `packages/ai-parrot/tests/knowledge/okf/test_uri.py`
  - `packages/ai-parrot/tests/knowledge/okf/test_frontmatter.py`
- **Responsibility**: Unit tests for all new code. Re-run FEAT-238 tests
  to confirm backwards compatibility via re-exports.
- **Depends on**: Modules 1–6

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_concept_type_has_graph_values` | Module 1 | ConceptType includes SYMBOL, RATIONALE, SKILL, CONCEPT_NODE, DOCUMENT_NODE |
| `test_relation_type_has_graph_values` | Module 1 | RelationType includes DEFINES, MENTIONS, EXPLAINS, CONTAINS |
| `test_concept_type_section_unified` | Module 1 | ConceptType.SECTION is usable for both graph and page contexts |
| `test_build_uri` | Module 3 | `build_uri("graphindex", "node-1")` → `"knowledge://graphindex/node-1"` |
| `test_parse_uri_knowledge` | Module 3 | `parse_uri("knowledge://graphindex/node-1")` → `("graphindex", "node-1")` |
| `test_parse_uri_legacy_pageindex` | Module 3 | `parse_uri("pageindex://tree/node")` → `("pageindex", "tree/node")` |
| `test_parse_uri_invalid_scheme` | Module 3 | Raises `ValueError` for unknown scheme |
| `test_re_export_concept_type` | Module 4 | `from parrot.knowledge.pageindex.okf import ConceptType` still works |
| `test_re_export_project_frontmatter` | Module 4 | `from parrot.knowledge.pageindex.okf import project_frontmatter` still works |
| `test_node_to_frontmatter_dict` | Module 5 | Correct mapping from UniversalNode fields |
| `test_node_to_frontmatter_dict_no_summary` | Module 5 | Falls back to title when summary is None |
| `test_project_node_sidecar` | Module 5 | YAML frontmatter + body combined correctly |
| `test_project_node_sidecar_byte_determinism` | Module 5 | Same input → identical output |
| `test_project_graph_sidecars_writes_files` | Module 5 | Files written to output_dir/nodes/ |
| `test_project_graph_sidecars_with_content_ref` | Module 5 | Full body loaded from content_store when content_ref is present |
| `test_project_graph_sidecars_content_ref_missing` | Module 5 | Falls back to summary when content_ref is unresolvable |
| `test_project_report_frontmatter` | Module 5 | Valid YAML with type=Document |
| `test_report_frontmatter_in_generate_report` | Module 6 | GRAPH_REPORT.md starts with `---` frontmatter |
| `test_build_includes_projection_stage` | Module 6 | build() writes sidecar files when output_dir is set |
| `test_build_skips_projection_without_output_dir` | Module 6 | No sidecars when output_dir is None |

### Integration Tests

| Test | Description |
|---|---|
| `test_feat238_tests_still_pass` | Run existing FEAT-238 test suite — all 20 tests pass with re-export shims |
| `test_full_build_with_projection` | End-to-end: extract → embed → persist → analytics → project sidecars |
| `test_sidecar_round_trip` | Project a node to .md, parse its frontmatter back, verify fields match |
| `test_cross_index_uri_round_trip` | `build_uri` → `parse_uri` → `build_uri` preserves identity |

### Test Data / Fixtures

```python
@pytest.fixture
def sample_nodes() -> list[UniversalNode]:
    return [
        UniversalNode(
            node_id="sym-builder-abc",
            kind=NodeKind.SYMBOL,
            title="GraphIndexBuilder",
            source_uri="file:///src/builder.py",
            summary="Orchestrates the 6-stage graph build pipeline.",
            domain_tags={"categories": ["python", "builder"]},
        ),
        UniversalNode(
            node_id="doc-readme-xyz",
            kind=NodeKind.DOCUMENT,
            title="README",
            source_uri="file:///README.md",
            content_ref="pageindex://docs/readme-node",
            summary="Project documentation root.",
        ),
    ]

@pytest.fixture
def sample_edges() -> list[UniversalEdge]:
    return [
        UniversalEdge(
            source_id="sym-builder-abc",
            target_id="doc-readme-xyz",
            kind=EdgeKind.REFERENCES,
        ),
    ]
```

---

## 5. Acceptance Criteria

- [ ] `ConceptType` enum contains all 16 values (11 existing + 5 new graph-native)
- [ ] `RelationType` enum contains all 12 values (8 existing + 4 new graph edge kinds)
- [ ] `ConceptType.SECTION` works in both graph and page contexts (unified alias)
- [ ] `from parrot.knowledge.pageindex.okf import ConceptType` still works (re-export)
- [ ] `from parrot.knowledge.pageindex.okf import project_frontmatter` still works
- [ ] All 20 FEAT-238 tests pass without modification (backwards compatibility)
- [ ] `build_uri("graphindex", "node-1")` returns `"knowledge://graphindex/node-1"`
- [ ] `parse_uri()` handles both `knowledge://` and legacy `pageindex://` URIs
- [ ] `project_graph_sidecars()` writes per-node `.md` files to `output_dir/nodes/`
- [ ] Each sidecar has valid YAML frontmatter parseable by `parse_frontmatter()`
- [ ] Sidecar body contains full text from `content_ref` when resolvable, else summary
- [ ] Sidecars are byte-deterministic (same input → same output)
- [ ] `GRAPH_REPORT.md` starts with OKF YAML frontmatter
- [ ] `GraphIndexBuilder.build()` includes projection stage (Stage 6.5) when `output_dir` is set
- [ ] Build skips projection when `output_dir` is not configured
- [ ] No breaking changes to existing GraphIndex public API
- [ ] All new unit tests pass: `pytest tests/knowledge/okf/ tests/knowledge/graphindex/test_projection.py -v`

---

## 6. Codebase Contract

### Verified Imports

```python
# These imports have been confirmed to work (2026-06-16):
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

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/knowledge/graphindex/schema.py
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

class UniversalEdge(BaseModel):                     # line 101
    source_id: str                                  # line 102
    target_id: str                                  # line 103
    kind: EdgeKind                                  # line 104
    provenance: Provenance = Provenance.EXTRACTED   # line 105
    confidence: Optional[float] = None              # line 106

class NodeKind(str, Enum):                          # line 32
    DOCUMENT = "document"                           # line 33
    SECTION = "section"                             # line 34
    SYMBOL = "symbol"                               # line 35
    CONCEPT = "concept"                             # line 36
    RATIONALE = "rationale"                         # line 37
    SKILL = "skill"                                 # line 38

class EdgeKind(str, Enum):                          # line 52
    CONTAINS = "contains"                           # line 53
    REFERENCES = "references"                       # line 54
    DEFINES = "defines"                             # line 55
    MENTIONS = "mentions"                           # line 56
    EXPLAINS = "explains"                           # line 57

class BuildResult(BaseModel):                       # line 162
    tenant_id: str
    node_count: int = 0
    edge_count: int = 0
    inferred_edge_count: int = 0
    report_path: Optional[Path] = None
    errors: list[str] = Field(default_factory=list)

# packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py
class GraphIndexBuilder:                            # line 54
    def __init__(                                   # line 94
        self,
        persistence: GraphIndexPersistence,
        embedder: GraphIndexEmbedder,
        output_dir: Path,
        ignore_file: Optional[Path] = None,
        resolution_config: Optional[ResolutionConfig] = None,
        pageindex_toolkit: Optional[PageIndexToolkit] = None,
        signal_config: Optional[SignalRelevanceConfig] = None,
        detect_communities_enabled: bool = False,
        community_resolution: float = 1.0,
    ) -> None: ...

    async def build(self, sources: SourceConfig, ctx: TenantContext) -> BuildResult:  # line 122
    async def ingest_document(self, uri: str, ctx: TenantContext) -> IngestResult:    # line 245
    async def regenerate_report(self, ctx: TenantContext) -> Path:                    # line 304

# packages/ai-parrot/src/parrot/knowledge/graphindex/analytics.py
REPORT_FILENAME = "GRAPH_REPORT.md"                 # line 40

@dataclass
class AnalyticsResult:                              # line 48
    god_nodes: list[dict]                           # line 49
    surprising_connections: list[dict]               # line 50
    suggested_questions: list[str]                   # line 51
    communities: Optional["CommunitiesResult"]       # line 52

def generate_report(                                # line 268
    analytics: AnalyticsResult,
    output_dir: Path,
    llm_polish: bool = False,
) -> Path: ...

def _render_report(analytics: AnalyticsResult) -> str:  # line 300

# packages/ai-parrot/src/parrot/knowledge/pageindex/okf/ontology.py
class ConceptType(str, Enum):                       # line 21
    SECTION = "Section"                             # line 22

…(truncated)…
