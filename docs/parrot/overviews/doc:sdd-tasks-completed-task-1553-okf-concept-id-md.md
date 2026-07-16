---
type: Wiki Overview
title: 'TASK-1553: Deterministic Slug Generation (concept_id.py)'
id: doc:sdd-tasks-completed-task-1553-okf-concept-id-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: (which is volatile — reassigned by `reindex_node_ids` on every mutation),
  `concept_id`
relates_to:
- concept: mod:parrot.knowledge.pageindex.okf.concept_id
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.utils
  rel: mentions
---

# TASK-1553: Deterministic Slug Generation (concept_id.py)

**Feature**: FEAT-238 — OKF Knowledge Layer over PageIndex
**Spec**: `sdd/specs/okf-knowledge-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`concept_id` is the stable identity anchor for the entire OKF layer. Unlike `node_id`
(which is volatile — reassigned by `reindex_node_ids` on every mutation), `concept_id`
survives reindex, splice, and delete operations. All links, the in-memory graph, and
sidecar filenames are keyed by `concept_id`.

The slug must be **deterministic**: given the same title and parent path, the same
`concept_id` is produced every time. Collisions (duplicate titles at the same level)
are resolved with numeric suffixes that are also stable across runs.

Implements: Spec §2 (D3, D8), Spec §3 Module 2.

---

## Scope

- Implement `concept_id.py` in `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/`:
  - `derive_concept_id(title: str, parent_path: str = "") -> str` — deterministic slug
    from title, scoped under parent_path. Produces kebab-case slugs like
    `playbooks/aws-incident-response`.
  - `dedup_concept_ids(nodes: list[dict]) -> None` — resolve slug collisions with
    numeric suffixes (`-2`, `-3`, etc.). Must be stable across runs — sort nodes by
    tree position (depth-first order) before assigning suffixes.
  - `assign_concept_ids(tree: dict) -> None` — walk the tree depth-first, derive
    concept_ids for all nodes, dedup, and write `concept_id` onto each node dict.
- Write unit tests.

**NOT in scope**: Frontmatter projection (TASK-1554), graph keying (TASK-1555),
sidecar filename rename (TASK-1556).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/concept_id.py` | CREATE | Slug generation + dedup + tree assignment |
| `packages/ai-parrot/tests/knowledge/pageindex/test_okf_concept_id.py` | CREATE | Unit tests |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/__init__.py` | MODIFY | Add re-exports |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import re                                   # stdlib
import unicodedata                          # stdlib (for slug normalization)
from typing import Any, Optional            # stdlib
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/utils.py:217
def write_node_id(data: Any, node_id: int = 0) -> int:
    """Assign sequential node_id values to a tree structure."""
    # Walks depth-first — follow same traversal order for concept_id assignment

# packages/ai-parrot/src/parrot/knowledge/pageindex/utils.py:231
def get_nodes(structure: Any) -> list[dict]:
    """Flatten a tree into a list of nodes (without children)."""

# packages/ai-parrot/src/parrot/knowledge/pageindex/utils.py:210
def sanitize_filename(filename: str, replacement: str = "-") -> str:
    """Replace filesystem-unsafe characters."""
```

### Does NOT Exist

- ~~`parrot.knowledge.pageindex.okf.concept_id`~~ — does not exist yet; this task creates it
- ~~`node["concept_id"]`~~ — does not exist on current nodes; this task's `assign_concept_ids` adds it
- ~~`parrot.knowledge.pageindex.utils.slugify`~~ — no slugify function exists in utils

---

## Implementation Notes

### Pattern to Follow

```python
def derive_concept_id(title: str, parent_path: str = "") -> str:
    """Deterministic slug from title, scoped under parent_path.

    Examples:
        derive_concept_id("AWS Incident Response") -> "aws-incident-response"
        derive_concept_id("IR-4", "controls/nist-800-53") -> "controls/nist-800-53/ir-4"
    """
    slug = _slugify(title)
    if parent_path:
        return f"{parent_path.rstrip('/')}/{slug}"
    return slug


def _slugify(text: str) -> str:
    """Convert text to a URL-safe, deterministic kebab-case slug."""
    # Normalize unicode, lowercase, replace non-alnum with hyphens, collapse, strip
    ...
```

### Key Constraints

- **Determinism is paramount**: same input → same output, always. No randomness, no
  timestamps, no counters that depend on external state.
- **Dedup must be stable**: sort nodes by depth-first tree position before assigning
  suffixes. The first occurrence (in DFS order) gets the bare slug; subsequent
  duplicates get `-2`, `-3`, etc.
- **Parent path scoping**: a node's `concept_id` includes its ancestors' slugs
  (e.g. `section-a/subsection-b/topic`). This means `assign_concept_ids` must walk
  depth-first, building up the path.
