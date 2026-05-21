---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: GraphIndexToolkit Write Tools + Signal/Community Surface

**Feature ID**: FEAT-192
**Date**: 2026-05-21
**Author**: Jesús Lara
**Status**: draft
**Target version**: 0.x (GraphIndex is pre-production; no compat guarantees)

---

## 1. Motivation & Business Requirements

### Problem Statement

`GraphIndexToolkit`
(`packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py`)
today exposes 8 tools to agents — `find_node`, `find_references`,
`get_neighborhood`, `traverse`, `search_hybrid`, `find_central_nodes`,
`shortest_path`, `explain`. **Every one of them is read-only.** An
agent can query the graph but it cannot:

- Create a `CONCEPT` node when it discovers a new entity.
- Link a Section to a Concept it just identified.
- Attach a freshly-written summary to a node.
- Tag a node with `{"topic": "compliance"}` from inside a tool call.
- Merge two duplicate nodes the LLM realises are the same entity.
- Read decomposed FEAT-190 relevance signals for "why are these
  two connected?"
- List FEAT-191 communities or find which one a node belongs to.

That last paragraph is exactly Karpathy's central LLM-Wiki claim:
*"the LLM handles the bookkeeping — cross-references, summaries,
filing."* The current toolkit lets the LLM read the wiki; it does not
let the LLM **maintain** one.

Two secondary problems also bite:

1. **`_encode_query` uses a placeholder hash** (`toolkit.py:402-411`).
   The docstring at line 405 says *"in production, a real embedding
   model should be injected via a GraphIndexEmbedder."* It hasn't
   been wired. `find_node` and `search_hybrid` are effectively
   non-functional until this is fixed.
2. **There is no integration test that exercises the toolkit against
   a real assembled graph** — every existing test uses hand-built
   mocks. That's fine for read methods, but write methods touch
   pipeline-fragile state (assembler dicts, FAISS index, future
   community membership), so an integration test is warranted.

This spec adds the write-side, wires the signal/community
read-tools from FEAT-190 / FEAT-191, fixes the encoder, and adds a
real-graph integration test.

### Goals

- Add 7 write tools to `GraphIndexToolkit` that let an agent build /
  mutate the knowledge graph: `create_concept`, `create_node`,
  `link_nodes`, `unlink_nodes`, `attach_summary`, `tag_node`,
  `merge_nodes`.
- Add 4 read tools wrapping FEAT-190 + FEAT-191:
  `relevance(a, b)` (decomposed signals),
  `neighborhood_by_relevance(node_id, top_k)`,
  `list_communities(min_size)`,
  `find_community(node_id)`.
- Replace the placeholder query encoder with a real one driven by
  a `GraphIndexEmbedder` (`embed.py:22`) injected at construction.
- Keep all changes additive: every existing tool keeps its name,
  signature, and observed behaviour.
- Provide a real-graph integration test that wires
  `GraphAssembler` + `GraphIndexEmbedder` + `GraphIndexToolkit` end
  to end and exercises one full read+write+read cycle.

### Non-Goals (explicitly out of scope)

- **Tool persistence semantics** — the toolkit operates over the
  *in-memory* `rustworkx.PyDiGraph` + FAISS index. Writing back to
  ArangoDB on every mutation is **not** in scope; persistence is
  triggered explicitly by `GraphIndexBuilder.persist(...)` (existing
  pattern) or by a downstream "save" tool the wiki orchestrator
  adds in FEAT-193.
- **LLM-driven entity extraction during `create_concept`** — the
  tool takes the title/summary as inputs; the LLM is the one
  *deciding* what to create. No automatic NER.
- **Bulk imports** — every write tool is single-object. Batch
  ingestion stays in `LoaderExtractor` / `GraphIndexBuilder.build`.
- **Conflict resolution / optimistic locking** — single-process
  in-memory mutations; no concurrent-writer story. The wiki
  orchestrator (FEAT-193) handles ordering.
- **Edge weight mutation** — `link_nodes` accepts a `confidence`
  only when `provenance=INFERRED` (matching the schema invariant
  at `schema.py:123-141`). EXTRACTED edges cannot be weighted.
- **Undo / soft-delete** — `unlink_nodes` removes outright. The
  upstream `ingest_document` flow has soft-delete; the toolkit
  does not replicate it. (A future "audit log" mode is FEAT-193's
  concern.)
- **Concept catalog integration** — `parrot.knowledge.ontology.concept_catalog`
  is a separate subsystem. `create_concept` does NOT register
  with it; if the orchestrator wants that, it calls the catalog
  service directly.

---

