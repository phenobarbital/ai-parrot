# TASK-2659: Integration tests (multi-agent e2e, checkpoint, review pair) + documentation

**Feature**: FEAT-486 — Refactor Dev-Flow — Per-Seat LLM Configuration, Multi-Agent Development Pool, Configurable Review
**Spec**: `sdd/specs/refactor-dev-flow.spec.md`
**Status**: pending
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

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
