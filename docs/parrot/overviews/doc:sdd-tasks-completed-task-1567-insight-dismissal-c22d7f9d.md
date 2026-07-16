---
type: Wiki Overview
title: 'TASK-1567: Insight Dismissal + GRAPH_REPORT.md Knowledge Gaps Section'
id: doc:sdd-tasks-completed-task-1567-insight-dismissal-and-report-gaps-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: isolated nodes, sparse communities, bridge nodes
relates_to:
- concept: mod:parrot.knowledge.graphindex.analytics
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.schema
  rel: mentions
---

# TASK-1567: Insight Dismissal + GRAPH_REPORT.md Knowledge Gaps Section

**Feature**: FEAT-215 — GraphIndex Analytics Insights
**Spec**: `sdd/specs/FEAT-215-graphindex-analytics-insights.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1565, TASK-1566
**Assigned-to**: unassigned

---

## Context

> Implements Modules 3 and 4 of FEAT-215. Adds the ability to dismiss insights
> so they don't reappear in GRAPH_REPORT.md, and extends the report to include
> a "Knowledge Gaps" section with isolated nodes, sparse communities, and bridge
> nodes. These two modules are combined because dismissal filtering happens
> inside `generate_report()` / `_render_report()`, which is the same code that
> renders the new Knowledge Gaps section.

---

## Scope

- Add `DismissedInsights` Pydantic model in `analytics.py`
- Add `dismissed: Optional[DismissedInsights] = None` field to `AnalyticsResult`
- Implement `dismiss_insight(analytics_result, insight_id)` — adds ID to dismissed set
- Implement `list_unreviewed_insights(analytics_result)` — returns all non-dismissed insights
- Modify `_render_report()` to filter out dismissed insights from all sections
- Add "## Knowledge Gaps" section to `_render_report()` with three sub-sections:
  isolated nodes, sparse communities, bridge nodes
- Write unit tests for dismissal and report gaps section

**NOT in scope**: gap detection functions (TASK-1565), composite scoring (TASK-1566), toolkit tools (TASK-1568)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/analytics.py` | MODIFY | Add DismissedInsights model, dismissal functions, extend _render_report with Knowledge Gaps section + dismissal filtering |
| `packages/ai-parrot/tests/knowledge/graphindex/test_analytics.py` | MODIFY | Add dismissal + report gaps tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.

### Verified Imports
```python
# verified: analytics.py:20-26
from parrot.knowledge.graphindex.schema import (
    NodeKind,       # line 22
    UniversalNode,  # line 25
)

# verified: analytics.py:1, 13-14
from pydantic import BaseModel, Field  # for DismissedInsights model
from dataclasses import dataclass, field  # for AnalyticsResult extension
from typing import Optional
```

### Existing Signatures to Use
```python
# analytics.py:48-69 (AFTER TASK-1565 modifications)
@dataclass
class AnalyticsResult:
    god_nodes: list[dict] = field(default_factory=list)
    surprising_connections: list[dict] = field(default_factory=list)
    suggested_questions: list[str] = field(default_factory=list)
    communities: Optional["CommunitiesResult"] = None
    knowledge_gaps: Optional["KnowledgeGaps"] = None  # added by TASK-1565

# analytics.py:268-297 — generate_report (writes file)
def generate_report(
    analytics: AnalyticsResult,
    output_dir: Path,
    llm_polish: bool = False,
) -> Path:

# analytics.py:300-363 — _render_report (renders markdown string)
def _render_report(analytics: AnalyticsResult) -> str:
    lines: list[str] = ["# Knowledge Graph Report", ""]
    # --- God-Nodes section (lines 312-321) ---
    # --- Surprising Connections section (lines 323-335) ---
    # --- Suggested Questions section (lines 337-341) ---
    # --- Communities section (lines 343-363, conditional) ---
```

### Does NOT Exist
- ~~`analytics.DismissedInsights`~~ — does not exist yet (this task creates it)
- ~~`AnalyticsResult.dismissed`~~ — field does not exist yet
- ~~`analytics.dismiss_insight()`~~ — does not exist yet
- ~~`analytics.list_unreviewed_insights()`~~ — does not exist yet
- ~~`_render_report(analytics, dismissed=...)`~~ — no dismissed parameter yet; use `analytics.dismissed`
- ~~`UniversalNode.domain_tags["dismissed"]`~~ — dismissal is on AnalyticsResult, NOT per-node

---

## Implementation Notes

### DismissedInsights Model
```python
class DismissedInsights(BaseModel):
    """Tracks dismissed insight IDs. Session-scoped (not persisted to DB)."""
    dismissed_ids: set[str] = Field(default_factory=set)
```

### Insight ID Format
Each surprising connection and knowledge gap needs a stable ID for dismissal.
- Surprising connections: `f"surprise:{conn['source_id']}:{conn['target_id']}"`
- Isolated nodes: `f"isolated:{node['node_id']}"`
- Sparse communities: `f"sparse:{community['community_id']}"`
- Bridge nodes: `f"bridge:{node['node_id']}"`