## 2. Architectural Design

### Overview

`GraphIndexToolkit` gains write capabilities by holding (a) a
reference to the same `GraphAssembler` that built the graph and (b)
the original `UniversalNode` list. Writes go through the assembler's
existing `add_node` / `add_edge` methods (`assemble.py:45, 77`) so the
in-memory state stays consistent. The toolkit also gains a
`GraphIndexEmbedder` reference for proper query encoding and for
embedding freshly-created nodes when the agent calls
`create_concept` / `create_node`.

FEAT-190 and FEAT-191 are consumed via direct function imports;
their results are wrapped into the LLM-friendly dict shape the
toolkit's existing tools use.

### Component Diagram

```
                ┌─────────────────────────────────┐
                │       GraphIndexToolkit         │
                │  (parrot_tools.graphindex)      │
                └──────────────┬──────────────────┘
                               │
        ┌──────────────────────┼─────────────────────┐
        ▼                      ▼                     ▼
  ┌────────────┐       ┌────────────────┐    ┌────────────────┐
  │ Assembler  │       │ Embedder       │    │ signals (190)  │
  │ (existing) │       │ (existing)     │    │ communities    │
  │            │       │                │    │ (191)          │
  └────────────┘       └────────────────┘    └────────────────┘
        │                      │                     │
        │ add_node / add_edge  │ encode / get_embed  │ pure fns
        ▼                      ▼                     ▼
                  rustworkx PyDiGraph + FAISS index
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `GraphAssembler` (`assemble.py:24`) | reuse — held as instance attribute | All node/edge mutations route through `add_node`, `add_edge`. Existing `_node_index_map` / `_edge_index_map` updates handle the rustworkx index bookkeeping automatically. |
| `GraphIndexEmbedder` (`embed.py:22`) | reuse — held as instance attribute | `embed_nodes([new_node])` for freshly created nodes; `model.encode([query])` for query encoding (replaces placeholder). |
| `UniversalNode` / `UniversalEdge` (`schema.py:70, 101`) | construction | Write tools build instances and hand them to the assembler. |
| FEAT-190 `signal_relevance` | direct call | Wrapped by `relevance(a, b)` tool. |
| FEAT-191 `detect_communities` / `CommunitiesResult` | direct call (cached) | `list_communities` / `find_community` cache the last result on the toolkit instance; cache invalidated on any write. |
| Existing read tools | unchanged | `find_node`, `find_references`, `get_neighborhood`, `traverse`, `search_hybrid`, `find_central_nodes`, `shortest_path`, `explain` — same signatures and observable behaviour. |
| `AbstractToolkit` (`parrot/tools/toolkit.py:191`) | base class | Auto-discovery of new async methods as tools (unchanged pattern). |

### Data Models

No new Pydantic models in this spec; we reuse:

- `UniversalNode`, `UniversalEdge` (creation).
- `NodeKind`, `EdgeKind`, `Provenance` (input enums; the tool
  signature accepts string literals and converts).
- FEAT-190 `SignalRelevance`, `SignalRelevanceConfig`.
- FEAT-191 `Community`, `CommunitiesResult`.

Write tools accept primitive inputs and return dicts (LLM-friendly).

### New Public Interfaces

```python
# parrot_tools/graphindex/toolkit.py — additions to GraphIndexToolkit

