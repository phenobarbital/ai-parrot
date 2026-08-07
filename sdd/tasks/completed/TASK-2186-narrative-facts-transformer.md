# TASK-2186: `narrative_facts` transformer (generic shape)

**Feature**: FEAT-420 — FinanceReporter Tier-2 + Narrative Skill
**Spec**: `sdd/specs/finance-reporter-tier2-narrative.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 1** of the spec. The narrative layer is split along the
determinism boundary: this task builds the *deterministic* half — a registered
transformer that derives every **judgement** the prose needs as structured data,
so an LLM later renders words over facts it cannot invent.

FEAT-324 Module 3 ported the *math* of `sdd/artifacts/executive_summary.py` into
`library.py` but explicitly excluded sentence generation (`library.py:198-200`:
"WITHOUT any narrative sentence generation, which is a renderer/layout concern").
This task ports the **branching decisions** of `headline_text`, `division_read`,
`trend_clause` and the recommendation urgency — the if/elif logic, not the English.

Per the resolved open question, the transformer takes the **generic** shape: its
inputs are the *outputs of prior transform steps*, not raw DataFrames. This is
already supported — `_run_gate_or_raise` excludes prior-step aliases from column
gating (`runner.py:432-435,440`) and `_run_transforms_or_raise` feeds
`data_model[alias]` for them (`runner.py:460-461`).

---

## Scope

- Implement `narrative_facts(inputs, params) -> dict` in
  `parrot/outputs/a2ui/recipes/library.py`, registered via
  `@infographic_transformer("narrative_facts", requires_columns={}, ...)`.
- Inputs are prior-step `output_key`s: `variance_analysis`, `top_movers`,
  `division_breakdown`. Declare `requires_columns={}` — these are dicts, not
  frames, so column gating does not and must not apply.
- Emit the contract in §2 Data Models of the spec: `headline`, `top_driver`,
  `division_reads`, `watch`, `bright`, `n_snapshots`.
- Port the branching of `executive_summary.py`: `headline_text:159-180`
  (direction/state flags + the three-way sign combination),
  `division_read:183-201` (the four read kinds), `trend_clause:258-269`
  (day-over-day preferred, else since-first, else "new this period"), and the
  recommendation urgency at `369-382`.
- Preserve the `-5000` materiality threshold and the max-2 cap
  (`executive_summary.py:142`).
- Round money metrics to 2dp, matching the module convention (`library.py:18-20`).
- Guard division-by-zero exactly as the reference does (`library.py:98`).
- Write unit tests in the existing `test_library.py`.

**NOT in scope**:
- Any English sentence, phrase, or template string. This transformer emits
  *flags and names only*. Prose is TASK-2191 (skill) + TASK-2192 (mixin).
- The figure guard (TASK-2190).
- Consuming raw DataFrames or re-deriving totals — reuse the existing
  transformers' outputs; do NOT recompute `variance_analysis` math here.
- Touching any of the seven existing transformers.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/library.py` | MODIFY | Add `narrative_facts` after `top_movers`; keep the module docstring's transformer count accurate (currently says "all 7") |
| `packages/ai-parrot/tests/outputs/a2ui/recipes/test_library.py` | MODIFY | Add unit tests per the Test Specification below |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.

### Verified Imports

