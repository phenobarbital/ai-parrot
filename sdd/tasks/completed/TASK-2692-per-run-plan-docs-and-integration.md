# TASK-2692: Reference docs and end-to-end coverage

**Feature**: FEAT-490 — Per-run dev-flow model plan
**Spec**: `sdd/specs/per-run-model-plan.spec.md` (Module 6)
**Status**: pending
**Priority**: medium
**Estimated effort**: M
**Depends-on**: TASK-2688, TASK-2689, TASK-2691
**Assigned-to**: unassigned

---

## Context

`docs/dev_loop/dev-flow-model-plan.md` documents the build-time-only rule,
which this feature replaces for the dev-flow path. The end-to-end story also
needs coverage that no single earlier task owns.

Spec §3 Module 6.

---

## Scope

- Rewrite the build-time sections of `docs/dev_loop/dev-flow-model-plan.md`:
  seats are per-run for dev-flow; resume keeps original seats; the ops library
  seam exists but its console does not.
- Add the integration coverage from spec §4 that spans tasks: a console run
  applying a per-seat selection end to end, and the always-fresh `run_id`
  premise.

**NOT in scope**: new behaviour of any kind.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/dev_loop/dev-flow-model-plan.md` | MODIFY | Per-run rules |
| `packages/ai-parrot/tests/flows/dev_flow/test_server_dev_model_plan.py` | MODIFY | Integration coverage |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```python
# packages/ai-parrot/tests/flows/dev_flow/test_server_dev_model_plan.py
# Existing harness to reuse — do NOT build a second one:
def _load_module(name: str, filename: str)   # importlib from examples/dev_loop/
class _StubFlow                              # records ctx in .contexts
@pytest.fixture def make_client(server_dev, aiohttp_client)
def _nl_form(**extra) -> dict[str, Any]
class TestPlanMismatchDiff._roundtrip_form(server_dev, plan)
```

### Does NOT Exist
- ~~a docs generator for this page~~ — it is hand-written Markdown.

---

## Acceptance Criteria

- [ ] The reference doc no longer claims the seats are build-time for dev-flow.
- [ ] The doc states the resume rule and the ops seam/console split.
- [ ] Integration tests from spec §4 exist and pass.
- [ ] `pytest packages/ai-parrot/tests/flows/dev_flow packages/ai-parrot/tests/flows/dev_loop -v` passes.

---

## Test Specification

```python
async def test_run_endpoint_applies_ideation_model_end_to_end(): ...
async def test_console_run_id_is_always_fresh(): ...
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
**Notes**: Replaced `docs/dev_loop/dev-flow-model-plan.md`'s "Known
limitation" section (the only build-time-only claim left in the doc —
verified by grepping for "build-time" before and after) with a new
"Per-run application (FEAT-490)" section covering: the per-run mechanism
and how it composes with FEAT-480 checkpointing (fresh cache-miss rebuilds
with the plan merged in; never stored on the runner instance); the resume
rule (a resumed run keeps its original seats, reported via
`result.metadata`'s `model_plan_requested`/`model_plan_effective`/
`run_mode`); the dev console's always-fresh-by-default behaviour plus its
resume opt-in (correcting the same stale "no resume endpoint" premise
TASK-2688 already had to correct in code); the accepted fingerprint
limitation, pinned by TASK-2687's test; and the ops library seam
(Module 7/8) existing without its console.

Added the integration coverage spec §4 names that spans multiple tasks and
wasn't fully closed by any single earlier one: `test_run_endpoint_applies_
ideation_model_end_to_end` (`TestEndToEndAppliesThePerSeatSelection` in
`test_server_dev_model_plan.py`) drives the REAL recovery-enabled
`DevFlowRunner` (not the lightweight `_StubFlow`-only harness every other
test in that file uses) through the actual HTTP endpoint, with
`build_dev_flow` patched via `DevFlowRunner._dev_loop_flow_factory.
__globals__` to capture what it's called with — proving the full chain
POST → `handle_run` → `runner.run(model_plan=...)` → `build_dev_flow(
model_plan=...)` for a differing `research_primary`, closing the loop
between TASK-2686 (runner accepts the plan) and TASK-2688 (console passes
it) that neither task's own tests fully exercised together. A companion
control test confirms the no-submission case still reaches `build_dev_flow`
with the server's construction-time plan, byte-identical to before.
`test_console_run_id_is_always_fresh`'s corrected form
(`test_console_mints_a_fresh_run_id_when_none_is_supplied`) already exists
from TASK-2688/2689 — not duplicated here.

Caught and fixed one test-authoring bug during this task: a bare
`MagicMock()` used as `dev_loop_flow_kwargs["model_plan"]` crashed
`_execution_policy_for_fingerprint()` (iterates `model_plan.dev_pool`) with
`TypeError: Object of type MagicMock is not JSON serializable` before
`run()` ever reached `flow_factory` — replaced with a real, minimal
`DevFlowModelPlan(research_primary="claude-opus-5")` instance.

`pytest packages/ai-parrot/tests/flows/dev_flow packages/ai-parrot/tests/flows/dev_loop -v`
(the exact acceptance-criterion command): 1769 passed, 3 pre-existing
unrelated failures (`test_qa_codereview`, `test_secondopinion_brief`,
`test_subagent_parity` — the same three every other task in this feature
has verified failing identically on `dev` before this branch). `ruff
check` clean on the test file (the doc file is Markdown, not lint-checked).

**Deviations from spec**: none.

**POST-REVIEW CORRECTION (same session, before push)**: the adversarial
code-reviewer found that the resume rule this doc's new "Per-run
application (FEAT-490)" section describes (a resumed run keeps its
original seats) was not actually enforced by the code at the time this
task completed — `AgentsFlow.resume()` rebuilds a resumed run's
not-yet-completed nodes through the SAME `flow_factory` closure a fresh
build uses, so a per-run override was silently reaching them too. Fixed
in `dev_loop/runner.py`/`dev_flow/runner.py` (TASK-2685/2686's files);
full analysis in TASK-2687's completion note. The documentation added by
THIS task required no changes — it describes the rule as intended, and
the fix makes the code match what it already said, rather than the other
way around.