class GraphIndexToolkit(AbstractToolkit):

    def __init__(
        self,
        graph: rustworkx.PyDiGraph,
        faiss_index: faiss.Index,
        node_map: dict[str, int],
        node_id_list: list[str],
        client=None,
        # NEW:
        assembler: Optional[GraphAssembler] = None,
        embedder: Optional[GraphIndexEmbedder] = None,
        nodes: Optional[list[UniversalNode]] = None,
        signal_config: Optional[SignalRelevanceConfig] = None,
    ) -> None: ...

    # ---- Write tools (new) -------------------------------------

    async def create_concept(
        self,
        title: str,
        summary: str,
        source_uri: Optional[str] = None,
        categories: Optional[list[str]] = None,
    ) -> dict:
        """Create a CONCEPT node and embed it. Returns {node_id, ...}."""

    async def create_node(
        self,
        kind: str,           # NodeKind value, e.g. "concept" / "section"
        title: str,
        summary: Optional[str] = None,
        source_uri: Optional[str] = None,
        parent_id: Optional[str] = None,
        domain_tags: Optional[dict] = None,
    ) -> dict:
        """Generic node creation — escape hatch for kinds beyond CONCEPT."""

    async def link_nodes(
        self,
        source_id: str,
        target_id: str,
        kind: str,           # EdgeKind value
        confidence: Optional[float] = None,
    ) -> dict:
        """Add a directed edge. confidence iff provenance=INFERRED
        (validator enforced at the UniversalEdge layer)."""

    async def unlink_nodes(
        self,
        source_id: str,
        target_id: str,
        kind: Optional[str] = None,    # None → remove all edges between them
    ) -> dict:
        """Remove edge(s) between source_id and target_id."""

    async def attach_summary(
        self,
        node_id: str,
        summary: str,
    ) -> dict:
        """Set / overwrite the summary on an existing node. Re-embeds."""

    async def tag_node(
        self,
        node_id: str,
        key: str,
        value: str,
    ) -> dict:
        """Merge a single key/value into the node's domain_tags."""

    async def merge_nodes(
        self,
        canonical_id: str,
        duplicate_id: str,
    ) -> dict:
        """Re-point every edge of duplicate_id to canonical_id, then
        delete duplicate_id. Returns counts of redirected edges."""

    # ---- Read tools (signal + community wrappers) -------------

    async def relevance(self, node_a: str, node_b: str) -> dict:
        """FEAT-190 four-signal decomposed relevance.
        Returns {direct, source_overlap, adamic_adar, type_affinity,
        combined, direct_edges, shared_sources, aa_neighbours}."""

    async def neighborhood_by_relevance(
        self,
        node_id: str,
        top_k: int = 10,
    ) -> list[dict]:
        """Top-K nodes most relevant by FEAT-190 combined signal score."""

    async def list_communities(self, min_size: int = 2) -> list[dict]:
        """FEAT-191 Louvain partition; caches across calls until any
        write tool runs."""

    async def find_community(self, node_id: str) -> dict:
        """Returns the Community containing node_id."""
```

---

## 3. Module Breakdown

### Module 1: Toolkit constructor extension + assembler/embedder wiring
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py` (modify)
- **Responsibility**:
  - Add `assembler`, `embedder`, `nodes`, `signal_config` kwargs;
    keep them `Optional` so existing callers don't break.
  - Add `_write_supported` property: `True` iff `assembler` and
    `embedder` are both set.
  - Add `_invalidate_community_cache()` helper.
- **Depends on**: nothing new.

### Module 2: Replace `_encode_query` with a real embedder call
- **Path**: same file.
- **Responsibility**:
  - When `self.embedder` is set, `_encode_query(query, dim)` calls
    `self.embedder.model.encode([query])` and returns the result
    cast to `float32` and shaped `(1, dim)`.
  - When `self.embedder` is None, log a warning once and fall back
    to the existing placeholder hash (for backwards-compat tests).
  - Update the docstring at `toolkit.py:402` to reflect the new
    behaviour.
- **Depends on**: Module 1.

### Module 3: Write tools — node creation
- **Path**: same file.
- **Responsibility**:
  - `create_concept(title, summary, source_uri, categories)` —
    mints a deterministic node_id (SHA-1 of `concept::title::summary`),
    builds `UniversalNode(kind=CONCEPT, ...)`, calls
    `self.assembler.add_node(node)`, appends to `self.nodes`,
    embeds via `await self.embedder.embed_nodes([node])`, updates
    `node_map` / `node_id_list`. Stores `categories` in
    `domain_tags`. Invalidates the community cache.
  - `create_node(kind, title, summary, ...)` — generic version for
    non-Concept kinds. Validates `kind` against `NodeKind`.
  - Both return `{"node_id", "kind", "title", "status": "created"}`
    on success, `{"error": "..."}` when the write path is
    unsupported (no assembler/embedder).
- **Depends on**: Modules 1-2.

### Module 4: Write tools — edge mutations
- **Path**: same file.
- **Responsibility**:
  - `link_nodes(source_id, target_id, kind, confidence)` — builds
    `UniversalEdge`, calls `self.assembler.add_edge(edge)`.
    Confidence is validated by the `UniversalEdge` model itself
    (`schema.py:123`); the toolkit returns the validation error as
    a structured dict instead of raising.
  - `unlink_nodes(source_id, target_id, kind=None)` — uses
    `self.assembler.graph.remove_edge(src_idx, tgt_idx)` for each
    matching edge. Removes from `_edge_index_map`. Returns count
    removed.
- **Depends on**: Modules 1-2.

