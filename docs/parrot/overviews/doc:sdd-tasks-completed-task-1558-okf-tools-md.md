---
type: Wiki Overview
title: 'TASK-1558: Named Read Tools (tools.py)'
id: doc:sdd-tasks-completed-task-1558-okf-tools-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The enriched JSON + in-memory graph turn `PageIndexToolkit` from a single
  `_search_for`
relates_to:
- concept: mod:parrot.knowledge.pageindex.content_store
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.okf.graph
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.okf.ontology
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.okf.tools
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.utils
  rel: mentions
- concept: mod:parrot.tools
  rel: mentions
---

# TASK-1558: Named Read Tools (tools.py)

**Feature**: FEAT-238 — OKF Knowledge Layer over PageIndex
**Spec**: `sdd/specs/okf-knowledge-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1552, TASK-1555
**Assigned-to**: unassigned

---

## Context

The enriched JSON + in-memory graph turn `PageIndexToolkit` from a single `_search_for`
into a typed retrieval/traversal surface. This task creates the **separate named tools**
(spec constraint — no branching `search`) that the `ComplianceEvidenceAgent` and other
agents will use for multi-hop compliance queries.

Each tool is a **separate named tool** exposing the controlled `type` enum. Type-scoped
tools apply `type` as an **exact pre-filter** (deterministic gate) before ranking.

This is the payoff: the query "which NIST control satisfies this HIPAA safeguard, and
what evidence proves it" decomposes into a tool chain.

Implements: Spec §2.5 (Toolkit surface), Spec §3 Module 7.

---

## Scope

- Implement `tools.py` in `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/`:
  - `find_by_type(type: ConceptType, query: str) -> list[dict]` — hybrid search with
    an **exact `type` pre-filter** on the candidate set, then ranker.
  - `list_concepts(type: Optional[ConceptType] = None) -> list[dict]` — faceted browse
    over the ToC; optionally filtered by type.
  - `get_concept(concept_id: str) -> dict` — returns the self-describing unit
    (frontmatter + body); stable across reindex.
  - `get_related(concept_id: str, rel: Optional[str] = None) -> list[dict]` —
    in-memory graph traversal; typed `rel` filter.
  - `trace_mapping(concept_id: str) -> list[list[str]]` — multi-hop typed chain
    traversal (e.g. safeguard → controls → evidence).
  - `cite(concept_id: str) -> dict` — per-node provenance: document + page span + URL.
- Each function should be decorated with `@tool` for registration.
- Write unit tests.

**NOT in scope**: Write tools (create/edit concept, set edge — deferred to HITL loop),
toolkit integration/registration into PageIndexToolkit (TASK-1559).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/tools.py` | CREATE | 6 named read tools |
| `packages/ai-parrot/tests/knowledge/pageindex/test_okf_tools.py` | CREATE | Unit tests |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/__init__.py` | MODIFY | Add re-exports |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# From FEAT-238 tasks:
from parrot.knowledge.pageindex.okf.ontology import ConceptType, RelationType
from parrot.knowledge.pageindex.okf.graph import KnowledgeGraph

# Tool decorator:
from parrot.tools import tool                 # verified: parrot/tools/__init__.py

# For content loading:
from parrot.knowledge.pageindex.content_store import NodeContentStore  # content_store.py:37
from parrot.knowledge.pageindex.utils import find_node_by_id           # utils.py:308
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/okf/graph.py (TASK-1555)
class KnowledgeGraph:
    def neighbors(self, concept_id: str, rel: Optional[str] = None) -> list[dict]: ...
    def trace(self, concept_id: str, rel_chain: list[str]) -> list[list[str]]: ...
    def broken_links(self) -> list[dict]: ...
    def concepts(self) -> set[str]: ...

# packages/ai-parrot/src/parrot/knowledge/pageindex/okf/ontology.py (TASK-1552)
class ConceptType(str, Enum): ...   # 11 values
class RelationType(str, Enum): ...  # 8 values
```

### Does NOT Exist

- ~~`PageIndexToolkit.find_by_type()`~~ — does not exist; this task creates standalone tools
- ~~`PageIndexToolkit.get_related()`~~ — does not exist
- ~~`parrot.knowledge.pageindex.okf.tools`~~ — does not exist yet; this task creates it
- ~~`KnowledgeGraph.search()`~~ — no search method on the graph; search uses the toolkit's existing search infra

---

## Implementation Notes

### Pattern to Follow

```python
from parrot.tools import tool


@tool
def find_by_type(type: ConceptType, query: str) -> list[dict]:
    """Search for concepts of a specific type.

    Applies an exact type pre-filter on the candidate set before ranking.

    Args:
        type: The concept type to filter by (e.g. Control, Safeguard).
        query: The search query string.

    Returns:
        List of matching concept dicts with title, concept_id, summary.
    """
    ...
```

### Key Constraints

- **Separate named tools** — each is its own `@tool`-decorated function. No branching
  search with optional `type=` parameter (spec §4 constraint — multi-purpose tools
  activate unreliably in LLMs).
