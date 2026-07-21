---
type: Wiki Overview
title: 'TASK-1259: Cross-Domain Resolution — Level 1 Embedding Threshold'
id: doc:sdd-tasks-completed-task-1259-graphindex-cross-domain-resolution-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Cross-domain resolution is the mechanism that discovers implicit relationships
  between nodes produced by DIFFERENT extractors (e.g., a code symbol mentioned in
  a document section, or a concept that appears in both a rationale and a skill description).
  It uses embedding similarity
relates_to:
- concept: mod:parrot.knowledge.graphindex.schema
  rel: mentions
---

# TASK-1259: Cross-Domain Resolution — Level 1 Embedding Threshold

**Feature**: FEAT-187 — GraphIndex — Structured Knowledge Graph Indexing
**Spec**: `sdd/specs/graphindex.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1257, TASK-1258
**Assigned-to**: unassigned

---

## Context

Cross-domain resolution is the mechanism that discovers implicit relationships between nodes produced by DIFFERENT extractors (e.g., a code symbol mentioned in a document section, or a concept that appears in both a rationale and a skill description). It uses embedding similarity from the FAISS index built in TASK-1257 and operates over the assembled rustworkx graph from TASK-1258.

This is Level 1 resolution only — cosine similarity above a configurable threshold. Level 2 LLM verification is deferred to v2.

Implements: Spec §3 Module 5 (Resolution).

---

## Scope

- For each pair of nodes from DIFFERENT extractors, compute cosine similarity from the FAISS index
- If similarity > threshold (configurable), emit a `mentions` edge with `provenance="inferred"` and `confidence=sim`
- Threshold is configurable per kind-pair (single global threshold in v1)
- Skip pairs from the same extractor (same-extractor edges are already explicit)
- Return a list of new `UniversalEdge` objects to be merged into the graph
- Write unit tests for all resolution logic

**NOT in scope**: embedding computation (done by TASK-1257), graph assembly (done by TASK-1258), Level 2 LLM verification (v2)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/resolve.py` | CREATE | Cross-domain resolution: pairwise similarity check, threshold filtering, edge emission |
| `packages/ai-parrot/tests/knowledge/graphindex/test_resolve.py` | CREATE | Unit tests for resolution logic |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.graphindex.schema import (
    UniversalNode,       # node_id, kind, title, source_uri, provenance, ...
    UniversalEdge,       # source_id, target_id, kind, provenance, confidence
    Provenance,          # EXTRACTED, INFERRED, AMBIGUOUS
    NodeKind,            # DOCUMENT, SECTION, SYMBOL, CONCEPT, RATIONALE, SKILL
    EdgeKind,            # CONTAINS, REFERENCES, DEFINES, MENTIONS, EXPLAINS
)
```

### Dependencies from Prior Tasks
```python
# TASK-1257: FAISS index — provides similarity search
import faiss  # faiss-cpu; IndexFlatIP for cosine similarity on normalized vectors

# TASK-1258: Graph assembly — provides rustworkx PyDiGraph
import rustworkx  # rustworkx.PyDiGraph
```

### Does NOT Exist
- ~~Level 2 LLM verification~~ — deferred to v2
- ~~`resolve_with_llm()`~~ — not in v1
- ~~per-kind-pair threshold config~~ — v1 uses a single global threshold; per-kind-pair is a v1.5 enhancement

---

## Implementation Notes

### Pattern to Follow
```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class ResolutionConfig:
    """Configuration for cross-domain resolution."""
    threshold: float = 0.75  # global cosine similarity threshold
    max_edges_per_node: int = 10  # cap to prevent explosion

async def resolve_cross_domain(
    nodes: list[UniversalNode],
    faiss_index: faiss.Index,
    node_embeddings: dict[str, int],  # node_id -> faiss index position
    threshold: float = 0.75,
) -> list[UniversalEdge]:
    """Discover implicit cross-domain edges via embedding similarity.

    For each pair of nodes from different extractors, check cosine similarity.
    Emit 'mentions' edges where similarity exceeds threshold.
    """
    ...
```

### Key Constraints
- Async-first, type-hinted, Google-style docstrings
- Must skip pairs from the same extractor — check `source_uri` or extractor tag
- Confidence field on emitted edges must equal the cosine similarity score
- All emitted edges must have `provenance=Provenance.INFERRED`
- Must handle edge cases: nodes with no embedding, single-node graphs, all-same-extractor inputs

---

## Acceptance Criteria

- [ ] Pairwise similarity computed only for nodes from DIFFERENT extractors
- [ ] Edges emitted with `kind=EdgeKind.MENTIONS`, `provenance=Provenance.INFERRED`, `confidence=sim`
- [ ] Threshold is configurable; default is sensible (e.g., 0.75)
- [ ] Same-extractor pairs are skipped
- [ ] Edge cases handled: no embeddings, single node, empty input
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/graphindex/test_resolve.py -v`

---

## Test Specification

```python
import pytest
from parrot.knowledge.graphindex.schema import (
    UniversalNode, UniversalEdge, Provenance, NodeKind, EdgeKind,
)

class TestCrossDomainResolution:
    def test_emits_edge_above_threshold(self):
        """Two nodes from different extractors with high similarity should produce a mentions edge."""
        # Setup: two nodes, mock FAISS returning sim=0.9
        # Assert: one UniversalEdge with kind=MENTIONS, provenance=INFERRED, confidence=0.9

    def test_skips_below_threshold(self):
        """Pairs below threshold should not produce edges."""
        # Setup: two nodes, mock FAISS returning sim=0.3, threshold=0.75
        # Assert: empty result

    def test_skips_same_extractor(self):
        """Nodes from the same extractor should not be compared."""
        # Setup: two nodes from same source_uri / extractor
        # Assert: empty result even if similarity is high

    def test_empty_input(self):
        """Empty node list returns empty edge list."""
        # Assert: []

    def test_confidence_equals_similarity(self):
        """The confidence field must exactly equal the cosine similarity score."""
        # Setup: mock sim=0.82
        # Assert: edge.confidence == 0.82
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/graphindex.spec.md` for full context
2. **Check dependencies** — TASK-1257 (FAISS index) and TASK-1258 (graph assembly) must be done
3. **Verify the Codebase Contract** — confirm `UniversalNode`, `UniversalEdge`, FAISS index, and rustworkx graph interfaces
4. **Update status** in `sdd/tasks/index/graphindex.json` -> `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1259-graphindex-cross-domain-resolution.md`
8. **Update index** -> `"done"`

---

## Completion Note

*(Agent fills this in when done)*
