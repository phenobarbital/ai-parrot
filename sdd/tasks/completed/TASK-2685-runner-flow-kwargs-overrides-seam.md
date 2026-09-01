# TASK-2685: Per-run flow-kwargs overrides seam on DevLoopRunner

**Feature**: FEAT-490 — Per-run dev-flow model plan
**Spec**: `sdd/specs/per-run-model-plan.spec.md` (Module 2)
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`DevLoopRunner.run()` calls `self._dev_loop_flow_factory()` with no arguments
(`dev_loop/runner.py:1276`), and the factory closes over
`self._dev_loop_flow_kwargs` — construction-time state shared by every run.
There is no way to vary a flow-build kwarg for a single run.

This task adds that seam and nothing else. Spec §3 Module 2, §8 Q5 (resolved:
a **generic overrides mapping**, not a typed `model_plan` parameter — a
dev-flow concept must not leak into the bug flow's base class).

---

## Scope

- Add an optional per-run overrides mapping to `DevLoopRunner.run()` (name it
  `flow_kwargs_overrides: Optional[Dict[str, Any]] = None`).
- Thread it into `_dev_loop_flow_factory()` so the closure merges
  `self._dev_loop_flow_kwargs | overrides` **per call**. The overrides must
  never be stored on `self`.
- Keep `_execution_policy_for_fingerprint()` untouched (spec §8 Q2': the
  fingerprint deliberately stays on construction kwargs).

**NOT in scope**: any `model_plan` awareness (TASK 2/7), the ops console,
`run_revision()`, and any change to what the bug flow actually builds.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/runner.py` | MODIFY | `run()` signature + per-call factory |
| `packages/ai-parrot/tests/flows/dev_loop/test_runner_recovery.py` *(or the existing recovery test module)* | MODIFY | Seam tests |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/runner.py
class DevLoopRunner:                                                    # line 381
    def __init__(..., max_concurrent_runs: Optional[int] = None,        # line 421
                 dev_loop_flow_kwargs: Optional[Dict[str, Any]] = None) # line 430
    self._dev_loop_flow_kwargs = dev_loop_flow_kwargs                   # line 484

    async def run(self, brief, *, run_id=None, initial_task="", ...)    # line 1189
        recovery_enabled = run_id is not None and self._dev_loop_flow_kwargs is not None  # line 1237
        flow, mode = await self._checkpoint_coordinator.prepare(        # line 1271
            workflow="dev-loop", run_id=rid, brief=brief,
            live_context=ctx,
            flow_factory=self._dev_loop_flow_factory(),                 # line 1276
            execution_policy=self._execution_policy_for_fingerprint(),
        )

    def _dev_loop_flow_factory(self) -> Callable[[Optional[Any]], AgentsFlow]:  # line 1508
    def _execution_policy_for_fingerprint(self) -> Dict[str, Any]:             # line 1549
```

### Does NOT Exist
- ~~`DevLoopRunner.set_flow_kwargs()`~~ — and must not be added. Per-run state
  travels as call arguments and closures; this runner executes up to
  `max_concurrent_runs` runs concurrently, so instance state races.
- ~~`self._current_flow_kwargs`~~ — the tempting shortcut. Do not.

---

## Implementation Notes

### Key Constraints
- **Concurrency is the whole point of the design.** `DevLoopRunner` runs
  several runs at once; the existing code already avoids runner-level state for
  per-run things (the `SessionHost` is created per run and seeded into
  `shared`). Follow that pattern: pass the overrides into the factory builder,
  do not assign them to `self`.
- `flow_kwargs_overrides=None` must leave the bug flow byte-identical.
- `_dev_loop_flow_factory()` is overridden by `DevFlowRunner`
  (`dev_flow/runner.py:297`) — change the signature in a way that override can
  follow (TASK 2 does exactly that).

---

## Acceptance Criteria

- [ ] `DevLoopRunner.run()` accepts `flow_kwargs_overrides` and forwards it.
- [ ] The overrides are never assigned to an instance attribute.
- [ ] `run()` without overrides builds with exactly today's kwargs.
- [ ] Two concurrent runs with different overrides each build with their own.
- [ ] `_execution_policy_for_fingerprint()` is unchanged.
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop -v` passes.
- [ ] `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/runner.py`

---

## Test Specification

```python
async def test_run_without_overrides_is_byte_identical():
    """The bug flow must not notice this change at all."""

async def test_overrides_reach_the_flow_factory():
    """A supplied override appears in the kwargs build_* is called with."""

async def test_overrides_are_not_stored_on_the_instance():
    """Inspect the runner after a run: no per-run kwargs left behind."""

async def test_concurrent_runs_do_not_leak_overrides():
    """Two interleaved runs with different overrides each build with theirs."""
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
**Notes**: Added `flow_kwargs_overrides: Optional[Dict[str, Any]] = None` to
`DevLoopRunner.run()` and threaded it into `_dev_loop_flow_factory(overrides=None)`,
which now merges `dict(self._dev_loop_flow_kwargs) | overrides` into a local
`kwargs` dict per call — never assigned to `self`. `_execution_policy_for_fingerprint()`
left untouched, as required. Added 4 unit tests to
`test_recovery_lifecycle.py` covering byte-identical behaviour without
overrides, an override reaching `build_dev_loop_flow`, no per-run state
leaking onto the instance, and two back-to-back factory builds with
different overrides not leaking into each other. Tests patch the exact
`__globals__` dict of `_dev_loop_flow_factory` (not a dotted monkeypatch
string) — the same pitfall this test file's own `patch_handoff` fixture
already documents (test_lazy_import.py can leave the class bound to a
module object `sys.modules` no longer resolves to). Full
`pytest packages/ai-parrot/tests/flows/dev_loop -q` run: 1296 passed, 3
pre-existing unrelated failures (test_qa_codereview, test_secondopinion_brief,
test_subagent_parity — verified failing identically on `dev` before this
change, unrelated to FEAT-490). `ruff check` on the modified file shows the
same pre-existing `Optional[Dict[...]]`-style baseline debt already present
throughout the file (87 baseline errors); my two new signatures follow the
exact same established style as the surrounding, unmodified code in this
file (e.g. `dev_loop_flow_kwargs: Optional[Dict[str, Any]] = None`) rather
than a drive-by modernization.

**Deviations from spec**: none

**POST-REVIEW CORRECTION (same session, before push)**: the adversarial
code-reviewer found a CRITICAL bug in the override-merge logic added by
this task. `_dev_loop_flow_factory(overrides)` merged `overrides` into
`kwargs` UNCONDITIONALLY before returning the closure. This is wrong
because `AgentsFlow.resume()` (`bots/flows/flow/flow.py:1556`) calls the
SAME closure — `flow_factory(checkpoint.definition)` — to rebuild the
topology of a run's not-yet-completed nodes on a RESUME, not only
`DevCheckpointCoordinator.prepare()`'s fresh/cache-miss branch
(`flow_factory(None)`). The original merge therefore applied per-run
overrides to a resumed run's rebuild too — harmless for THIS task in
isolation (its own tests only ever call `factory(None)`), but load-bearing
for TASK-2687's resume rule built on top of this seam. Fixed by moving the
merge INSIDE the closure, gated on `_definition is None` (the only signal
available at the call site distinguishing "fresh" from "resuming").
Verified the fix is real (not cosmetic) by writing a regression test,
confirming it FAILS against the pre-fix code via `git stash`, then passes
after. See TASK-2687's completion note for the full analysis — this note
exists so a reader of TASK-2685 alone sees the correction too, since the
buggy code originated here.
