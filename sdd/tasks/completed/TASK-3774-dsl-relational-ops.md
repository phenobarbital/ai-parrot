# TASK-3774: DSL group_by / pivot / join / union

**Feature**: FEAT-598 — A2UI Linked Surfaces
**Spec**: `sdd/specs/a2ui-linked-surfaces.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3773
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2, second half. TASK-3773 created `linked/dsl.py` with the executor framework
(`apply_transform`, `TransformError`, the `_register` dispatch table, `frame_from_records` /
`frame_to_records`) and the six row-local ops. This task adds the four relational ops —
`group_by`, `pivot`, `join`, `union` — as pure additions to the dispatch table, plus their golden
fixtures (incl. the mandatory join-collision-prefix and null-never-matches cases, spec M12). `join`
and `union` read **sibling** frames from `apply_transform(..., frames=...)`: the executor (TASK-3780)
executes join/union dependencies first and passes their already-transformed frames.

---

## Scope

- Add `_op_group_by`, `_op_pivot`, `_op_join`, `_op_union` to `linked/dsl.py` via `@_register(...)`.
- Add the seven relational fixtures under `linked/contract/fixtures/dsl/` (they are auto-picked-up by
  TASK-3773's parametrised `test_dsl_golden.py` — do NOT edit that file).
- Create `test_dsl_relational.py` with the named semantics tests from spec §4.

**NOT in scope**: changing `apply_transform`, `TransformError` or the conversion helpers (owned by
TASK-3773 — if one is wrong for your fixtures, stop and report); dependency ordering between sources
(TASK-3780); validating that `join.with` / `union.sources` name sibling keys (TASK-3777 does that at
envelope-validation time — here a missing key raises `TransformError`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/dsl.py` | MODIFY | add 4 relational ops to the dispatch table |
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/dsl/group_by_sum.json` | CREATE | single key, sum |
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/dsl/group_by_all_aggs.json` | CREATE | two keys, sum/avg/count/min/max, nulls in values |
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/dsl/pivot_basic.json` | CREATE | index × columns × values with aggregate |
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/dsl/join_inner.json` | CREATE | inner equality join on one key |
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/dsl/join_left_null_never_matches.json` | CREATE | left join; null keys on both sides never match |
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/dsl/join_prefix_on_collision.json` | CREATE | colliding non-key columns take `<with>_` prefix |
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/dsl/union_matching_columns.json` | CREATE | concat on column intersection, in order |
| `packages/ai-parrot/tests/outputs/a2ui/linked/test_dsl_relational.py` | CREATE | named semantics tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import pandas as pd                                          # existing core dependency
# net-new in TASK-3773 (linked/dsl.py) — reuse, never redefine:
from parrot.outputs.a2ui.linked.dsl import (
    TransformError, apply_transform, frame_from_records, frame_to_records,
)
# private seam inside dsl.py (same module — no import needed): _register, _require_columns, _DISPATCH
# net-new in TASK-3769:
from parrot.outputs.a2ui.linked.models import TransformSpec  # GroupBy, Pivot, Join, Union op models
```

### Existing Signatures to Use
```python
# linked/dsl.py (TASK-3773)
class TransformError(Exception):
    def __init__(self, source_key: str | None, op_index: int, message: str) -> None: ...
def apply_transform(frame, spec, *, frames: Mapping[str, pd.DataFrame]) -> pd.DataFrame: ...
_OpFn = Callable[[pd.DataFrame, Any, Mapping[str, pd.DataFrame], int], pd.DataFrame]
def _register(op_name: str) -> Callable[[_OpFn], _OpFn]: ...
def _require_columns(frame, columns: list[str], op_index: int, op_name: str) -> None: ...
# In the op models (TASK-3769 — read the file, use its exact attribute names). Wire keys per spec §7:
#   GroupBy(op="group_by", by: list[str], aggregate: dict[str, "sum"|"avg"|"count"|"min"|"max"])
#   Pivot(op="pivot", index: str|list[str], columns: str, values: str, aggregate: <agg>)
#   Join(op="join", with_: <sibling key> (wire key "with" — Python keyword, TASK-3769 aliases it),
#        how: "inner"|"left", on: list[{left, right}])
#   Union(op="union", sources: list[<sibling keys>])
```

