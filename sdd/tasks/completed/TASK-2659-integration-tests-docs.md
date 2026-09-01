# TASK-2659: Integration tests (multi-agent e2e, checkpoint, review pair) + documentation

**Feature**: FEAT-486 — Refactor Dev-Flow — Per-Seat LLM Configuration, Multi-Agent Development Pool, Configurable Review
**Spec**: `sdd/specs/refactor-dev-flow.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2652, TASK-2653, TASK-2655, TASK-2656, TASK-2658
**Assigned-to**: unassigned

---

## Context

Spec §4 Integration Tests + §5 documentation criterion. Proves the feature
end-to-end with stubbed dispatchers and closes the docs requirement.
Deliberately does NOT depend on TASK-2657 (FEAT-482-gated) — partner
coverage stays in 2657's own tests.

---

## Scope

- `test_dev_flow_multi_agent_end_to_end`: stubbed dispatchers; plan with 2
  pool specs + multi-task index ⇒ both workers dispatch, INFO deployment
  log emitted, per-seat usage attributed (`development.w1`/`w2`) on the
  FEAT-479 run ledger (`get_run_ledger`, `dev_loop/runner.py:545-595`).
- `test_dev_flow_checkpoint_resume_with_plan`: run with a plan, checkpoint,
  resume same plan ⇒ hit; changed routing-relevant field ⇒ fingerprint
  mismatch/fresh run (`compute_input_fingerprint`, `dev_loop/checkpoint.py`).
- `test_dev_flow_review_pair_end_to_end`: QA path invokes the
  parallel-perspective pair; adversary verdict merged; adversary performed
  no writes.
- Docs: update `docs/dev_loop/` (model-plan usage, new conf keys, Mantle
  counter-review, collapse rule) and `examples/dev_loop/README.md`/`GUIA.md`
  console sections (new selectors, defaults, NIM caveat).

**NOT in scope**: partner e2e (TASK-2657), new features of any kind.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/flows/dev_flow/test_feat486_integration.py` | CREATE | The three integration tests |
| `docs/dev_loop/` (model-plan page — name per existing doc conventions) | CREATE/MODIFY | Feature docs |
| `examples/dev_loop/README.md`, `examples/dev_loop/GUIA.md` | MODIFY | Console docs |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```python
# FEAT-479 (verified 2026-09-01):
# parrot/observability/context.py:126-158 — usage_attribution(run_id, seat)
# parrot/flows/dev_loop/runner.py:545-595 — _create_run_registry()/get_run_ledger();
#   per-run EventRegistry(forward_to_global=False) + RunLedgerRecorder
# parrot/observability/recorders/run_ledger.py — RunLedgerRecorder, SeatUsage, by_seat()
# Token usage is recorded from the AWAITED AfterClientCallEvent on the per-run registry;
#   a client not bound via _events_registry (dispatchers/llm.py:376-390) never reaches the ledger.

# FEAT-480:
# parrot/flows/dev_loop/checkpoint.py — compute_input_fingerprint(), TOPOLOGY_VERSION="1",
#   DevCheckpointCoordinator; resume goes through the flow FACTORY, seeds fresh FlowContext.

# Existing integration-test style: packages/ai-parrot/tests/flows/dev_flow/test_definition.py
#   and dev_loop test modules — follow their stub/dispatcher-double patterns.
```

### Does NOT Exist
- ~~Partner seat (`ideation.partner`) in the ledger~~ — only after FEAT-482 + TASK-2657; do not assert it here.
- ~~Live-provider calls in tests~~ — all dispatchers stubbed; no network.

---

## Implementation Notes

- pytest + pytest-asyncio; reuse existing fixtures/doubles from
  `tests/flows/dev_loop/` (grep for dispatcher stubs before writing new ones).
- The ledger assertion is the FEAT-479 contract test: assert
  `by_seat()` keys include `development.w1`/`development.w2`.
- Docs follow existing `docs/dev_loop/nova-backend.md` tone/structure.

---

## Acceptance Criteria

