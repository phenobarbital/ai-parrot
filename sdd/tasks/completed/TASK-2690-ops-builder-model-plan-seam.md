# TASK-2690: Add a model_plan parameter to build_dev_loop_flow

**Feature**: FEAT-490 — Per-run dev-flow model plan
**Spec**: `sdd/specs/per-run-model-plan.spec.md` (Module 7)
**Status**: pending
**Priority**: medium
**Estimated effort**: L
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §8 Q3 (resolved): the ops topology gets the **library** seam, not the
console UI. The premise that this was "the same seam, another builder" was
wrong — `build_dev_loop_flow` has no `model_plan` among its 27 kwargs, and the
ops console has no per-seat selectors at all (`static/index.html` contains no
`model_plan`; `server.py` touches `DevFlowModelPlan` only at `:1657`, to
resolve the research partner).

This task gives the ops builder parity so an embedder can pass a plan. Building
the ops console's UI is a separate feature.

Spec §3 Module 7.

---

## Scope

- Add `model_plan: DevFlowModelPlan | None = None` to `build_dev_loop_flow()`
  (`dev_loop/flow.py:332`).
- Wire it to that topology's seats with the SAME precedence its dev-flow
  sibling uses: an explicit `codereview_dispatcher` / `development_pool_config`
  passed by the caller still wins over the plan.
- `model_plan=None` must leave every existing call byte-identical.

**NOT in scope**: the ops runner (TASK 7), the ops console UI, `/api/config`,
any form parser.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/flow.py` | MODIFY | New kwarg + node wiring |
| `packages/ai-parrot/tests/flows/dev_loop/` | MODIFY/CREATE | Parity + byte-identical tests |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/flow.py
def build_dev_loop_flow(                                                # line 332
    *, dispatcher, jira_toolkit, log_toolkits, redis_url,
    development_pool_config=None,                                       # line 344
    development_dispatcher_builder=None,                                # line 345
    codereview_dispatcher=None,                                         # line 349
    research_coordinator=None,                                          # line 355
    checkpoint=False, checkpoint_required=False, checkpoint_store=None, # lines 358-360
    ...)                                                                # 27 kwargs total

# Reference implementation — the dev-flow sibling doing exactly this:
# packages/ai-parrot/src/parrot/flows/dev_flow/factories.py
resolved_plan = resolve_model_plan(model_plan)                          # line 259
pool_config = resolved_plan.to_pool_config()                            # line 260
review_dispatcher = codereview_dispatcher                               # line 272
if review_dispatcher is None and resolved_plan is not None:             # line 273
    review_dispatcher = _assemble_review_pair(resolved_plan, dispatcher)# line 274
IdeationNode(model=resolved_plan.research_primary if resolved_plan else None)  # line 308
```

### Does NOT Exist
- ~~`build_dev_loop_flow(model_plan=…)`~~ — this task is what adds it. Nothing
  in the ops path accepts a plan today; do not assume parity before this lands.
- ~~per-seat selectors in the ops console~~ — `static/index.html` has none, and
  none are added here.
- ~~an `IdeationNode` in the ops topology~~ — that is dev-flow's. Map the plan
  onto the seats this topology actually has; verify them by reading the builder
  before wiring anything.

---

## Implementation Notes

### Key Constraints
- **The ops bug flow has no reported problem.** This is a seam, not a
  behaviour change. A regression here is a pure loss.
- Mirror the dev-flow precedence exactly, so the two topologies cannot drift
  into different answers for "explicit dispatcher vs plan".

---

## Acceptance Criteria

