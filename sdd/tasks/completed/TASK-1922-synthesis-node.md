# TASK-1922: SynthesisNode — post-merge reconciliation owner

**Feature**: FEAT-378 — DevLoop Enhancement — Feature-Mode Topology
**Spec**: `sdd/specs/devloop-enhancement.spec.md`
**Status**: done
**Completed**: 2026-07-27
**Verification**: verified
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1918, TASK-1919
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3. The explicit "reduce → synthesize" step of the diamond:
after `DevelopmentNode` merges the sub-worktrees (FEAT-323
`merge_sequential`), this node dispatches an agent in the integrated worktree
to reconcile inter-worker inconsistencies and run the integration test suite.
Resolved decision: separate node (own telemetry, own on_error), not a
DevelopmentNode phase.

---

## Scope

- Implement `SynthesisNode(DevLoopNode)` in
  `parrot/flows/dev_loop/nodes/synthesis.py`, node id `"synthesis"`,
  registered via `@register_dev_loop_node`:
  - Input: `DevelopmentOutput` + worktree path from shared state.
  - Dispatches a claude-code agent (cwd = integrated worktree) with a brief:
    review inter-worker consistency (interfaces, imports, duplications), run
    `pytest`, commit reconciliation adjustments.
  - Parses final JSON into `SynthesisReport{consistent, adjustments, summary}`.
  - `consistent=False` after the agent's attempt (or dispatch/parse failure)
    → raise so the on_error edge routes to `failure_handler` (edge wired in
    TASK-1925).
  - Publishes the report to shared state for QA/handoff consumption.
- Unit tests with stubbed dispatcher.

**NOT in scope**: any change to `DevelopmentNode`, `SubWorktreeManager`, or
merge logic (FEAT-323 already provides them); topology edges (TASK-1925);
a dedicated subagent prompt file is NOT required if the brief is built
inline like other short dispatches — decide by following the closest
existing pattern and document the choice.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/synthesis.py` | CREATE | SynthesisNode |
| `packages/ai-parrot/tests/flows/dev_loop/test_synthesis_node.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.nodes.base import register_dev_loop_node, DevLoopNode  # verified 2026-07-27
from parrot.flows.dev_loop.models import SynthesisReport  # TASK-1918
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/worktree_manager.py:75  (verified 2026-07-27)
class SubWorktreeManager:
    async def merge_sequential(self, *, resolver: Optional[Resolver] = None) -> MergeReport: ...  # :181
    # ⚠ ASYNC. Runs BEFORE this node (inside DevelopmentNode) — SynthesisNode
    # only consumes the integrated worktree; it never calls merge itself.

# packages/ai-parrot/src/parrot/flows/dev_loop/models.py
class DevelopmentOutput(BaseModel):  # :452 — upstream input shape

# packages/ai-parrot/src/parrot/flows/dev_loop/agent_pool.py
def aggregate_outputs(results, incomplete) -> DevelopmentOutput: ...  # :340
```

### Does NOT Exist
- ~~`SynthesisNode` / node id `"synthesis"`~~ — this task creates it (NodeId literal extended in TASK-1919).
- ~~A `SynthesisMixin` shared with `AgentsFlow`~~ — `parrot/bots/flows/flow/nodes.py` has an unrelated `SynthesisNode` for generic flows. Do NOT import or subclass it; the dev_loop node is independent (name collision only — keep the dev_loop class in the dev_loop package namespace).
- ~~Re-running `merge_sequential` here~~ — merge already happened in DevelopmentNode.

---

## Implementation Notes

### Pattern to Follow
Follow the dispatch shape of an existing short-dispatch node (e.g. QANode's
sdd-qa dispatch, qa.py:113-249) — build profile, dispatch with cwd override,
parse single JSON output.

### Key Constraints
- Async; `self.logger` around dispatch and on inconsistency findings.
- The dispatched agent operates in the INTEGRATED worktree, not the repo root.
- Timebox awareness: keep the brief scoped to reconciliation + integration
  pytest, not a re-review (QA panel does that next).

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py:113-249` — dispatch pattern
- Spec §2 Internal Behavior item 4

---

## Acceptance Criteria

- [ ] `SynthesisNode` registered under `"synthesis"`; consumes DevelopmentOutput + worktree, produces `SynthesisReport` in shared state
- [ ] `consistent=False` / dispatch failure → node raises (on_error path testable)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/test_synthesis_node.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/nodes/synthesis.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_synthesis_node.py
async def test_synthesis_happy_path(): ...
async def test_synthesis_inconsistent_raises(): ...
async def test_synthesis_dispatch_failure_raises(): ...
async def test_report_published_to_shared_state(): ...
```

---

## Agent Instructions

1. **Read the spec** (§2 Internal Behavior item 4, §6, §7)
2. **Check dependencies** — TASK-1918, TASK-1919 completed
3. **Verify the Codebase Contract** — re-grep anchors (FEAT-377 merge may shift lines)
4. **Update status** in `sdd/tasks/index/devloop-enhancement.json` → `"in-progress"`
5. **Implement**, **verify criteria**, move file to `sdd/tasks/completed/`, update index → `"done"`, fill Completion Note

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-27
**Notes**: `SynthesisNode` implemented in `nodes/synthesis.py`, registered
as `"dev_loop.synthesis"` (node id `"synthesis"`). No dedicated subagent
prompt file — used `ClaudeCodeDispatchProfile(subagent=None,
system_prompt_override=...)`, the documented inline-session fallback
(models.py's own docstring), since the task explicitly allowed this
choice for a brief this narrowly scoped; documented the decision in the
module docstring. Reads `shared["research_output"]` for the integrated
worktree path (the key every existing dev-loop node — including the
unmodified `DevelopmentNode` — keys off; TASK-1925's topology bridge is
expected to populate/alias it for the feature-mode path too, since
`DevelopmentOutput` itself carries no `worktree_path`) and
`shared["development_output"]`; writes `shared["synthesis_report"]`
**before** raising on `consistent=False` so `failure_handler` gets the
diagnostic. Dispatch failures (`DispatchExecutionError`/
`DispatchOutputValidationError`) are intentionally left unhandled —
they propagate straight to the `on_error` edge (TASK-1925), matching the
"dispatch/parse failure → raise" acceptance criterion; nothing here
degrades a synthesis failure to a passing result. All 4 unit tests pass;
full dev_loop suite green except the pre-existing, unrelated
`test_models_module_is_pure` test-order flake (reproduced identically
before this task's changes).

**Deviations from spec**: none
