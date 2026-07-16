---
type: Wiki Overview
title: 'TASK-1777: Deterministic Tab-Assembly Helper'
id: doc:sdd-tasks-completed-task-1777-tab-assembly-helper-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'that returns the block list: TITLE block + TAB_VIEW block containing'
relates_to:
- concept: mod:parrot.bots.flows.core.result
  rel: mentions
- concept: mod:parrot.bots.flows.core.storage.memory
  rel: mentions
- concept: mod:parrot.bots.flows.crew.result_infographic
  rel: mentions
- concept: mod:parrot.tools.infographic_toolkit
  rel: mentions
---

# TASK-1777: Deterministic Tab-Assembly Helper

**Feature**: FEAT-308 — AgentCrew ResultAgent End-of-Flow Multi-Tab Infographic Node
**Spec**: `sdd/specs/agentcrew-node-infographic.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1775
**Assigned-to**: unassigned

---

## Context

> Spec §3 Module 2. The infographic's Tab 2 (Final Result) and Tabs 3…N
> (per-agent) are built **deterministically** from `ExecutionMemory` — no LLM
> call needed. This helper reads the crew's execution memory, converts each
> agent's `NodeResult` into a tab block, excludes the ResultAgent itself,
> and handles large/non-text results (summarize or link out via ArtifactStore).
> The Tab 1 (Executive Summary) blocks are LLM-authored by the ResultAgent
> (TASK-1778) and merged in front by the caller (TASK-1779).

---

## Scope

- Create `parrot/bots/flows/crew/result_infographic.py` with:
  - `build_deterministic_tabs(execution_memory, final_output, exclude_node_id, artifact_store=None) -> List[Dict]`
    that returns the block list: TITLE block + TAB_VIEW block containing
    Tab 2 (Final Result) and one tab per research agent (Tabs 3…N).
  - Logic to detect large (> `_INLINE_THRESHOLD`) or non-text results and
    summarize / link out to `ArtifactStore`.
  - A `merge_tab1_blocks(tab1_blocks, deterministic_blocks) -> List[Dict]`
    helper that inserts the LLM-authored Tab 1 content as the first tab in
    the TAB_VIEW.
- Write unit tests for all assembly paths.

**NOT in scope**: LLM authoring of Tab 1 (that's TASK-1778). Calling `render()` (that's TASK-1779). Modifying `ExecutionMemory`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/crew/result_infographic.py` | CREATE | Tab-assembly helper functions |
| `tests/unit/test_tab_assembly.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.flows.core.result import NodeResult          # result.py:39
from parrot.bots.flows.core.storage.memory import ExecutionMemory  # memory.py:19
from parrot.tools.infographic_toolkit import _INLINE_THRESHOLD     # infographic_toolkit.py:49
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flows/core/storage/memory.py
class ExecutionMemory(VectorStoreMixin):                              # L19
    results: dict                                                     # L45
    def get_snapshot(self) -> Dict[str, Any]: ...                    # L134
    # snapshot returns: {original_query, results, execution_order, execution_graph, ...}
    def get_results_by_agent(self, agent_id: str) -> Optional[NodeResult]: ...  # L79

# packages/ai-parrot/src/parrot/bots/flows/core/result.py
@dataclass
class NodeResult:                                                     # L39
    node_id: str                                                      # L63
    node_name: str                                                    # L64
    task: str                                                         # L65
    result: Any                                                       # L66
    def to_text(self) -> str: ...                                    # L88
    @property
    def agent_id(self) -> str: ...                                   # L76 (alias of node_id)

# packages/ai-parrot/src/parrot/tools/infographic_toolkit.py
_INLINE_THRESHOLD: int = 50_000                                      # L49
```

### Does NOT Exist
- ~~`ExecutionMemory.get_all_results()`~~ — not a method; iterate `self.results` or use `get_snapshot()`.
- ~~`NodeResult.is_large()`~~ — no such method; check `len(result.to_text()) > _INLINE_THRESHOLD`.
- ~~`ArtifactStore.publish()`~~ — verify the actual `ArtifactStore` API before using; if it doesn't exist yet, use a placeholder that returns `None` and documents the TODO.

---

## Implementation Notes

### Block Structure for TAB_VIEW
```python
# The block list to return follows the infographic block schema:
blocks = [
    {
        "block_type": "title",
        "content": "Crew Execution Report: <crew_name>",
    },
    {
        "block_type": "tab_view",
        "tabs": [
            # Tab 1 slot — filled later by merge_tab1_blocks
            # Tab 2 — Final Result
            {"label": "Final Result", "blocks": [{"block_type": "text", "content": "..."}]},
            # Tabs 3..N — per-agent
            {"label": "<agent_name>", "blocks": [{"block_type": "text", "content": "..."}]},
        ],
    },
]
```

### Key Constraints
- **Exclude the ResultAgent's `node_id`** from the per-agent tabs.
- Results where `len(to_text()) > _INLINE_THRESHOLD` or non-text types
  (DataFrame, bytes, etc.) should be summarized or linked out.
- Use `self.logger` if this becomes a class, otherwise `logging.getLogger(__name__)`.
- The function must be pure-ish (deterministic given the same memory snapshot).

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/infographic_toolkit.py` — block schema
- `packages/ai-parrot/src/parrot/bots/flows/core/storage/memory.py` — memory API

---

## Acceptance Criteria

- [ ] `build_deterministic_tabs` returns correct blocks for 0 research agents (just Final Result tab)
- [ ] `build_deterministic_tabs` returns correct blocks for 8 agents (10 tabs total slot, no clamp)
- [ ] ResultAgent's `node_id` is excluded from per-agent tabs
- [ ] Large results (> `_INLINE_THRESHOLD`) are summarized or linked out, not dumped raw
- [ ] `merge_tab1_blocks` inserts Tab 1 as the first tab in the TAB_VIEW
- [ ] Unit tests pass: `pytest tests/unit/test_tab_assembly.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/bots/flows/crew/result_infographic.py`

---

## Test Specification

```python
# tests/unit/test_tab_assembly.py
import pytest
from unittest.mock import MagicMock
from parrot.bots.flows.core.result import NodeResult
from parrot.bots.flows.crew.result_infographic import (
    build_deterministic_tabs,
    merge_tab1_blocks,
)


