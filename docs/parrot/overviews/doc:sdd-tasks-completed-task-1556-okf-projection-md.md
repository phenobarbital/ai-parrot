---
type: Wiki Overview
title: 'TASK-1556: Deterministic Sidecar & Index Generation (projection.py)'
id: doc:sdd-tasks-completed-task-1556-okf-projection-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This module is the "single writer" that projects the authoritative JSON onto
  disk.
relates_to:
- concept: mod:parrot.knowledge.pageindex.content_store
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.okf.frontmatter
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.okf.projection
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.utils
  rel: mentions
---

# TASK-1556: Deterministic Sidecar & Index Generation (projection.py)

**Feature**: FEAT-238 — OKF Knowledge Layer over PageIndex
**Spec**: `sdd/specs/okf-knowledge-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1552, TASK-1554
**Assigned-to**: unassigned

---

## Context

This module is the "single writer" that projects the authoritative JSON onto disk.
It generates frontmatter-enriched sidecars (one `<concept_id>.md` per node) and a
root `index.md` view. Both are **pure functions of the JSON** — regenerating from the
same tree MUST produce byte-identical output. No hand-edits; single writer.

This is where the D1 guarantee ("JSON authoritative; frontmatter is a deterministic
projection") is enforced on disk.

Implements: Spec §2.2 (Frontmatter Projection), §2.4 (`index.md`), Spec §3 Module 5.

---

## Scope

- Implement `projection.py` in `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/`:
  - `project_sidecar(node: dict, tree_name: str, body: str) -> str` — combine
    projected frontmatter + body into a complete sidecar string.
  - `project_sidecars(tree: dict, tree_name: str, content_store: NodeContentStore) -> ProjectionReport` —
    regenerate ALL sidecars from authoritative JSON. For each node: read the existing
    body from `content_store`, prepend projected frontmatter, and write back. Files are
    named `<concept_id>.md` (with slashes in concept_id flattened for the filename).
  - `generate_index_md(tree: dict, tree_name: str) -> str` — root-level `index.md`
    as a deterministic listing of the JSON ToC (one entry per top-level concept with
    title + summary, grouped, with bundle-relative links).
  - `flatten_concept_id_for_filename(concept_id: str) -> str` — convert
    slash-containing concept_ids to flat filenames (e.g. `playbooks/aws-ir` →
    `playbooks--aws-ir`).
- Write unit tests.

**NOT in scope**: Graph building (TASK-1555), migration (TASK-1557), tool definitions (TASK-1558).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/projection.py` | CREATE | Sidecar projection + index generation |
| `packages/ai-parrot/tests/knowledge/pageindex/test_okf_projection.py` | CREATE | Unit tests |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/__init__.py` | MODIFY | Add re-exports |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# From TASK-1554 (frontmatter):
from parrot.knowledge.pageindex.okf.frontmatter import project_frontmatter

# From existing codebase:
from parrot.knowledge.pageindex.content_store import NodeContentStore  # content_store.py:37
from parrot.knowledge.pageindex.utils import get_nodes                 # utils.py:231
from parrot.knowledge.pageindex.utils import structure_to_list         # utils.py:249
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py
class NodeContentStore:
    def save(self, tree_name: str, node_id: str, markdown: str) -> None:  # line 116
    def load(self, tree_name: str, node_id: str) -> Optional[str]:        # line 123
    def list_node_ids(self, tree_name: str) -> list[str]:                  # line 182
    def delete_node(self, tree_name: str, node_id: str) -> bool:           # line 148
    # _node_path builds: self._tree_dir(tree_name) / f"{node_id}.md"      # line 86-88
    # _NODE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")                  # line 34
    # NOTE: slash in concept_id is NOT valid per _NODE_ID_RE — must flatten
```

### Does NOT Exist

- ~~`NodeContentStore.save_with_frontmatter()`~~ — no such method; use `save()` with pre-composed string
- ~~`NodeContentStore.rename(old_id, new_id)`~~ — no rename method exists
- ~~`parrot.knowledge.pageindex.okf.projection`~~ — does not exist yet; this task creates it

---

## Implementation Notes

### Pattern to Follow

```python
def flatten_concept_id_for_filename(concept_id: str) -> str:
    """Convert slash-containing concept_id to a flat filename stem.

    Example: "playbooks/aws-incident-response" -> "playbooks--aws-incident-response"
    """
    return concept_id.replace("/", "--")


def project_sidecar(node: dict, tree_name: str, body: str) -> str:
    """Combine frontmatter + body into a complete sidecar string."""
    frontmatter = project_frontmatter(node, tree_name)
    return f"{frontmatter}\n{body}"


def project_sidecars(
    tree: dict,
    tree_name: str,
    content_store: NodeContentStore,
) -> ProjectionReport:
    """Regenerate all sidecars from authoritative JSON."""
    # 1. For each node in the tree:
    #    a. Read existing body (by node_id or concept_id — both may exist during migration)
    #    b. Build frontmatter from project_frontmatter()
    #    c. Write combined sidecar to concept_id-keyed filename via content_store.save()
    # 2. Return a report: nodes projected, files written, etc.
    ...
```

