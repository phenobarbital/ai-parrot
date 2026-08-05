# TASK-2123: Per-run `require_plan_approval` override in DevelopmentNode

**Feature**: FEAT-412 — Dev-Flow: SDD-Oriented AgentsFlow for Feature Development
**Spec**: `sdd/specs/sdd-dev-flow.spec.md`
**Status**: done
**Completed**: 2026-08-05
**Verification**: verified
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (plan-gate half) + §8 (resolved 2026-08-05): dev.html
exposes a per-run plan-approval toggle. Today the flag is fixed at flow
construction (`DevelopmentNode(require_plan_approval=...)`), so a UI toggle
would require rebuilding the flow. This task makes the node honor a per-run
shared-state override.

---

## Scope

- In `dev_loop/nodes/development.py`: the plan-gate check currently reads
  `self._require_plan_approval` (set at :135 from ctor param :94, checked
  at :251). Change the check to:
  `shared.get("require_plan_approval", self._require_plan_approval)` —
  i.e. an explicit per-run value in shared state (True OR False) wins;
  absence falls back to the constructor flag. Keep the existing
  `shared.get("_plan_gate_checked")` retry-idempotency guard untouched.
- Unit tests for both override directions + fallback.

**NOT in scope**: the gate model extension (TASK-2122), server form
plumbing of `extra_shared["require_plan_approval"]` (TASK-2129), UI toggle
(TASK-2130).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py` | MODIFY | Shared-state override in the plan-gate check |
| `packages/ai-parrot/tests/flows/dev_loop/test_plan_gate_override.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py
# (verified 2026-08-05)
#   ctor param:    require_plan_approval: bool = False          # :94
#   stored as:     object.__setattr__(self, "_require_plan_approval", ...)  # :135
#   gate check:    if not self._require_plan_approval or \
#                     shared.get("_plan_gate_checked"): return   # :251
#   no-host path:  shared.get("session_host") is None → warn + skip  # :255-262
#   gate helper:   host.open_gate(kind="plan_approval", node_id=self.name,
#                     title=..., instructions=...,
#                     ttl_seconds=gate_ttl_for("plan_approval"),
#                     on_expiry="approve")                        # :276-283
#   wait:          gate = await host.wait_gate(gate_id)           # :284
#   not approved:  raise RuntimeError(...)                        # :285-288
```

### Does NOT Exist
- ~~`shared["require_plan_approval"]` consumption~~ — nothing reads that key
  today; this task adds it.
- ~~a public setter for `_require_plan_approval`~~ — the node uses
  `object.__setattr__` at construction only; do NOT mutate the attribute,
  read the shared-state override at check time instead.

---

## Implementation Notes

### Key Constraints
- The override must distinguish "key absent" (fallback to ctor flag) from
  "explicitly False" (suppress the gate even if the ctor flag is True) —
  use a sentinel-aware `shared.get(...)` lookup, not truthiness.
- `_plan_gate_checked` semantics unchanged: the gate opens at most once per
  run even across FEAT-377 repair-loop re-entries.
- Additive only — no signature changes to the ctor; all existing tests
  (incl. `test_runner_park.py` plan-gate cases) must pass unmodified.

### References in Codebase
- `nodes/development.py:245-290` — the plan-gate block to modify
- `runner.py:885 DevLoopRunner.run(..., extra_shared=...)` — how per-run
  values reach shared state (server passes `extra_shared`)

---

## Acceptance Criteria

- [ ] `shared["require_plan_approval"]=True` opens the plan gate with ctor flag False
- [ ] `shared["require_plan_approval"]=False` suppresses the gate with ctor flag True
- [ ] Key absent → constructor flag behavior (both values)
- [ ] Existing dev_loop suite passes unmodified
- [ ] `ruff check` clean

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_plan_gate_override.py
async def test_shared_true_overrides_ctor_false(): ...
async def test_shared_false_overrides_ctor_true(): ...
async def test_absent_key_falls_back_to_ctor(): ...
async def test_plan_gate_checked_guard_still_wins(): ...
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/sdd-dev-flow.json` → `"in-progress"`
5. **Implement**, **verify**, move this file to `sdd/tasks/completed/`,
   update index → `"done"`, fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-05
**Notes**:

`DevelopmentNode._check_plan_approval` now resolves the requirement per run:

```python
override = shared.get("require_plan_approval")
required = self._require_plan_approval if override is None else bool(override)
if not required or shared.get("_plan_gate_checked"):
    return
```

Implementation choices worth recording:

- **Sentinel, not truthiness** (as the task required): an explicit `False`
  suppresses a gate the constructor flag would have opened, while an absent
  key falls back to that flag. A present-but-`None` value is treated as
  *absent* rather than as `False` — a form/JSON payload that omits the field
  (or sends `null`) must not silently disable a flow-level plan gate.
  Pinned by `test_none_value_is_treated_as_absent`.
- `_require_plan_approval` is **read**, never mutated — no `object.__setattr__`
  at check time, so concurrent runs sharing one node instance cannot leak
  each other's toggle.
- The `_plan_gate_checked` guard is untouched and still short-circuits ahead
  of any gate work, so a QA-repair-loop re-entry cannot re-open the gate even
  with the override set (`test_plan_gate_checked_guard_still_wins`,
  `test_preset_checked_guard_suppresses_override`).
- The no-host legacy fallback (warn + proceed) applies to the override path
  too (`test_override_without_host_warns_and_proceeds`).

9 new tests, all passing. Regression: `test_gate_integration.py`,
`test_runner_park.py`, `test_development_node.py`, `test_development.py` →
57 passed unmodified. `ruff`: new test file 0 findings;
`development.py` unchanged at 28 (pre-existing, same count as on `dev`).

**Deviations from spec**: none.
