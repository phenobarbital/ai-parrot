# TASK-3773: DSL executor framework + select/rename/filter/sort/limit/derive

**Feature**: FEAT-598 — A2UI Linked Surfaces
**Spec**: `sdd/specs/a2ui-linked-surfaces.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3769
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (DSL executor, pandas). A linked surface's `transform.ops` is a closed, declarative
list of ten operations (spec §2 `TransformOp`, §7 "DSL v1 semantics"). ai-parrot ships the **Python
reference executor** plus golden JSON fixtures that every renderer executor (the bundled UI's `dsl.ts`,
TASK-3793; `navigator-frontend-next`) must also pass (G1, AC7). This task lays down the executor
framework (`apply_transform`, `TransformError`, op dispatch, records↔frame conversion) and the six
row-local operations; TASK-3774 adds the four relational ones (`group_by`, `pivot`, `join`, `union`)
to the same file.

---

## Scope

- Create `linked/dsl.py` with `TransformError`, `apply_transform(frame, spec, *, frames)`, a per-op
  dispatch table, and the ops `select`, `rename`, `filter`, `sort`, `limit`, `derive`.
- Provide the two conversion helpers every fixture test uses: `frame_from_records(rows)` and
  `frame_to_records(frame)` (records orient, ISO-8601 dates, `NaN`/`NaT` → `None`).
- A `ref` spec returns the input frame unchanged (ref transforms are renderer-side TypeScript).
- Create the ten core-op fixtures under `linked/contract/fixtures/dsl/` (list below) — including the
  mandatory null, timezone-aware datetime, dtype-preservation, ordering-stability and empty cases.
- Create `test_dsl_golden.py`, parametrised over **every** `*.json` in the dsl fixture directory (so
  TASK-3774's fixtures are picked up without editing this file), and `test_dsl_core.py` (error paths).

**NOT in scope**: `group_by`, `pivot`, `join`, `union` (they raise `TransformError("… not implemented")`
from the dispatch table until TASK-3774 lands — see blueprint); `asyncio.to_thread` wrapping (TASK-3780 does
that at the call site); TypeScript executor (TASK-3793); `ref` loading (TASK-3794); the op models themselves
(TASK-3769 owns `linked/models.py`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/dsl.py` | CREATE | executor framework + 6 core ops |
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/dsl/select_basic.json` | CREATE | select keeps + orders columns |
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/dsl/rename_basic.json` | CREATE | rename mapping, untouched columns keep order |
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/dsl/filter_nulls.json` | CREATE | null never matches (eq/ne/gt/in/contains) |
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/dsl/filter_ops.json` | CREATE | every filter op on non-null data, chained |
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/dsl/sort_stable_nulls_last.json` | CREATE | stable multi-key sort, nulls last both directions |
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/dsl/limit_basic.json` | CREATE | limit n (incl. n > len) |
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/dsl/derive_arith_div_zero.json` | CREATE | nested + - * / tree, `/` by zero → null |
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/dsl/dtype_preservation.json` | CREATE | ints stay ints, floats stay floats, bools stay bools through select/filter/sort |
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/dsl/tz_datetime_roundtrip.json` | CREATE | tz-aware ISO datetimes survive filter/sort unchanged (offset preserved) |
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/dsl/empty_input.json` | CREATE | empty rows through a full core-op chain → `[]` |
| `packages/ai-parrot/tests/outputs/a2ui/linked/test_dsl_golden.py` | CREATE | parametrised golden runner over the whole dsl fixture dir |
| `packages/ai-parrot/tests/outputs/a2ui/linked/test_dsl_core.py` | CREATE | error paths, ref skip, non-mutation |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import pandas as pd                                    # existing core dependency (spec §7 External Dependencies)
# net-new in TASK-3769 — field names fixed by spec §2 Data Models:
from parrot.outputs.a2ui.linked.models import TransformSpec   # ops: list[TransformOp] | None; ref: TransformRef | None
from parrot.outputs.a2ui.linked.models import (               # the ten op models, discriminator field "op"
    Select, Rename, Filter, GroupBy, Sort, Limit, Derive, Pivot, Join, Union,
)
import parrot.outputs.a2ui.linked                      # tests: Path(parrot.outputs.a2ui.linked.__file__).parent / "contract"
```

### Existing Signatures to Use
```python
# Op model fields come from TASK-3769 (spec §2 + §7). Read linked/models.py after TASK-3769 lands and use its
# exact attribute names. Expected shape (spec §7 — the wire keys):
#   Select(op="select", columns: list[str])
#   Rename(op="rename", mapping: dict[str, str])
#   Filter(op="filter", column: str, op_: "eq|ne|gt|ge|lt|le|in|contains", value: Any)
#       NOTE: the wire key for the comparison is `op` on the JSON side, which collides with the
#       discriminator — TASK-3769 decides the Python attribute name/alias; USE WHAT TASK-3769 DEFINED.
#   Sort(op="sort", by: list[{column, direction: "asc"|"desc"}])
#   Limit(op="limit", n: int)
#   Derive(op="derive", name: str, expr: <binary tree of + - * / over column names and numeric constants>)
```

### Does NOT Exist
- ~~`parrot.outputs.a2ui.linked.dsl`~~ — net-new (this task).
- ~~`apply_transform(..., frames=None)` default~~ — `frames` is keyword-only and required by the skeleton.
- ~~Any `eval`/`query()`/`DataFrame.eval` string path for `derive`~~ — forbidden: `expr` is a JSON tree,
  walked explicitly (no code on the wire, G7).
- ~~A Python executor for `ref` transforms~~ — `ref` is renderer-side only (spec M2).
- ~~`TransformError` in `catalog/`~~ — lives in `linked/dsl.py` only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/linked/dsl.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/dsl/select_basic.json", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/dsl/rename_basic.json", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/dsl/filter_nulls.json", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/dsl/filter_ops.json", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/dsl/sort_stable_nulls_last.json", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/dsl/limit_basic.json", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/dsl/derive_arith_div_zero.json", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/dsl/dtype_preservation.json", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/dsl/tz_datetime_roundtrip.json", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/dsl/empty_input.json", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/outputs/a2ui/linked/test_dsl_golden.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/outputs/a2ui/linked/test_dsl_core.py", "action": "CREATE"}
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

This task implements the first set (select, rename, filter, sort, limit, derive). Copy the rules above
into the module docstring of `dsl.py` so both halves (TASK-3773/TASK-3774) cite one source.

### Fixture JSON shape (spec §4 "Test Data")
`{"input": [...rows], "frames": {"<sibling>": [...rows]}?, "ops": [...wire ops], "expected": [...rows]}`
— plus an optional `"description"` string (intent, human-readable; ignored by the runner) and an
optional `"error": {"op_index": N}` instead of `expected` for fixtures that must raise.
Complete example (`select_basic.json`):
```json
{
  "description": "select keeps only the listed columns, in the listed order",
  "input": [{"day": "2026-09-01", "visits": 3, "program": "epson"},
            {"day": "2026-09-02", "visits": 5, "program": "hisense"}],
  "ops": [{"op": "select", "columns": ["visits", "day"]}],
  "expected": [{"visits": 3, "day": "2026-09-01"}, {"visits": 5, "day": "2026-09-02"}]
}
```
Fixture intents (each file MUST have ≥ 3 input rows except `empty_input`):
- `rename_basic` — `{"visits": "total"}`; unmapped columns keep position.
- `filter_nulls` — a column with `null`s; four ops chained on separate fixtures-in-one? NO: one op per
  fixture is simpler — use `ne` on a column containing null and assert the null row is dropped
  (null never matches, even for `ne`).
- `filter_ops` — chain `ge`, `lt`, `in`, `contains` (substring, case-sensitive) on non-null data.
- `sort_stable_nulls_last` — two-key sort (`program asc`, `visits desc`) with ties and nulls; ties keep
  input order; nulls last in BOTH directions.
- `limit_basic` — `n=2`; plus the rule `n` ≥ len returns all rows (put that in `test_dsl_core.py`).
- `derive_arith_div_zero` — `expr` = `{"op": "/", "left": {"op": "+", "left": {"column": "a"}, "right": {"const": 1}}, "right": {"column": "b"}}`
  with a `b = 0` row → `null`. (Expr node shape is whatever TASK-3769's `Derive` model defines — the
  fixture MUST use TASK-3769's wire shape; the example above is the intended one.)
- `dtype_preservation` — ints stay JSON integers (`3`, not `3.0`) after a filter that removes rows.
- `tz_datetime_roundtrip` — values like `"2026-09-01T10:00:00-05:00"`; after `sort`, expected rows
  carry the identical strings (offset preserved; never converted to UTC).
- `empty_input` — `input: []` through select+filter+sort+limit → `expected: []`.

### Key Constraints
- Pure: no I/O, never mutate `frame` or any frame in `frames` (copy before assigning).
- `TransformError(source_key, op_index, message)`; `apply_transform` itself has no `source_key`
  argument (skeleton is fixed) — raise with `source_key=None` and let the caller (TASK-3780) re-raise /
  annotate it with the key. Keep `op_index` = 0-based index in `spec.ops`.
- Missing column in any op → `TransformError`; `derive` over a non-numeric column → `TransformError`.
- No `print`; module logger `logging.getLogger(__name__)` for debug only.

### References in Codebase
- Spec §3 M2 skeleton (signature fixed), §7 semantics, §4 test table rows `test_dsl_golden`,
  `test_dsl_derive_rejects_non_arith`, `test_dsl_ref_is_skipped_in_python`.

---

## Implementation Blueprint

### Steps (in order)
1. Read `linked/models.py` (from TASK-3769) and note the exact attribute names of the ten op models and the
   `Derive.expr` node shape — *why*: the dispatch reads those attributes; never re-guess them.
2. Write `dsl.py` from the blocks below — *why*: the dispatch table is the seam TASK-3774 extends without
   touching the framework.
3. Implement the six core op functions (FILL IN markers) — *why*: each is one pandas idiom; semantics are
   §7, the fixtures pin them.
4. Write the ten fixtures by hand from the intents above, computing `expected` by reasoning, NOT by
   running your implementation and pasting its output — *why*: fixtures are the cross-language contract;
   generated goldens would bake in Python quirks.
5. Write the two test files; run them — *why*: AC7.

### `packages/ai-parrot/src/parrot/outputs/a2ui/linked/dsl.py` (CREATE) — block 1/2: framework
```python
"""Transform DSL v1 — Python reference executor (FEAT-598, spec §3 M2, §7).

<paste the two §7 "DSL v1 semantics" bullets here verbatim>

Pure: no I/O; inputs are never mutated. ``ref`` transforms are renderer-side TypeScript and are
skipped here (the caller records ``transform_skipped: ref``).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

from parrot.outputs.a2ui.linked.models import TransformSpec

if TYPE_CHECKING:
    import pandas as pd

logger = logging.getLogger(__name__)

__all__ = ["TransformError", "apply_transform", "frame_from_records", "frame_to_records"]


class TransformError(Exception):
    """A DSL op failed: missing column, derive type mismatch, absent join key, …

    Attributes:
        source_key: Linked-source key (dataModel root key) — ``None`` when raised inside
            :func:`apply_transform`; the executor (TASK-3780) fills it in.
        op_index: 0-based index of the failing op in ``TransformSpec.ops``.
    """

    def __init__(self, source_key: str | None, op_index: int, message: str) -> None:
        super().__init__(message)
        self.source_key = source_key
        self.op_index = op_index
        self.message = message


def frame_from_records(rows: list[dict[str, Any]]) -> "pd.DataFrame":
    """Build a frame from ``orient="records"`` rows (fixture/renderer shape)."""
    import pandas as pd

    # FILL IN: keep int columns int (a column with a null must not silently become float in the
    #   OUTPUT — see frame_to_records) and keep ISO datetime strings as strings unless an op needs a
    #   comparison; bounded by fixtures dtype_preservation + tz_datetime_roundtrip (offset preserved).
    return pd.DataFrame.from_records(rows)


def frame_to_records(frame: "pd.DataFrame") -> list[dict[str, Any]]:
    """Serialise to ``orient="records"``: ISO-8601 dates, ``NaN``/``NaT`` → ``None``, ints stay ints."""
    # FILL IN: use frame.to_json(orient="records", date_format="iso") + json.loads, or an explicit walk;
    #   whichever you pick must make every fixture byte-compare after json round-trip (AC7).
    return json.loads(frame.to_json(orient="records", date_format="iso"))


_OpFn = Callable[["pd.DataFrame", Any, Mapping[str, "pd.DataFrame"], int], "pd.DataFrame"]
_DISPATCH: dict[str, _OpFn] = {}


def _register(op_name: str) -> Callable[[_OpFn], _OpFn]:
    def deco(fn: _OpFn) -> _OpFn:
        _DISPATCH[op_name] = fn
        return fn

    return deco


def _require_columns(frame: "pd.DataFrame", columns: list[str], op_index: int, op_name: str) -> None:
    missing = [c for c in columns if c not in frame.columns]
    if missing:
        raise TransformError(None, op_index, f"{op_name}: unknown column(s) {missing}; have {list(frame.columns)}")


def apply_transform(
    frame: "pd.DataFrame", spec: TransformSpec | None, *, frames: Mapping[str, "pd.DataFrame"]
) -> "pd.DataFrame":
    """Apply ``spec.ops`` in order and return a NEW frame.

    Args:
        frame: The source's own fetched frame.
        spec: The transform; ``None`` or an empty ``ops`` list returns a copy of ``frame``.
        frames: Sibling source key → ALREADY-executed frame (``join.with`` / ``union.sources``).

    Returns:
        The transformed frame. A ``ref`` spec returns ``frame`` unchanged (renderer-side only).

    Raises:
        TransformError: On any op failure (``source_key`` is ``None`` here).
    """
    if spec is None or spec.ref is not None:
        return frame
    out = frame.copy()
    for index, op in enumerate(spec.ops or []):
        fn = _DISPATCH.get(op.op)
        if fn is None:
            raise TransformError(None, index, f"op {op.op!r} is not implemented")
        out = fn(out, op, frames, index)
    return out
```
**Why this shape**: the skeleton (spec M2) fixes `apply_transform`'s signature and `TransformError`'s
payload; the `_register` table lets TASK-3774 add four ops with pure additions (no edit to
`apply_transform`), so the two tasks never fight over the same lines. `pandas` is imported lazily so
`import parrot.outputs.a2ui.linked.dsl` stays cheap.

### `…/linked/dsl.py` (CREATE) — block 2/2: the six core ops (append below block 1)
```python
@_register("select")
def _op_select(frame, op, frames, index):
    _require_columns(frame, list(op.columns), index, "select")
    return frame[list(op.columns)].copy()


@_register("rename")
def _op_rename(frame, op, frames, index):
    _require_columns(frame, list(op.mapping), index, "rename")
    return frame.rename(columns=dict(op.mapping))


@_register("filter")
def _op_filter(frame, op, frames, index):
    # FILL IN: build a boolean mask for eq|ne|gt|ge|lt|le|in|contains; rows whose value is null NEVER
    #   match (also for ne) — combine with `frame[col].notna()`; `in` takes a list value; `contains`
    #   is substring on str values; bounded by §7 + fixtures filter_nulls / filter_ops.
    raise NotImplementedError


@_register("sort")
def _op_sort(frame, op, frames, index):
    # FILL IN: stable multi-key sort (kind="mergesort" per key applied last-key-first, or
    #   sort_values(..., kind="stable")) with nulls LAST for both directions (na_position="last");
    #   bounded by fixture sort_stable_nulls_last.
    raise NotImplementedError


@_register("limit")
def _op_limit(frame, op, frames, index):
    return frame.head(int(op.n)).copy()


@_register("derive")
def _op_derive(frame, op, frames, index):
    # FILL IN: walk op.expr recursively (column ref → numeric Series, const → number, + - * / node);
    #   non-numeric column → TransformError(None, index, ...); x / 0 → None (null), never inf;
    #   bounded by §7 "arith only" + fixture derive_arith_div_zero + test_dsl_derive_rejects_non_arith.
    raise NotImplementedError
```
**Why**: one function per op keeps each ≤ ~15 lines and maps 1:1 to the TS port (TASK-3793). Do not add
ops outside the closed set (G7).

### `packages/ai-parrot/tests/outputs/a2ui/linked/test_dsl_golden.py` (CREATE)
```python
"""Golden DSL fixtures — the cross-executor contract (FEAT-598 AC7)."""

import json
from pathlib import Path

import pytest

import parrot.outputs.a2ui.linked
from parrot.outputs.a2ui.linked.dsl import TransformError, apply_transform, frame_from_records, frame_to_records
from parrot.outputs.a2ui.linked.models import TransformSpec

DSL_DIR = Path(parrot.outputs.a2ui.linked.__file__).parent / "contract" / "fixtures" / "dsl"
FIXTURES = sorted(DSL_DIR.glob("*.json"))


@pytest.mark.parametrize("path", FIXTURES, ids=[p.stem for p in FIXTURES])
def test_dsl_golden(path: Path) -> None:
    case = json.loads(path.read_text())
    spec = TransformSpec.model_validate({"ops": case["ops"]})
    frames = {k: frame_from_records(v) for k, v in (case.get("frames") or {}).items()}
    # FILL IN: when case has "error": assert TransformError with that op_index; else assert
    #   frame_to_records(apply_transform(...)) == case["expected"] (exact, order-sensitive).
    raise NotImplementedError


def test_fixture_dir_not_empty() -> None:
    assert len(FIXTURES) >= 10
```

### `packages/ai-parrot/tests/outputs/a2ui/linked/test_dsl_core.py` (CREATE)
```python
"""Core DSL error paths and invariants (FEAT-598 M2)."""

import pytest

from parrot.outputs.a2ui.linked.dsl import TransformError, apply_transform, frame_from_records
from parrot.outputs.a2ui.linked.models import TransformSpec


def test_dsl_ref_is_skipped_in_python() -> None:
    # FILL IN: TransformSpec with ref=TransformRef(name="group_by_day@1.0.0", integrity="sha384-x")
    #   → apply_transform returns the SAME frame object.
    raise NotImplementedError


def test_dsl_derive_rejects_non_arith() -> None:
    # FILL IN: derive over a string column → TransformError with op_index 0.
    raise NotImplementedError


def test_select_unknown_column_raises() -> None: ...          # FILL IN: TransformError, op_index set
def test_apply_transform_does_not_mutate_input() -> None: ... # FILL IN: input frame equal before/after
def test_limit_larger_than_frame_returns_all() -> None: ...  # FILL IN
```

### FILL IN checklist
- [ ] `dsl.py::frame_from_records` / `frame_to_records` — dtype + tz round-trip; bounded by fixtures dtype_preservation, tz_datetime_roundtrip
- [ ] `dsl.py::_op_filter` — null never matches; bounded by §7 + filter_* fixtures
- [ ] `dsl.py::_op_sort` — stable, nulls last; bounded by sort_stable_nulls_last
- [ ] `dsl.py::_op_derive` — arith tree walk, div-by-zero → null, non-numeric → TransformError
- [ ] ten fixture files — hand-computed `expected`
- [ ] test bodies in both test files

---

## Acceptance Criteria

- [ ] `apply_transform` signature exactly `(frame, spec, *, frames)`; `TransformError(source_key, op_index, message)`
- [ ] select/rename/filter/sort/limit/derive pass every core fixture; `ref` spec returns frame unchanged
- [ ] The golden runner is parametrised over the whole fixture dir (no per-file list)
- [ ] Inputs never mutated; no `eval`/`DataFrame.eval`/`query` string paths
- [ ] `ruff check packages/ai-parrot/src/parrot/outputs/a2ui/linked/dsl.py` clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/outputs/a2ui/linked/test_dsl_golden.py -q`
- `pytest packages/ai-parrot/tests/outputs/a2ui/linked/test_dsl_core.py -q`

---

## Test Specification

See the two test blocks above; add one parametrised test per filter operator if the golden coverage
leaves any of `eq|ne|gt|ge|lt|le|in|contains` untested.

---

## Agent Instructions

1. Read the spec (§3 M2, §7) and `linked/models.py` from TASK-3769.
2. Verify TASK-3769 is done (models importable).
3. Implement from the blueprint; fill every `# FILL IN:`; never change `apply_transform`'s signature.
4. Run the Validation Commands (in a worktree prefix `PYTHONPATH=packages/ai-parrot/src`).
5. Commit only the files in the table; update the per-spec index; fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
