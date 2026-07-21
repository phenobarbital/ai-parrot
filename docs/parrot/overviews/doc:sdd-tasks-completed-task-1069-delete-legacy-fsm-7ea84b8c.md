---
type: Wiki Overview
title: 'TASK-1069: Delete legacy `parrot/bots/flow/fsm.py` and update `parrot/bots/flow/loader.py`'
id: doc:sdd-tasks-completed-task-1069-delete-legacy-fsm-and-update-loader-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements Spec §3 Module 10. The new `parrot/bots/flows/flow.py` is fully
  functional after TASK-1067 + TASK-1068. The legacy file `parrot/bots/flow/fsm.py`
  (1815 lines, contains the broken polling executor + 6 duplicated symbols) can now
  be removed.
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows.core.fsm
  rel: mentions
- concept: mod:parrot.bots.flows.flow
  rel: mentions
---

# TASK-1069: Delete legacy `parrot/bots/flow/fsm.py` and update `parrot/bots/flow/loader.py`

**Feature**: FEAT-163 — AgentsFlow Refactor — DAG Engine on flows.core
**Spec**: `sdd/specs/agentsflow-refactor-spec3.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1067, TASK-1068
**Assigned-to**: unassigned

---

## Context

Implements Spec §3 Module 10. The new `parrot/bots/flows/flow.py` is fully functional after TASK-1067 + TASK-1068. The legacy file `parrot/bots/flow/fsm.py` (1815 lines, contains the broken polling executor + 6 duplicated symbols) can now be removed.

`parrot/bots/flow/loader.py` imports `AgentsFlow` and `TransitionCondition` from `.fsm`. Those imports must be retargeted to the new module locations before the legacy file is deleted, otherwise the loader breaks.

Legacy tests against the old `AgentsFlow` API are also removed (`test_fsm.py`, `test_agentsflow_branch.py`, `test_flow_integration.py`, `test_decision_node.py` — verify exact list at impl time; some may need partial migration instead of deletion).

---

## Scope

1. **Update `parrot/bots/flow/loader.py`**:
   - Current: `from .fsm import AgentsFlow, TransitionCondition` (verify exact line + import set).
   - New: `from parrot.bots.flows.flow import AgentsFlow` + `from parrot.bots.flows.core.fsm import TransitionCondition`.
   - Verify the rest of `loader.py` continues to work (it may use `AgentsFlow.add_agent` / `task_flow` / etc. — the new `AgentsFlow` API is different, so the loader may need additional adjustments). If `loader.py` invokes methods that no longer exist on the new `AgentsFlow`, surface this in the task's Completion Note for follow-up; do NOT silently break the loader.

2. **Delete `parrot/bots/flow/fsm.py`**:
   - `git rm packages/ai-parrot/src/parrot/bots/flow/fsm.py`.
   - Verify no other in-repo imports point at `parrot.bots.flow.fsm` via `grep -rn "parrot.bots.flow.fsm\|from.*flow\.fsm" packages/ai-parrot/src/ packages/ai-parrot/tests/`. If any remain (other than `loader.py` already updated), retarget them before deletion.

3. **Delete legacy tests** that exercise the old `AgentsFlow` API:
   - Candidates: `test_fsm.py`, `test_agentsflow_branch.py`, `test_flow_integration.py`, `test_decision_node.py`. **Verify each before deleting** — some may test underlying primitives that are still relevant (e.g., `test_decision_node.py` testing `DecisionResult` / `DecisionMode` semantics). Keep what's still valid; delete only the AgentsFlow-runtime tests.
   - The replacements live in TASK-1070's integration test suite (`tests/bots/flows/test_agents_flow.py`).

4. **Cleanup `parrot/bots/flow/__init__.py`** if it re-exports anything from `.fsm`. Remove those re-exports.

**NOT in scope**:
- Migrating `parrot/flows/dev_loop/flow.py` (spec non-goal: deferred follow-up; documented broken).
- Migrating `examples/crew/*.py` (spec non-goal: deferred).
- Touching `parrot/bots/orchestration/` (separate deletion track).
- Moving the supporting modules (`decision_node.py`, `interactive_node.py`, `definition.py`, `svelteflow.py`, `actions.py`, `cel_evaluator.py`) to `parrot/bots/flows/` (deferred cleanup spec).

---

## Files to Create / Modify / Delete

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flow/fsm.py` | DELETE | Legacy executor, 1815 LOC, removed in full |
| `packages/ai-parrot/src/parrot/bots/flow/loader.py` | MODIFY | Retarget imports to new locations |
| `packages/ai-parrot/src/parrot/bots/flow/__init__.py` | MODIFY (conditional) | Drop re-exports from `.fsm` if any |
| `packages/ai-parrot/tests/bots/flow/test_fsm.py` | DELETE (likely) | Legacy AgentsFlow runtime tests |
| `packages/ai-parrot/tests/bots/flow/test_agentsflow_branch.py` | DELETE (likely) | Same |
| `packages/ai-parrot/tests/bots/flow/test_flow_integration.py` | DELETE (likely) | Same |
| `packages/ai-parrot/tests/bots/flow/test_decision_node.py` | KEEP or PRUNE | Keep tests on `DecisionResult`/`DecisionMode` semantics; delete runtime-coupled ones |

---

## Codebase Contract (Anti-Hallucination)

### Verified — current state of `loader.py`

```python
# packages/ai-parrot/src/parrot/bots/flow/loader.py
from .fsm import AgentsFlow, TransitionCondition
# Verify the exact line and any other symbols imported from .fsm.
# Look for usages like AgentsFlow(name=..., ...), TransitionCondition.SUCCESS, etc.
```

### New import targets

```python
# Replace with:
from parrot.bots.flows.flow import AgentsFlow              # parrot/bots/flows/flow.py (TASK-1065+)
from parrot.bots.flows.core.fsm import TransitionCondition # parrot/bots/flows/core/fsm.py:17
```

### Legacy symbols in `fsm.py` that get deleted

```python
# packages/ai-parrot/src/parrot/bots/flow/fsm.py
class TransitionCondition(str, Enum):    # line 52  — replaced by core/fsm.py:17
class AgentTaskMachine(StateMachine):    # line 61  — replaced by core/fsm.py:40
class FlowTransition:                    # line 117 — replaced by core/transition.py:28
class FlowNode(Node):                    # line 199 — replaced by modified core/node.py
class AgentsFlow(PersistenceMixin, SynthesisMixin):  # line 278 — replaced by parrot/bots/flows/flow.py
def _would_create_cycle(...):            # line 1252 — replaced by FlowDefinition validator (TASK-1064)
```

### Does NOT Exist (post-deletion)

- ~~`parrot.bots.flow.fsm`~~ — module deleted.
- ~~Any import `from parrot.bots.flow.fsm import ...`~~ — must be retargeted before deletion.

---

## Implementation Notes

### Step-by-step

1. **Pre-check**: `grep -rn "from parrot.bots.flow.fsm\|from .fsm\|from \.fsm" packages/ai-parrot/src/ packages/ai-parrot/tests/` — list all current usage sites of `fsm.py`. Confirm only the loader (and possibly tests scheduled for deletion) appears in `src/`.
2. **Update `loader.py`**:
   - Replace imports.
   - Inspect the body for any use of `AgentsFlow.add_agent(...)`, `AgentsFlow.task_flow(...)`, etc. — methods that exist on the LEGACY API but not the new one. If found, document them in the Completion Note and either:
     - Migrate to the new API (`add_node` + `from_definition`), OR
     - Mark the affected loader paths as TODO (broken) with a clear comment — this is a known-broken follow-up.
3. **Update `parrot/bots/flow/__init__.py`** if it re-exports `AgentsFlow` / `TransitionCondition` from `.fsm`. Either remove the re-export, or retarget it to the new location. Coordinate with downstream consumers.
4. **Delete `fsm.py`**: `git rm packages/ai-parrot/src/parrot/bots/flow/fsm.py`.
5. **Inspect and trim legacy tests**:
   - For each candidate file (`test_fsm.py`, `test_agentsflow_branch.py`, `test_flow_integration.py`, `test_decision_node.py`), check whether its tests reference `parrot.bots.flow.fsm.AgentsFlow` (the runtime). If yes → delete (replacements in TASK-1070).
   - If a test references only `parrot.bots.flow.decision_node.DecisionResult` / `DecisionMode` (declarative primitives still in use), keep it.
6. **Verify nothing broken**: `pytest packages/ai-parrot/tests/ -v` — expect failures ONLY in `parrot/flows/dev_loop/` and `examples/crew/` (known-broken, out of scope). Document those failures in the Completion Note.

### Key Constraints

- The new `AgentsFlow` API differs substantially from the legacy one. If `loader.py` calls methods that no longer exist (e.g., `add_agent`, `task_flow`), this task surfaces the gap — do not silently break.
- Do NOT touch `parrot/bots/orchestration/` (separate deletion track per spec non-goal).
- `parrot/flows/dev_loop/flow.py` will become unimportable as soon as `fsm.py` is deleted (it imports `from parrot.bots.flow import AgentsFlow` which transitively used `.fsm`). This is the expected known-broken state — document it explicitly in the commit message and PR description.
- A single commit deleting `fsm.py` AND updating `loader.py` is preferred so the tree is never in a state where `loader.py` references a deleted module.

### References in Codebase

- Pre-check command: `grep -rn "parrot\.bots\.flow\.fsm\|from \.fsm" packages/ai-parrot/`
- Spec §1 Non-Goals — confirms `parrot/flows/dev_loop/` is out of scope.
- Spec §7 Known Risks — "Dev Loop Flow stays broken" documented.

---

## Acceptance Criteria

- [ ] `packages/ai-parrot/src/parrot/bots/flow/fsm.py` no longer exists.
- [ ] `git diff HEAD~ -- packages/ai-parrot/src/parrot/bots/flow/loader.py` shows the import retargeting.
- [ ] `grep -rn "from parrot\.bots\.flow\.fsm\|from \.fsm import" packages/ai-parrot/src/` returns NOTHING.
- [ ] `python -c "from parrot.bots.flow.loader import *"` succeeds (or `import parrot.bots.flow.loader` — pick the right form by reading the file).
- [ ] Legacy `test_fsm.py`, `test_agentsflow_branch.py`, `test_flow_integration.py` deleted (verify against the actual file list at impl time).
- [ ] `pytest packages/ai-parrot/tests/bots/flow/ -v` passes for whatever remains.
- [ ] `pytest packages/ai-parrot/tests/bots/flows/ -v` passes (the new tests from TASK-1060–1068).
- [ ] Known-broken paths documented in PR description: `parrot/flows/dev_loop/flow.py`, `examples/crew/*flow*.py`.
- [ ] `parrot/bots/orchestration/` untouched — `git diff` confirms.
- [ ] No linting errors on `loader.py`.

---

## Test Specification

This is largely a deletion task — the primary verification is that no tree-wide import breaks.

```bash
# Run after the changes:
grep -rn "from parrot\.bots\.flow\.fsm\|from \.fsm import\|import .*\.flow\.fsm" \
    packages/ai-parrot/src/ packages/ai-parrot/tests/
# Expected: zero matches.

python -c "import parrot.bots.flow.loader"  # must succeed

pytest packages/ai-parrot/tests/bots/flow/ -v   # remaining tests in old dir
pytest packages/ai-parrot/tests/bots/flows/ -v  # new tests
```

---

## Agent Instructions

1. Confirm TASK-1067 and TASK-1068 are in `sdd/tasks/completed/`.
2. Run `grep -rn "parrot\.bots\.flow\.fsm\|from \.fsm" packages/ai-parrot/` to enumerate all usage sites.
3. Read `parrot/bots/flow/loader.py` end-to-end. Identify which methods of the legacy `AgentsFlow` it calls — these are the symbols that may break with the new API.
4. Update `loader.py` imports + retarget any legacy-API method calls (or document them as TODO for follow-up).
5. Update `parrot/bots/flow/__init__.py` if it re-exports `.fsm` symbols.
6. Delete `parrot/bots/flow/fsm.py` via `git rm`.
7. Inspect and trim legacy test files per the criteria above.
8. Run the full test suite for the flow / flows directories; commit. Document known-broken paths (`dev_loop`, examples) in the commit message.
9. Move this task file to `sdd/tasks/completed/` and update the per-spec index.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-12
**Notes**: fsm.py deleted (1815 LOC), loader.py retargeted to new parrot.bots.flows.flow.AgentsFlow and parrot.bots.flows.core.fsm.TransitionCondition. __init__.py retargeted to new locations; FlowNode removed from re-exports (no equivalent). FlowLoader.to_agents_flow marked TODO (broken with new API). 135/135 tests pass.
**Deviations from spec**: No legacy test files found in tests/bots/flow/ (test_fsm.py etc were already absent — only test_definition_cycle.py existed). 
**Known-broken paths documented in PR**: parrot/flows/dev_loop/flow.py (imports legacy AgentsFlow transitively), parrot/bots/flow/loader.py:FlowLoader.to_agents_flow (uses legacy add_agent/task_flow API), examples/crew (out of scope).