def _make_node_result(node_id, name, result_text):
    return NodeResult(
        node_id=node_id, node_name=name, task="test",
        result=result_text, metadata={},
    )


class TestBuildDeterministicTabs:
    def test_single_result_one_tab(self):
        """0 research agents → only Final Result tab."""
        mem = MagicMock()
        mem.results = {}
        blocks = build_deterministic_tabs(mem, final_output="Done", exclude_node_id="result-agent")
        tab_view = next(b for b in blocks if b["block_type"] == "tab_view")
        assert len(tab_view["tabs"]) == 1  # just Final Result

    def test_many_agents_no_clamp(self):
        """8 research agents → 9 tabs (Final Result + 8 agent tabs)."""
        mem = MagicMock()
        mem.results = {f"agent-{i}": _make_node_result(f"agent-{i}", f"Agent {i}", f"Result {i}") for i in range(8)}
        blocks = build_deterministic_tabs(mem, final_output="Done", exclude_node_id="result-agent")
        tab_view = next(b for b in blocks if b["block_type"] == "tab_view")
        assert len(tab_view["tabs"]) == 9

    def test_excludes_result_agent(self):
        """The ResultAgent's node_id is absent from per-agent tabs."""
        mem = MagicMock()
        mem.results = {
            "researcher": _make_node_result("researcher", "Researcher", "data"),
            "result-agent": _make_node_result("result-agent", "ResultAgent", "infographic"),
        }
        blocks = build_deterministic_tabs(mem, final_output="Done", exclude_node_id="result-agent")
        tab_view = next(b for b in blocks if b["block_type"] == "tab_view")
        tab_labels = [t["label"] for t in tab_view["tabs"]]
        assert "ResultAgent" not in tab_labels
        assert "Researcher" in tab_labels or "Final Result" in tab_labels

    def test_large_result_linked_out(self):
        """Oversized result is summarized, not dumped raw."""
        mem = MagicMock()
        huge = "x" * 60_000
        mem.results = {"agent-1": _make_node_result("agent-1", "Agent 1", huge)}
        blocks = build_deterministic_tabs(mem, final_output="Done", exclude_node_id="result-agent")
        tab_view = next(b for b in blocks if b["block_type"] == "tab_view")
        agent_tab = next(t for t in tab_view["tabs"] if t["label"] != "Final Result")
        content = str(agent_tab["blocks"])
        assert len(content) < 60_000


class TestMergeTab1Blocks:
    def test_inserts_tab1_first(self):
        """Tab 1 (Exec Summary) is the first tab after merge."""
        tab1 = [{"block_type": "text", "content": "Executive Summary"}]
        det_blocks = [
            {"block_type": "title", "content": "Report"},
            {"block_type": "tab_view", "tabs": [
                {"label": "Final Result", "blocks": [{"block_type": "text", "content": "Done"}]},
            ]},
        ]
        merged = merge_tab1_blocks(tab1, det_blocks)
        tab_view = next(b for b in merged if b["block_type"] == "tab_view")
        assert tab_view["tabs"][0]["label"] == "Executive Summary"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/agentcrew-node-infographic.spec.md` §3 Module 2
2. **Check dependencies** — TASK-1775 must be complete (crew_report template registered)
3. **Verify the Codebase Contract** — confirm `ExecutionMemory.results`, `get_snapshot()`, `NodeResult.to_text()` signatures
4. **Check ArtifactStore API** — grep for `ArtifactStore` in `parrot/storage/` to confirm the publish interface; if absent, implement a fallback (truncate + note)
5. **Implement** the helper functions
6. **Write and run** unit tests
7. **Update status** and move to completed when done

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-07-14
**Notes**: Implemented `build_deterministic_tabs` and `merge_tab1_blocks` in
`parrot/bots/flows/crew/result_infographic.py`. Verified and corrected three
stale contract details against the real block schema
(`parrot/models/infographic.py`, `InfographicToolkit._validate_blocks`):
(1) block dicts discriminate on `"type"`, not `"block_type"`; (2) `TitleBlock`
uses a `title` field, not `content`; (3) `TabPane` requires an `id`. Content
blocks use `SummaryBlock` (`type="summary"`), whose own hard
`max_length=2000` is enforced regardless of `_INLINE_THRESHOLD` (50_000,
which gates the page-level `html_inline` decision, not per-block length).
`ArtifactStore.save_artifact()` requires `user_id`/`session_id`/backends this
helper doesn't have — `artifact_store` is a duck-typed `publish(key, text)`
placeholder (falls back to truncate+note when absent), per the task's own
fallback guidance; TODO for TASK-1779 to wire real session context if needed.
Confirmed via an ad-hoc pytest sanity check that `merge_tab1_blocks`'s output
validates cleanly through the real `InfographicResponse`/`TabViewBlock`
models (`TabPane` requires >= 2 tabs; since Tab 1 is always merged in before
the crew's Final-Result tab, the real minimum is always >= 2 — resolves an
apparent tension with spec G5's "minimum 1" language, which refers to the
deterministic-tabs-only count before merging). 10 unit tests pass, ruff
clean.

**Deviations from spec**: none (contract corrections documented above; no
behavioral deviation from Module 2's scope)
