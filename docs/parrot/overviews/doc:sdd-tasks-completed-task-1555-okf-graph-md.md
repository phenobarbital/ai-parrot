---
type: Wiki Overview
title: 'TASK-1555: In-Memory Knowledge Graph (graph.py)'
id: doc:sdd-tasks-completed-task-1555-okf-graph-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The in-memory knowledge graph is the backbone that enables multi-hop retrieval.
relates_to:
- concept: mod:parrot.knowledge.pageindex
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.content_store
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.okf.graph
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.okf.ontology
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.utils
  rel: mentions
---

# TASK-1555: In-Memory Knowledge Graph (graph.py)

**Feature**: FEAT-238 — OKF Knowledge Layer over PageIndex
**Spec**: `sdd/specs/okf-knowledge-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1552, TASK-1553
**Assigned-to**: unassigned

---

## Context

The in-memory knowledge graph is the backbone that enables multi-hop retrieval.
It resolves markdown hyperlinks and typed `relates_to` edges into an adjacency
structure keyed by `concept_id`. This is what makes the `ComplianceEvidenceAgent`'s
traversal queries possible — e.g., safeguard → control → evidence.

The graph is built at load time, not persisted (D4 — ArangoDB persistence is phase 2).
Broken links (target concept absent) are tolerated and collected for lint — never an
error (OKF §5.3 / §9).

Implements: Spec §2.3 (In-memory knowledge graph), Spec §3 Module 4.

---

## Scope

- Implement `graph.py` in `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/`:
  - `KnowledgeGraph` class:
    - `__init__(self, tree: dict)` — builds adjacency from `relates_to` edges + parsed
      markdown hyperlinks in sidecar bodies.
    - `neighbors(self, concept_id: str, rel: Optional[str] = None) -> list[dict]` —
      return neighbors, optionally filtered by relation type.
    - `trace(self, concept_id: str, rel_chain: list[str]) -> list[list[str]]` —
      multi-hop traversal following a chain of typed relations (e.g.
      `[maps_to, satisfied_by]`).
    - `broken_links(self) -> list[dict]` — return all edges whose target `concept_id`
      does not exist in the tree.
    - `concepts(self) -> set[str]` — return all known concept_ids.
  - `parse_markdown_links(body: str) -> list[str]` — extract markdown link targets
    from a body string, skipping links inside fenced code blocks.
  - `build_graph(tree: dict, content_loader: Callable) -> KnowledgeGraph` — convenience
    function that loads bodies via `content_loader` and builds the full graph.
- Write unit tests.

**NOT in scope**: ArangoDB persistence (phase 2), LLM-inferred edge classification (D10),
tool definitions (TASK-1558).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/graph.py` | CREATE | KnowledgeGraph + link parser |
| `packages/ai-parrot/tests/knowledge/pageindex/test_okf_graph.py` | CREATE | Unit tests |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/__init__.py` | MODIFY | Add re-exports |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# From TASK-1552 (ontology):
from parrot.knowledge.pageindex.okf.ontology import RelationType, RelatesTo

# From existing utils (for tree walking):
from parrot.knowledge.pageindex.utils import get_nodes             # utils.py:231
from parrot.knowledge.pageindex.utils import structure_to_list     # utils.py:249

# NodeContentStore.loader_for() returns a Callable[[str], Optional[str]]
from parrot.knowledge.pageindex.content_store import NodeContentStore  # content_store.py:37
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/utils.py:231
def get_nodes(structure: Any) -> list[dict]:
    """Flatten a tree into a list of nodes (without children)."""

# packages/ai-parrot/src/parrot/knowledge/pageindex/utils.py:249
def structure_to_list(structure: Any) -> list[dict]:
    """Flatten a tree into a list preserving parent nodes."""

# packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py:197
def loader_for(self, tree_name: str) -> Callable[[str], Optional[str]]:
    """Return a closure node_id -> Optional[str] for tree_name."""
```

### Does NOT Exist

- ~~`parrot.knowledge.pageindex.graph`~~ — no graph module exists at the pageindex level
- ~~`KnowledgeGraph`~~ — does not exist anywhere
- ~~`parrot.knowledge.pageindex.okf.graph`~~ — this task creates it
- ~~`node["edges"]`~~ — nodes do not have an "edges" field; edges come from `relates_to`

---

## Implementation Notes

### Pattern to Follow

```python
class KnowledgeGraph:
    def __init__(self, tree: dict) -> None:
        self._adj: dict[str, list[dict]] = {}  # concept_id -> [{concept, rel}, ...]
        self._concepts: set[str] = set()
        self._broken: list[dict] = []
        self._build(tree)

    def _build(self, tree: dict) -> None:
        # 1. Collect all concept_ids
        # 2. For each node, add relates_to edges to adjacency
        # 3. For each node body, parse markdown links → relates_to with rel=references
        # 4. Collect broken links (target not in self._concepts)
        ...
```

### Key Constraints