- [ ] `build_dev_loop_flow(model_plan=None)` is byte-identical to today.
- [ ] A plan selects the ops seats it maps to.
- [ ] An explicit `codereview_dispatcher` still wins over the plan.
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop -v` passes untouched.

---

## Test Specification

```python
def test_build_dev_loop_flow_without_plan_is_byte_identical(): ...
def test_build_dev_loop_flow_applies_the_plan(): ...
def test_explicit_dispatcher_still_wins_over_the_plan(): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/per-run-model-plan.spec.md` for full context — especially §2 (Overview)
   and §8 (every open question is resolved there; do not re-open them).
2. **Check dependencies** — verify `Depends-on` tasks are in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** before writing ANY code. The line numbers
   above were correct on 2026-09-01; this repo drifts fast (an unrelated merge
   moved two of these files by 100+ lines in one afternoon). Re-grep the
   symbol, and if it moved, update the contract FIRST.
4. **Update status** in `sdd/tasks/index/per-run-model-plan.json` → `in-progress`.
5. **Implement** following the scope. Do not widen it.
6. **Verify** every acceptance criterion.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update the index** → `done`, and fill in the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-01
**Notes**: Added `model_plan: Optional[DevFlowModelPlan] = None` to
`build_dev_loop_flow()`. Wired to the TWO seats this topology actually
has (no `IdeationNode` — verified by reading the builder first, per the
"Does NOT Exist" list): the development pool
(`development_pool_config`/`development_dispatcher_builder`) and QANode's
review pair (`codereview_dispatcher`). Precedence matches the dev-flow
sibling exactly (explicit argument > plan > default), adapted for the one
real difference: this builder already exposes `development_pool_config`
as a direct kwarg (FEAT-323 predates this feature), so the "explicit
wins" check applies to it too, not just the dispatcher-builder — dev-flow's
own `build_dev_flow_node_factories` has no such kwarg to protect.
`research_coordinator` is untouched — it stays an explicit-only seam,
matching the task's own "Does NOT Exist" guidance not to invent an
ideation-equivalent mapping.

**Local duplication, not a private cross-package import**: the review-pair
assembly logic (`_build_primary_reviewer`/`_assemble_review_pair`) is
duplicated locally in `dev_loop/flow.py` rather than imported from
`dev_flow.factories` — those are underscore-prefixed (private) there, and
`dev_flow/factories.py` itself sets the precedent of keeping a small
helper (`_with_graph`) local "rather than importing a private symbol
across packages." Both duplicated helpers use ONLY `dev_loop`-native
symbols (`code_review.CodeReviewDispatcherFactory`,
`dispatchers.mantle.MantleAdversarialReviewDispatcher`,
`agent_builder.build_dispatcher`, `catalog.PRIMARY_REVIEW_BACKENDS`), so
no new cross-package dependency was introduced by them.

**Circular import found and fixed**: a top-level
`from parrot.flows.dev_flow.model_plan import DevFlowModelPlan,
resolve_model_plan` broke test collection
(`ImportError: cannot import name 'DevFlowModelPlan' from partially
initialized module`) whenever something imports `dev_flow` before
`dev_loop` finishes initializing — `dev_flow/model_plan.py` itself imports
`parrot.flows.dev_loop.catalog`/`models.base` at module load, and
`dev_loop/flow.py` is imported transitively by `dev_loop/__init__.py`
(via `commands.py` → `runner.py` → `flow.py`), so a module-level import
of `dev_flow.model_plan` from `dev_loop/flow.py` is a genuine cycle.
Caught by running `pytest packages/ai-parrot/tests/flows/dev_flow -q`
(the full task suite, not just the new test file) — a
`test_complementary_research.py` collection error. Fixed by moving
`DevFlowModelPlan` to a `TYPE_CHECKING`-guarded import (safe: the file
already has `from __future__ import annotations`, so the signature's type
hint is never evaluated at runtime) and `resolve_model_plan` to a lazy,
function-body import (mirrors the existing `agent_builder.build_dispatcher`
lazy-import pattern a few lines below it, same file). This is exactly the
FEAT-490-cross-cutting risk the wider spec's Module 7/8 worktree-strategy
note flags — worth calling out for whoever eventually revisits Module 8.

Added `packages/ai-parrot/tests/flows/dev_loop/test_model_plan_seam.py`
(new file, mirrors `tests/flows/dev_flow/test_plan_threading.py`'s
harness/assertion style exactly — materialized node private attributes:
`_pool_config`/`_dispatcher_builder` on `DevelopmentNode`,
`_codereview_dispatcher` on `QANode`): byte-identical without a plan
(omitted, explicit `None`, and every existing explicit kwarg still
honoured), the plan applying to both seats, explicit-argument-wins for
both seats independently, the no-IdeationNode / research_coordinator-
untouched guard, and the unknown-backend rejection tests. 19 new tests,
all passing. `pytest packages/ai-parrot/tests/flows/dev_flow -q`: 449
passed (this is what caught the circular import). `pytest
packages/ai-parrot/tests/flows/dev_loop -q`: 1315 passed, 3 pre-existing
unrelated failures (same three as every other task in this feature).
`ruff check`: the test file is clean; `flow.py` gained exactly 2 new
baseline-style violations (`Optional[DevFlowModelPlan]`/`UP045`,
`UP006`), matching the file's own pre-existing, unmodernized
`Optional[...]`/`Dict[...]` convention throughout (29 baseline errors
before this task's edit, 31 after) — not a drive-by modernization.

**Deviations from spec**: none in behavior. The circular-import fix
(TYPE_CHECKING + lazy import) is an implementation detail necessitated by
the codebase's actual module graph, not present in the task's Codebase
Contract — documented here since a future maintainer touching these
imports needs to know why they are structured this way.
