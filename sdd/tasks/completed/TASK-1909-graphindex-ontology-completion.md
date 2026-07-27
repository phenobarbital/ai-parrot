# TASK-1909: GraphIndex ontology completion — route all node/edge kinds

**Feature**: FEAT-377 — Graph Engineering Hardening
**Spec**: `sdd/specs/graphindex-as-engineering-devloop.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Module 2 (spec §3). The `NodeKind` enum has 9 members and `EdgeKind` has 10,
but the Arango meta-ontology maps only 6 of each: `wiki_page`/`run`/`claim`
nodes and `produced`/`about`/`supported_by`/`contradicts` edges are silently
dropped by `_upsert_nodes`/`_create_edges` ("Unknown kind" warning). This is
the prerequisite for dev-loop graph write-back (Module 4) reaching Arango
deployments.

---

## Scope

- In `meta_ontology.py`:
  - Add entries to `COLLECTION_TO_KIND` (lines 191-198):
    `"gi_wiki_pages": "wiki_page"`, `"gi_runs": "run"`, `"gi_claims": "claim"`.
    (`KIND_TO_COLLECTION` at line 201 is derived — no separate edit.)
  - Add matching entity definitions to `_ENTITY_DEFS` (lines 30-120),
    following the structure of the existing 6 (document..skill). Update the
    module docstring ("6 entity types" → 9).
  - Add to `EDGE_KIND_TO_COLLECTION` (lines 204-211):
    `"produced": "gi_produced"`, `"about": "gi_about"`,
    `"supported_by": "gi_supported_by"`, `"contradicts": "gi_contradicts"`.
- Locate where the `gi_*` Arango collections are ensured/created at
  bootstrap (grep `gi_documents` outside meta_ontology.py — likely
  `persist.py`) and confirm the new collections are created through the
  same mechanism. If creation iterates the mapping dicts, no change needed —
  state that in the completion note; if collections are listed literally,
  extend the list.
- Add the enum-completeness regression test: every `NodeKind` member has a
  `KIND_TO_COLLECTION` entry, every `EdgeKind` member has an
  `EDGE_KIND_TO_COLLECTION` entry.
- Add a persistence routing test: `_upsert_nodes` with `run`/`claim`/
  `wiki_page` nodes emits no "Unknown kind" warning.

**NOT in scope**: dev_loop code (Modules 3-6); SQLite persistence (already
handles all kinds); changing `Provenance` or `AssertionMeta`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/meta_ontology.py` | MODIFY | 3 node + 4 edge mappings + entity defs |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/persist.py` | MODIFY (maybe) | only if collections are listed literally |
| `packages/ai-parrot/tests/knowledge/graphindex/test_meta_ontology.py` | MODIFY/CREATE | enum-completeness + routing tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.graphindex import NodeKind, EdgeKind, UniversalNode, UniversalEdge
# verified: graphindex/__init__.py:63-111 (__all__); enums in schema.py:36,64
from parrot.knowledge.graphindex.meta_ontology import (
    COLLECTION_TO_KIND, KIND_TO_COLLECTION, EDGE_KIND_TO_COLLECTION,
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/graphindex/schema.py:53-61
class NodeKind(str, Enum):
    DOCUMENT="document"; SECTION="section"; SYMBOL="symbol"; CONCEPT="concept"
    RATIONALE="rationale"; SKILL="skill"; WIKI_PAGE="wiki_page"; RUN="run"; CLAIM="claim"

# schema.py:82-91
class EdgeKind(str, Enum):
    CONTAINS="contains"; REFERENCES="references"; DEFINES="defines"; MENTIONS="mentions"
    EXPLAINS="explains"; EXTENDS="extends"; PRODUCED="produced"; ABOUT="about"
    SUPPORTED_BY="supported_by"; CONTRADICTS="contradicts"

# meta_ontology.py:191-198 — COLLECTION_TO_KIND (6 entries, gi_documents..gi_skills)
# meta_ontology.py:201    — KIND_TO_COLLECTION = {v: k for k, v in COLLECTION_TO_KIND.items()}
# meta_ontology.py:204-211 — EDGE_KIND_TO_COLLECTION (6 entries, gi_contains..gi_extends)
# meta_ontology.py:30-120 — _ENTITY_DEFS (6 entity type definitions — copy their shape)

# persist.py:240 — the drop site:
collection = KIND_TO_COLLECTION.get(node.kind.value)
if not collection:
    logger.warning("Unknown kind '%s' for node %s", node.kind, node.node_id)
    continue
```

### Does NOT Exist
- ~~`gi_wiki_pages` / `gi_runs` / `gi_claims` collections~~ — this task adds the mappings
- ~~`gi_produced` / `gi_about` / `gi_supported_by` / `gi_contradicts`~~ — same
- ~~a 7th-9th entry in `_ENTITY_DEFS`~~ — docstring says "6 entity types"; this task extends it

