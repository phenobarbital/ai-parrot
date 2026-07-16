---
type: Wiki Overview
title: 'Feature Specification: OKF Knowledge Layer over PageIndex'
id: doc:sdd-specs-okf-knowledge-layer-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: PageIndex sidecars are **bare markdown** — a node body file (e.g. `0043.md`)
  does
relates_to:
- concept: mod:parrot.knowledge.pageindex.content_store
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.okf
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.store
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.tree_ops
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.utils
  rel: mentions
- concept: mod:parrot.loaders.abstract
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: OKF Knowledge Layer over PageIndex

**Feature ID**: FEAT-238
**Date**: 2026-06-15
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.next
**Related**: FEAT-199 (pageindex-embedding-router), FEAT-150 (matryoshka)

---

## 1. Motivation & Business Requirements

### Problem Statement

PageIndex sidecars are **bare markdown** — a node body file (e.g. `0043.md`) does
not describe itself. Its `type`, `title`, identity, and provenance all live in the
JSON ToC, *separate* from the body. Three things follow:

1. **Nodes are not self-describing artifacts.** A sidecar cannot be read, shared, or
   reasoned about in isolation; it is meaningless without the JSON index.
2. **There is no knowledge graph.** Inter-document references exist only as prose; the
   markdown hyperlinks between sections/documents are not resolved into navigable edges.
3. **Multi-hop retrieval is impossible.** The `ComplianceEvidenceAgent`'s natural queries
   are traversals — "which NIST 800-53 control satisfies this HIPAA safeguard, and what
   evidence proves it" — which flat per-document retrieval cannot answer.

### Goals

- Enrich the **authoritative JSON node** with OKF fields (`concept_id`, `type`,
  `source`, `relates_to`).
- Write a **deterministic frontmatter mirror** onto each sidecar (and an `index.md`
  view) as pure projections of the JSON — single-writer, regenerated on rebuild, so
  drift is structurally impossible.
- Resolve markdown hyperlinks + typed `relates_to` edges into an **in-memory knowledge
  graph** keyed by stable `concept_id`.
- Ship an **`okf-migrate`** command to retrofit existing trees.
- Expose typed retrieval/traversal **read tools** (`find_by_type`, `get_related`,
  `trace_mapping`, etc.) that enable multi-hop compliance queries.

### Non-Goals (explicitly out of scope)

- **Not** making frontmatter authoritative (D1 — JSON stays the source of truth).
- **Not** materializing the graph in ArangoDB (D4 — phase 2).
- **Not** building the thematic folder layout or per-folder `index.md` (D7 — phase 2).
- **Not** the LLM maintenance loop (ingest → query → lint write-back, contradiction
  reconciliation). Autonomous mutation of knowledge is a separate concern gated
  through the HITL suite.
- **Not** adopting OKF as the internal model — OKF is a boundary projection /
  interchange format; the internal representation stays the PageIndex tree + `Document`.
- Runtime fallback-on-failure was not explored — see `sdd/proposals/okf-knowledge-layer.brainstorm.md` for design rationale.

---

## 2. Architectural Design

### Overview

This feature adds an OKF-compatible knowledge layer over PageIndex. The design
follows the brainstorm's recommended approach: **JSON authoritative; frontmatter +
`index.md` are deterministic projections** (D1).

Key principles:

- **`concept_id` (stable slug) ≠ `node_id` (volatile position).** Links target
  `concept_id`; the resolver joins by `concept_id`, never `node_id` (D3).
- **Sidecar filename is `<concept_id>.md`** (D8). Content refs become
  `pageindex://<tree>/<concept_id>`.
- **`type` is a controlled ontological vocabulary; `tags` remain free namespaces** (D9).
- **Graph is implicit, resolved in memory** from hyperlinks + `relates_to` (D4).
- **Typed edges as an OKF-tolerant superset** (`relates_to`) supporting
  `maps_to` / `satisfies` / `supersedes` (D5).
- **Migrate resolves only explicit markdown links** into `relates_to` (D10);
  LLM-inferred edges deferred to HITL-gated pass.
- **Frontmatter `summary` reuses the FEAT-199 embedding target text** (D11) —
  one embedding target, one source of truth, zero divergence.
- **Determinism by construction.** Frontmatter and `index.md` are pure functions of
  the authoritative JSON. Regenerating from the same JSON MUST produce byte-identical
  output.

### Enriched Node Schema (authoritative, in JSON)

