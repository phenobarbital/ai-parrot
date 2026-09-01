# TASK-2676: Collapse the duplicate research-partner env keys onto FEAT-482's

**Feature**: FEAT-487 — Collapse the duplicate research-partner env keys
**Spec**: `sdd/specs/dev-flow-partner-env-key-dedup.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Carved out of FEAT-486 TASK-2657's Completion Note. FEAT-482 and FEAT-486
each invented env keys for the same research-partner seat because FEAT-486
was decomposed before FEAT-482 merged. FEAT-482's set shipped first, owns
the seat's implementation and carries a per-backend model dimension, so it
wins; FEAT-486's three keys are retired.

Full rationale, harm analysis and the key comparison table: spec §1.

---

## Scope

- Delete `ENV_PARTNER_ENABLED` / `ENV_PARTNER_BACKEND` / `ENV_PARTNER_MODEL`
  from `dev_flow/model_plan.py` (`:81-83`).
- Repoint `resolve_model_plan()`'s partner block (`:335-353`) at FEAT-482's
  keys:
  - `enabled` ← `DEV_FLOW_RESEARCH_PARTNER != ""`
  - `backend` ← `DEV_FLOW_RESEARCH_PARTNER` (falling back to
    `DEFAULT_PARTNER_BACKEND`)
  - `model` ← `DEV_FLOW_RESEARCH_PARTNER_GPT_MODEL` or
    `_NOVA_MODEL`, **selected by the resolved backend** (this is the latent
    bug the dedup also fixes: today a `nova` partner defaults its model to
    `gpt-5.6-sol`)
  Prefer delegating to `catalog.resolve_research_partner_backend(config_getter)`
  over re-parsing the key locally, so enable/backend semantics AND the
  Anthropic family guard stay in one place.
- Keep `ResearchPartnerPlan`'s field names (`enabled`/`backend`/`model`)
  and the console payload shape EXACTLY as they are — `factories.
  _resolve_research_coordinator()` and `/api/config` consume fields, not keys.
- Preserve precedence: explicit plan value > config > built-in default.
- Update the three docs that publish the retired key names.
- Update `tests/flows/dev_flow/test_model_plan.py` (the only other importer
  of the constants) and add the spec §4 tests.

**NOT in scope**: any change to FEAT-482's keys, resolver or coordinator;
`ResearchPartnerPlan` field renames; per-backend model fields on the plan;
the other three seat groups.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_flow/model_plan.py` | MODIFY | Remove 3 constants; repoint the partner block |
| `packages/ai-parrot/tests/flows/dev_flow/test_model_plan.py` | MODIFY | Retire constant imports; add spec §4 tests |
| `docs/dev_loop/dev-flow-model-plan.md` | MODIFY | Key table → FEAT-482's names |
| `examples/dev_loop/README.md` | MODIFY | Key table → FEAT-482's names |
| `examples/dev_loop/GUIA.md` | MODIFY | Key table → FEAT-482's names (Spanish) |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` at `95957471a` (post-FEAT-486 merge), 2026-09-01.
> Re-verify before starting: `dev` moves.

### Verified Imports
```python
from parrot import conf
from parrot.flows.dev_loop.catalog import resolve_research_partner_backend
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_flow/model_plan.py
DEFAULT_PARTNER_BACKEND: str = "gpt"                        # :66  KEEP
DEFAULT_PARTNER_MODEL: str = "gpt-5.6-sol"                  # :67  KEEP (gpt fallback)
ENV_PARTNER_ENABLED = "DEV_FLOW_RESEARCH_PARTNER_ENABLED"   # :81  REMOVE
ENV_PARTNER_BACKEND = "DEV_FLOW_RESEARCH_PARTNER_BACKEND"   # :82  REMOVE
ENV_PARTNER_MODEL   = "DEV_FLOW_RESEARCH_PARTNER_MODEL"     # :83  REMOVE
class ResearchPartnerPlan(BaseModel):                       # :109 fields UNCHANGED
    enabled: bool = False; backend: str = ...; model: str = ...
def resolve_model_plan(plan=None, *, config_getter=None) -> DevFlowModelPlan
#   partner block :335-353 — sole reader of the three constants.
#   `config_getter` signature is (key, fallback=...) -> Any; tests inject a
#   dict-backed lambda. Keep it and pass it through.

# packages/ai-parrot/src/parrot/conf.py — FEAT-482, authoritative
DEV_FLOW_RESEARCH_PARTNER            fallback ""                             # :1131
DEV_FLOW_RESEARCH_PARTNER_GPT_MODEL  fallback "gpt-5.6-sol"                  # :1137
DEV_FLOW_RESEARCH_PARTNER_NOVA_MODEL fallback "us.amazon.nova-2-lite-v1:0"   # :1141

# packages/ai-parrot/src/parrot/flows/dev_loop/catalog.py
def resolve_research_partner_backend(config_getter=None) -> str              # :157
#   returns "" | "gpt" | "nova"; RAISES ValueError naming (gpt, nova) on a
#   bad value, and also validates the resolved model against the Anthropic
#   family guard (validate_research_partner_model, :124).

# packages/ai-parrot/src/parrot/flows/dev_flow/factories.py
def _resolve_research_coordinator(explicit, plan)                            # :52
#   reads plan.research_partner.{enabled,backend,model} — NO change needed.
```

