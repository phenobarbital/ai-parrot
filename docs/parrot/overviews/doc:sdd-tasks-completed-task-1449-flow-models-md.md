---
type: Wiki Overview
title: 'TASK-1449: Implement ScrapingFlow, FlowNode, and FlowResult models'
id: doc:sdd-tasks-completed-task-1449-flow-models-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: affinity. It validates the graph structure (no cycles, no dangling refs)
  and provides
relates_to:
- concept: mod:parrot_tools.scraping
  rel: mentions
- concept: mod:parrot_tools.scraping.flow_models
  rel: mentions
---

# TASK-1449: Implement ScrapingFlow, FlowNode, and FlowResult models

**Feature**: FEAT-222 — ScrapingFlow: Composable Long-Horizon Scraping
**Spec**: `sdd/specs/scrapingflow-composable-scraping.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`ScrapingFlow` is the DAG model connecting FlowNodes with data-dependency edges and session
affinity. It validates the graph structure (no cycles, no dangling refs) and provides
topological ordering for execution.

Implements spec §Module 2 (ScrapingFlow & FlowNode models).

---

## Scope

- Create `FlowNode` Pydantic model: id, plan_ref, inputs, session, on_error, max_retries
- Create `ScrapingFlow` Pydantic model: name, description, nodes, global_params
  - Implement `validate_dag()` as `@model_validator(mode="after")` — builds adjacency list
    from `inputs` refs, runs Kahn's algorithm for cycle detection, verifies all refs exist
  - Implement `topological_order()` → `List[FlowNode]` as a public method
- Create `FlowResult` Pydantic model: flow_name, node_results, success, error_message,
  elapsed_seconds, nodes_completed, nodes_total, checkpoint_path, resumed_from
- Write comprehensive unit tests

**NOT in scope**: TemplatePlan (TASK-1448), FlowExecutor (TASK-1452), input resolution grammar

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/scraping/flow_models.py` | CREATE | FlowNode, ScrapingFlow, FlowResult |
| `packages/ai-parrot-tools/tests/scraping/test_flow_models.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, Field, model_validator  # pydantic v2
```

### Does NOT Exist
- ~~`parrot_tools.scraping.ScrapingFlow`~~ — this is what you're creating
- ~~`parrot_tools.scraping.FlowNode`~~ — this is what you're creating
- ~~`parrot_tools.scraping.FlowResult`~~ — this is what you're creating

---

## Implementation Notes

### Key Constraints
- `validate_dag()` must detect cycles using Kahn's algorithm (or equivalent topological sort)
- `validate_dag()` must verify every `"node_id.field"` in `inputs` refers to an existing node ID
- `topological_order()` returns nodes in execution order (dependencies before dependents)
- `FlowNode.inputs` format: `{"param_name": "node_id.field_name"}` — parsing of the ref
  string (splitting on `.`) is validated but actual field resolution is FlowExecutor's job

---

## Acceptance Criteria

- [ ] `FlowNode` validates fields and defaults correctly
- [ ] `ScrapingFlow` accepts valid connected DAGs
- [ ] `ScrapingFlow` rejects circular dependencies with a clear error message
- [ ] `ScrapingFlow` rejects refs to non-existent node IDs
- [ ] `topological_order()` returns correct execution order
- [ ] `FlowResult` stores per-node results and flow metadata
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/scraping/test_flow_models.py -v`

---

## Test Specification

```python
import pytest
from parrot_tools.scraping.flow_models import FlowNode, ScrapingFlow, FlowResult


class TestScrapingFlow:
    def test_valid_linear_dag(self):
        flow = ScrapingFlow(name="test", nodes=[
            FlowNode(id="a", plan_ref="plan-a"),
            FlowNode(id="b", plan_ref="plan-b", inputs={"url": "a.product_url"}),
        ])
        order = flow.topological_order()
        assert [n.id for n in order] == ["a", "b"]

    def test_cycle_detection(self):
        with pytest.raises(ValueError, match="cycle"):
            ScrapingFlow(name="test", nodes=[
                FlowNode(id="a", plan_ref="p", inputs={"x": "b.field"}),
                FlowNode(id="b", plan_ref="p", inputs={"x": "a.field"}),
            ])

    def test_dangling_ref(self):
        with pytest.raises(ValueError, match="nonexistent"):
            ScrapingFlow(name="test", nodes=[
                FlowNode(id="a", plan_ref="p", inputs={"x": "nonexistent.field"}),
            ])

    def test_diamond_dag(self):
        flow = ScrapingFlow(name="test", nodes=[
            FlowNode(id="root", plan_ref="p"),
            FlowNode(id="left", plan_ref="p", inputs={"x": "root.field"}),
            FlowNode(id="right", plan_ref="p", inputs={"x": "root.field"}),
            FlowNode(id="sink", plan_ref="p", inputs={"a": "left.field", "b": "right.field"}),
        ])
        order = flow.topological_order()
        assert order[0].id == "root"
        assert order[-1].id == "sink"
```

---

## Completion Note

Created `flow_models.py` with `FlowNode`, `ScrapingFlow`, and `FlowResult`
Pydantic v2 models.

- `FlowNode`: id, plan_ref, inputs, session ("default"), on_error
  (abort|skip|retry, default abort), max_retries (ge=1, default 3).
- `ScrapingFlow.validate_dag()` is a `model_validator(mode="after")` that runs
  `_compute_topological_order()`: checks unique ids, parses each input ref's
  source node (`ref.split(".",1)[0]`, so `node.field`, `node.field[N]`, and
  `node.field[*]` all resolve to their source), rejects dangling refs and
  self-references, then runs Kahn's algorithm. Cycles raise a "cycle" error
  listing the involved nodes; dangling refs name the missing node.
- `topological_order()` recomputes the order (deterministic — declaration
  order is the stable tiebreaker, so independent nodes preserve declared
  order; dependencies always precede dependents).
- `FlowResult`: flow_name, node_results, success, error_message,
  elapsed_seconds, nodes_completed, nodes_total, checkpoint_path, resumed_from.

14 unit tests pass (linear/diamond/cycle/self-cycle/dangling/duplicate/fan-out
refs/multi-input); ruff clean.
