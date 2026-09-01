# TASK-2687: A resumed run keeps the seats it was created with

**Feature**: FEAT-490 — Per-run dev-flow model plan
**Spec**: `sdd/specs/per-run-model-plan.spec.md` (Module 3)
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-2686
**Assigned-to**: unassigned

---

## Context

Spec §8 Q1 (resolved): when a run resumes from a checkpoint and the caller
submits a *different* plan, the **original seats win**. A resumed run's
completed nodes were produced by those models; adopting new ones mid-history
makes the bundle self-contradictory. The new plan must be reported as not
applied, never silently swapped.

Reachable only by an embedder reusing a stable `run_id` — the dev console mints
a fresh one on every request (`server_dev.py:640`), so it always takes the
fresh path.

Spec §3 Module 3, §7 (accepted limitation).

---

## Scope

- Implement the rule: on `mode == "resumed"`, the newly submitted plan does not
  take effect.
- Record, on the run's snapshot/bundle, the effective plan and whether the run
  was `fresh` or `resumed`, so a caller can tell what actually ran.
- Add a test that pins the **accepted limitation**: a per-run plan does NOT
  move the checkpoint fingerprint (`_execution_policy_for_fingerprint`,
  `dev_flow/runner.py:327`). This is a decision, not an oversight — assert it
  so it cannot drift silently.

**NOT in scope**: changing `_execution_policy_for_fingerprint` (§8 Q2'
resolved: leave it), the console's reporting (TASK 4).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_flow/runner.py` | MODIFY | Resume rule + effective-plan recording |
| `packages/ai-parrot/tests/flows/dev_flow/` | MODIFY | Resume + fingerprint tests |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/checkpoint.py
async def prepare(...) -> tuple[AgentsFlow, Literal["fresh", "resumed"]]:  # line 471
    if existing is None:                                                   # line 553
        self.emit_recovery_event("cache_miss", ...)                        # line 554
        flow = flow_factory(None)                                          # line 555
        return flow, "fresh"                                               # line 558
    # ...otherwise AgentsFlow.resume(...) and return (flow, "resumed")

# packages/ai-parrot/src/parrot/flows/dev_flow/runner.py
def _execution_policy_for_fingerprint(self) -> dict[str, Any]:             # line 327
    # FEAT-486 note (lines 336-344) documents which plan fields join the
    # fingerprint: pool shape, review backend, partner-enabled IN;
    # pure model strings OUT. LEAVE THIS METHOD ALONE.
```

### Does NOT Exist
- ~~`DevCheckpointCoordinator.prepare(model_plan=…)`~~ — the coordinator takes
  no plan and must stay workflow-agnostic.
- ~~a "seats" field on the checkpoint envelope~~ — the resume rule is enforced
  by NOT rebuilding, not by storing seats in the checkpoint.

---

## Implementation Notes

The rule is mostly a matter of *not* doing something: the resume branch does
not call `flow_factory`, so the original seats survive by construction. The
work is (a) making that explicit and documented rather than incidental, and
(b) reporting it, so a caller who submitted a plan learns it was not applied.

---

## Acceptance Criteria

- [ ] A resumed run does not adopt a newly submitted plan.
- [ ] The run records its effective plan and `fresh|resumed` mode.
- [ ] A test asserts a per-run plan does not move the fingerprint.
- [ ] `_execution_policy_for_fingerprint` is unmodified (diff shows no change).
- [ ] `pytest packages/ai-parrot/tests/flows/dev_flow -v` passes.

---

## Test Specification

```python
async def test_resumed_run_keeps_original_seats(): ...
async def test_resumed_run_reports_the_plan_as_not_applied(): ...
def test_per_run_plan_does_not_move_the_fingerprint():
    """Accepted limitation (spec §7), asserted rather than assumed."""
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
**Notes**: In `DevFlowRunner.run()`, introduced a `mode: Literal["fresh",
"resumed"] = "fresh"` local (default applies when recovery is disabled —
inherently a plain fresh run) and a `model_plan_applied = model_plan is not
None and mode != "resumed"` flag, documented with an explicit comment
tracing WHY the resume rule already holds by construction:
`DevCheckpointCoordinator.prepare()` never calls `flow_factory` on the
resume branch (only on a cache miss), so a resumed run's seats were never
going to be rebuilt with the newly submitted plan in the first place —
TASK-2686's `flow_kwargs_overrides` only ever reaches `build_dev_flow` on
the fresh path. Extended the metadata recording added in TASK-2686 with
`result.metadata["model_plan_effective"]` (the requested plan's dump when
`model_plan_applied`, else `None`) and `result.metadata["run_mode"]` (the
`mode` value). `_execution_policy_for_fingerprint()` is untouched — `git
diff` on that method shows no lines changed, confirmed. Added 6 tests to
`test_runner.py`: a resumed run running the coordinator's own returned flow
object directly (no rebuild), a resumed run reporting
`model_plan_effective=None` with `model_plan_requested` still populated, a
symmetric fresh-run control, the accepted-limitation fingerprint test (two
runs with different per-run plans produce byte-identical
`execution_policy` dicts, and neither contains a `model_plan` key since
none was supplied at construction time), and a structural guard pinning
`_execution_policy_for_fingerprint`'s signature still takes no per-run
argument. `pytest packages/ai-parrot/tests/flows/dev_flow -q`: 443 passed.
`pytest packages/ai-parrot/tests/flows/dev_loop -q`: 1296 passed, 3
pre-existing unrelated failures (same as TASK-2685/2686). `ruff check`
clean.

**Deviations from spec**: none