```python
# In library.py these are ALREADY imported at the top — do not re-add:
from parrot.outputs.a2ui.recipes.transformers import infographic_transformer  # library.py:35
import pandas as pd                                                          # library.py:33
import json                                                                  # library.py:30
from typing import Any                                                       # library.py:31
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/outputs/a2ui/recipes/library.py
_MONEY_COLUMNS = ["rev_actual", "rev_budget", "ebitda_actual", "ebitda_budget"]  # line 39
def _day_totals_for(df: pd.DataFrame) -> dict[str, Any]: ...                     # line 82
#   returns: rev_actual, rev_budget, rev_variance, rev_variance_pct,
#            ebitda_actual, ebitda_budget, ebitda_variance   (all 2dp-rounded)
#   division guard: `round(rev_variance / rev_b * 100, 2) if rev_b else 0.0`     # line 98

# The decorator signature to use (transformers.py:164):
@infographic_transformer(
    "narrative_facts",
    requires_columns={},          # inputs are prior-step dicts, NOT frames
    description="...",
    params_schema={...},
)
def narrative_facts(inputs: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]: ...

# UPSTREAM CONTRACTS this task consumes (all verified in library.py):
#
# variance_analysis output (lines 239-250):
{
  "first_snapshot": str, "last_snapshot": str,
  "first_totals": {...}, "last_totals": {...},   # _day_totals_for shape
  "rev_pct_change": float,        # >0 narrowing, <0 widening, 0 flat
  "ebitda_dollar_change": float,  # >0 improved, <0 worsened, 0 held_steady
  "rev_direction": "narrowing" | "widening" | "flat",
  "ebitda_direction": "improved" | "worsened" | "held_steady",
  "rev_state": "behind" | "ahead",
  "n_snapshots": int,
}
# NOTE: variance_analysis ALREADY computes rev_direction/ebitda_direction/rev_state
#       (lines 229-237). Reuse them — do NOT recompute from the raw deltas.
#
# top_movers output (line 315):
{"worst": [{"division": str, "project": str,
            "ebitda_variance": float, "trend": float | None}, ...],
 "best":  [ ... same shape ... ]}
# trend is None when the project is absent at the first snapshot (lines 302-306).
#
# division_breakdown output (line 188): {division_name: {
#   "rev_actual","rev_budget","ebitda_actual","ebitda_budget",  # 2dp
#   "rev_variance","ebitda_variance",                           # 2dp
#   "projects": [{"name": str, "rev_variance": float, "ebitda_variance": float}]}}
```

```python
# REFERENCE LOGIC TO PORT — sdd/artifacts/executive_summary.py
# This file is a standalone reference artifact, NOT an importable module.
# Port the branching; never import it.

# headline_text:159-180 — the three-way combination to encode as booleans:
#   rev_pct_change > 0 and ebitda_dollar_change > 0  -> both_improving
#   rev_pct_change < 0 and ebitda_dollar_change < 0  -> both_worsening
#   otherwise                                        -> diverging

# division_read:183-201 — the FOUR read kinds, in the reference's decision order:
#   not read_worst and ebitda_variance >= 0 -> "on_track"
#   not read_worst and ebitda_variance <  0 -> "spread"
#   read_worst     and ebitda_variance >= 0 -> "offset_by"  (name the best positive project)
#   read_worst     and ebitda_variance <  0 -> "concentrated"
# where read_worst = [p for p in sorted(projects, key=ebitda_variance)
#                     if p["ebitda_variance"] < -5000][:2]        # line 142

# trend_clause:258-269 — preference order for a project's trend label:
#   day-over-day when available -> else since-first -> else "new this period"
# NOTE: top_movers exposes ONE `trend` field (first->latest), not both. Emit the
#   label from that single field; do NOT invent a day-over-day value that the
#   upstream transformer does not provide.

# recommendation urgency:369-382 — from the top driver's trend sign:
#   trend < 0    -> "immediate"
#   trend > 0    -> "confirm_trend"
#   trend == 0/None -> "check_timing"
#   no negative project at all -> top_driver is None, urgency "none"
```

### Does NOT Exist

- ~~`transformer_registry.get("narrative_facts")`~~ — this task creates it.
- ~~`transformer_registry.get("days")`~~ — no `days` transformer exists and this
  task does NOT create one (the spec migrates to A2UI layouts instead).
- ~~`import sdd.artifacts.executive_summary`~~ — `sdd/artifacts/*.py` are NOT
  package modules. Port the logic; never import.
- ~~`executive_summary.headline_text` / `division_read` / `trend_clause`
  available anywhere in `parrot/`~~ — unported; that is this task's job.
- ~~a `trend_day_over_day` field on `top_movers` entries~~ — only `trend` exists
  (`library.py:302-306`).
- ~~`variance_analysis` returning `divisions`~~ — it does not; division data
  comes from `division_breakdown`.
- ~~`_day_totals_for` accepting a dict~~ — it takes a `pd.DataFrame` (line 82).
  This task's inputs are dicts; do not pass them to it.

---

## Implementation Notes

### Pattern to Follow

```python
# Follow the exact registration + docstring style of the existing transformers,
# e.g. top_movers (library.py:253-315):
@infographic_transformer(
    "narrative_facts",
    requires_columns={},
    description=(
        "Structured narrative judgements derived from prior steps' outputs "
        "(port of the BRANCHING in executive_summary.headline_text / "
        "division_read / trend_clause, WITHOUT any English). Inputs are the "
        "output_keys of variance_analysis, top_movers and division_breakdown."
    ),
    params_schema={
        "materiality_threshold": {"type": "number", "default": -5000},
        "max_named_per_division": {"type": "integer", "default": 2},
    },
)
def narrative_facts(inputs: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    """See the ``@infographic_transformer`` description above."""
    variance = inputs["variance_analysis"]
    movers = inputs["top_movers"]
    divisions = inputs["division_breakdown"]
    ...
```