- **Controlled vocabulary in tool schemas** — `find_by_type` and `list_concepts` expose
  the `ConceptType` enum in their parameter types. Free-text `type` arguments are
  forbidden.
- **Deterministic gate before probabilistic ranker** — `find_by_type` filters by `type`
  *exactly* before any hybrid ranking (the filter decides, the ranker proposes).
- **Type/rel filters are a guide, not a contract** — access restriction for sensitive
  types (e.g. `Evidence`) lives in the execution layer (PBAC), not here.
- **`get_concept` returns frontmatter + body** — the self-describing unit. Must use
  `concept_id` for lookup (stable), never `node_id`.
- **`trace_mapping` default chain**: `[maps_to, satisfied_by]` for compliance queries,
  but should accept arbitrary chains.
- **These tools need state** (the tree, graph, content_store). They will likely need
  to be methods on a class or use a closure pattern that receives the state at
  initialization. The `@tool` decorator should still work on the exposed methods.

---

## Acceptance Criteria

- [ ] `find_by_type` filters candidates by exact `type` before ranking
- [ ] `list_concepts` returns all concepts, optionally filtered by type
- [ ] `get_concept` returns frontmatter + body for a concept_id
- [ ] `get_related` returns graph neighbors, filterable by rel type
- [ ] `trace_mapping` follows multi-hop typed chains
- [ ] `cite` returns source provenance (document, pages, url)
- [ ] All tools are decorated with `@tool` and have clear docstrings
- [ ] Tools expose `ConceptType` enum in schemas, not free-text type args
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/pageindex/test_okf_tools.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/pageindex/test_okf_tools.py
import pytest
from parrot.knowledge.pageindex.okf.ontology import ConceptType


@pytest.fixture
def enriched_tree():
    return {
        "doc_name": "guide.pdf",
        "structure": [
            {
                "node_id": "0000",
                "concept_id": "safeguards/hipaa-164",
                "type": "Safeguard",
                "title": "HIPAA §164",
                "summary": "Security safeguard",
                "source": {"document": "guide.pdf", "pages": [1, 5]},
                "relates_to": [{"concept": "controls/nist-ir-4", "rel": "maps_to"}],
                "nodes": [],
            },
            {
                "node_id": "0001",
                "concept_id": "controls/nist-ir-4",
                "type": "Control",
                "title": "NIST IR-4",
                "summary": "Incident handling",
                "source": {"document": "guide.pdf", "pages": [6, 10]},
                "relates_to": [{"concept": "evidence/ir-plan", "rel": "satisfied_by"}],
                "nodes": [],
            },
            {
                "node_id": "0002",
                "concept_id": "evidence/ir-plan",
                "type": "Evidence",
                "title": "IR Plan",
                "summary": "Incident response plan document",
                "source": {"document": "guide.pdf", "pages": [11, 15]},
                "relates_to": [],
                "nodes": [],
            },
        ],
    }


class TestFindByType:
    def test_filters_by_type(self, enriched_tree):
        # find_by_type(ConceptType.CONTROL, "incident") → only Control-typed results
        ...

    def test_returns_empty_for_no_match(self, enriched_tree):
        # find_by_type(ConceptType.GUIDELINE, "anything") → []
        ...


class TestGetConcept:
    def test_returns_concept(self, enriched_tree):
        # get_concept("controls/nist-ir-4") → dict with title, summary, body
        ...

    def test_not_found_raises(self, enriched_tree):
        # get_concept("nonexistent") → raises or returns None
        ...


class TestGetRelated:
    def test_returns_neighbors(self, enriched_tree):
        # get_related("safeguards/hipaa-164") → includes nist-ir-4
        ...

    def test_filters_by_rel(self, enriched_tree):
        # get_related("safeguards/hipaa-164", rel="maps_to") → only maps_to edges
        ...


class TestTraceMapping:
    def test_multi_hop_chain(self, enriched_tree):
        # trace_mapping("safeguards/hipaa-164") → path through control to evidence
        ...


class TestCite:
    def test_returns_provenance(self, enriched_tree):
        # cite("controls/nist-ir-4") → {document, pages, url}
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/okf-knowledge-layer.spec.md` — especially §2.5
2. **Check dependencies** — TASK-1552 (ontology) and TASK-1555 (graph) must be done
3. **Verify** the `@tool` decorator import path and usage pattern
4. **Implement** all 6 tools with proper docstrings and enum-typed parameters
5. **Write tests** and verify they pass
6. **Move this file** to `sdd/tasks/completed/` when done

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-15
**Notes**: Implemented OKFToolkit class with 6 @tool-decorated methods: find_by_type (exact type pre-filter), list_concepts (faceted browse), get_concept (concept_id lookup), get_related (graph traversal), trace_mapping (multi-hop chain), cite (provenance). Added re-export to __init__.py. All 24 tests pass. No linting errors.

**Completed by**: sdd-worker
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