---

## Implementation Notes

### Key Constraints
- Naming convention: plural snake-case collections with `gi_` prefix for
  nodes; edge collections named after the edge kind.
- `KIND_TO_COLLECTION` is derived by inversion — adding to
  `COLLECTION_TO_KIND` is sufficient and keeps them consistent.
- The enum-completeness test is the regression guard the spec's acceptance
  criteria require — parametrize over enum members so new kinds fail loudly.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/graphindex/persist.py:225-266` — `_upsert_nodes` / `_create_edges` lookups

---

## Acceptance Criteria

- [ ] Every `NodeKind` member has a collection mapping (test-enforced)
- [ ] Every `EdgeKind` member has an edge-collection mapping (test-enforced)
- [ ] `_upsert_nodes` routes `run`/`claim`/`wiki_page` without "Unknown kind"
- [ ] New collections are created by the ensure/bootstrap path (or verified automatic)
- [ ] `pytest packages/ai-parrot/tests/knowledge/graphindex/ -v` passes
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/graphindex/` clean

---

## Test Specification

```python
@pytest.mark.parametrize("kind", list(NodeKind))
def test_every_node_kind_has_collection(kind):
    assert kind.value in KIND_TO_COLLECTION

@pytest.mark.parametrize("kind", list(EdgeKind))
def test_every_edge_kind_has_collection(kind):
    assert kind.value in EDGE_KIND_TO_COLLECTION

def test_upsert_routes_memory_kinds(caplog):
    """run/claim/wiki_page nodes produce no 'Unknown kind' warning."""
```

---

## Agent Instructions

1. **Read the spec** for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/graphindex-as-engineering-devloop.json` → `"in-progress"`
5. **Implement**, **verify**, move this file to `sdd/tasks/completed/`, update index → `"done"`, fill the Completion Note

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-26
**Notes**:
- `meta_ontology.py`: added `wiki_page`/`run`/`claim` to `_ENTITY_DEFS`
  (same property shape as `rationale` — title/source_uri/kind/summary/
  content_ref/embedding_ref/provenance, `vectorize=["summary","title"]`)
  and `COLLECTION_TO_KIND` (`gi_wiki_pages`/`gi_runs`/`gi_claims`); added
  `produced`/`about`/`supported_by`/`contradicts` to `_RELATION_DEFS`
  (same shape as `contains`/`references`/etc. — wildcard from/to,
  `field_match` discovery, provenance-only property) and
  `EDGE_KIND_TO_COLLECTION`. `KIND_TO_COLLECTION` updated automatically
  (derived by inversion). Updated the module + `build_graphindex_ontology`
  docstrings (6→9 entities, 6→10 relations).
- Bootstrap check (per task instruction): grepped for `gi_documents`/
  `COLLECTION_TO_KIND`/`EDGE_KIND_TO_COLLECTION` repo-wide — the only
  hits are `meta_ontology.py` and `persist.py`. `loader.py:198-201`
  confirms `build_graphindex_ontology()` IS the tenant ontology passed to
  `TenantContext`, so `initialize_tenant` provisions every `gi_*`
  collection from `_ENTITY_DEFS`/`_RELATION_DEFS` automatically — no
  literal collection list to extend, no `persist.py` change needed.
- Added the enum-completeness regression guard
  (`TestEnumCompleteness`, parametrized over `list(NodeKind)`/
  `list(EdgeKind)`) and a routing test
  (`TestPersistenceRoutesMemoryKinds::test_upsert_routes_memory_kinds_without_warning`)
  asserting no "Unknown kind" warning for run/claim/wiki_page nodes.
- Updated the pre-existing hard-coded counts in `test_meta_ontology.py`
  (6→9 entities, 6→10 relations/edge-collections) that would otherwise
  have failed once the new mappings landed, and extended
  `test_persist.py`'s `test_nodes_routed_to_correct_collections` /
  `test_edges_routed_to_correct_collections` (which assert
  `set(KIND_TO_COLLECTION.values())`/`set(EDGE_KIND_TO_COLLECTION.values())`
  equality against the collections actually called) with the 3 new node
  kinds and 4 new edge kinds — these would have failed otherwise since
  the expected set grew but the test's node/edge fixtures hadn't.
- `pytest packages/ai-parrot/tests/knowledge/graphindex/ -v`: 620 passed.
- `ruff check packages/ai-parrot/src/parrot/knowledge/graphindex/`: 2
  pre-existing unused-import errors in `meta_ontology.py` (`typing.Any`,
  `TraversalPattern`) and pre-existing errors in unrelated files
  (`signals.py`) — confirmed via `git stash` diff that these predate this
  task's changes; left untouched (out of scope, no code path here uses
  them either way).

**Deviations from spec**: none.