### Key Constraints

- **Pure function.** No clocks, no I/O, no randomness — same input must give a
  byte-identical dict. This is a hard FEAT-324 requirement (G3/G7).
- **Sync, not async** — transformers are called synchronously by
  `_run_transforms_or_raise` (`runner.py:448`, note it is NOT a coroutine).
- **No English.** If a string in your output would read as a sentence, it belongs
  in the skill (TASK-2191), not here. Emit enum-ish flags and entity names only.
- Input alias names are the recipe's `output_key`s. Use the three names above and
  fail with a clear `KeyError`-derived message if an expected input is absent
  (the runner wraps any exception into `stage="transform"`, `runner.py:478-486`).
- Money values 2dp-rounded, consistent with siblings (`library.py:18-20`).
- Do NOT bump the module's `__all__` — registration is by import side effect and
  `__all__` is deliberately empty (`library.py:37`).

### References in Codebase

- `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/library.py:253-315` —
  `top_movers`, the closest structural analogue (dict-returning, param-driven)
- `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/library.py:191-250` —
  `variance_analysis`, whose output this consumes
- `sdd/artifacts/executive_summary.py:87-152` — `analyze()`, the reference that
  assembled all of these judgements in one place
- `packages/ai-parrot/tests/outputs/a2ui/recipes/test_library.py` — existing
  test style for these transformers

---

## Acceptance Criteria

- [ ] `narrative_facts` is registered: `transformer_registry.get("narrative_facts")` resolves
- [ ] Registered with `requires_columns={}` (verified via `transformer_registry.manifest("narrative_facts").requires_columns == {}`)
- [ ] Output matches the spec §2 contract keys exactly: `headline`, `top_driver`, `division_reads`, `watch`, `bright`, `n_snapshots`
- [ ] All four `division_reads` kinds are reachable and produced per the reference's decision order
- [ ] `offsetter` is populated **only** for `kind == "offset_by"`, `None` otherwise
- [ ] Materiality threshold `-5000` and the max-2 cap are honoured and param-overridable
- [ ] Single-snapshot input yields `flat`/`held_steady` and claims no trend
- [ ] Zero-budget division does not raise
- [ ] Output contains **no** sentence-like strings (assert no value matches `r"\s\w+\s\w+\s\w+\s"` outside of entity names)
- [ ] Function is sync and pure (calling twice on the same input gives equal dicts)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/outputs/a2ui/recipes/test_library.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/outputs/a2ui/recipes/library.py`
- [ ] `mypy` clean on the changed file

---

## Test Specification

```python
# packages/ai-parrot/tests/outputs/a2ui/recipes/test_library.py  (append)
import pytest
from parrot.outputs.a2ui.recipes.transformers import transformer_registry


@pytest.fixture
def upstream_outputs():
    """The three prior-step outputs narrative_facts consumes.

    Shaped to exercise every branch:
      - 'Retail' : net negative with one project < -5000   -> concentrated
      - 'Wholesale': net positive despite a negative project -> offset_by
      - 'Services': net positive, nothing material          -> on_track
      - 'Thin'   : net negative, nothing material           -> spread
    """
    return {
        "variance_analysis": {
            "first_snapshot": "20260701", "last_snapshot": "20260703",
            "first_totals": {...}, "last_totals": {...},
            "rev_pct_change": 1.5, "ebitda_dollar_change": -20000.0,
            "rev_direction": "narrowing", "ebitda_direction": "worsened",
            "rev_state": "behind", "n_snapshots": 3,
        },
        "top_movers": {
            "worst": [{"division": "Retail", "project": "Alpha",
                       "ebitda_variance": -42000.0, "trend": -8000.0}],
            "best": [{"division": "Wholesale", "project": "Zeta",
                      "ebitda_variance": 31000.0, "trend": None}],
        },
        "division_breakdown": { ... },
    }