```jsonc
{
  "node_id": "0043",                          // volatile structural position
  "concept_id": "playbooks/aws-incident-response", // STABLE identity + link target + filename
  "type": "Playbook",                          // LLM-classified once; content-addressed cache
  "title": "AWS Incident Response and Compliance Playbook",
  "summary": "Incident-response steps aligned to CC7.x ...",
  "source": {
    "document": "AICPA_SOC2_Compliance_Guide_on_AWS.pdf",
    "pages": [43, 47],
    "url": "https://..."
  },
  "relates_to": [
    { "concept": "controls/nist-800-53-ir-4", "rel": "maps_to" }
  ],
  "nodes": [ /* children */ ]
}
```

### Frontmatter Projection (deterministic mirror)

```yaml
---
type: Playbook
title: AWS Incident Response and Compliance Playbook
id: playbooks/aws-incident-response
node_id: "0043"
resource: pageindex://soc2_hipaa/playbooks/aws-incident-response
tags: [soc2, aws, incident-response]
timestamp: 2026-06-15T00:00:00Z
summary: >-
  Incident-response steps aligned to CC7.x ...
relates_to:
  - concept: controls/nist-800-53-ir-4
    rel: maps_to
---
```

### Component Diagram

```
                ┌──────────────────────────────────────────────────────────┐
                │                   PageIndexToolkit                        │
                │                                                          │
                │   insert_content ──→ type classification (T3 step)       │
                │   import_pdf    ──→ type classification (T3 step)        │
                │   _persist()    ──→ projection.project_sidecars()        │
                │                                                          │
                └──────────────────┬───────────────────────────────────────┘
                                   │
          ┌────────────────────────┼────────────────────────────────────┐
          │                        │                                    │
          ▼                        ▼                                    ▼
  ┌───────────────┐     ┌──────────────────┐              ┌─────────────────┐
  │  ontology.py  │     │  concept_id.py   │              │ frontmatter.py  │
  │  (type enum)  │     │  (slug + dedup)  │              │ (Pydantic model │
  │               │     │                  │              │  + projection)  │
  └───────┬───────┘     └────────┬─────────┘              └────────┬────────┘
          │                      │                                 │
          └──────────┬───────────┘                                 │
                     │                                             │
                     ▼                                             ▼
          ┌──────────────────┐                          ┌──────────────────┐
          │   projection.py  │                          │  NodeContentStore│
          │  (sidecars +     │──────────────────────────│  .save() writes  │
          │   index.md)      │                          │  <concept_id>.md │
          └────────┬─────────┘                          └──────────────────┘
                   │
                   ▼
          ┌──────────────────┐        ┌──────────────────┐
          │    graph.py      │───────▶│   tools.py       │
          │  (in-memory adj  │        │  find_by_type    │
          │   by concept_id) │        │  get_concept     │
          │                  │        │  get_related     │
          └──────────────────┘        │  trace_mapping   │
                                      │  list_concepts   │
                                      │  cite            │
                                      └──────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `NodeContentStore` (`content_store.py`) | **edit** | Save now writes `<concept_id>.md` with projected frontmatter + body (was `<node_id>.md` bare markdown) |
| `JSONTreeStore` (`store.py`) | **transparent** | No changes needed — it serializes the tree dict as-is; new OKF fields persist automatically |
| `PageIndexToolkit` (`toolkit.py`) | **edit** | Ingest methods gain a T3 type-classification step; `_persist()` triggers sidecar projection; new read tools registered |
| `tree_ops.py` (`reindex_node_ids` / `splice_subtree` / `delete_node`) | **edit** | Must preserve `concept_id` through reindex; trigger re-projection on mutation |
| `utils.py` (`find_node_by_id` / `get_nodes`) | **reuse** | Used by projection + graph build for tree walks |
| `_strip_keys_in_place` (`toolkit.py:897`) | **no change** | Only strips `(token_count, line_num)` — new OKF fields survive |
| FEAT-199 `NodeEmbeddingStore` / `content_key` | **reuse** | Content-addressing pattern for the type classification cache; shared `summary` target text (D11) |
| `PageIndexLoader` (`loader.py`) | **no change now** | Phase-2 `OKFLoader` will extend `AbstractLoader` (same pattern) |

### Data Models

```python
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class ConceptType(str, Enum):
    """Controlled ontological vocabulary for OKF node types (D9)."""
    SECTION = "Section"          # structural fallback
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


class RelationType(str, Enum):
    """Typed edge vocabulary (OKF-superset, D5)."""
    REFERENCES = "references"       # untyped prose link fallback
    MAPS_TO = "maps_to"
    SATISFIES = "satisfies"
    SATISFIED_BY = "satisfied_by"
    SUPERSEDES = "supersedes"
    SUPERSEDED_BY = "superseded_by"
    IMPLEMENTS = "implements"
    PART_OF = "part_of"