### Key Constraints

- **`_NODE_ID_RE` accepts `[A-Za-z0-9_-]{1,64}`** — slashes are NOT valid. The
  `flatten_concept_id_for_filename()` function MUST convert slashes to `--` (double
  dash) before passing to `content_store.save()`. This is the filename stem; the
  `content_store` adds `.md`.
- **Filename length**: the flattened concept_id must stay within 64 chars to pass
  `_validate_node_id`. If longer, truncate deterministically (hash suffix).
- **Body preservation**: the projection does NOT modify the body content. It only
  prepends/replaces the frontmatter header.
- **Old sidecar cleanup**: when `node_id.md` exists but the new filename is
  `concept_id.md`, the old file should be cleaned up. Track renamed files in the report.
- **`index.md` format** (D7): one entry per top-level concept, with title + summary.
  No frontmatter in `index.md` (per OKF §6, except optional `okf_version`).
  Sort entries deterministically.

---

## Acceptance Criteria

- [ ] `project_sidecar()` produces frontmatter + body in correct format
- [ ] `project_sidecars()` regenerates all sidecars from a tree's JSON
- [ ] **Byte-deterministic**: two runs on the same tree → identical files
- [ ] Sidecar filenames are `<flattened_concept_id>.md`, not `<node_id>.md`
- [ ] `flatten_concept_id_for_filename()` handles slashes correctly
- [ ] `generate_index_md()` produces a deterministic root-level index
- [ ] Old `<node_id>.md` sidecars are cleaned up when renamed
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/pageindex/test_okf_projection.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/pageindex/test_okf_projection.py
import pytest
from parrot.knowledge.pageindex.okf.projection import (
    project_sidecar,
    flatten_concept_id_for_filename,
    generate_index_md,
)


class TestFlattenConceptId:
    def test_simple_id(self):
        assert flatten_concept_id_for_filename("aws-ir") == "aws-ir"

    def test_slash_replaced(self):
        assert flatten_concept_id_for_filename("playbooks/aws-ir") == "playbooks--aws-ir"

    def test_multiple_slashes(self):
        result = flatten_concept_id_for_filename("a/b/c")
        assert "/" not in result
        assert result == "a--b--c"


class TestProjectSidecar:
    def test_combines_frontmatter_and_body(self):
        node = {
            "node_id": "0001",
            "concept_id": "test-concept",
            "type": "Section",
            "title": "Test",
            "summary": "A test node",
        }
        result = project_sidecar(node, "tree1", "Body content here.")
        assert result.startswith("---\n")
        assert "Body content here." in result

    def test_byte_deterministic(self):
        node = {
            "node_id": "0001",
            "concept_id": "test",
            "type": "Section",
            "title": "Test",
            "summary": "",
        }
        a = project_sidecar(node, "t", "body")
        b = project_sidecar(node, "t", "body")
        assert a == b


class TestGenerateIndexMd:
    def test_lists_top_level_concepts(self):
        tree = {
            "structure": [
                {"concept_id": "a", "title": "Alpha", "summary": "First", "nodes": []},
                {"concept_id": "b", "title": "Beta", "summary": "Second", "nodes": []},
            ]
        }
        index = generate_index_md(tree, "test_tree")
        assert "Alpha" in index
        assert "Beta" in index

    def test_deterministic(self):
        tree = {
            "structure": [
                {"concept_id": "a", "title": "A", "summary": "", "nodes": []},
            ]
        }
        assert generate_index_md(tree, "t") == generate_index_md(tree, "t")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/okf-knowledge-layer.spec.md`
2. **Check dependencies** — TASK-1552 (ontology) and TASK-1554 (frontmatter) done
3. **Verify** `NodeContentStore` API — confirm `save()`, `_NODE_ID_RE` still match
4. **Implement** `projection.py` with all functions
5. **Write tests** emphasizing byte-determinism
6. **Move this file** to `sdd/tasks/completed/` when done

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-15
**Notes**: Implemented flatten_concept_id_for_filename, project_sidecar, project_sidecars (byte-deterministic), generate_index_md, and ProjectionReport model. Old node_id.md cleanup implemented. Added re-exports to __init__.py. All 22 tests pass. No linting errors.

**Deviations from spec**: none