### Does NOT Exist
- Any importer of `ENV_PARTNER_*` beyond `model_plan.py` and
  `tests/flows/dev_flow/test_model_plan.py` — confirm with
  `grep -rn ENV_PARTNER packages/ examples/` before deleting.
- A per-backend model field on `ResearchPartnerPlan` — deliberately NOT added.
- A deprecation shim for the retired keys — see the open question below.

---

## Implementation Notes

- `resolve_research_partner_backend()` RAISES on an invalid value. That is
  consistent with `resolve_model_plan` already raising on an unknown
  `dev_pool` backend, so let it propagate rather than swallowing it.
- Resolve the backend FIRST, then pick the model default from it — the
  ordering is what fixes the `nova`-defaults-to-`gpt-5.6-sol` mismatch.
- `conf` module attributes vs `config_getter`: FEAT-482's resolver reads
  through the getter, but `resolve_backend_model()` reads `conf.*` module
  attributes directly. For the model default, read via the injected getter
  with the `conf.*` value as the fallback — that is the pattern the rest of
  `resolve_model_plan` already uses, and it keeps tests injectable.

## Reference Code
- `model_plan.py:355-375` — the review-pair block, same explicit>env>default
  shape to mirror for the partner block.
- `tests/flows/dev_flow/test_model_plan.py:33-40` — the `_getter` dict-lambda
  fixture to reuse for the new tests.

---

## Acceptance Criteria

- [ ] The three `ENV_PARTNER_*` constants are gone
- [ ] `grep -rn "DEV_FLOW_RESEARCH_PARTNER_ENABLED\|_PARTNER_BACKEND\|DEV_FLOW_RESEARCH_PARTNER_MODEL" packages/ examples/ docs/` returns nothing
- [ ] `DEV_FLOW_RESEARCH_PARTNER=nova` ⇒ plan `enabled=True, backend="nova"`, model from `_NOVA_MODEL`
- [ ] Unset key ⇒ `enabled=False` (unconfigured deployment unchanged)
- [ ] Explicit plan values still beat config
- [ ] `ResearchPartnerPlan` fields and `/api/config` payload unchanged
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_flow/ -v`; `ruff check` clean
- [ ] The three docs publish only FEAT-482's key names

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_flow/test_model_plan.py (extend)
class TestPartnerKeyDedup:
    def test_partner_enabled_from_feat482_key(self): ...
    def test_partner_disabled_when_key_unset(self): ...
    def test_partner_model_follows_backend(self): ...       # nova -> _NOVA_MODEL
    def test_explicit_plan_still_beats_config(self): ...
    def test_retired_keys_are_ignored(self): ...            # _ENABLED alone: no-op
    def test_invalid_backend_surfaces_feat482_error(self): ...  # match "gpt, nova"
```

---

## Agent Instructions

1. **Read the spec** at the path in the header
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — `dev` moves; re-anchor the line numbers
   and re-run the `ENV_PARTNER` grep before deleting anything
4. **Update status** in `sdd/tasks/index/dev-flow-partner-env-key-dedup.json` → `"in-progress"`
5. **Implement**; 6. **Verify**; 7. **Move this file** to `sdd/tasks/completed/`
   via `scripts/sdd/close_task.sh`; 8. **Update index** → `"done"`;
9. **Fill in the Completion Note**

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
