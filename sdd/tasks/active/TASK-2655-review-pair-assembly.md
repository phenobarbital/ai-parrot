# TASK-2655: Assemble the configurable review pair from the plan

**Feature**: FEAT-486 — Refactor Dev-Flow — Per-Seat LLM Configuration, Multi-Agent Development Pool, Configurable Review
**Spec**: `sdd/specs/refactor-dev-flow.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2651, TASK-2652, TASK-2654
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (assembly half, goal G5). With the plan threaded
(TASK-2652) and the Mantle adversary available (TASK-2654), build the
`ParallelPerspectiveReviewDispatcher` pair from `plan.review` and hand it
to dev_flow as `codereview_dispatcher`.

---

## Scope

- In `dev_flow/factories.py` (or a small helper beside it): when
  `model_plan.review` is present and no explicit `codereview_dispatcher`
  was passed, assemble
  `ParallelPerspectiveReviewDispatcher(primary=<write-enabled reviewer from
  plan.review.primary via agent_builder/factory>, adversary=
  MantleAdversarialReviewDispatcher(model=plan.review.counter_model))`.
- Explicit `codereview_dispatcher=` argument always wins over the plan
  (precedence test).
- Defaults produce: primary claude-code/`claude-opus-5` (write-enabled,
  `ClaudeCodeReviewDispatcher` with `model=`), adversary Mantle/`gpt-5.6-sol`.
- Unit tests: assembly from defaults, precedence, JudgeSpec/judge-panel
  code untouched (import-level assertion that no judge module changed —
  covered by not touching those files).

**NOT in scope**: the dispatcher itself (TASK-2654), console (TASK-2658),
judge panel (never).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_flow/factories.py` | MODIFY | pair assembly + precedence |
| `packages/ai-parrot/tests/flows/dev_flow/test_review_pair.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_flow.model_plan import DevFlowModelPlan  # TASK-2651
# MantleAdversarialReviewDispatcher — from wherever TASK-2654 placed it (grep first)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py (verified 2026-09-01)
class ParallelPerspectiveReviewDispatcher:   # :341
    def __init__(self, *, primary, adversary, judge_dispatcher=None, judge_enabled=False): ...  # :361-373
    # asyncio.gather of both (:392-402); deterministic merge _merge_verdicts (:462)
class ClaudeCodeReviewDispatcher:            # :191, __init__(*, dispatcher, model=None) (:202) — write-enabled primary

# dev_flow/factories.py:41-56 — build surface this task extends (post-TASK-2652 shape: re-read it)
# QANode wraps a None codereview_dispatcher in ClaudeCodeReviewDispatcher (qa.py:147-148) —
#   plan-assembled pair must be passed explicitly so that fallback never fires.
```

### Does NOT Exist
- ~~`JudgeSpec` changes / judge-panel involvement~~ — forbidden (spec-resolved: pair rides ParallelPerspectiveReviewDispatcher).
- ~~A registry mapping plan.review.primary to arbitrary review dispatchers~~ — keep it simple: claude-code primary via `ClaudeCodeReviewDispatcher(model=...)`; other primary backends may use `CodeReviewDispatcherFactory.create` (`code_review.py:180`) if the spec's `DevAgentSpec` names one.

---

## Implementation Notes

- Precedence: explicit argument > plan > today's default (None → QANode's
  own Claude wrap). Assert all three in tests.
- Do not construct clients eagerly at build time if the siblings defer —
  match how existing dispatchers are instantiated in `server.py:497-529`
  (`_resolve_codereview_dispatcher`) for lifecycle style.

---

## Acceptance Criteria

- [ ] Default plan ⇒ ParallelPerspective pair Opus 5 primary + Mantle gpt-5.6-sol adversary
- [ ] Explicit `codereview_dispatcher` argument overrides the plan
- [ ] No judge-panel/JudgeSpec file touched
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_flow/test_review_pair.py -v`; `ruff check` clean

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_flow/test_review_pair.py
class TestReviewPairAssembly:
    def test_default_pair_assembly(self): ...
    def test_explicit_dispatcher_wins(self): ...
    def test_no_plan_no_pair(self): ...
```

---

## Agent Instructions

1. **Read the spec**; 2. **Check dependencies** — TASK-2651/2652/2654 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** first
4. **Update status** in `sdd/tasks/index/refactor-dev-flow.json` → `"in-progress"`
5. **Implement**; 6. **Verify**; 7. **Move this file** to `sdd/tasks/completed/`;
8. **Update index** → `"done"`; 9. **Fill in the Completion Note**

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