class TestNarrativeFacts:
    def test_registered_with_no_column_requirements(self):
        """Prior-step dict inputs must not be column-gated."""
        assert transformer_registry.manifest("narrative_facts").requires_columns == {}

    def test_headline_flags_reuse_upstream_directions(self, upstream_outputs):
        """rev_direction/ebitda_direction/rev_state come from variance_analysis."""
        out = transformer_registry.get("narrative_facts")(upstream_outputs, {})
        assert out["headline"]["rev_direction"] == "narrowing"
        assert out["headline"]["ebitda_direction"] == "worsened"
        assert out["headline"]["rev_state"] == "behind"
        assert out["headline"]["diverging"] is True

    def test_division_read_kinds(self, upstream_outputs):
        """All four kinds are produced per the reference decision order."""
        out = transformer_registry.get("narrative_facts")(upstream_outputs, {})
        kinds = {d["division"]: d["kind"] for d in out["division_reads"]}
        assert kinds == {"Retail": "concentrated", "Wholesale": "offset_by",
                         "Services": "on_track", "Thin": "spread"}

    def test_offsetter_only_for_offset_by(self, upstream_outputs):
        out = transformer_registry.get("narrative_facts")(upstream_outputs, {})
        for read in out["division_reads"]:
            if read["kind"] == "offset_by":
                assert read["offsetter"]
            else:
                assert read["offsetter"] is None

    def test_materiality_threshold_and_cap(self, upstream_outputs):
        """Only < -5000 projects are named, max 2."""

    def test_urgency_branches(self, upstream_outputs):
        """trend<0 -> immediate; >0 -> confirm_trend; None/0 -> check_timing."""

    def test_top_driver_none_when_no_negative_project(self):
        """No negative project -> top_driver is None, urgency 'none'."""

    def test_single_snapshot_claims_no_trend(self):
        """n_snapshots == 1 -> flat/held_steady, trend labels are 'new this period'."""

    def test_zero_budget_division_does_not_raise(self):
        """Mirrors the library.py:98 guard."""

    def test_emits_no_prose(self, upstream_outputs):
        """No output value may read as an English sentence."""
        import re
        out = transformer_registry.get("narrative_facts")(upstream_outputs, {})

        def walk(v):
            if isinstance(v, str):
                assert not re.search(r"\s\w+\s\w+\s\w+\s", v), f"prose leaked: {v!r}"
            elif isinstance(v, dict):
                for i in v.values():
                    walk(i)
            elif isinstance(v, list):
                for i in v:
                    walk(i)

        walk(out)

    def test_pure_and_deterministic(self, upstream_outputs):
        fn = transformer_registry.get("narrative_facts")
        assert fn(upstream_outputs, {}) == fn(upstream_outputs, {})
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context (§2 Data Models
   carries the exact output contract; §7 Known Risks carries the gotchas)
2. **Check dependencies** — none; this task can start immediately
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists
   - Confirm the three upstream output contracts still match `library.py:239-250`,
     `315`, `188`
   - If anything has changed, update the contract FIRST, then implement
4. **Update status** in `sdd/tasks/index/finance-reporter-tier2-narrative.json`
   → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2186-narrative-facts-transformer.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Sonnet)
**Date**: 2026-08-07
**Notes**: Implemented `narrative_facts` in `library.py` right after `top_movers`,
registered with `requires_columns={}`. Ported the headline three-way
combination (`both_improving`/`both_worsening`/`diverging`), the four
`division_reads` kinds (`on_track`/`spread`/`concentrated`/`offset_by`) with
the materiality threshold (`-5000`, param-overridable) and max-2 cap, the
top-driver recommendation urgency (`immediate`/`confirm_trend`/`check_timing`),
and `watch`/`bright` lists carrying a `trend_basis` (`since_first` |
`new_this_period` — no day-over-day label invented, since `top_movers` only
exposes one `trend` field). Added `TestNarrativeFacts` (11 tests) to
`test_library.py` covering registration, all four division-read branches,
offsetter-only-for-offset_by, materiality cap, urgency branches, top_driver
None case, single-snapshot pass-through, zero-budget non-raise, no-prose-leak,
and purity/determinism. All 26 tests in `test_library.py` pass; `ruff check`
and `mypy` clean on `library.py`.

**Deviations from spec**: none. `first_label`/`last_label` in `headline` were
mapped to `variance_analysis`'s `first_snapshot`/`last_snapshot` string values
(the spec's data-model sketch names them without defining their source
explicitly; this is the only sensible source given the available inputs).
