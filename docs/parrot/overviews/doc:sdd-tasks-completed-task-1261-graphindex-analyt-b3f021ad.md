---
type: Wiki Overview
title: 'TASK-1261: Analytics + Report — Centrality, Connections, GRAPH_REPORT.md'
id: doc:sdd-tasks-completed-task-1261-graphindex-analytics-report-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Analytics and reporting is the stage that extracts actionable insights from
  the assembled and resolved knowledge graph. It computes centrality metrics to identify
  "god-nodes" (highly connected concepts), ranks cross-domain edges by confidence
  to surface surprising connections, an
relates_to:
- concept: mod:parrot.bots.prompts
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.schema
  rel: mentions
---

# TASK-1261: Analytics + Report — Centrality, Connections, GRAPH_REPORT.md

**Feature**: FEAT-187 — GraphIndex — Structured Knowledge Graph Indexing
**Spec**: `sdd/specs/graphindex.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1258, TASK-1259
**Assigned-to**: unassigned

---

## Context

Analytics and reporting is the stage that extracts actionable insights from the assembled and resolved knowledge graph. It computes centrality metrics to identify "god-nodes" (highly connected concepts), ranks cross-domain edges by confidence to surface surprising connections, and generates a deterministic `GRAPH_REPORT.md` with suggested questions for agent consumption.

This is a v1 deterministic-template implementation. No LLM is used for report generation in v1; an optional `--llm-polish` flag is planned for v1.5.

Implements: Spec §3 Module 7 (Analytics + Report).

---

## Scope

- Compute `rustworkx.betweenness_centrality` and `rustworkx.eigenvector_centrality` for identifying god-nodes
- Rank cross-domain `mentions` edges by confidence score for "surprising connections"
- Generate templated suggested questions:
  - "How does {A} relate to {B}?" (for high-confidence cross-domain edges)
  - "What rationale exists for {function}?" (for rationale nodes linked to symbols)
  - "Which sections mention {symbol}?" (for symbol nodes with section edges)
- Write deterministic `GRAPH_REPORT.md` to tenant's output directory
- No LLM in v1; optional `--llm-polish` flag stubbed for v1.5
- Write unit tests for all analytics and report logic

**NOT in scope**: embedding, persistence, toolkit methods, community detection (v1.5)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/analytics.py` | CREATE | Centrality computation, connection ranking, report generation |
| `packages/ai-parrot/tests/knowledge/graphindex/test_analytics.py` | CREATE | Unit tests for analytics and report generation |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import rustworkx
# rustworkx.betweenness_centrality(graph) -> dict[int, float]
# rustworkx.eigenvector_centrality(graph) -> dict[int, float]
# These operate on rustworkx.PyDiGraph

from parrot.knowledge.graphindex.schema import (
    UniversalNode, UniversalEdge, NodeKind, EdgeKind, Provenance,
)
```

### Downstream Integration (not this task, but for reference)
```python
from parrot.bots.prompts.builder import PromptBuilder
# PromptBuilder.build({"knowledge_content": report_text}) -> KNOWLEDGE_LAYER
# Report injection into agent prompts is a downstream concern
```

### Does NOT Exist
- ~~`rustworkx.community_detection`~~ — community detection uses `leidenalg` (v1.5, not this task)
- ~~LLM-polished report~~ — v1 is deterministic templates only
- ~~`rustworkx.pagerank`~~ — use `betweenness_centrality` and `eigenvector_centrality` instead
- ~~`PromptBuilder.inject_report()`~~ — no such method; report injection is via template variables

---

## Implementation Notes

### Pattern to Follow
```python
from dataclasses import dataclass, field
from pathlib import Path

@dataclass
class AnalyticsResult:
    """Results from graph analytics computation."""
    god_nodes: list[dict]  # [{node_id, title, kind, betweenness, eigenvector}]
    surprising_connections: list[dict]  # [{source, target, confidence, source_kind, target_kind}]
    suggested_questions: list[str]

