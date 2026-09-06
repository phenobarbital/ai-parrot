# TASK-2917: Bookstore — communities via graphindex, LLM labels, persistence, CLI

**Feature**: FEAT-533 — Bookstore Conceptual Relations
**Spec**: `sdd/specs/wikitoolkit-bookstore-conceptual-relations.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2912, TASK-2916
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview step 3 (Stage 3), §3 Module 3, goal G4. The book graph
(cards + relations) is adapted into graphindex's `UniversalNode` /
`UniversalEdge` schema, clustered with `detect_communities` (Leiden,
Louvain fallback) using rel weights (made effective by TASK-2912), and
the partition is persisted on the fichas and in the `communities`
table. Labels come from one LLM prompt per community with a
deterministic fallback.

---

## Scope

- `relations.py`:
  - `build_book_graph(cards, relations) -> tuple[GraphAssembler,
    list[UniversalNode]]`: node per card (`node_id=book_id`,
    `kind=NodeKind.DOCUMENT`, `title`, `source_uri=source_path`,
    `summary`, `domain_tags={"genre","traditions","scope","book_id"}`);
    edge per relation except `same_community`
    (`kind=EdgeKind.REFERENCES`; `provenance=INFERRED` + `confidence`
    for `origin="llm"`, else `EXTRACTED` with `confidence=None`;
    `domain_tags={"rel","origin","weight"}`).
  - `detect_book_communities(cards, relations, *, resolution=1.0,
    seed=42, algorithm="leiden") -> tuple[CommunitiesResult,
    InterCommunityGraph, GraphAssembler]`.
  - `_LABEL_PROMPT` + `async label_community(adapter, community,
    cards_by_id) -> CommunityLabelDraft` (titles, authors, traditions,
    topics of up to 10 members; ≤ 6-word label + one sentence);
    `fallback_label(community, cards_by_id) -> tuple[str, origin]`
    (`derive_community_label(titles)` → `"derived"`; empty or singleton
    → member title → `"title"`).
  - `communities_from_result(result, inter, labels, cards_by_id, *,
    now) -> list[BookCommunity]` (inter-relations rows touching each
    community as `InterCommunityRelation.model_dump()`).
- `Bookstore._relate_stage3(resolution)` (replace the TASK-2916 stub):
  - visible cards < 3 → note `"communities: skipped (<3 books)"`, return.
  - relations = `merged_relations(...)` minus `same_community`.
  - detect; label (LLM when `has_llm`, else fallback; per-community
    try/except → fallback); build `BookCommunity` rows.
  - persist: `_communities_store()` = project DB when a project location
    exists else global → `upsert_communities` (replace all); for every
    scope store: `delete_relations(origin="community")`; write
    `same_community` edges (`origin="community"`, weight
    `REL_WEIGHTS["same_community"]`) into the src scope store; set
    `community_id`/`community_label` on each card via
    `set_card_community` in the card's own scope DB (cards not in the
    graph → `None`).
  - `summary.communities = len(result.communities)`; note the algorithm.
- `Bookstore.communities() -> list[BookCommunity]`
  (`merged_communities(self._stores())`), `get_community(id)` (raise
  `BookstoreError` when unknown).
- CLI: `bookstore communities [--json]` (id | label | algorithm | size |
  cohesion | centroid); `bookstore list --by-community`; `bookstore
  relate --communities-only` now does real work.
- `conftest.py::make_adapter._structured`: `CommunityLabelDraft` branch.
- Tests per the Test Specification.

**NOT in scope**: toolkit/MCP tools (TASK-2918); export (TASK-2919);
hierarchical communities.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/bookstore/relations.py` | MODIFY | graph adapter, detection, labels |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | `_relate_stage3`, `communities`, `get_community`, `_communities_store` |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py` | MODIFY | `communities`, `list --by-community` |
| `packages/ai-parrot/tests/knowledge/bookstore/conftest.py` | MODIFY | label draft branch |
| `packages/ai-parrot/tests/knowledge/bookstore/test_communities.py` | CREATE | Stage 3 tests |
| `packages/ai-parrot/tests/knowledge/bookstore/test_cli.py` | MODIFY | `communities` output |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.graphindex.communities import detect_communities, derive_community_label, Community, CommunitiesResult   # communities.py:505, 166, 50, 85
from parrot.knowledge.graphindex.inter_community import compute_inter_community_graph, InterCommunityRelation, InterCommunityGraph   # inter_community.py:94, 26, 70
from parrot.knowledge.graphindex.assemble import GraphAssembler          # assemble.py:24
from parrot.knowledge.graphindex.schema import NodeKind, EdgeKind, Provenance, UniversalNode, UniversalEdge   # schema.py:36, 64, ~28, 149, 184
from parrot.knowledge.bookstore.models import BookCard, BookRelation, BookCommunity, CommunityLabelDraft, REL_WEIGHTS   # TASK-2913
from parrot.knowledge.bookstore.catalog import merged_relations, merged_communities   # TASK-2913
```