### Does NOT Exist
- ~~Multi-join in one step, non-equality join predicates, `right`/`outer` joins~~ — v1 is `inner|left`, equality, one join per step (§7).
- ~~Union by position / union filling missing columns with nulls~~ — union is on the **intersection** of column names.
- ~~`pd.merge` default suffixes (`_x`/`_y`) on the wire~~ — collisions take the `<with>_` prefix instead.
- ~~Any change to `apply_transform`'s body~~ — the dispatch table is the extension seam.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/linked/dsl.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/dsl/group_by_sum.json", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/dsl/group_by_all_aggs.json", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/dsl/pivot_basic.json", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/dsl/join_inner.json", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/dsl/join_left_null_never_matches.json", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/dsl/join_prefix_on_collision.json", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/dsl/union_matching_columns.json", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/outputs/a2ui/linked/test_dsl_relational.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

> **Wire-name note (fixed by TASK-3769 `linked/models.py`)**: the union discriminator is `op` (`"op": "filter"`), so the
> Filter comparison field is **`operator`** (`eq|ne|gt|ge|lt|le|in|contains`), NOT `op` as spec §7 prose writes it;
> Join's sibling key is `with` on the wire (`with_` attribute, alias — dump with `by_alias=True`); the derive
> expression is a recursive `{operator, left, right}` tree where a string operand is a column and a number a constant.
> Fixtures, `dsl.py` and `dsl.ts` all use these names.


### DSL v1 semantics (verbatim from spec §7 — binding for every executor; fixtures are the contract)
- `select {columns}` keep+order; `rename {mapping}`; `filter {column, op ∈ eq|ne|gt|ge|lt|le|in|contains, value}` (null never matches); `group_by {by, aggregate: {col: sum|avg|count|min|max}}`; `sort {by: [{column, direction}]}` (stable; nulls last); `limit {n}`; `derive {name, expr}` where `expr` is a binary tree of `+ - * /` over column names and numeric constants only (`/` by zero → null); `pivot {index, columns, values, aggregate}`; `join {with: <sibling key>, how ∈ inner|left, on: [{left, right}]}` — equality only, `null` never matches, colliding column names take `<with>_` prefix, one join per step; `union {sources: [<sibling keys>]}` — concatenation on the intersection of column names, in order.
- Row records are `orient="records"`; dates serialize ISO-8601; numeric dtypes preserved; a Python `TransformError` ↔ a TS thrown `TransformError` with the same `(source_key, op_index)`.

### Decisions this task fixes (write them into the fixtures, so every renderer inherits them)
- **group_by output order**: groups in order of first appearance in the input (`sort=False`), output
  columns = `by` columns then aggregate columns in `aggregate` dict order — *because* renderers
  iterate insertion order and the TS port must match without a sort step.
- **group_by nulls**: aggregates skip nulls (`count` counts non-null values of that column); a null in
  a `by` column forms no group (dropped) — consistent with "null never matches".
- **avg** of ints may be float; `sum`/`min`/`max` of an int column stay ints; `count` is an int.
- **pivot**: one output row per distinct `index` value (first-appearance order); one column per
  distinct `columns` value (first-appearance order), named by the value's string form; missing cells
  → `null`.
- **join column order**: left columns, then right non-key columns in right-frame order; the right
  `on.right` key columns are dropped when named identically to the left key, kept (prefixed if they
  collide) otherwise.