class RelatesTo(BaseModel):
    """A typed edge in the knowledge graph."""
    concept: str = Field(..., description="Target concept_id")
    rel: RelationType = Field(default=RelationType.REFERENCES)


class SourceProvenance(BaseModel):
    """Per-node provenance, citable."""
    document: str = Field(..., description="Source document filename")
    pages: Optional[list[int]] = Field(default=None, description="[start_page, end_page]")
    url: Optional[str] = Field(default=None, description="Source URL if available")


class ConceptFrontmatter(BaseModel):
    """Pydantic v2 model for the deterministic frontmatter projection."""
    type: ConceptType
    title: str
    id: str = Field(..., description="concept_id — stable link target")
    node_id: str = Field(..., description="Mirrored for debugging; NOT a link target")
    resource: str = Field(..., description="pageindex://<tree>/<concept_id>")
    tags: list[str] = Field(default_factory=list)
    timestamp: str
    summary: str = Field(..., description="Reuses FEAT-199 embedding target text (D11)")
    relates_to: list[RelatesTo] = Field(default_factory=list)
    source: Optional[SourceProvenance] = None
```

### New Public Interfaces

```python
# --- concept_id.py ---
def derive_concept_id(title: str, parent_path: str = "") -> str:
    """Deterministic slug from title, scoped under parent_path."""
    ...

def dedup_concept_ids(nodes: list[dict]) -> None:
    """Resolve slug collisions with numeric suffixes (stable across runs)."""
    ...


# --- graph.py ---
class KnowledgeGraph:
    """In-memory adjacency keyed by concept_id."""

    def __init__(self, tree: dict) -> None: ...
    def neighbors(self, concept_id: str, rel: Optional[str] = None) -> list[dict]: ...
    def trace(self, concept_id: str, rel_chain: list[str]) -> list[list[str]]: ...
    def broken_links(self) -> list[str]: ...


# --- projection.py ---
def project_frontmatter(node: dict, tree_name: str) -> str:
    """Pure function: node → YAML frontmatter string (byte-deterministic)."""
    ...

def project_sidecars(tree: dict, tree_name: str, content_store: 'NodeContentStore') -> None:
    """Regenerate all sidecars from authoritative JSON."""
    ...

def generate_index_md(tree: dict, tree_name: str) -> str:
    """Root-level index.md view of the JSON ToC."""
    ...


# --- migrate.py ---
async def okf_migrate(
    tree_name: str,
    tree_store: 'JSONTreeStore',
    content_store: 'NodeContentStore',
    adapter: Any,
    *,
    force_reclassify: bool = False,
) -> dict:
    """Retrofit an existing tree with OKF fields. Returns migration report."""
    ...