### Existing Signatures to Use
```python
# graphindex/communities.py
def detect_communities(graph: rustworkx.PyDiGraph, nodes: list[UniversalNode], resolution: float = 1.0, seed: int = 42,
                       signal_config=None, embedder=None, write_back_to_nodes: bool = True, algorithm: str = "leiden") -> CommunitiesResult   # line 505
    # Leiden when leidenalg+igraph importable, else Louvain with a logged warning; result.algorithm says which ran
class Community(BaseModel):   # line 50 — community_id (16-char sha1 of sorted member ids), size, member_node_ids (centroid first), centroid_node_id, cohesion, modularity_contribution, top_titles (≤5), label; frozen
class CommunitiesResult(BaseModel):   # line 85 — modularity, resolution, seed, weighted, communities (sorted by size desc), node_to_community: dict[str,str], algorithm
def derive_community_label(titles: Iterable[str], max_terms: int = 3) -> str   # line 166 — "" when nothing salient

# graphindex/inter_community.py
def compute_inter_community_graph(graph, communities_result) -> InterCommunityGraph   # line 94 — reads payload "weight"
class InterCommunityRelation(BaseModel): source_community_id, target_community_id, source_label, target_label, directed_edge_count, reverse_edge_count, total_weight, reverse_weight, coupling_ratio   # line 26; frozen
class InterCommunityGraph(BaseModel): relations, community_count, connected_pairs, total_possible_pairs, density   # line 70

# graphindex/assemble.py
class GraphAssembler:  def __init__(self, tenant_id: str); .graph; add_nodes(list[UniversalNode]) -> list[int]; add_edges(list[UniversalEdge]) -> list[Optional[int]]   # lines 35, 113, 124
    # add_edge payload: source_id, target_id, kind, provenance, confidence (+ "weight" after TASK-2912 when domain_tags["weight"] numeric)

# graphindex/schema.py
class UniversalNode(BaseModel): node_id, kind, title, source_uri, content_ref=None, summary=None, embedding_ref=None, domain_tags={}, parent_id=None, provenance=..., assertion=None   # line 149
class UniversalEdge(BaseModel): source_id, target_id, kind, provenance, confidence, assertion=None, domain_tags={}   # line 184 — validator: confidence set IFF provenance == INFERRED

# bookstore/library.py (after TASK-2916)
async def relate_books(...) -> RelateSummary   # Stage 3 hook: `if communities: await self._relate_stage3(resolution)`
async def _relate_stage3(self, resolution: float) -> None   # STUB to replace
self.locations: list[LibraryLocation]  (project first); _stores(); _catalog(scope); list_books(); _visible_ids(); _relations_store_for(book_id)
```

### Does NOT Exist
- ~~`Bookstore.communities/get_community/_communities_store`~~ — created here.
- ~~`build_book_graph`, `detect_book_communities`, `label_community`, `fallback_label`, `communities_from_result`, `_LABEL_PROMPT`~~ — created here.
- ~~`Community.description`~~ — graphindex communities carry only `label`; description lives on `BookCommunity`.
- ~~Persisting a `Community` object directly~~ — persist `BookCommunity` rows (TASK-2913 table), not graphindex models.
- ~~`detect_communities(..., weights=...)`~~ — weights come only from the edge payload (TASK-2912) or `signal_config`; there is no `weights` kwarg.
- ~~`GraphAssembler.add_edge` accepting a dict~~ — it takes a `UniversalEdge`.