- [ ] Three integration tests pass: `pytest packages/ai-parrot/tests/flows/dev_flow/test_feat486_integration.py -v`
- [ ] Docs updated (dev_loop docs + console README/GUIA) with defaults table and NIM caveat
- [ ] Full suite still green: `pytest packages/ai-parrot/tests/flows/ -v`
- [ ] `ruff check` clean on new test file

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_flow/test_feat486_integration.py
class TestFeat486Integration:
    async def test_dev_flow_multi_agent_end_to_end(self): ...
    async def test_dev_flow_checkpoint_resume_with_plan(self): ...
    async def test_dev_flow_review_pair_end_to_end(self): ...
```

---

## Agent Instructions

1. **Read the spec**; 2. **Check dependencies** — TASK-2652/2653/2655/2656/2658 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** first
4. **Update status** in `sdd/tasks/index/refactor-dev-flow.json` → `"in-progress"`
5. **Implement**; 6. **Verify**; 7. **Move this file** to `sdd/tasks/completed/`;
8. **Update index** → `"done"`; 9. **Fill in the Completion Note**

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude Opus 5)
**Date**: 2026-09-01
**Notes**:
- `test_feat486_integration.py` — 13 tests over the three spec §4 rows.
  Everything external is stubbed (no provider, no git, no Redis); what is
  NOT stubbed is the machinery under test: the real `DevelopmentNode` /
  `DevAgentPool` wave loop, the real `RunLedgerRecorder`, the real
  `compute_input_fingerprint`, and the real
  `ParallelPerspectiveReviewDispatcher` merge.
- **Multi-agent e2e**: a 2-spec plan + 2-task index asserts all three
  contracts at once — both workers materialize and dispatch, the FEAT-486
  INFO log names `w1=nova:zai.glm-5` / `w2=nova:qwen...`, and FEAT-479
  attribution lands `development.w1` / `development.w2` on the ledger's
  `by_seat()`. The dispatcher double reproduces the real attribution
  contract rather than faking it: it enters
  `usage_attribution(run_id, seat=node_id)` exactly as
  `dispatchers/llm.py:215` does, and builds its `UsageRecord` off the same
  `current_run_id` / `current_seat` ContextVars the real
  `UsageRecordingSubscriber` reads. (`RunLedgerRecorder.record` is a
  coroutine — awaited inside the block, as the real fan-out does.)
  A companion test proves the SAME plan collapses to one seat on a
  1-task index.
- **Checkpoint**: fingerprints computed through the real
  `compute_input_fingerprint`. Same plan ⇒ identical digest (hit);
  changed pool shape or review backend ⇒ different digest (fresh run);
  model-string-only change ⇒ SAME digest (hit, as designed). Plus two
  guard tests: `TOPOLOGY_VERSION == "1"` and `_SHARED_DATA_ALLOWLIST`
  asserted member-for-member. And a regression test proving a run with NO
  plan produces the byte-identical digest a pre-FEAT-486 deployment would.
- **Review pair**: both seats invoked; the adversary's `passed=False` vetoes
  the merged verdict; `files_modified` is the primary's only, even when
  the adversary claims an edit; `use_tools=False` with no `tools` kwarg;
  and a Mantle outage degrades without failing the gate.
- **Docs**: new `docs/dev_loop/dev-flow-model-plan.md` (207 lines,
  following `nova-backend.md`'s operator-reference tone) — seat table,
  the nine conf keys, validation posture, collapse rule, deployment log,
  the read-only counter-reviewer's three structural layers, the
  fingerprint in/out table, planner interaction, the NIM caveat, and the
  build-time limitation. `examples/dev_loop/README.md` and `GUIA.md`
  (Spanish, matching its register) each gain a selector-group table, the
  defaults, the NIM caveat and the two stated limitations, plus the new
  keys in their variables tables.
- Full `packages/ai-parrot/tests/flows/` suite: **1727 passed**, 10
  skipped, 4 failed — all four verified to fail IDENTICALLY on unmodified
  `dev` with the same command (the three documented in TASK-2653 plus
  `test_dev_recovery_integration.py::test_runtime_entrypoints_build_per_run_flows`,
  which passes in isolation and is an ordering artifact). Net: +160
  passing tests, zero new failures. `ruff check` clean on the new test
  file.

**Deviations from spec**: none. Note that the partner e2e is deliberately
absent (out of scope, and TASK-2657 is gated on FEAT-482) — no test
asserts an `ideation.partner` seat.