```

---

## 3. Module Breakdown

### Module 1: `ontology.py` — Controlled Type Vocabulary
- **Path**: `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/ontology.py`
- **Responsibility**: `ConceptType` enum (compliance domain), `RelationType` enum,
  `SourceProvenance` and `RelatesTo` Pydantic models. Structural fallback `Section`
  when LLM classification is unavailable.
- **Depends on**: none (leaf module)

### Module 2: `concept_id.py` — Deterministic Slug Generation
- **Path**: `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/concept_id.py`
- **Responsibility**: `derive_concept_id(title, parent_path)` deterministic slug;
  `dedup_concept_ids(nodes)` numeric-suffix collision resolution; stable across runs.
- **Depends on**: none (leaf module)

### Module 3: `frontmatter.py` — Frontmatter Model & Projection
- **Path**: `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/frontmatter.py`
- **Responsibility**: `ConceptFrontmatter` Pydantic v2 model; `project(node) → yaml`
  pure function (field order fixed, values verbatim from JSON); parse/round-trip.
- **Depends on**: Module 1 (ontology)

### Module 4: `graph.py` — In-Memory Knowledge Graph
- **Path**: `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/graph.py`
- **Responsibility**: Parse markdown hyperlinks + `relates_to` from each node; build
  adjacency keyed by `concept_id`. Untyped prose links become `rel: references`;
  typed edges come from `relates_to`. Broken links tolerated and collected for lint.
  `KnowledgeGraph` class with `neighbors()`, `trace()`, `broken_links()`.
- **Depends on**: Module 1 (ontology), Module 2 (concept_id for keying)

### Module 5: `projection.py` — Deterministic Sidecar & Index Generation
- **Path**: `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/projection.py`
- **Responsibility**: `project_sidecars(tree, tree_name, content_store)` regenerates
  all sidecars (frontmatter + body) from authoritative JSON; `generate_index_md()`
  builds root-level `index.md` as deterministic listing of JSON ToC. Files are named
  `<concept_id>.md` (D8).
- **Depends on**: Module 1 (ontology), Module 3 (frontmatter), `NodeContentStore`

### Module 6: `migrate.py` — okf-migrate Command
- **Path**: `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/migrate.py`
- **Responsibility**: Retrofit existing trees — derive `concept_id`, classify `type`
  (LLM, content-addressed cache, structural fallback), build `source` from `doc_name`
  + page span, parse body markdown links → `relates_to`, rename sidecars
  `<node_id>.md` → `<concept_id>.md`, generate root `index.md`. Idempotent.
  Emits a migration report (nodes processed, type histogram, links resolved vs. broken,
  slug collisions).
- **Depends on**: Modules 1–5, `JSONTreeStore`, `NodeContentStore`, LLM adapter

### Module 7: `tools.py` — Named Read Tools
- **Path**: `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/tools.py`
- **Responsibility**: Separate named tools (D constraint — no branching `search`):
  `find_by_type(type, query)`, `list_concepts(type?)`, `get_concept(concept_id)`,
  `get_related(concept_id, rel?)`, `trace_mapping(concept_id)`, `cite(concept_id)`.
  Each exposes the controlled `type` enum in its schema. Type-scoped tools apply
  `type` as an **exact pre-filter** before ranking.
- **Depends on**: Module 1 (ontology), Module 4 (graph), `PageIndexToolkit` (search infra)

### Module 8: Integration Edits — `tree_ops.py`, `toolkit.py`, `content_store.py`
- **Path**: Existing files in `packages/ai-parrot/src/parrot/knowledge/pageindex/`
- **Responsibility**:
  - `tree_ops.py`: `reindex_node_ids` / `splice_subtree` / `delete_node` preserve
    `concept_id` through renumbering and trigger re-projection.
  - `toolkit.py`: Ingest methods (`insert_content`, `import_pdf`) gain a T3
    type-classification step after the Two-Step CoT; `_persist()` triggers
    `project_sidecars()`; new OKF read tools registered.
  - `content_store.py`: `_node_path()` and `_validate_node_id()` accept concept_id
    format (slash-containing slugs); sidecar lookup by concept_id.
- **Depends on**: Modules 1–7

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_concept_type_enum` | ontology | All expected types present; `Section` is fallback |
| `test_relation_type_enum` | ontology | All edge types present; `references` is default |
| `test_derive_concept_id_deterministic` | concept_id | Same title + parent → same slug always |
| `test_dedup_concept_ids` | concept_id | Numeric suffixes resolve collisions stably |
| `test_frontmatter_projection_deterministic` | frontmatter | Same node → byte-identical YAML output |
| `test_frontmatter_round_trip` | frontmatter | project → parse → project yields identical YAML |
| `test_graph_build_from_relates_to` | graph | Typed edges build correct adjacency |
| `test_graph_build_from_markdown_links` | graph | Prose links become `rel: references` |
| `test_graph_broken_links_tolerated` | graph | Missing targets collected, not fatal |
| `test_graph_trace_multi_hop` | graph | `trace(id, [maps_to, satisfied_by])` traverses correctly |
| `test_project_sidecars_byte_deterministic` | projection | Two runs on same JSON → identical files |
| `test_generate_index_md` | projection | Root index lists all top-level concepts with links |
| `test_sidecar_named_by_concept_id` | projection | Files are `<concept_id>.md`, not `<node_id>.md` |
| `test_migrate_idempotent` | migrate | Two runs on same tree → identical output |
| `test_migrate_type_content_addressed` | migrate | Same content → same type classification |
| `test_migrate_renames_sidecars` | migrate | `<node_id>.md` → `<concept_id>.md` |
| `test_migrate_report_histogram` | migrate | Report includes type histogram + link stats |
| `test_reindex_preserves_concept_id` | tree_ops | `reindex_node_ids` does not touch `concept_id` |
| `test_splice_preserves_concept_id` | tree_ops | `splice_subtree` keeps `concept_id` stable |
| `test_delete_preserves_concept_id` | tree_ops | `delete_node` on other nodes keeps `concept_id` |
| `test_strip_keys_spares_okf_fields` | toolkit | `_strip_keys_in_place` does not strip `concept_id` / `type` / `source` / `relates_to` |

### Integration Tests

