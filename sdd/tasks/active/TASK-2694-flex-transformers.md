# TASK-2694: Flex infographic transformers (Payroll Contribution, Utilization, Proximity)

**Feature**: FEAT-491 — Flex A2UI Dashboard Agent
**Spec**: `sdd/specs/flex-agent-infographic-a2ui.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2693
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2. Every dashboard number must come from a **registered, pure**
`@infographic_transformer` `(inputs, params) -> dict` (FEAT-324 G1 — never
from replaying LLM code). Section names in the recipe (TASK-2697) resolve to
these registry names 1:1, and each transformer hard-codes its input frame
key to the frozen dataset aliases from spec §2: `msl`, `finance`, `hours`,
`employees`, `region_utilization`, `rep_utilization`.

**Pinned formulas (spec §2, resolved Q&A — do NOT deviate):**
- Payroll % to Revenue = `sum(Payroll) / sum(Revenue)` from `finance`
  (denominator is Revenue ALONE, not Revenue + PC Revenue).
- Worked Hours = `sum(hours)` from `hours` (pay_code/cost_center filterable);
  `finance["Total Hours"]` only as FTE cross-check.
- Rep Utilization = `employees_worked / average_active` recomputed from
  `rep_utilization`; `region_utilization` precomputed column = cross-check.
- Proximity Staffing = per-store nearest-N employees, haversine, radius
  param (default 50 miles), two map layers + coverage table.

---

## Scope

- Implement `agents/flex_dashboard/transformers.py` with registered
  transformers (names ARE the registry keys):
  - `payroll_hero` — dict with `worked_hours_total`, `payroll_total`,
    `revenue_total`, `payroll_pct` (inputs: `hours`, `finance`).
  - `worked_hours_by_month` (inputs: `hours`; params: `month`, `pay_code`,
    `cost_center`, `flex_type` NOT accepted — dataset lacks it).
  - `payroll_by_month` (inputs: `finance`; params: `month`).
  - `revenue_by_month` (inputs: `finance`; params: `month`).
  - `payroll_pct_by_month` (inputs: `finance`; params: `month`).
  - `pay_code_hours` (inputs: `hours`; params: `month`, `pay_code`, `cost_center`).
  - `pay_code_allocation` (inputs: `hours`; params: `month`, `cost_center`).
  - `rep_utilization_by_region` (inputs: `rep_utilization`,
    `region_utilization`; params: `month`, `category`).
  - `proximity_staffing` (inputs: `msl`, `employees`; params: `radius_miles`
    default 50, `nearest_n` default 3, `flex_type`) → store layer, employee
    layer, coverage table.
  - `narrative_facts` — consumes PRIOR step output keys (not dataset
    aliases); must be the LAST section (FinanceReporter pattern).
- Each transformer: declare `params_schema` for exactly the filters its
  dataset supports (per-section filter rule, proposal U1).
- All input cleaning via `normalize.py` (TASK-2693) — no inline parsing.
- Haversine with numpy (no new dependency).
- Unit tests per spec §4: `test_payroll_hero_totals`,
  `test_payroll_pct_denominator` (regression pin), `test_month_series_transformers`,
  `test_pay_code_sections`, `test_per_section_filters`,
  `test_rep_utilization_formula`, `test_proximity_staffing`,
  `test_transformers_registered`.

**NOT in scope**: the agent class (TASK-2696), recipe descriptor
(TASK-2697), any I/O or QuerySource access (transformers are pure).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `agents/flex_dashboard/transformers.py` | CREATE | registered pure transformers |
| `packages/ai-parrot/tests/unit/bots/test_flex_dashboard_transformers.py` | CREATE | unit tests over `flex_frames` fixture |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.outputs.a2ui.recipes.transformers import (
    infographic_transformer,   # verified: recipes/transformers.py:164
    transformer_registry,      # verified: used in tests/unit/bots/test_finance_reporter_descriptors.py:8
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/recipes/transformers.py
def infographic_transformer(name=..., ..., params_schema: dict | None = None)  # line 164
# Registers a pure function  (inputs: dict[str, Any], params: dict[str, Any]) -> dict
# by decorator side effect AT IMPORT TIME (line 5). The registry object exposes
# .register(func, ..., params_schema=...) (line 74) and .get(name) (used by
# publish_recipe at bots/mixins/infographic_authoring.py:341).
```

### Reference transformers (pattern to copy)
- `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/library.py` — the
  FEAT-420 finance transformers: note how each hard-codes
  `df = inputs["snapshots"]` (alias 1:1 rule) and declares `requires_columns`.
- `examples/agents/a2ui/deterministic_refresh_dashboard.py` — transformers
  with declared filter params (`{window}` / `{plan}` placeholders).

### Does NOT Exist
- ~~flex transformers in `parrot/outputs/a2ui/recipes/library.py`~~ — that
  module holds budget-variance (FEAT-420) transformers ONLY; do not add
  flex code there, and do not import flex names from it.
- ~~a `category` column in raw `rep_utilization`~~ — raw is `catagory`;
  canonicalize via `normalize.canonicalize_columns` first.
- ~~`haversine` PyPI package as a dependency~~ — implement with numpy
  (spec §7 External Dependencies: no new packages).

---

## Implementation Notes

### Key Constraints
- Transformers are PURE: no network, no DatasetManager access, no logging
  requirements — inputs dict in, plain dict out (JSON-safe values only).
- Determinism: stable sort orders (sort by month key / store name) so replay
  is byte-identical.
- `narrative_facts` inputs are the OTHER transformers' output keys — mirror
  `agents/finance_reporter.py:216-222` ("Prior-step output_keys, NOT dataset
  aliases").
- Filter params: when a param is absent/None the transformer returns the
  unfiltered aggregate; params only narrow rows of that transformer's own
  dataset(s).

### References in Codebase
- `agents/flex_dashboard/normalize.py` (TASK-2693) — all cleaning.
- `sdd/specs/flex-agent-infographic-a2ui.spec.md` §2, §4, §7.

---

## Acceptance Criteria

- [ ] All transformers listed in Scope are registered and resolvable via
      `transformer_registry.get(<name>)`.
- [ ] `payroll_pct` uses Revenue alone as denominator (dedicated regression test).
- [ ] Per-section filter rule enforced: a `flex_type` param never reaches or
      alters finance-only transformers.
- [ ] `proximity_staffing` returns two layers + coverage table; radius/nearest_n
      are params with defaults (50, 3).
- [ ] `narrative_facts` consumes prior-step outputs and is documented as last.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/bots/test_flex_dashboard_transformers.py -v`
- [ ] `ruff check agents/flex_dashboard/` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/bots/test_flex_dashboard_transformers.py
# Load agents/flex_dashboard/transformers.py by file path (importlib.util) —
# copy _load_finance_reporter() from test_finance_reporter_descriptors.py.
from parrot.outputs.a2ui.recipes.transformers import transformer_registry

def test_transformers_registered(loaded_flex_transformers):
    for name in ["payroll_hero", "worked_hours_by_month", ..., "narrative_facts"]:
        assert transformer_registry.get(name)

def test_payroll_pct_denominator(flex_frames):
    out = payroll_hero({"hours": ..., "finance": ...}, {})
    assert out["payroll_pct"] == pytest.approx(payroll_total / revenue_total)
    # and NOT payroll / (revenue + pc_revenue)
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2693 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/flex-agent-infographic-a2ui.json` → `"in-progress"`
5. **Implement** per scope
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note**

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