- **Markdown link parsing**: extract `[text](/path)` and `[text](path)` patterns from
  body markdown. Skip links inside fenced code blocks (` ``` `). Bundle-relative links
  (recommended by OKF §5.1) resolve to concept_ids by stripping leading `/`.
- **Untyped prose links** become `rel: references` (noise). Typed `relates_to` edges
  from the JSON are gold. Both go into the same adjacency.
- **Broken links are tolerated**: when a link target is not a known `concept_id`,
  collect it in `_broken` but do not raise. This follows OKF §5.3/§9.
- **Multi-hop `trace()`**: follows a chain like `[maps_to, satisfied_by]` — at each
  hop, filter neighbors by the next `rel` in the chain. Return all paths found.
- **No ArangoDB dependency** — purely in-memory, standard library data structures.

---

## Acceptance Criteria

- [ ] `KnowledgeGraph` builds from a tree dict with `relates_to` edges
- [ ] `neighbors()` returns correct edges, filterable by `rel`
- [ ] `trace()` follows multi-hop typed chains correctly
- [ ] `broken_links()` reports edges to non-existent concept_ids
- [ ] `parse_markdown_links()` extracts links, skipping fenced code blocks
- [ ] Graph is built from both `relates_to` and parsed markdown links
- [ ] Broken links are tolerated — never raise an exception
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/pageindex/test_okf_graph.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/pageindex/test_okf_graph.py
import pytest
from parrot.knowledge.pageindex.okf.graph import (
    KnowledgeGraph,
    parse_markdown_links,
)


class TestParseMarkdownLinks:
    def test_extracts_relative_links(self):
        body = "See [control](/controls/nist-ir-4) for details."
        links = parse_markdown_links(body)
        assert "controls/nist-ir-4" in links

    def test_skips_fenced_code_blocks(self):
        body = "text\n```\n[link](/inside-code)\n```\n[real](/outside)"
        links = parse_markdown_links(body)
        assert "outside" in links
        assert "inside-code" not in links

    def test_extracts_multiple_links(self):
        body = "[a](/one) and [b](/two)"
        links = parse_markdown_links(body)
        assert len(links) == 2


@pytest.fixture
def tree_with_edges():
    return {
        "structure": [
            {
                "node_id": "0000",
                "concept_id": "safeguards/hipaa-164",
                "title": "HIPAA 164",
                "relates_to": [
                    {"concept": "controls/nist-ir-4", "rel": "maps_to"}
                ],
                "nodes": [],
            },
            {
                "node_id": "0001",
                "concept_id": "controls/nist-ir-4",
                "title": "NIST IR-4",
                "relates_to": [
                    {"concept": "evidence/ir-plan-v2", "rel": "satisfied_by"}
                ],
                "nodes": [],
            },
            {
                "node_id": "0002",
                "concept_id": "evidence/ir-plan-v2",
                "title": "IR Plan v2",
                "relates_to": [],
                "nodes": [],
            },
        ],
    }


class TestKnowledgeGraph:
    def test_neighbors(self, tree_with_edges):
        g = KnowledgeGraph(tree_with_edges)
        n = g.neighbors("safeguards/hipaa-164")
        assert any(e["concept"] == "controls/nist-ir-4" for e in n)

    def test_neighbors_filtered_by_rel(self, tree_with_edges):
        g = KnowledgeGraph(tree_with_edges)
        n = g.neighbors("safeguards/hipaa-164", rel="maps_to")
        assert len(n) == 1
        assert n[0]["concept"] == "controls/nist-ir-4"

    def test_trace_multi_hop(self, tree_with_edges):
        g = KnowledgeGraph(tree_with_edges)
        paths = g.trace("safeguards/hipaa-164", ["maps_to", "satisfied_by"])
        assert any("evidence/ir-plan-v2" in path for path in paths)

    def test_broken_links_collected(self):
        tree = {
            "structure": [
                {
                    "node_id": "0000",
                    "concept_id": "a",
                    "title": "A",
                    "relates_to": [{"concept": "nonexistent", "rel": "references"}],
                    "nodes": [],
                },
            ],
        }
        g = KnowledgeGraph(tree)
        assert len(g.broken_links()) == 1

    def test_concepts(self, tree_with_edges):
        g = KnowledgeGraph(tree_with_edges)
        assert "controls/nist-ir-4" in g.concepts()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/okf-knowledge-layer.spec.md` for full context
2. **Check dependencies** — verify TASK-1552 (ontology) and TASK-1553 (concept_id) are done
3. **Verify** that `get_nodes` and `structure_to_list` still exist in `utils.py`
4. **Implement** `graph.py` with the KnowledgeGraph class
5. **Write tests** and verify they pass
6. **Move this file** to `sdd/tasks/completed/` when done

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-15
**Notes**: Implemented KnowledgeGraph class with neighbors(), trace(), broken_links(), concepts(), and add_prose_links(). Also implemented parse_markdown_links() skipping fenced code blocks, and build_graph() convenience factory. Added re-exports to __init__.py. All 29 tests pass. No linting errors.

**Deviations from spec**: none

**Deviations from spec**: none | describe if any
