---
type: Wiki Overview
title: 'TASK-1566: Knowledge Lint Engine'
id: doc:sdd-tasks-completed-task-1566-knowledge-lint-engine-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements Karpathy's lint pattern for the OKF knowledge graph. The KnowledgeGraph
relates_to:
- concept: mod:parrot.knowledge.pageindex.content_store
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.okf.graph
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.okf.lint
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.utils
  rel: mentions
---

# TASK-1566: Knowledge Lint Engine

**Feature**: FEAT-216 — OKF Knowledge Lint & Bundle Interchange
**Spec**: `sdd/specs/FEAT-216-okf-knowledge-lint-and-bundle.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1565
**Assigned-to**: unassigned

---

## Context

Implements Karpathy's lint pattern for the OKF knowledge graph. The KnowledgeGraph
already collects broken links in `_broken` (graph.py:99) but doesn't surface them
as a structured report. This task creates a new `lint.py` module with 4 lint checks:
orphan concepts, broken links, missing concepts, stale claims.

Implements: Spec §3 Module 2.

---

## Scope

- Create `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/lint.py` with:
  - `LintFinding` Pydantic model (kind, concept_id, detail, severity)
  - `LintReport` Pydantic model (tree_name, orphans, broken_links, missing_concepts, stale_claims, total_findings, total_concepts)
  - `lint_knowledge_base(graph, tree, content_store, stale_days=90) -> LintReport` function
- Implement 4 lint checks:
  - **Orphan detection**: concept nodes with zero inbound `relates_to` edges
  - **Broken link audit**: surface `KnowledgeGraph.broken_links()` as `LintFinding` objects
  - **Missing concept pages**: concepts referenced in `relates_to` but absent from the graph
  - **Stale claims**: concepts with `timestamp` older than `stale_days` from now
- Export new symbols from `okf/__init__.py`
- Create unit tests in `test_okf_lint.py`

**NOT in scope**: bundle import/export, OKFToolkit integration (TASK-1569), contradiction detection.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/lint.py` | CREATE | Lint engine with LintFinding, LintReport, lint_knowledge_base() |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/__init__.py` | MODIFY | Export lint symbols |
| `packages/ai-parrot/tests/knowledge/pageindex/test_okf_lint.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.pageindex.okf.graph import KnowledgeGraph  # verified: graph.py:73
from parrot.knowledge.pageindex.okf.graph import build_graph      # verified: graph.py:240
from parrot.knowledge.pageindex.content_store import NodeContentStore  # verified: content_store.py
from parrot.knowledge.pageindex.utils import structure_to_list    # verified: utils.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/okf/graph.py
class KnowledgeGraph:
    def __init__(self, tree: dict[str, Any]) -> None:  # line 88
    # self._adj: dict[str, list[dict]] = {}  — adjacency (concept_id → list of edge dicts)
    # self._in_adj: dict[str, list[dict]] = {}  — reverse adjacency
    # self._broken: list[dict] = []  — broken edge dicts: {"source": cid, "target": target, "rel": rel}
    # self._concepts: set[str] = set()  — known concept_ids
    def neighbors(self, concept_id: str, rel: Optional[str] = None) -> list[dict]:  # line 167
    def broken_links(self) -> list[dict]:  # line 223 — returns self._broken
    def concepts(self) -> set[str]:  # line 231 — returns self._concepts
```

### Does NOT Exist
- ~~`KnowledgeGraph.orphans()`~~ — no such method; compute by scanning `_in_adj`
- ~~`KnowledgeGraph.missing_concepts()`~~ — no such method
- ~~`KnowledgeGraph._in_adj`~~ — verify this exists; if not, compute inbound edges by iterating `_adj`
- ~~`okf.lint`~~ — this module does not exist yet; this task creates it

---

## Implementation Notes

### Pattern to Follow
```python
# Follow the ProjectionReport pattern from projection.py:39
class LintReport(BaseModel):
    tree_name: str
    orphans: list[LintFinding] = Field(default_factory=list)
    broken_links: list[LintFinding] = Field(default_factory=list)
    missing_concepts: list[LintFinding] = Field(default_factory=list)
    stale_claims: list[LintFinding] = Field(default_factory=list)
    total_findings: int = 0
    total_concepts: int = 0
```

### Key Constraints
- Pure function: `lint_knowledge_base()` has no side effects (reads only)
- Orphan detection: a concept with zero inbound edges from `_adj` (or `_in_adj`). Verify how KnowledgeGraph stores reverse edges — if `_in_adj` doesn't exist, build inbound edge set by iterating `_adj`.
- Stale claims: parse `timestamp` field from node dict. Use `datetime.fromisoformat()`. Flag if `(now - timestamp).days > stale_days`.
- `total_findings` = sum of all 4 categories
- `total_concepts` = `len(graph.concepts())`

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/graph.py` — KnowledgeGraph to consume
- `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/projection.py:39` — ProjectionReport pattern

---

## Acceptance Criteria

- [ ] `lint.py` created with `LintFinding`, `LintReport`, `lint_knowledge_base()`
- [ ] Orphan detection: concepts with zero inbound `relates_to` edges found
- [ ] Broken link audit: `KnowledgeGraph.broken_links()` surfaced as findings
- [ ] Missing concept pages: concepts referenced in `relates_to` but not in graph detected
- [ ] Stale claims: concepts with `timestamp` older than `stale_days` flagged
- [ ] Empty graph returns report with zero findings
- [ ] Exports added to `okf/__init__.py`
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/pageindex/test_okf_lint.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/pageindex/test_okf_lint.py
import pytest
from unittest.mock import MagicMock
from parrot.knowledge.pageindex.okf.lint import (
    lint_knowledge_base,
    LintReport,
    LintFinding,
)
from parrot.knowledge.pageindex.okf.graph import KnowledgeGraph


def _make_tree_with_orphan():
    """Tree where node B has zero inbound edges."""
    ...

def _make_tree_with_broken_link():
    """Tree where node A references non-existent concept 'ghost'."""
    ...


def test_lint_finds_orphans():
    tree = _make_tree_with_orphan()
    graph = KnowledgeGraph(tree)
    report = lint_knowledge_base(graph, tree, MagicMock())
    assert len(report.orphans) >= 1
    assert report.orphans[0].kind == "orphan"


def test_lint_finds_broken_links():
    tree = _make_tree_with_broken_link()
    graph = KnowledgeGraph(tree)
    report = lint_knowledge_base(graph, tree, MagicMock())
    assert len(report.broken_links) >= 1


def test_lint_finds_missing_concepts():
    # Concept references a target not in the graph's concepts set
    ...


def test_lint_finds_stale_claims():
    # Concept with timestamp > 90 days old
    ...


def test_lint_empty_graph():
    tree = {"structure": []}
    graph = KnowledgeGraph(tree)
    report = lint_knowledge_base(graph, tree, MagicMock())
    assert report.total_findings == 0
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/FEAT-216-okf-knowledge-lint-and-bundle.spec.md`
2. **Check dependencies** — TASK-1565 must be completed (ConceptType.OTHER exists)
3. **Read `graph.py`** carefully to understand `_adj`, `_in_adj` (if it exists), `_broken`, `_concepts`
4. **Implement** `lint.py` as a pure function module
5. **Run tests**: `pytest packages/ai-parrot/tests/knowledge/pageindex/test_okf_lint.py -v`

---

## Completion Note

*(Agent fills this in when done)*
