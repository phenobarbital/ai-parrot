# TASK-2125: DevIntakeNode — brief validation + kind routing

**Feature**: FEAT-412 — Dev-Flow: SDD-Oriented AgentsFlow for Feature Development
**Spec**: `sdd/specs/sdd-dev-flow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2121
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (intake half). First node of the dev-flow graph: validates
the user-selected `DevFlowBrief` (no LLM classification — spec Non-Goals)
and returns it so CEL edge predicates route on `result.kind`
(`enhancement`/`new_feature` → ideation; `feature` → planner).

---

## Scope

- Create `packages/ai-parrot/src/parrot/flows/dev_flow/nodes/__init__.py`
  and `nodes/dev_intake.py` with `DevIntakeNode`, registered as
  `dev_flow.dev_intake` via `register_dev_loop_node`.
- Behavior (mirror `IntentClassifierNode`):
  - `_load_brief`: accept the brief from `ctx` shared state
    (`ctx["dev_brief"]`) or parse a JSON prompt via `parse_dev_brief`.
  - When `kind == "feature"`: publish `ctx["feature_brief"]` (the exact key
    `PlannerNode` reads).
  - Always publish `ctx["dev_brief"]`; emit one `flow.intake_validated`
    event to `flow:{run_id}:flow` (lazy Redis, same pattern as
    `IntentClassifierNode._emit_validated_event`).
  - Return the validated brief (routing happens on `result.kind`).
- Unit tests.

**NOT in scope**: IdeationNode (TASK-2126), topology/edges (TASK-2127).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_flow/nodes/__init__.py` | CREATE | Node package exports |
| `packages/ai-parrot/src/parrot/flows/dev_flow/nodes/dev_intake.py` | CREATE | DevIntakeNode |
| `packages/ai-parrot/tests/flows/dev_flow/test_dev_intake.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.nodes.base import (   # verified 2026-08-05
    DevLoopNode,               # nodes/base.py:193
    register_dev_loop_node,    # nodes/base.py:174 (idempotent @register_node)
)
from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.types import DependencyResults
from parrot.flows.dev_flow.models import (        # TASK-2121
    DevRequestBrief, DevFlowBrief, parse_dev_brief,
)
from parrot.flows.dev_loop.models import FeatureBrief  # models/base.py:725
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/base.py:174
def register_dev_loop_node(name: str):
    # no-op when name already in NODE_REGISTRY (safe across re-imports)

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/intent_classifier.py
# PATTERN to mirror (do not import/subclass IntentClassifierNode):
#   class IntentClassifierNode(DevLoopNode):
#       async def execute(self, ctx, deps): ...
#       def _load_brief(self, prompt, ctx): ...    # ctx-or-JSON-prompt loading
#       def _emit_validated_event(self, run_id, brief): ...  # XADD flow.intake_validated
#       def _ensure_redis(self): ...               # lazy cached async client
#       async def close(self): ...                 # release pool
```

### Does NOT Exist
- ~~`dev_flow.dev_intake` node type~~ — this task registers it.
- ~~allowlist/path-traversal validation for DevRequestBrief~~ — those guards
  are `WorkBrief.acceptance_criteria`-specific (see intent_classifier.py
  docstring); `DevRequestBrief` carries no acceptance criteria. Do NOT
  invent one.
- ~~`ctx["work_brief"]` / `ctx["bug_brief"]` publication~~ — dev-flow never
  populates the bug-mode keys.

---

## Implementation Notes

### Key Constraints
- Registration decorator: `@register_dev_loop_node("dev_flow.dev_intake")` —
  the helper is generic (checks NODE_REGISTRY by name); node types are
  namespaced `dev_flow.*`.
- The node must be constructible without a live Redis (lazy connect on
  first execute), mirroring the classifier.
- async throughout; `self.logger`; Google docstrings.

### References in Codebase
- `dev_loop/nodes/intent_classifier.py` — the complete pattern
- `dev_loop/nodes/base.py` — DevLoopNode helpers (`shared_state`)

---

## Acceptance Criteria

- [ ] `DevIntakeNode` registered as `dev_flow.dev_intake`; import works
- [ ] enhancement/new_feature briefs validate and return; `feature` brief additionally populates `ctx["feature_brief"]`
- [ ] `flow.intake_validated` event XADDed once per run (fake Redis)
- [ ] Tests pass: `pytest packages/ai-parrot/tests/flows/dev_flow/test_dev_intake.py -v`; `ruff` clean

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_flow/test_dev_intake.py
async def test_loads_brief_from_ctx(): ...
async def test_loads_brief_from_json_prompt(): ...
async def test_feature_kind_publishes_feature_brief(tmp_path): ...
async def test_invalid_brief_raises_before_return(): ...
async def test_emits_intake_validated_event(): ...
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2121 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/sdd-dev-flow.json` → `"in-progress"`
5. **Implement**, **verify**, move this file to `sdd/tasks/completed/`,
   update index → `"done"`, fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