- **union**: the output column list is the intersection **in the column order of the first frame**
  (the source's own frame), then rows of the own frame, then each `sources[i]` frame, in order.
- **union** where `sources` names the source itself is not special-cased — TASK-3777 rejects it.

### Complete fixture example (`join_prefix_on_collision.json`)
```json
{
  "description": "left join; non-key column 'visits' exists on both sides -> right copy becomes targets_visits",
  "input": [{"store": "A", "visits": 3}, {"store": "B", "visits": 5}, {"store": "C", "visits": 1}],
  "frames": {"targets": [{"store": "A", "visits": 10}, {"store": "B", "visits": 4}]},
  "ops": [{"op": "join", "with": "targets", "how": "left", "on": [{"left": "store", "right": "store"}]}],
  "expected": [{"store": "A", "visits": 3, "targets_visits": 10},
               {"store": "B", "visits": 5, "targets_visits": 4},
               {"store": "C", "visits": 1, "targets_visits": null}]
}
```
Other fixture intents:
- `group_by_sum` — by `program`, `{"visits": "sum"}`; first-appearance group order.
- `group_by_all_aggs` — by `[program, day]`, one agg of each kind on columns containing nulls.
- `pivot_basic` — index `day`, columns `program`, values `visits`, aggregate `sum`; one missing cell.
- `join_inner` — unmatched left rows dropped; matched rows keep left order.
- `join_left_null_never_matches` — null key rows on BOTH sides; left null row survives with null right
  columns and does not match the right null row.
- `union_matching_columns` — own frame `{a,b,c}`, sibling `{b,a,d}` → columns `[a, b]`.

### Key Constraints
- Missing sibling key in `frames` → `TransformError(None, op_index, "join: sibling 'x' not executed")`.
- Never mutate inputs (`frames` values included).
- Do not use `pd.merge`'s NaN-matches-NaN behaviour: drop / mask null keys explicitly before merging.

---

## Implementation Blueprint

### Steps (in order)
1. Read `linked/dsl.py` (from TASK-3773) and `linked/models.py` — *why*: reuse `_register` /
   `_require_columns` and the models' exact attribute names (`Join`'s `with` alias).
2. Append the four op functions (block below) at the end of `dsl.py` — *why*: pure additions to the
   dispatch table; no existing line changes, so TASK-3773's behaviour is untouched.
3. Hand-write the seven fixtures (compute `expected` by reasoning) — *why*: cross-language contract.
4. Write `test_dsl_relational.py`; run it plus TASK-3773's golden runner — *why*: the golden runner now
   covers your fixtures too.

### `packages/ai-parrot/src/parrot/outputs/a2ui/linked/dsl.py` (MODIFY)
```python
# occurrences: 0 at task-writing time — the file is created by TASK-3773. Anchor: append at END OF FILE,
# after `_op_derive` (the last core op TASK-3773 registers). Verify with `grep -c '@_register("derive")' dsl.py` == 1.
_AGGS = {"sum": "sum", "avg": "mean", "count": "count", "min": "min", "max": "max"}


def _sibling(frames, key: str, index: int, op_name: str):
    if key not in frames:
        raise TransformError(None, index, f"{op_name}: sibling source {key!r} was not executed")
    return frames[key]


@_register("group_by")
def _op_group_by(frame, op, frames, index):
    by = list(op.by)
    _require_columns(frame, by + list(op.aggregate), index, "group_by")
    # FILL IN: groupby(by, sort=False, dropna=True).agg({col: _AGGS[fn]}) ; reset_index(); keep int
    #   dtypes for sum/min/max of ints and count; output column order = by + aggregate order;
    #   bounded by "Decisions this task fixes" + fixtures group_by_*.
    raise NotImplementedError


@_register("pivot")
def _op_pivot(frame, op, frames, index):
    # FILL IN: pivot_table(index=…, columns=…, values=…, aggfunc=_AGGS[op.aggregate], sort=False);
    #   flatten columns to the string form of each value; first-appearance order; missing → null;
    #   bounded by fixture pivot_basic.
    raise NotImplementedError


@_register("join")
def _op_join(frame, op, frames, index):
    right = _sibling(frames, op.with_, index, "join")  # FILL IN: use TASK-3769's real attribute name for "with"
    left_keys = [pair.left for pair in op.on]
    right_keys = [pair.right for pair in op.on]
    _require_columns(frame, left_keys, index, "join")
    _require_columns(right, right_keys, index, "join")
    # FILL IN: rename colliding right non-key columns to f"{with}_{col}"; exclude null-key rows from
    #   matching on both sides (left join keeps left null-key rows with null right columns);
    #   pd.merge(how=op.how, left_on=…, right_on=…, sort=False); column order per "Decisions";
    #   bounded by §7 + fixtures join_*.
    raise NotImplementedError


@_register("union")
def _op_union(frame, op, frames, index):
    others = [_sibling(frames, key, index, "union") for key in op.sources]
    # FILL IN: columns = [c for c in frame.columns if all(c in o.columns for o in others)];
    #   pd.concat([frame[columns], *(o[columns] for o in others)], ignore_index=True);
    #   bounded by fixture union_matching_columns.
    raise NotImplementedError
```
**Why**: every op is registered, not wired into `apply_transform`, so this is additive. Null-key
handling is explicit because pandas merges `NaN` with `NaN` by default, which violates §7.

