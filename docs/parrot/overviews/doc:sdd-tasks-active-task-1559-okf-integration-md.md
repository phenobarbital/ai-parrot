---
type: Wiki Overview
title: 'TASK-1559: Integration Edits — tree_ops, toolkit, content_store'
id: doc:sdd-tasks-active-task-1559-okf-integration-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This is the final integration task. All new OKF modules exist; now they must
  be wired
relates_to:
- concept: mod:parrot.knowledge.pageindex.content_store
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.okf.concept_id
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.okf.graph
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.okf.ontology
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.okf.projection
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.okf.tools
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.tree_ops
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.utils
  rel: mentions
---

# TASK-1559: Integration Edits — tree_ops, toolkit, content_store

**Feature**: FEAT-238 — OKF Knowledge Layer over PageIndex
**Spec**: `sdd/specs/okf-knowledge-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-1552, TASK-1553, TASK-1554, TASK-1555, TASK-1556, TASK-1557, TASK-1558
**Assigned-to**: unassigned

---

## Context

This is the final integration task. All new OKF modules exist; now they must be wired
into the existing PageIndex components:

- `tree_ops.py`: mutations must preserve `concept_id` and trigger re-projection.
- `toolkit.py`: ingest methods gain a T3 type-classification step; `_persist()` triggers
  sidecar projection; new OKF read tools registered.
- `content_store.py`: must accept concept_id-keyed filenames (flattened).

This task also ensures backward compatibility — the existing API continues to work
without OKF enrichment when the LLM classification is unavailable (structural fallback
to `Section`).

Implements: Spec §3 Module 8.

---

## Scope

### tree_ops.py edits
- `reindex_node_ids()`: must **preserve `concept_id`** through renumbering. Currently
  `write_node_id()` only touches `node_id` (confirmed V1) — verify no regression.
  Add a test that concept_id survives reindex.
- `splice_subtree()`: after splicing, if new nodes lack `concept_id`, assign them.
  Trigger re-projection for affected subtree.
- `delete_node()`: clean up the concept_id-keyed sidecar when deleting a node.

### toolkit.py edits
- `insert_content()` / `insert_markdown()` / `import_pdf()`: after building the
  subtree, call `assign_concept_ids()` on the new nodes and `_classify_type()` for
  each (with content-addressed cache and `Section` fallback). This is the T3 step.
- `_persist()` (or the equivalent save path): after saving the tree JSON, trigger
  `project_sidecars()` to regenerate frontmatter on affected sidecars.
- Register the OKF read tools (`find_by_type`, `get_concept`, `get_related`,
  `trace_mapping`, `list_concepts`, `cite`) so they appear in the toolkit's tool list.

### content_store.py edits
- `_node_path()`: accept flattened concept_id strings (already valid per `_NODE_ID_RE`
  pattern `[A-Za-z0-9_-]{1,64}` — flattened concept_ids use `--` for slashes).
  No regex change needed if flattened IDs stay within 64 chars. Add a check/test.
- `loader_for()`: the returned closure should be able to load by concept_id
  (flattened) in addition to node_id. Implement a fallback: try concept_id first,
  fall back to node_id for backward compatibility.

### Backward compatibility
- All existing tests must continue to pass — no breaking changes to the public API.
- Trees without OKF fields (`concept_id`, `type`, etc.) must still work. The T3 step
  and projection are additive; they should no-op gracefully when the OKF subpackage
  is available but fields are missing.

**NOT in scope**: Creating the OKF modules themselves (TASK-1552–1558), ArangoDB
persistence (phase 2), HITL write tools.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/tree_ops.py` | MODIFY | Preserve concept_id; trigger re-projection |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | T3 classification step; projection trigger; tool registration |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py` | MODIFY | Accept concept_id-keyed filenames; dual-key loader |
| `packages/ai-parrot/tests/knowledge/pageindex/test_tree_ops.py` | MODIFY | Add concept_id preservation tests |
| `packages/ai-parrot/tests/knowledge/pageindex/test_toolkit.py` | MODIFY | Add T3 integration tests |
| `packages/ai-parrot/tests/knowledge/pageindex/test_content_store.py` | MODIFY | Add concept_id-keyed tests |
| `packages/ai-parrot/tests/knowledge/pageindex/test_okf_integration.py` | CREATE | End-to-end integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# From FEAT-238 modules:
from parrot.knowledge.pageindex.okf.concept_id import assign_concept_ids
from parrot.knowledge.pageindex.okf.ontology import ConceptType
from parrot.knowledge.pageindex.okf.projection import project_sidecars, flatten_concept_id_for_filename
from parrot.knowledge.pageindex.okf.graph import KnowledgeGraph, build_graph
from parrot.knowledge.pageindex.okf.tools import (
    find_by_type, list_concepts, get_concept, get_related, trace_mapping, cite,
)

# Existing:
from parrot.knowledge.pageindex.tree_ops import reindex_node_ids, splice_subtree, delete_node
from parrot.knowledge.pageindex.content_store import NodeContentStore
from parrot.knowledge.pageindex.utils import find_node_by_id, write_node_id
```

### Existing Signatures to Use