### Module 5: Write tools — node mutations + merge
- **Path**: same file.
- **Responsibility**:
  - `attach_summary(node_id, summary)` — updates `graph[idx]["summary"]`
    AND the corresponding `UniversalNode` in `self.nodes`. Re-embeds
    via `embed_nodes([updated_node])`.
  - `tag_node(node_id, key, value)` — shallow-merges into
    `graph[idx]["domain_tags"]` and the matching `UniversalNode`.
  - `merge_nodes(canonical_id, duplicate_id)`:
    1. Collect every out-edge and in-edge of `duplicate_id`.
    2. For each, create the equivalent edge with `canonical_id` in
       the duplicate's slot (skip if the canonical already has an
       edge of that kind to/from the other endpoint).
    3. Remove `duplicate_id` from `graph`, `_node_index_map`,
       `node_map`, `node_id_list`, and `self.nodes`.
    4. Note: the FAISS index does NOT support row deletion; mark
       the duplicate's FAISS position as orphaned (its node_id is
       removed from `node_id_list[position]` and replaced with
       `None`, which the read tools already check at
       `toolkit.py:91, 248`).
- **Depends on**: Modules 1-2.

### Module 6: Signal + community read tools
- **Path**: same file.
- **Responsibility**:
  - `relevance(a, b)` — imports FEAT-190 lazily, calls
    `signal_relevance(self.graph, self.nodes, a, b, self.signal_config)`,
    returns the Pydantic result as a `model_dump()` dict.
  - `neighborhood_by_relevance(node_id, top_k)` — wraps
    FEAT-190 `relevance_neighborhood`.
  - `list_communities(min_size)` — lazily imports FEAT-191,
    calls `detect_communities(self.graph, self.nodes, signal_config=self.signal_config)`
    on first call (or after cache invalidation), caches the
    result on `self._community_cache`, filters by `min_size`.
  - `find_community(node_id)` — uses cached
    `node_to_community` lookup; returns the full `Community` dict.
- **Depends on**: Modules 1, FEAT-190, FEAT-191. Lazy imports
  keep the toolkit usable when those features aren't installed
  (read+write tools still work; only the four wrapped methods
  return `{"error": "feature X not available"}`).

### Module 7: Real-graph integration test
- **Path**: `packages/ai-parrot-tools/tests/graphindex/test_toolkit_e2e.py`
  (new)