### `packages/ai-parrot/tests/outputs/a2ui/linked/test_dsl_relational.py` (CREATE)
```python
"""Relational DSL ops — semantics fixed in spec §7 (FEAT-598 M2)."""

import pytest

from parrot.outputs.a2ui.linked.dsl import TransformError, apply_transform, frame_from_records, frame_to_records
from parrot.outputs.a2ui.linked.models import TransformSpec


def _run(rows, ops, frames=None):
    spec = TransformSpec.model_validate({"ops": ops})
    sib = {k: frame_from_records(v) for k, v in (frames or {}).items()}
    return frame_to_records(apply_transform(frame_from_records(rows), spec, frames=sib))


def test_dsl_join_null_never_matches() -> None: ...           # FILL IN
def test_dsl_join_prefix_on_collision() -> None: ...           # FILL IN
def test_dsl_union_by_matching_columns() -> None: ...          # FILL IN
def test_join_missing_sibling_raises_transform_error() -> None: ...  # FILL IN: op_index asserted
def test_group_by_first_appearance_order() -> None: ...        # FILL IN
def test_relational_ops_do_not_mutate_siblings() -> None: ...  # FILL IN
```

### FILL IN checklist
- [ ] `_op_group_by` — order, null handling, dtype; bounded by "Decisions" + group_by fixtures
- [ ] `_op_pivot` — column naming/order, missing → null
- [ ] `_op_join` — alias for `with`, null keys, prefix, column order
- [ ] `_op_union` — intersection in own-frame order
- [ ] seven fixtures, hand-computed
- [ ] test bodies

---

## Acceptance Criteria

- [ ] The four ops are registered; `apply_transform` unchanged
- [ ] All 17 dsl fixtures (10 from TASK-3773 + 7 here) pass `test_dsl_golden.py`
- [ ] Null keys never match; collisions take `<with>_`; union on intersection in order (AC7)
- [ ] `ruff check packages/ai-parrot/src/parrot/outputs/a2ui/linked/dsl.py` clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/outputs/a2ui/linked/test_dsl_relational.py -q`

> `test_dsl_relational.py` MUST itself parametrise `test_dsl_golden_relational[<fixture>]` over the seven fixtures this task
> adds (same loader as TASK-3773's `test_dsl_golden.py`, which is NOT edited and is re-run as an acceptance criterion,
> not a validation command — it belongs to TASK-3773).

---

## Test Specification

As in the test block above; each named test mirrors a spec §4 row (`test_dsl_join_null_never_matches`,
`test_dsl_join_prefix_on_collision`, `test_dsl_union_by_matching_columns`).

---

## Agent Instructions

1. Read spec §3 M2 and §7; read `linked/dsl.py` and `linked/models.py`.
2. Verify TASK-3773 is done.
3. Implement from the blueprint, filling every `# FILL IN:`; do not edit TASK-3773's functions.
4. Run the Validation Commands (worktree: `PYTHONPATH=packages/ai-parrot/src`).
5. Commit only the listed files; update the index; fill the Completion Note.

---

## Completion Note


- Task: TASK-3774
- Feature: a2ui-linked-surfaces
- Implementation SHA: 9b0c4f57254408dd57392528f4fcb9b6fc686431
- Closed at (UTC): 2026-09-26T00:47:49+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| coder_record_review | NOT recorded - coder_record_review MCP tool rejects every payload including {} (systemic tool outage, confirmed also on coder_record_feedback and coder_record_native_observation) |
| merge_validation_outcome | failed: 2/599 pre-existing failures unrelated to this task's diff (test_agent_a2ui_stream.py brittle source-string assertions, fail identically on clean origin/dev). See issue:181bd0c01bb4. |
| seat_summary | Seat: gpt-5.6-terra - Backend: codex - Model: gpt-5.6-terra - Attempts: 1 - Duration: 108.5s - Tokens: n/a |
