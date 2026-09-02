# TASK-2718: server_dev.py — Add research_primary_models to _model_plan_payload

**Feature**: FEAT-494 — select-model-dev-flow-ideation-model
**Spec**: `sdd/specs/select-model-dev-flow-ideation-model.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2717
**Assigned-to**: unassigned

---

## Context

`_model_plan_payload()` in `server_dev.py` (lines 353–391) serialises the
resolved `DevFlowModelPlan` for `/api/config`. It exposes `pool_backends`,
`review_primary_backends`, and `partner_backends` as curated lists, but does
NOT include a corresponding `research_primary_models` list for the ideation
seat. Any surface querying `defaults.model_plan` has no named curated model
list for that seat.

This task implements spec §3 Module 2.

**Requires TASK-2717 first**: the new `"research_primary"` role added to the
`claude-code` backend in TASK-2717 is not a prerequisite at runtime (this
task reads `get_backend("claude-code").models` directly), but the catalog
change must be committed before this task so the full Fable model list
is present in the models tuple that `_model_plan_payload` serialises.

---

## Scope

- In `_model_plan_payload()`, add:
  ```python
  "research_primary_models": list(llm_catalog.get_backend("claude-code").models) if llm_catalog.get_backend("claude-code") else [],
  ```
  This derives from the catalog entry so it picks up any future Fable additions
  automatically without duplicating the list.

**NOT in scope**:
- `catalog.py` changes (TASK-2717).
- Test files (TASK-2719).
- `dev.html` changes (the datalist already reads from the catalog's `backends`
  array automatically — no UI change needed).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/dev_loop/server_dev.py` | MODIFY | Add `research_primary_models` key to `_model_plan_payload()` return dict |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# server_dev.py already imports llm_catalog at module level — use the existing alias
from parrot.flows.dev_loop import catalog as llm_catalog
# verified: examples/dev_loop/server_dev.py (top-of-file imports)

# llm_catalog.get_backend signature:
# packages/ai-parrot/src/parrot/flows/dev_loop/catalog.py:409-417
def get_backend(backend_id: str) -> Optional[BackendInfo]: ...
# Returns Optional[BackendInfo] — MUST guard against None
```

### Existing Signatures to Use

```python
# examples/dev_loop/server_dev.py:353-391
def _model_plan_payload(plan: DevFlowModelPlan, *, review_pair_active: bool = True) -> dict[str, Any]:
    return {
        "review_pair_active": review_pair_active,
        "research_primary": plan.research_primary,
        "research_partner": plan.research_partner.model_dump(mode="json"),
        "dev_agents": [{"agent": spec.agent, "model": spec.model, "count": spec.count} for spec in plan.dev_pool],
        "review": {
            "primary": {"agent": plan.review.primary.agent, "model": plan.review.primary.model},
            "counter_model": plan.review.counter_model,
        },
        "pool_backends": list(supported_dev_pool_backends()),
        "review_primary_backends": list(llm_catalog.PRIMARY_REVIEW_BACKENDS),
        "partner_backends": [b.id for b in llm_catalog.backends_for_role("research_partner")],
        # ← add "research_primary_models" here
    }

# packages/ai-parrot/src/parrot/flows/dev_loop/catalog.py:409-417
def get_backend(backend_id: str) -> Optional[BackendInfo]:
    return _BY_ID.get(backend_id)

# packages/ai-parrot/src/parrot/flows/dev_loop/catalog.py:214-227
class BackendInfo(NamedTuple):
    models: Tuple[str, ...]  # line 224 — this is what we serialize
```

### Does NOT Exist

- ~~`llm_catalog.RESEARCH_PRIMARY_BACKENDS`~~ — no such constant; use `llm_catalog.get_backend("claude-code").models`.
- ~~`llm_catalog.research_primary_models()`~~ — no such function.
- ~~`plan.research_primary_models`~~ — `DevFlowModelPlan` has no such field; derive from catalog.

---

## Implementation Notes

### Pattern to Follow

Follow the exact pattern of `pool_backends` and `partner_backends` already
in the return dict — derive from the catalog, not from a hardcoded literal:

```python
# existing pattern in _model_plan_payload():
"pool_backends": list(supported_dev_pool_backends()),
"review_primary_backends": list(llm_catalog.PRIMARY_REVIEW_BACKENDS),
"partner_backends": [b.id for b in llm_catalog.backends_for_role("research_partner")],

# new addition — same style:
"research_primary_models": (
    list(llm_catalog.get_backend("claude-code").models)
    if llm_catalog.get_backend("claude-code") else []
),
```

### Key Constraints

- `llm_catalog.get_backend("claude-code")` returns `Optional[BackendInfo]` —
  guard against `None` even though the entry is always present in practice.
- The key name must be exactly `"research_primary_models"` (the test in
  TASK-2719 asserts this exact key).
- Do NOT hardcode the model list — derive it from the catalog so Module 1's
  additions are automatically reflected.

### References in Codebase

- `examples/dev_loop/server_dev.py:353-391` — `_model_plan_payload()`
- `packages/ai-parrot/src/parrot/flows/dev_loop/catalog.py:409-417` — `get_backend()`

---

## Acceptance Criteria

- [ ] `_model_plan_payload()` return dict contains `"research_primary_models"` key.
- [ ] The value is a list (not `None`, not a tuple).
- [ ] The list contains `"claude-fable-5-1"` and `"claude-fable-5"` (requires TASK-2717 complete).
- [ ] The list contains `"claude-opus-5"` (regression guard).
- [ ] `pytest packages/ai-parrot/tests/flows/dev_flow/test_server_dev_model_plan.py -v` passes
      (all existing tests still green).

---

## Test Specification

No new test file — tests are in TASK-2719. Run after implementation:

```bash
source .venv/bin/activate
pytest packages/ai-parrot/tests/flows/dev_flow/test_server_dev_model_plan.py -v
```

---

## Agent Instructions

When you pick up this task:

1. **Confirm TASK-2717 is completed** — verify `sdd/tasks/completed/TASK-2717-*.md` exists.
2. **Read the spec** at `sdd/specs/select-model-dev-flow-ideation-model.spec.md`.
3. **Verify the Codebase Contract** — open `examples/dev_loop/server_dev.py` around line 353
   to confirm `_model_plan_payload()` shape before editing.
4. Add the `"research_primary_models"` key to the return dict of `_model_plan_payload()`.
5. Run `pytest packages/ai-parrot/tests/flows/dev_flow/test_server_dev_model_plan.py -v`
   and confirm all existing tests pass.
6. Commit: `feat(FEAT-494): add research_primary_models to _model_plan_payload`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