| Test | Description |
|---|---|
| `test_ingest_with_type_classification` | `insert_content` → T3 step assigns `type` → sidecar has frontmatter |
| `test_import_pdf_full_pipeline` | PDF → build → enrich → sidecars with frontmatter + `source.pages` |
| `test_tools_find_by_type` | `find_by_type(Control, query)` returns only `Control`-typed nodes |
| `test_tools_get_related_typed` | `get_related(id, rel=maps_to)` returns correct edges |
| `test_tools_trace_mapping_multihop` | `trace_mapping` follows safeguard → control → evidence chain |
| `test_okf_conformance` | Every sidecar has parseable frontmatter with non-empty `type` |

### Test Data / Fixtures

```python
@pytest.fixture
def sample_tree():
    """A small tree with 3 nodes for unit testing projections."""
    return {
        "doc_name": "test_corpus",
        "structure": [
            {
                "node_id": "0000",
                "title": "HIPAA Security Rule",
                "summary": "Overview of HIPAA security safeguards",
                "start_index": 1,
                "end_index": 5,
                "nodes": [
                    {
                        "node_id": "0001",
                        "title": "Administrative Safeguards",
                        "summary": "Policies and procedures...",
                        "start_index": 2,
                        "end_index": 3,
                        "nodes": [],
                    }
                ],
            },
            {
                "node_id": "0002",
                "title": "NIST 800-53 IR-4",
                "summary": "Incident handling control",
                "start_index": 6,
                "end_index": 8,
                "nodes": [],
            },
        ],
    }


@pytest.fixture
def enriched_tree(sample_tree):
    """sample_tree with OKF fields applied (post-migration)."""
    # concept_ids, types, source, relates_to populated
    ...
```

---

## 5. Acceptance Criteria

- [ ] Every sidecar carries OKF-conformant frontmatter (non-empty `type`) that is a
  **byte-deterministic projection** of its JSON node; regenerating yields identical bytes.
- [ ] `concept_id` is stable across `reindex_node_ids` / `splice_subtree` / `delete_node`;
  links and the in-memory graph resolve by `concept_id` only.
- [ ] The in-memory graph is built from hyperlinks + `relates_to` with **no ArangoDB
  dependency**; broken links are tolerated and reported, never fatal.
- [ ] A root `index.md` is generated as a deterministic view of the JSON ToC.
- [ ] `okf-migrate` rewrites all existing trees **idempotently** and emits a report.
- [ ] `type` classification is content-addressed → migration/rebuild is reproducible.
- [ ] The resulting bundle passes an OKF v0.1 conformance check (parseable frontmatter,
  non-empty `type`, unknown types/keys tolerated, broken links tolerated).
- [ ] The §2 tools are **separate named tools** exposing the controlled `type` enum;
  type-scoped tools apply `type` as an **exact pre-filter** (deterministic gate) before
  ranking; sensitive-`type` access is enforced in the execution layer, not the tool.
- [ ] `_strip_keys_in_place` does not strip `concept_id` / `type` / `source` / `relates_to`.
- [ ] All unit tests pass (`pytest tests/unit/ -v`)
- [ ] All integration tests pass (`pytest tests/integration/ -v`)
- [ ] No breaking changes to existing `PageIndexToolkit` public API.
- [ ] `insert_content` / `import_pdf` continue to work without OKF enrichment when
  LLM classification is unavailable (structural fallback to `Section`).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports

```python
from parrot.knowledge.pageindex.content_store import NodeContentStore  # verified: content_store.py:37
from parrot.knowledge.pageindex.store import JSONTreeStore             # verified: store.py:23
from parrot.knowledge.pageindex.tree_ops import reindex_node_ids       # verified: tree_ops.py:16
from parrot.knowledge.pageindex.tree_ops import splice_subtree         # verified: tree_ops.py:45
from parrot.knowledge.pageindex.tree_ops import delete_node            # verified: tree_ops.py:81
from parrot.knowledge.pageindex.utils import find_node_by_id           # verified: utils.py:308
from parrot.knowledge.pageindex.utils import get_nodes                 # verified: utils.py:231
from parrot.knowledge.pageindex.utils import write_node_id             # verified: utils.py:217
from parrot.loaders.abstract import AbstractLoader                     # verified: loader.py:28 (phase-2 OKFLoader base)
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py
class NodeContentStore:
    def __init__(self, storage_dir: str | Path, cache_size: int = 256) -> None:  # line 54
    def save(self, tree_name: str, node_id: str, markdown: str) -> None:          # line 116
    def load(self, tree_name: str, node_id: str) -> Optional[str]:                # line 123
    def has(self, tree_name: str, node_id: str) -> bool:                          # line 142
    def delete_node(self, tree_name: str, node_id: str) -> bool:                  # line 148

…(truncated)…