- **Responsibility**: One end-to-end test that:
  1. Builds a tiny `GraphAssembler` with 4 known nodes + 3 edges.
  2. Builds a `GraphIndexEmbedder` with a stubbed deterministic
     `model.encode` (so the test doesn't need a real model).
  3. Constructs `GraphIndexToolkit(assembler=..., embedder=..., nodes=...)`.
  4. Calls `create_concept("Compliance")` — asserts node count goes
     up, the new concept appears in `find_node`/embedding search.
  5. Calls `link_nodes(...)` to add a REFERENCES edge — asserts
     `find_references` sees it.
  6. Calls `merge_nodes(...)` to dedupe — asserts edges re-pointed.
  7. Calls `list_communities()` — asserts result has the expected
     count + cohesion (when FEAT-191 is available).
- **Depends on**: Modules 1-6.

### Module 8: Update toolkit module docstring + `__init__` exports
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py`
  module docstring + `__init__.py` if applicable.
- **Responsibility**: Document write capabilities; bump tool count
  from 8 → 19 in the docstring. Tag every new method with
  `# WRITE` or `# READ (signals)` / `# READ (communities)` in
  inline comments for grep-ability.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_toolkit_accepts_assembler_kwarg` | 1 | New ctor kwargs stored; `_write_supported` is True iff both set. |
| `test_toolkit_without_assembler_write_returns_error` | 1 | `create_concept(...)` returns `{"error": "..."}` when no assembler. |
| `test_encode_query_uses_real_embedder` | 2 | When embedder set, `_encode_query` calls `model.encode` (mocked); returns shape `(1, dim)`. |
| `test_encode_query_falls_back_when_no_embedder` | 2 | No embedder → placeholder hash path used + warning logged once. |
| `test_create_concept_adds_node_and_embeds` | 3 | After call: `graph.num_nodes()` +1; `embed_nodes` called once with the new node; `find_node(...)` returns it. |
| `test_create_concept_invalidates_community_cache` | 3 | After cache pre-populated, `create_concept` clears `_community_cache`. |
| `test_create_node_validates_kind` | 3 | Bad `kind` string → `{"error": "..."}`, no mutation. |
| `test_link_nodes_extracted_rejects_confidence` | 4 | EXTRACTED + confidence → error from UniversalEdge validator, surfaced as `{"error": ...}`. |
| `test_link_nodes_inferred_requires_confidence` | 4 | INFERRED without confidence → error. |
| `test_link_nodes_adds_edge` | 4 | After call: edge appears in `find_references` of both endpoints. |
| `test_unlink_nodes_removes_one_kind` | 4 | `unlink(a, b, "references")` removes only the REFERENCES edge; CONTAINS edge between same pair stays. |
| `test_unlink_nodes_kind_none_removes_all` | 4 | `unlink(a, b)` with `kind=None` removes every edge between a and b. |
| `test_attach_summary_updates_payload_and_reembeds` | 5 | `graph[idx]["summary"]` matches; `embed_nodes` called with the updated node. |
| `test_tag_node_shallow_merges` | 5 | Existing tags preserved; new key/value added. |
| `test_merge_nodes_redirects_edges` | 5 | Edges from `duplicate_id` now exist on `canonical_id`; duplicate_id removed from `node_map`. |
| `test_merge_nodes_skips_existing_edges` | 5 | Duplicate's edges that would duplicate an existing canonical edge are skipped, not double-added. |
| `test_merge_nodes_orphans_faiss_position` | 5 | After merge, `node_id_list[duplicate_faiss_pos] is None`. |
| `test_relevance_returns_decomposed` | 6 | `relevance(a, b)` returns a dict with `direct`, `source_overlap`, `adamic_adar`, `type_affinity`, `combined`. |
| `test_neighborhood_by_relevance_respects_top_k` | 6 | Returns ≤ top_k results sorted by combined desc. |
| `test_list_communities_filters_by_min_size` | 6 | `list_communities(min_size=3)` excludes communities of size < 3. |
| `test_list_communities_caches_until_write` | 6 | Two consecutive calls hit detect_communities once (mock); a write tool in between → second call re-runs. |
| `test_find_community_returns_correct_membership` | 6 | For a node in community C, `find_community(node_id)` returns C's `community_id`. |
| `test_existing_read_tools_unchanged` | (all) | `find_node`, `find_references`, `get_neighborhood`, `traverse`, `search_hybrid`, `find_central_nodes`, `shortest_path`, `explain` produce the same outputs as before for the same fixture inputs. |

### Integration Tests

| Test | Description |
|---|---|
| `test_toolkit_e2e_create_link_merge_lookup` | The Module 7 end-to-end flow on a real `GraphAssembler` + stubbed embedder. |
| `test_toolkit_e2e_full_wiki_loop` | Build empty graph → `create_concept('A')` + `create_concept('B')` → `link_nodes(A, B, 'references')` → `relevance(A, B)` shows direct=1.0 + type_affinity=1.0 → `list_communities` returns single community of size 2. |
| `test_toolkit_works_without_optional_features` | Construct toolkit with `assembler` + `embedder` but without `signal_config`; `relevance(...)` still works (uses default `SignalRelevanceConfig`). |

### Test Data / Fixtures

```python
# tests/graphindex/fixtures/toolkit_e2e.py

@pytest.fixture
def real_toolkit() -> GraphIndexToolkit:
    """A toolkit wired to a real GraphAssembler + a stubbed embedder
    (deterministic encode → unit vector based on title hash). Pre-populated
    with 4 nodes and 3 edges so write tests start from a non-trivial
    state."""

@pytest.fixture
def stubbed_embedder() -> GraphIndexEmbedder:
    """Embedder whose model.encode returns deterministic vectors so
    embed_nodes / find_node assertions are reproducible."""
```

---

## 5. Acceptance Criteria

- [ ] `GraphIndexToolkit.__init__` accepts the new
      `assembler`, `embedder`, `nodes`, `signal_config` kwargs (all
      `Optional`). Existing constructors continue to work unchanged.
- [ ] 7 write tools exist and are auto-registered:
      `create_concept`, `create_node`, `link_nodes`, `unlink_nodes`,
      `attach_summary`, `tag_node`, `merge_nodes`.
- [ ] 4 signal/community read tools exist and are auto-registered:
      `relevance`, `neighborhood_by_relevance`, `list_communities`,
      `find_community`.
- [ ] Tool discovery (`list_tool_names()`) returns the 8 existing
      tools **plus** the 11 new tools (19 total).
- [ ] `_encode_query` calls the injected embedder's `model.encode`
      when available; falls back to the placeholder hash with a
      one-shot warning otherwise.
- [ ] `create_concept` and `create_node` route through
      `GraphAssembler.add_node`, embed the new node via
      `GraphIndexEmbedder.embed_nodes([node])`, update `node_map` /
      `node_id_list`, and invalidate the community cache.
- [ ] `link_nodes` constructs a `UniversalEdge` and routes through
      `GraphAssembler.add_edge`. EXTRACTED + confidence and INFERRED
      without confidence both produce structured `{"error": ...}`
      responses, NOT exceptions, so an LLM agent can recover.
- [ ] `unlink_nodes` removes one edge (`kind=str`) or all edges
      (`kind=None`) between the given pair and updates
      `_edge_index_map`.
- [ ] `attach_summary` updates both the graph payload and the
      `UniversalNode` in `self.nodes`, then re-embeds.
- [ ] `tag_node` shallow-merges into `domain_tags`; existing keys are
      preserved.
- [ ] `merge_nodes` redirects every edge from `duplicate_id` to
      `canonical_id` (deduping), removes the duplicate node from the
      graph + maps, and orphans its FAISS position by setting
      `node_id_list[pos] = None`.
- [ ] `relevance(a, b)` returns a dict mirroring FEAT-190
      `SignalRelevance.model_dump()`.
- [ ] `list_communities(min_size)` returns FEAT-191 communities,
      filtered by size; results are cached until any write tool runs.
- [ ] `find_community(node_id)` returns the matching `Community`
      dict.
- [ ] When FEAT-190 or FEAT-191 are not yet installed, the four
      wrapped tools return `{"error": "feature X not available"}`
      instead of raising ImportError. (Lazy imports.)
- [ ] Integration test `test_toolkit_e2e_create_link_merge_lookup`
      runs end-to-end against a real `GraphAssembler` and a stubbed
      embedder; asserts node count, edge count, lookup results, and
      community membership.
- [ ] Module docstring updated to reflect write capabilities; tool
      count noted as 19.
- [ ] No new external dependencies.
- [ ] All previously-passing tests under
      `packages/ai-parrot-tools/tests/graphindex/` still pass.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor** (verified 2026-05-21)

### Verified Imports

```python
from parrot.tools.toolkit import AbstractToolkit         # tools/toolkit.py:191
from parrot.knowledge.graphindex.schema import (
    EdgeKind, NodeKind, Provenance,
    UniversalEdge, UniversalNode,
)
from parrot.knowledge.graphindex.assemble import GraphAssembler   # assemble.py:24
from parrot.knowledge.graphindex.embed import GraphIndexEmbedder  # embed.py:22
import faiss, rustworkx, numpy as np
# Lazy (FEAT-190 / FEAT-191):
#   from parrot.knowledge.graphindex.signals import signal_relevance, ...
#   from parrot.knowledge.graphindex.communities import detect_communities
```

### Existing Class Signatures

```python
# packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py
class GraphIndexToolkit(AbstractToolkit):              # line 27
    def __init__(
        self,
        graph: rustworkx.PyDiGraph,                    # line 49
        faiss_index: faiss.Index,
        node_map: dict[str, int],
        node_id_list: list[str],
        client=None,
    ) -> None: ...                                     # line 47

    async def find_node(self, query: str) -> dict: ... # line 67
    async def find_references(self, node_id: str) -> list[dict]: ...  # line 108
    async def get_neighborhood(self, node_id: str, depth: int = 2) -> dict: ...  # line 148
    async def traverse(self, from_id, relation, to_kind=None) -> list[dict]: ...  # line 188
    async def search_hybrid(self, query, top_k=10) -> list[dict]: ...  # line 221
    async def find_central_nodes(self, top_k=10, metric="betweenness") -> list[dict]: ...  # line 273
    async def shortest_path(self, from_id, to_id) -> list[dict]: ...  # line 317
    async def explain(self, node_id) -> str: ...        # line 344
    def _encode_query(self, query, dim) -> np.ndarray: ...  # line 402
```

```python
# packages/ai-parrot/src/parrot/knowledge/graphindex/assemble.py
class GraphAssembler:                                  # line 24
    def add_node(self, node: UniversalNode) -> int: ...  # line 45
    def add_edge(self, edge: UniversalEdge) -> Optional[int]: ...  # line 77
    # self.graph: rustworkx.PyDiGraph                  # line 37
    # self._node_index_map: dict[str, int]             # line 38
    # self._edge_index_map: dict[tuple, int]           # line 39
    # The above maps MUST be kept in sync on every mutation;
    # remove_edge / remove_node helpers do NOT exist today and
    # are NOT added in this spec — we use rustworkx primitives
    # (graph.remove_edge / graph.remove_node) directly + maintain
    # the maps from inside the toolkit's write tools.
```

```python
# packages/ai-parrot/src/parrot/knowledge/graphindex/embed.py
class GraphIndexEmbedder:                              # line 22
    self.model                                         # line 47 — EmbeddingModel
    self.index: faiss.IndexFlatL2                      # line 48
    self._node_id_map: list[str]                       # line 49

    async def embed_nodes(self, nodes, batch_size=64) -> list[UniversalNode]: ...  # line 55
    def get_embedding(self, node_id: str) -> Optional[np.ndarray]: ...  # line 157
    # model.encode([query]) is the await-able encoder used by Module 2.
```

```python
# packages/ai-parrot/src/parrot/knowledge/graphindex/schema.py
class UniversalEdge(BaseModel):                        # line 101
    @model_validator(mode="after")
    def _validate_confidence_with_provenance(self):    # line 123
        # EXTRACTED + confidence → ValueError
        # INFERRED without confidence → ValueError
        # Toolkit catches these and returns structured {"error": ...}
```

```python
# rustworkx 0.17 primitives used:
graph.add_node(payload) -> int                          # used by assembler
graph.add_edge(src_idx, tgt_idx, payload) -> int        # used by assembler
graph.remove_edge(src_idx, tgt_idx)                     # used directly by unlink
graph.remove_node(idx)                                  # used directly by merge_nodes
graph.out_edges(idx) -> iterable[(s, t, payload)]
graph.in_edges(idx) -> iterable[(s, t, payload)]
graph.edge_indices_from_endpoints(src_idx, tgt_idx)     # for unlink-by-kind
graph[idx]                                              # node payload (dict)
```

### Integration Points

| New Method | Connects To | Via | Verified At |
|---|---|---|---|
| `create_concept` / `create_node` | `GraphAssembler.add_node` | direct call | `assemble.py:45` |
| `create_concept` / `create_node` | `GraphIndexEmbedder.embed_nodes` | `await embed_nodes([node])` | `embed.py:55` |
| `link_nodes` | `GraphAssembler.add_edge` | direct call | `assemble.py:77` |
| `unlink_nodes` | `graph.remove_edge(src, tgt)` | rustworkx primitive | rustworkx 0.17 |
| `merge_nodes` | `graph.remove_node(idx)` + map cleanup | rustworkx + assembler internals | `assemble.py:38-39` |
| `attach_summary` | `graph[idx]` mutation + re-embed | direct + `embedder.embed_nodes` | `assemble.py:70`, `embed.py:55` |
| `tag_node` | `graph[idx]["domain_tags"]` dict merge | direct | `assemble.py:62` |
| `relevance` | FEAT-190 `signal_relevance` | lazy import | (FEAT-190) |
| `list_communities` | FEAT-191 `detect_communities` | lazy import | (FEAT-191) |
| `_encode_query` | `embedder.model.encode([query])` | replaces placeholder | `embed.py:47` |

### Does NOT Exist (Anti-Hallucination)

- ~~`GraphAssembler.remove_node`, `.remove_edge`, `.update_node`~~ —
  no such methods. Mutations use rustworkx primitives directly with
  the toolkit maintaining `_node_index_map` / `_edge_index_map`.
- ~~`faiss.IndexFlatL2.remove`~~ — FAISS does not support row deletion
  for `IndexFlatL2`. `merge_nodes` orphans the row by setting
  `node_id_list[pos] = None`; read tools already skip on
  `pos < 0 or pos >= len(node_id_list)` (`toolkit.py:91, 248`).
- ~~`GraphIndexToolkit.update_node`~~ — there's no monolithic update;
  `attach_summary` + `tag_node` are the granular tools. Renaming /
  retitling is NOT in this spec (it would need a `rename_node` tool;
  add as follow-up if the wiki orchestrator wants it).
- ~~`AbstractToolkit.register_tool`~~ — tools are discovered by
  the base class scanning public async methods; explicit
  registration is not used in this codebase.
- ~~`rustworkx.PyDiGraph.merge_nodes(a, b)`~~ — not a primitive;
  we implement it on top of `out_edges` / `in_edges` / `remove_node`.
- ~~`signal_relevance(graph, a, b)` (3-arg form)~~ — FEAT-190 spec
  requires the `nodes` list as the second positional arg; the
  toolkit passes `self.nodes` automatically.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Existing tool style**: all tools are `async def` returning JSON-
  serialisable `dict` / `list[dict]`, with `{"error": "..."}` for
  failure paths. The toolkit base class auto-registers them.
  Replicate that contract.
- **Lazy imports for FEAT-190 / FEAT-191** to keep the toolkit
  shippable independently:
  ```python
  try:
      from parrot.knowledge.graphindex.signals import signal_relevance
  except ImportError:
      signal_relevance = None
  ```
  Each wrapped tool checks for `None` and returns
  `{"error": "FEAT-190 signals module not available"}`.
- **No exceptions to callers** — LLM agents can't catch
  exceptions; every error path returns a structured dict. Internal
  validation errors (e.g. `UniversalEdge` confidence/provenance
  mismatch) are caught and re-shaped.
- **`assembler.graph is self.graph`** — the toolkit holds the
  PyDiGraph reference; mutations via the assembler are visible
  immediately to the toolkit's read tools.
- **Embedder index sync**: `embed_nodes` appends to the FAISS index
  and updates the embedder's internal `_node_id_map`; the toolkit
  additionally appends to `self.node_id_list` and `self.node_map`
  to keep query encoding consistent.

### Known Risks / Gotchas

- **FAISS index growth**: every `create_concept` / `create_node`
  adds a row to the in-memory FAISS index. There's no
  defragmentation. For wiki use this is fine (graphs are usually
  < 50k nodes); document the limit in the module docstring.
- **`merge_nodes` and FAISS orphans**: orphaned rows still consume
  memory and can be returned by `find_node` if their embedding is
  closest to a query. We filter at read time
  (`node_id_list[pos] is None → skip`), which means
  `find_node`/`search_hybrid` may return strictly fewer than `top_k`
  results after a merge. Acceptable; documented.
- **Edge deduplication on merge**: the spec deduplicates by
  `(source, target, kind)` triple — same key as
  `_edge_index_map` (`assemble.py:39, 108`). Edges differing only
  by provenance/confidence collapse; we keep the one with
  EXTRACTED provenance over INFERRED, otherwise highest confidence.
- **Community cache invalidation granularity**: any write tool
  clears the entire cache. A future optimisation could compute
  partition deltas; not in v1.
- **Encoding warm-up**: replacing the placeholder encoder means
  the first `find_node` call after construction loads the embedding
  model. Document this; the existing FAISS placeholder was
  microsecond-fast.
- **Concurrent toolkit instances**: each toolkit instance holds its
  own caches but shares the assembler. Two toolkits over the same
  assembler can produce divergent `_community_cache` values until
  invalidated. Out of scope; single-toolkit per assembler is the
  convention.
- **`merge_nodes(canonical, duplicate)` directionality**: edges
  going **into** the duplicate become edges **into** canonical with
  the same external endpoint. Self-loops created by the merge
  (e.g. an edge between canonical and duplicate) are dropped.
  Documented in the docstring.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `faiss-cpu` | already a transitive dep | In-memory ANN; existing toolkit dep. |
| `rustworkx` | already a transitive dep | Graph primitives. |
| `networkx` | `>=3.0` (already at `pyproject.toml:205`) | Indirectly via FEAT-190 / FEAT-191. |
| `numpy` | already a transitive dep | Vector ops. |

No new dependencies.

---

## 8. Open Questions

- [ ] **Should `merge_nodes` produce an INFERRED `MENTIONS` edge
      between the canonical and any node previously connected only
      to the duplicate?** — *Owner: implementation*. Current spec
      simply re-points the edges. An optional `bridge_inferred:
      bool = False` flag could create a marker for downstream
      provenance reconstruction. Likely follow-up FEAT.
- [ ] **`create_concept` content body**: should it also persist the
      summary as a `pageindex://<concept_tree>/<node_id>.md` sidecar
      à la FEAT-189? — *Owner: orchestrator (FEAT-193)*. The wiki
      orchestrator can route concept bodies through PageIndex
      separately; FEAT-192 keeps the concept's full text on the
      UniversalNode's `summary` field for now.
- [ ] **Read-only mode**: should there be a `read_only: bool = False`
      ctor flag to disable the 7 write tools entirely (so an agent
      that's only meant to query can be sandboxed)? — *Owner:
      implementation*. Add if the orchestrator surfaces "read-only
      mode" as a configuration knob.

---

## Worktree Strategy

- **Default isolation**: `per-spec` — single worktree at
  `.claude/worktrees/feat-192-graphindex-toolkit-write-and-signals`.
- **Why not parallel**: Modules 1-5 (write tools) all touch the same
  file; Modules 6-7 depend on FEAT-190 / FEAT-191 being importable.
- **Cross-feature dependencies**:
  - FEAT-190 (`signal_relevance`, `relevance_neighborhood`).
  - FEAT-191 (`detect_communities`, `CommunitiesResult`).
  - Lazy imports mean FEAT-192 builds and ships standalone; the
    four wrapped tools degrade gracefully when the dependencies
    are absent.
- **Suggested task order**: Modules 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-21 | Jesús Lara | Initial draft. |