```python
# tree_ops.py
def reindex_node_ids(tree: dict[str, Any]) -> None:              # line 16
def splice_subtree(target, subtree, parent_node_id=None) -> list[str]:  # line 45
def delete_node(tree: dict[str, Any], node_id: str) -> bool:     # line 81

# utils.py
def write_node_id(data: Any, node_id: int = 0) -> int:           # line 217
    # Only writes node_id — does NOT touch concept_id (confirmed V1)

# toolkit.py
async def insert_content(self, tree_name, content, parent_node_id=None, hint=None):  # line 514
async def insert_markdown(self, tree_name, markdown, parent_node_id=None, doc_name=None):  # ~line 485
async def import_pdf(self, tree_name, pdf_path, parent_node_id=None, ...):  # line 557
def _strip_keys_in_place(subtree, keys: tuple[str, ...]) -> None:  # line 897
    # Called with ("token_count", "line_num") — does NOT strip OKF fields (confirmed V3)

# content_store.py
def _node_path(self, tree_name: str, node_id: str) -> Path:      # line 86
    # self._tree_dir(tree_name) / f"{node_id}.md"
# _NODE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")             # line 34
```

### Does NOT Exist

- ~~`tree_ops.reindex_concept_ids()`~~ — no such function; concept_ids are NOT reindexed
- ~~`toolkit._classify_type()`~~ — does not exist yet; this task adds the T3 step
- ~~`toolkit._project_sidecars()`~~ — does not exist yet; this task wires projection in
- ~~`content_store.load_by_concept_id()`~~ — no such method; modify `loader_for()` closure

---

## Implementation Notes

### Key Constraints

- **`write_node_id` in utils.py** only touches `node_id` — do NOT modify it. The
  concept_id preservation is inherent because `write_node_id` never writes
  `concept_id`. Add a test to lock this guarantee.
- **T3 step is optional** — if no LLM adapter is available, skip classification and
  use `ConceptType.SECTION` as the structural fallback. The ingest pipeline must not
  break when classification is unavailable.
- **Projection is opt-in initially** — only trigger `project_sidecars()` when the tree
  has OKF-enriched nodes (check for `concept_id` presence). This ensures backward
  compatibility for trees that haven't been migrated.
- **Content store dual-key loading**: the `loader_for()` closure should try loading by
  flattened concept_id first, then fall back to node_id. This handles the transition
  period where some sidecars are still keyed by node_id.
- **Tool registration**: follow the existing pattern in `PageIndexToolkit` for
  registering tools. The OKF tools need access to the tree, graph, and content_store —
  pass them via the toolkit instance.
- **Run ALL existing tests** after changes to confirm no regressions.

---

## Acceptance Criteria

- [ ] `reindex_node_ids` preserves `concept_id` on all nodes (test added)
- [ ] `splice_subtree` assigns `concept_id` to new nodes if missing
- [ ] `delete_node` cleans up concept_id-keyed sidecar
- [ ] `insert_content` / `import_pdf` run T3 type classification step
- [ ] `_persist()` triggers `project_sidecars()` for enriched trees
- [ ] OKF read tools are registered and accessible via the toolkit
- [ ] Content store accepts flattened concept_id filenames
- [ ] `loader_for()` closure loads by concept_id with node_id fallback
- [ ] **All existing tests still pass** — no regressions
- [ ] Trees without OKF fields continue to work (backward compatibility)
- [ ] `insert_content` / `import_pdf` work without LLM adapter (Section fallback)
- [ ] All new tests pass: `pytest packages/ai-parrot/tests/knowledge/pageindex/ -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/pageindex/test_okf_integration.py
import pytest


class TestTreeOpsConceptIdPreservation:
    def test_reindex_preserves_concept_id(self):
        tree = {
            "structure": [
                {"node_id": "0000", "concept_id": "intro", "title": "Intro", "nodes": []},
                {"node_id": "0001", "concept_id": "controls", "title": "Controls", "nodes": []},
            ]
        }
        from parrot.knowledge.pageindex.tree_ops import reindex_node_ids
        reindex_node_ids(tree)
        assert tree["structure"][0]["concept_id"] == "intro"
        assert tree["structure"][1]["concept_id"] == "controls"

    def test_splice_preserves_existing_concept_id(self):
        # Splice a new subtree; existing nodes keep their concept_id
        ...

    def test_delete_preserves_sibling_concept_id(self):
        # Delete a node; remaining nodes keep their concept_id
        ...


class TestToolkitT3Step:
    @pytest.mark.asyncio
    async def test_insert_content_assigns_type(self):
        # insert_content → T3 step → node has type field
        ...

    @pytest.mark.asyncio
    async def test_insert_content_fallback_without_llm(self):
        # insert_content without adapter → type = "Section"
        ...


class TestContentStoreDualKey:
    def test_load_by_flattened_concept_id(self, tmp_path):
        from parrot.knowledge.pageindex.content_store import NodeContentStore
        store = NodeContentStore(tmp_path)
        store.save("tree", "playbooks--aws-ir", "content")
        assert store.load("tree", "playbooks--aws-ir") == "content"

    def test_loader_for_concept_id(self, tmp_path):
        from parrot.knowledge.pageindex.content_store import NodeContentStore
        store = NodeContentStore(tmp_path)
        store.save("tree", "playbooks--aws-ir", "content")
        loader = store.loader_for("tree")
        assert loader("playbooks--aws-ir") == "content"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/okf-knowledge-layer.spec.md`
2. **Check dependencies** — ALL previous FEAT-238 tasks (TASK-1552–1558) must be done
3. **Verify** all existing file signatures haven't changed since spec was written
4. **Run existing tests FIRST** to establish a clean baseline
5. **Make changes incrementally** — modify one file, run its tests, proceed
6. **Run the FULL test suite** after all changes to confirm no regressions
7. **Move this file** to `sdd/tasks/completed/` when done

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