### Dismissal Functions
```python
def dismiss_insight(analytics: AnalyticsResult, insight_id: str) -> None:
    """Mark an insight as dismissed. Creates DismissedInsights if needed."""
    if analytics.dismissed is None:
        analytics.dismissed = DismissedInsights()
    analytics.dismissed.dismissed_ids.add(insight_id)

def list_unreviewed_insights(analytics: AnalyticsResult) -> list[dict]:
    """Return all insights not in the dismissed set."""
    dismissed_ids = analytics.dismissed.dismissed_ids if analytics.dismissed else set()
    # Collect from surprising_connections + knowledge_gaps, filter by ID
    ...
```

### Report Knowledge Gaps Section
Add after the Communities section in `_render_report()`:
```markdown
## Knowledge Gaps

### Isolated Nodes
| Node | Kind | Degree |
|------|------|--------|
| ...  | ...  | ...    |

### Sparse Communities
| Community | Size | Cohesion | Top Members |
|-----------|------|----------|-------------|
| ...       | ...  | ...      | ...         |

### Bridge Nodes
| Node | Kind | Communities Connected |
|------|------|---------------------|
| ...  | ...  | ...                 |
```

### Key Constraints
- `_render_report` filters out dismissed IDs before rendering each section
- Knowledge Gaps section only renders when `analytics.knowledge_gaps` is not None and has content
- Dismissed connections should also be filtered from the Surprising Connections table
- The `dismissed` field on `AnalyticsResult` is `Optional` — existing code that doesn't set it continues to work

### References in Codebase
- `analytics.py:300-363` — `_render_report()` structure to extend
- `analytics.py:268-297` — `generate_report()` entry point (no changes needed, delegates to _render_report)

---

## Acceptance Criteria

- [ ] `DismissedInsights` model created with `dismissed_ids: set[str]`
- [ ] `AnalyticsResult` has `dismissed: Optional[DismissedInsights] = None`
- [ ] `dismiss_insight()` adds ID to dismissed set
- [ ] `list_unreviewed_insights()` returns only non-dismissed insights
- [ ] Dismissed surprising connections filtered from GRAPH_REPORT.md
- [ ] "Knowledge Gaps" section in GRAPH_REPORT.md with isolated nodes, sparse communities, bridge nodes
- [ ] Knowledge Gaps section omitted when `knowledge_gaps` is None
- [ ] All existing analytics/report tests still pass
- [ ] New tests pass: `pytest packages/ai-parrot/tests/knowledge/graphindex/test_analytics.py -v -k "dismiss or unreviewed or report_knowledge"`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/knowledge/graphindex/analytics.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/graphindex/test_analytics.py
import pytest
from parrot.knowledge.graphindex.analytics import (
    AnalyticsResult,
    DismissedInsights,
    dismiss_insight,
    list_unreviewed_insights,
    _render_report,
)


class TestInsightDismissal:
    def test_dismiss_insight(self):
        """Dismissed insight ID stored in set."""
        analytics = AnalyticsResult(
            surprising_connections=[
                {"source_id": "a", "target_id": "b", "confidence": 0.9,
                 "source_kind": "concept", "target_kind": "symbol"},
            ]
        )
        dismiss_insight(analytics, "surprise:a:b")
        assert "surprise:a:b" in analytics.dismissed.dismissed_ids

    def test_list_unreviewed_excludes_dismissed(self):
        """Only non-dismissed insights returned."""
        analytics = AnalyticsResult(
            surprising_connections=[
                {"source_id": "a", "target_id": "b", "confidence": 0.9,
                 "source_kind": "concept", "target_kind": "symbol"},
                {"source_id": "c", "target_id": "d", "confidence": 0.8,
                 "source_kind": "section", "target_kind": "skill"},
            ]
        )
        dismiss_insight(analytics, "surprise:a:b")
        unreviewed = list_unreviewed_insights(analytics)
        ids = [i["id"] for i in unreviewed]
        assert "surprise:a:b" not in ids
        assert "surprise:c:d" in ids


class TestReportKnowledgeGaps:
    def test_report_includes_knowledge_gaps_section(self, graph_with_gaps):
        """GRAPH_REPORT.md contains Knowledge Gaps section."""
        # Build AnalyticsResult with knowledge_gaps populated
        report = _render_report(analytics)
        assert "## Knowledge Gaps" in report
        assert "### Isolated Nodes" in report
        assert "### Sparse Communities" in report
        assert "### Bridge Nodes" in report

    def test_report_omits_gaps_when_none(self):
        """No Knowledge Gaps section when knowledge_gaps is None."""
        analytics = AnalyticsResult()
        report = _render_report(analytics)
        assert "## Knowledge Gaps" not in report

    def test_dismissed_connections_filtered_in_report(self):
        """Dismissed surprising connections not in report output."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1565 and TASK-1566 are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm TASK-1565 and TASK-1566 changes are present
4. **Update status** in `sdd/tasks/index/graphindex-analytics-insights.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1567-insight-dismissal-and-report-gaps.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.6)
**Date**: 2026-06-16
**Notes**: Added DismissedInsights Pydantic model. Added dismissed field to AnalyticsResult. Implemented dismiss_insight() and list_unreviewed_insights(). Updated _render_report() to filter dismissed insights from all sections and added "## Knowledge Gaps" section with isolated nodes, sparse communities, and bridge nodes subsections. Added 12 new tests. All 66 tests pass. Linting clean.

**Deviations from spec**: none