def compute_analytics(
    graph: rustworkx.PyDiGraph,
    nodes: list[UniversalNode],
    edges: list[UniversalEdge],
    top_k: int = 10,
) -> AnalyticsResult:
    """Compute centrality metrics and rank cross-domain connections."""
    ...

def generate_report(
    analytics: AnalyticsResult,
    output_dir: Path,
    llm_polish: bool = False,  # stubbed for v1.5
) -> Path:
    """Generate GRAPH_REPORT.md from analytics results.

    Returns path to the written report file.
    """
    ...
```

### Report Template (v1)
```markdown
# Knowledge Graph Report

## God-Nodes (Most Central)
| Rank | Node | Kind | Betweenness | Eigenvector |
|------|------|------|-------------|-------------|
| 1    | {title} | {kind} | {score} | {score} |

## Surprising Connections
| Source | Target | Confidence | Why Interesting |
|--------|--------|------------|-----------------|
| {A}    | {B}    | {sim}      | Cross-domain: {kind_a} <-> {kind_b} |

## Suggested Questions
- How does {A} relate to {B}?
- What rationale exists for {function}?
- Which sections mention {symbol}?
```

### Key Constraints
- Async-first where applicable, type-hinted, Google-style docstrings
- Report must be deterministic (same input = same output) — no randomness, no LLM in v1
- Centrality functions operate on `rustworkx.PyDiGraph` with integer node indices
- Must map between rustworkx integer indices and `UniversalNode.node_id` strings
- Top-K defaults to 10 for both god-nodes and surprising connections

---

## Acceptance Criteria

- [ ] Betweenness centrality and eigenvector centrality computed correctly
- [ ] God-nodes ranked and top-K returned
- [ ] Cross-domain `mentions` edges ranked by confidence
- [ ] Suggested questions generated from templates (3 question patterns)
- [ ] `GRAPH_REPORT.md` written to output directory with correct format
- [ ] Report is deterministic: same input produces identical output
- [ ] `llm_polish` parameter accepted but is a no-op in v1
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/graphindex/test_analytics.py -v`

---

## Test Specification

```python
import pytest
import rustworkx
from parrot.knowledge.graphindex.schema import (
    UniversalNode, UniversalEdge, NodeKind, EdgeKind, Provenance,
)

class TestAnalytics:
    def test_god_nodes_ranked_by_centrality(self):
        """Nodes with highest betweenness centrality appear first."""
        # Setup: build a small rustworkx graph with known topology
        # Assert: god_nodes[0] has the highest centrality

    def test_surprising_connections_ranked_by_confidence(self):
        """Cross-domain edges ranked by descending confidence."""
        # Setup: edges with varying confidence scores
        # Assert: surprising_connections sorted by confidence desc

    def test_suggested_questions_generated(self):
        """At least one question generated for each template pattern."""
        # Setup: graph with symbols, rationales, sections
        # Assert: questions contain expected patterns

    def test_deterministic_report(self):
        """Same input produces identical report text."""
        # Setup: run generate_report twice with same input
        # Assert: outputs are byte-identical

    def test_empty_graph_produces_empty_report(self):
        """Empty graph yields report with empty tables."""
        # Setup: empty PyDiGraph
        # Assert: report generated without errors, tables are empty

    def test_llm_polish_is_noop(self):
        """llm_polish=True does not change output in v1."""
        # Setup: same input, llm_polish=True vs False
        # Assert: identical output
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/graphindex.spec.md` for full context
2. **Check dependencies** — TASK-1258 (graph assembly) and TASK-1259 (cross-domain resolution) must be done
3. **Verify the Codebase Contract** — confirm `rustworkx.betweenness_centrality` and `rustworkx.eigenvector_centrality` signatures
4. **Update status** in `sdd/tasks/index/graphindex.json` -> `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1261-graphindex-analytics-report.md`
8. **Update index** -> `"done"`

---

## Completion Note

*(Agent fills this in when done)*
