---
type: Wiki Overview
title: 'TASK-1557: okf-migrate Command (migrate.py)'
id: doc:sdd-tasks-completed-task-1557-okf-migrate-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: OKF fields. It takes a bare tree (node_id-keyed, no concept_id, no type,
  no
relates_to:
- concept: mod:parrot.knowledge.pageindex.content_store
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.okf.concept_id
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.okf.frontmatter
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.okf.graph
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.okf.migrate
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.okf.ontology
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.okf.projection
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.store
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.utils
  rel: mentions
---

# TASK-1557: okf-migrate Command (migrate.py)

**Feature**: FEAT-238 — OKF Knowledge Layer over PageIndex
**Spec**: `sdd/specs/okf-knowledge-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-1552, TASK-1553, TASK-1554, TASK-1555, TASK-1556
**Assigned-to**: unassigned

---

## Context

`okf-migrate` is the deliverable command that retrofits existing PageIndex trees with
OKF fields. It takes a bare tree (node_id-keyed, no concept_id, no type, no
`relates_to`) and enriches it fully: derives concept_ids, classifies types (via LLM
with content-addressed cache + structural fallback), builds `source` from `doc_name`
and page spans, parses markdown links → `relates_to`, renames sidecars, and generates
`index.md`.

The command MUST be **idempotent**: re-running on an already-migrated tree produces
identical output (the core determinism acceptance test).

Implements: Spec §7 (Deliverable — okf-migrate), Spec §3 Module 6.

---

## Scope

- Implement `migrate.py` in `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/`:
  - `async def okf_migrate(tree_name, tree_store, content_store, adapter, *, force_reclassify=False) -> MigrationReport` — the main migration function:
    1. Load authoritative JSON via `tree_store.load(tree_name)`.
    2. For each node: derive `concept_id` via `assign_concept_ids()`.
    3. Classify `type` via LLM — content-addressed cache key:
       `sha1(model_id + title + summary)`. Structural fallback `Section` when
       classification unavailable.
    4. Build `source` from `doc_name` + `start_index`/`end_index`.
    5. Parse body markdown links → `relates_to` candidates (`rel: references`).
    6. Write enriched fields back into JSON (authoritative).
    7. Rename sidecars: `<node_id>.md` → `<flattened_concept_id>.md` with
       frontmatter projection.
    8. Generate root `index.md`.
    9. Save the enriched tree via `tree_store.save()`.
    10. Emit `MigrationReport`.
  - `MigrationReport(BaseModel)` — report model: nodes_processed, types_assigned
    (histogram), links_resolved, links_broken, slug_collisions, files_renamed.
  - `_classify_type(node, adapter, cache) -> ConceptType` — LLM classification
    with content-addressed caching.
  - `_build_source(node, doc_name) -> SourceProvenance` — build provenance from
    `doc_name` + `start_index`/`end_index`.
- Write unit and integration tests.

**NOT in scope**: Tool registration (TASK-1558), toolkit integration (TASK-1559),
LLM-inferred edge classification beyond explicit markdown links (D10).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/migrate.py` | CREATE | Migration command + report model |
| `packages/ai-parrot/tests/knowledge/pageindex/test_okf_migrate.py` | CREATE | Unit + integration tests |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/__init__.py` | MODIFY | Add re-exports |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# From previous FEAT-238 tasks:
from parrot.knowledge.pageindex.okf.ontology import ConceptType, SourceProvenance, RelatesTo
from parrot.knowledge.pageindex.okf.concept_id import assign_concept_ids
from parrot.knowledge.pageindex.okf.frontmatter import project_frontmatter
from parrot.knowledge.pageindex.okf.graph import parse_markdown_links
from parrot.knowledge.pageindex.okf.projection import (
    project_sidecars,
    flatten_concept_id_for_filename,
    generate_index_md,
)

# From existing codebase:
from parrot.knowledge.pageindex.store import JSONTreeStore             # store.py:23
from parrot.knowledge.pageindex.content_store import NodeContentStore  # content_store.py:37
from parrot.knowledge.pageindex.utils import get_nodes                 # utils.py:231
from parrot.knowledge.pageindex.utils import structure_to_list         # utils.py:249
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/store.py
class JSONTreeStore:
    def load(self, tree_name: str) -> dict[str, Any]:              # line 59
    def save(self, tree_name: str, tree: dict[str, Any]) -> None:  # line 65
    def list_names(self) -> list[str]:                              # line 46

# packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py
class NodeContentStore:
    def save(self, tree_name: str, node_id: str, markdown: str) -> None:  # line 116
    def load(self, tree_name: str, node_id: str) -> Optional[str]:        # line 123
    def list_node_ids(self, tree_name: str) -> list[str]:                  # line 182
    def delete_node(self, tree_name: str, node_id: str) -> bool:           # line 148

# Node page provenance fields (from builder.py:381-399):
# node["start_index"]: int — physical page start
# node["end_index"]: int — physical page end

# Node existing fields:
# node["node_id"], node["title"], node["summary"], node.get("doc_name")
```

### Does NOT Exist

- ~~`JSONTreeStore.migrate()`~~ — no migration method; use `load()` + `save()`
- ~~`NodeContentStore.rename()`~~ — no rename; delete old + save new
- ~~`node["type"]`~~ — does not exist pre-migration; this task adds it
- ~~`node["concept_id"]`~~ — does not exist pre-migration; this task adds it
- ~~`node["source"]`~~ — does not exist pre-migration; this task adds it
- ~~`node["relates_to"]`~~ — does not exist pre-migration; this task adds it

---

## Implementation Notes

### Pattern to Follow

```python
async def okf_migrate(
    tree_name: str,
    tree_store: JSONTreeStore,
    content_store: NodeContentStore,
    adapter: Any,
    *,
    force_reclassify: bool = False,
) -> MigrationReport:
    tree = tree_store.load(tree_name)
    report = MigrationReport(tree_name=tree_name)

    # 1. Assign concept_ids
    assign_concept_ids(tree)

    # 2. For each node: classify type, build source, parse links
    nodes = structure_to_list(tree.get("structure", []))
    for node in nodes:
        node["type"] = await _classify_type(node, adapter, cache, force_reclassify)
        node["source"] = _build_source(node, tree.get("doc_name", "")).model_dump()
        body = content_store.load(tree_name, node["node_id"]) or ""
        links = parse_markdown_links(body)
        node["relates_to"] = [{"concept": link, "rel": "references"} for link in links]
        report.nodes_processed += 1

    # 3. Save enriched tree
    tree_store.save(tree_name, tree)

    # 4. Project sidecars (rename node_id.md → concept_id.md)
    project_sidecars(tree, tree_name, content_store)

    # 5. Generate index.md
    index_content = generate_index_md(tree, tree_name)
    # Write index.md to content dir...

    return report
```

### Key Constraints

- **Idempotency**: re-running on an already-migrated tree MUST produce identical output.
  The content-addressed type cache ensures `_classify_type` returns the same value.
  `assign_concept_ids` is deterministic by design. The projection is byte-deterministic.
- **Content-addressed type cache**: key is `sha1(model_id + title + summary)`.
  Cache can be a simple dict persisted to a JSON sidecar file alongside the tree.
  `force_reclassify=True` bypasses the cache.
- **`doc_name` for source**: the tree-level `doc_name` field provides the source
  document filename. Nodes inherit it. `start_index`/`end_index` provide page spans.
- **Sidecar rename**: use `content_store.delete_node(tree_name, old_node_id)` to
  remove old file, then `content_store.save(tree_name, flattened_concept_id, new_content)`
  to write the new one.
- **Batch LLM calls**: for large trees, consider batching type classification to
  respect rate limits. However, the cache means most nodes are classified once.

---

## Acceptance Criteria

- [ ] `okf_migrate` enriches all nodes with `concept_id`, `type`, `source`, `relates_to`
- [ ] **Idempotent**: running twice produces identical tree JSON and sidecar files
- [ ] Type classification uses content-addressed cache — same content → same type
- [ ] Structural fallback to `Section` when LLM classification unavailable
- [ ] `source.pages` populated from `start_index`/`end_index`
- [ ] Sidecars renamed from `<node_id>.md` to `<concept_id>.md`
- [ ] Root `index.md` generated
- [ ] `MigrationReport` includes: nodes_processed, type histogram, links stats, slug collisions
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/pageindex/test_okf_migrate.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/pageindex/test_okf_migrate.py
import pytest
from unittest.mock import AsyncMock
from parrot.knowledge.pageindex.okf.migrate import okf_migrate, MigrationReport


@pytest.fixture
def bare_tree():
    """A pre-migration tree with no OKF fields."""
    return {
        "doc_name": "guide.pdf",
        "structure": [
            {
                "node_id": "0000",
                "title": "Introduction",
                "summary": "Overview of the guide",
                "start_index": 1,
                "end_index": 5,
                "nodes": [],
            },
            {
                "node_id": "0001",
                "title": "Controls",
                "summary": "Security controls",
                "start_index": 6,
                "end_index": 10,
                "nodes": [],
            },
        ],
    }


class TestOkfMigrate:
    @pytest.mark.asyncio
    async def test_enriches_all_nodes(self, bare_tree, tmp_path):
        # Setup stores with bare_tree
        # Run okf_migrate
        # Assert concept_id, type, source, relates_to on every node
        ...

    @pytest.mark.asyncio
    async def test_idempotent(self, bare_tree, tmp_path):
        # Run migration twice
        # Compare tree JSON byte-for-byte
        ...

    @pytest.mark.asyncio
    async def test_type_content_addressed(self, bare_tree, tmp_path):
        # Run migration, check type assigned
        # Run again, verify LLM not called second time (cache hit)
        ...

    @pytest.mark.asyncio
    async def test_fallback_to_section(self, bare_tree, tmp_path):
        # Run migration with adapter=None (no LLM)
        # All types should be "Section"
        ...

    @pytest.mark.asyncio
    async def test_report_histogram(self, bare_tree, tmp_path):
        # Run migration
        # Check report.types_histogram has expected counts
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/okf-knowledge-layer.spec.md` — especially §7
2. **Check dependencies** — all of TASK-1552 through TASK-1556 must be complete
3. **Verify** that `JSONTreeStore.load/save` and `NodeContentStore` APIs haven't changed
4. **Implement** `migrate.py` with full migration pipeline
5. **Write tests** emphasizing idempotency and content-addressed caching
6. **Move this file** to `sdd/tasks/completed/` when done

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-15
**Notes**: Implemented okf_migrate() with full pipeline: concept_id assignment, type classification (LLM + content-addressed cache + Section fallback), source provenance, markdown link → relates_to parsing, sidecar rename via project_sidecars, index.md generation. MigrationReport includes histogram, link stats, slug collision count. All 14 tests pass. No linting errors.

**Deviations from spec**: none

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