---

## Implementation Notes

### Pattern to Follow
```python
# relations.py — mirror wiki/cli.py:_load_graphindex_nodes_edges (lines 900-952)
nodes = [UniversalNode(node_id=c.book_id, kind=NodeKind.DOCUMENT, title=c.title, source_uri=c.source_path,
                       summary=c.summary or None, domain_tags={"genre": c.genre, "traditions": c.traditions, "scope": c.scope, "book_id": c.book_id})
         for c in cards]
edges = []
for r in relations:
    if r.rel == "same_community": continue
    inferred = r.origin == "llm"
    edges.append(UniversalEdge(source_id=r.src_book_id, target_id=r.dst_book_id, kind=EdgeKind.REFERENCES,
                               provenance=Provenance.INFERRED if inferred else Provenance.EXTRACTED,
                               confidence=r.confidence if inferred else None,
                               domain_tags={"rel": r.rel, "origin": r.origin, "weight": r.weight}))
asm = GraphAssembler(tenant_id="bookstore"); asm.add_nodes(nodes); asm.add_edges(edges)
result = detect_communities(asm.graph, nodes, resolution=resolution, seed=seed, algorithm=algorithm)
inter = compute_inter_community_graph(asm.graph, result)
```

### Key Constraints
- Community ids change with membership (spec §7) → re-label every run; never look labels up by id from a previous run.
- Wrap `detect_communities` in try/except → note `"communities: failed (<exc>)"` and leave the previous partition untouched.
- `same_community` edges are rewritten from scratch (delete `origin="community"` in every scope store first).
- Singleton communities are allowed; label = the book title, `label_origin="title"`.
- `bookstore communities` must show `algorithm` so a silent Louvain fallback is visible.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:900-1040` — adapter + communities + inter-community orchestration
- `packages/ai-parrot/tests/knowledge/graphindex/test_communities.py:57` — `_build_two_cliques` (shape for a two-cluster fixture)

---

## Acceptance Criteria

- [ ] Two author/tradition-dense groups → two communities; ids stable across an unchanged re-run
- [ ] `< 3` visible cards → skip with a note; no `communities` rows written
- [ ] LLM edges become `INFERRED` + confidence; others `EXTRACTED`; `domain_tags["weight"]` set → `CommunitiesResult.weighted` is `True`
- [ ] `same_community` edges rewritten; stale ones removed
- [ ] Labels: LLM when available; `derive_community_label` fallback; singleton → title; `label_origin` recorded
- [ ] `communities` table written to the project DB only (global when no project scope); cards' `community_id/label` in their own scope DB
- [ ] `bookstore communities` and `list --by-community` work; `--json` shape matches `BookCommunity`
- [ ] `pytest packages/ai-parrot/tests/knowledge/bookstore/ -q` green; `ruff check` clean

---

## Test Specification

```python
# tests/knowledge/bookstore/test_communities.py
def test_build_book_graph_edge_weights_and_provenance(): ...
def test_detect_book_communities_two_clusters(): ...
def test_fallback_label_derived_and_singleton_title(): ...
async def test_stage3_skipped_under_three_cards(store, ...): ...
async def test_stage3_persists_partition_and_same_community_edges(store, ...): ...
async def test_stage3_rewrites_same_community_edges(store, ...): ...
async def test_stage3_labels_llm_then_fallback_on_error(store, ...): ...
async def test_communities_table_in_project_db_only(store, ...): ...
async def test_community_id_stable_for_same_membership(store, ...): ...
async def test_get_community_unknown_raises(store): ...
# test_cli.py
def test_communities_cli_table_and_json(...): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2912 and TASK-2916 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/wikitoolkit-bookstore-conceptual-relations.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2917-bookstore-communities.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