- **Slug format**: lowercase, hyphens between words, no special chars. Forward slashes
  separate hierarchy levels only (from parent_path).
- **Handle edge cases**: empty titles → `"untitled"`, titles that are all punctuation,
  very long titles (truncate at ~80 chars before the suffix).

---

## Acceptance Criteria

- [ ] `derive_concept_id("AWS Incident Response")` → `"aws-incident-response"`
- [ ] `derive_concept_id("IR-4", "controls/nist-800-53")` → `"controls/nist-800-53/ir-4"`
- [ ] `dedup_concept_ids` resolves collisions with stable numeric suffixes
- [ ] `assign_concept_ids` walks a tree depth-first and writes `concept_id` on every node
- [ ] Running `assign_concept_ids` twice on the same tree produces identical `concept_id` values
- [ ] Empty/degenerate titles produce valid slugs (e.g. `"untitled"`)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/pageindex/test_okf_concept_id.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/knowledge/pageindex/okf/`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/pageindex/test_okf_concept_id.py
import pytest
from parrot.knowledge.pageindex.okf.concept_id import (
    derive_concept_id,
    dedup_concept_ids,
    assign_concept_ids,
)


class TestDeriveConceptId:
    def test_simple_title(self):
        assert derive_concept_id("AWS Incident Response") == "aws-incident-response"

    def test_with_parent_path(self):
        result = derive_concept_id("IR-4", "controls/nist-800-53")
        assert result == "controls/nist-800-53/ir-4"

    def test_special_characters_stripped(self):
        result = derive_concept_id("HIPAA §164.312(a)(1)")
        assert "/" not in result or result.count("/") == 0
        assert result  # non-empty

    def test_empty_title(self):
        assert derive_concept_id("") == "untitled"

    def test_deterministic(self):
        a = derive_concept_id("Some Title", "parent")
        b = derive_concept_id("Some Title", "parent")
        assert a == b


class TestDedupConceptIds:
    def test_no_collisions(self):
        nodes = [
            {"concept_id": "a", "title": "A"},
            {"concept_id": "b", "title": "B"},
        ]
        dedup_concept_ids(nodes)
        assert nodes[0]["concept_id"] == "a"
        assert nodes[1]["concept_id"] == "b"

    def test_collision_suffixes(self):
        nodes = [
            {"concept_id": "overview", "title": "Overview"},
            {"concept_id": "overview", "title": "Overview"},
            {"concept_id": "overview", "title": "Overview"},
        ]
        dedup_concept_ids(nodes)
        assert nodes[0]["concept_id"] == "overview"
        assert nodes[1]["concept_id"] == "overview-2"
        assert nodes[2]["concept_id"] == "overview-3"

    def test_stable_across_runs(self):
        nodes = [
            {"concept_id": "x", "title": "X"},
            {"concept_id": "x", "title": "X"},
        ]
        dedup_concept_ids(nodes)
        first_run = [n["concept_id"] for n in nodes]
        # Reset
        nodes[0]["concept_id"] = "x"
        nodes[1]["concept_id"] = "x"
        dedup_concept_ids(nodes)
        assert [n["concept_id"] for n in nodes] == first_run


class TestAssignConceptIds:
    def test_assigns_to_all_nodes(self):
        tree = {
            "structure": [
                {"title": "Root", "node_id": "0000", "nodes": [
                    {"title": "Child", "node_id": "0001", "nodes": []},
                ]},
            ]
        }
        assign_concept_ids(tree)
        root = tree["structure"][0]
        assert "concept_id" in root
        assert "concept_id" in root["nodes"][0]

    def test_idempotent(self):
        tree = {
            "structure": [
                {"title": "Root", "node_id": "0000", "nodes": []},
            ]
        }
        assign_concept_ids(tree)
        first = tree["structure"][0]["concept_id"]
        assign_concept_ids(tree)
        assert tree["structure"][0]["concept_id"] == first
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/okf-knowledge-layer.spec.md` for full context
2. **Check dependencies** — none; this is a leaf task (parallel with TASK-1552)
3. **Verify the Codebase Contract** — grep for existing slug/concept_id utilities
4. **Implement** `concept_id.py` with all three functions
5. **Write tests** and verify they pass
6. **Update** `okf/__init__.py` re-exports
7. **Move this file** to `sdd/tasks/completed/` when done
8. **Update index** → `"done"`

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-15
**Notes**: Implemented derive_concept_id, dedup_concept_ids, and assign_concept_ids in concept_id.py. Added re-exports to __init__.py. All 24 tests pass. No linting errors.

**Deviations from spec**: none
