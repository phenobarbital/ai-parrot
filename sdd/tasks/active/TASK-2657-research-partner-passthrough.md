# TASK-2657: Research-partner passthrough (FEAT-482 coordinator wiring) — GATED

**Feature**: FEAT-486 — Refactor Dev-Flow — Per-Seat LLM Configuration, Multi-Agent Development Pool, Configurable Review
**Spec**: `sdd/specs/refactor-dev-flow.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2651, TASK-2656
**Assigned-to**: unassigned

> **⛔ EXTERNAL GATE — FEAT-482 must be merged first.** This task wires
> `model_plan.research_partner` into FEAT-482's
> `ComplementaryResearchCoordinator` seam. As of 2026-09-01 FEAT-482 is in
> progress upstream and its modules (`dev_flow/research_partner.py`,
> `complementary_research.py`, the `IdeationNode` coordinator kwarg) do NOT
> exist. **Do not start this task until they are on `dev`** — verify with:
> `ls packages/ai-parrot/src/parrot/flows/dev_flow/research_partner.py`.
> If FEAT-482 is still unmerged when every other FEAT-486 task is done,
> ship the feature without this task (spec §Worktree Strategy contingency)
> and leave it pending.

---

## Context

Spec §3 Module 5, partner half (goal G6). The partner stays disabled by
default; when the plan enables it, dev_flow builds/injects the FEAT-482
coordinator with the plan's backend+model.

---

## Scope

- In `dev_flow/factories.py`: when `model_plan.research_partner.enabled`,
  resolve the partner via FEAT-482's `resolve_research_partner_backend()` /
  `ResearchPartnerFactory` using the plan's `backend` (`"gpt"` → Mantle
  `gpt-5.6-sol`; `"nova"` → `us.amazon.nova-2-lite-v1:0`) and `model`,
  build the `ComplementaryResearchCoordinator`, and pass it to
  `IdeationNode` via the coordinator kwarg FEAT-482 added.
- Disabled (default) ⇒ no coordinator constructed, byte-identical wiring.
- Soft degradation is FEAT-482's job — do not add failure handling beyond
  passing the coordinator; assert in a test that a coordinator failure does
  not propagate (reusing FEAT-482's own test doubles if available).
- Unit tests: disabled ⇒ no coordinator; enabled ⇒ coordinator with plan
  backend/model; plan model overrides FEAT-482 env default.

**NOT in scope**: implementing any FEAT-482 machinery; console toggle UI
(TASK-2658, which may land before this and simply have the toggle produce
`enabled=true` plans that no-op until this task lands — acceptable, spec
contingency).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_flow/factories.py` | MODIFY | coordinator build + inject |
| `packages/ai-parrot/tests/flows/dev_flow/test_partner_passthrough.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_flow.model_plan import DevFlowModelPlan  # TASK-2651
```

### Signatures expected FROM FEAT-482 (unverified — VERIFY ON DISK before starting)
```python
# Per sdd/specs/devflow-complementary-research.spec.md §2 (approved design):
# dev_flow/research_partner.py — AbstractResearchPartner, ResearchPartnerFactory,
#   resolve_research_partner_backend(), BedrockResearchPartner
# dev_flow/complementary_research.py — ComplementaryResearchCoordinator
# dev_flow/nodes/ideation.py — one optional coordinator kwarg
# conf keys DEV_FLOW_RESEARCH_PARTNER* ("" disabled default, "gpt", "nova")
# resolve_research_partner_backend() REJECTS Anthropic partner models
#   (us.anthropic.*/global.anthropic.*/claude-*) — do not route claude models here.
```

### Does NOT Exist (as of 2026-09-01 — the gate)
- ~~`dev_flow/research_partner.py`~~, ~~`dev_flow/complementary_research.py`~~,
  ~~`ComplementaryResearchCoordinator`~~, ~~`IdeationNode(coordinator=...)`~~,
  ~~`DEV_FLOW_RESEARCH_PARTNER*` conf keys~~ — FEAT-482 not yet landed.
  Re-verify every one of these before starting; update this contract with
  real file:line anchors once they exist.

---

## Implementation Notes

- Plan wins over env for backend/model (consistent with TASK-2651
  precedence); FEAT-482's own env selector remains the fallback when the
  plan says enabled but names nothing.
- Anthropic partner models are rejected by FEAT-482's resolver by design —
  surface that `ValueError` untouched.

---

## Acceptance Criteria

- [ ] FEAT-482 modules verified on disk before any code written
- [ ] Disabled default ⇒ no coordinator, wiring byte-identical
- [ ] Enabled ⇒ coordinator built with plan backend/model; plan overrides env
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_flow/test_partner_passthrough.py -v`; `ruff check` clean

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_flow/test_partner_passthrough.py
class TestPartnerPassthrough:
    def test_disabled_default_no_coordinator(self): ...
    def test_enabled_builds_coordinator_with_plan_selection(self): ...
    def test_plan_overrides_env_default(self, monkeypatch): ...
```

---

## Agent Instructions

1. **Read the spec**; 2. **Check dependencies** — TASK-2651/2656 completed AND the FEAT-482 gate above
3. **Verify the Codebase Contract** — the "expected FROM FEAT-482" block MUST be re-anchored to real file:line before implementing
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
