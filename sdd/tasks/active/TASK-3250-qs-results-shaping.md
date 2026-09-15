# TASK-3250: Result shaping — DataFrame → bounded JSON-safe `ExecutionResult`

**Feature**: FEAT-558 — QuerysourceToolkit — tenant-scoped query-slug and MultiQuery tools
**Spec**: `sdd/specs/querysource-toolkit-refactor.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3246
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 (`results.py`), design research S8/S9. `QS.query(output_format="pandas")` returns a DataFrame;
`MultiQS.query()` returns a DataFrame or a `dict[str, DataFrame]` (`multi/__init__.py:522-531`). The LLM must
receive a bounded, JSON-serialisable payload with honest counts (`returned_rows` vs `total_rows`, `truncated`).

---

## Scope

- Implement `results.py`: `json_safe(value)`, `frame_to_result(...)`, `multi_to_result(...)`.
- Unit + contract tests on real pandas frames (datetime, NaT, NaN, numpy scalars, categorical, empty).

**NOT in scope**: calling QS/MultiQS (TASK-3252/3254).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/querysource/results.py` | CREATE | shaping helpers |
| `packages/ai-parrot-tools/tests/querysource/test_results.py` | CREATE | contract tests with real pandas |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import pandas as pd                                   # ai-parrot-tools dependency (used by parrot_tools/qsource.py:12, querytoolkit.py:16)
from parrot_tools.querysource.models import ExecutionResult, MultiQueryResult   # TASK-3246
```

### Existing Signatures to Use
```python
# querysource/queries/qs.py:363  async def query(self, output_format=None) → (result, error); with 'pandas' result is a DataFrame
# querysource/queries/multi/__init__.py:522-531  result is a DataFrame, or dict[str, DataFrame] when several frames remain
# parrot_tools/qsource.py:398-402 (to be deleted) — datetime → isoformat serializer, the behaviour to keep
```

### Does NOT Exist
- ~~`ExecutionResult.row_count`~~ — use `returned_rows` / `total_rows`.
- ~~`df.to_json()` as the output~~ — the tools return `list[dict]` rows inside a Pydantic model; `_post_execute` dumps it.
- ~~pandas `errors='ignore'` datetime coercion~~ (old tool, line 361) — do not coerce types; only serialise.

---

## Implementation Notes

### Key Constraints
- `json_safe`: `datetime/date/time` → `isoformat()`; `Decimal` → `float`; numpy scalars → `.item()`; `NaN`/`NaT`/`None` → `None`; `bytes` → `base64`-less `repr`? → NO: `bytes.decode("utf-8", "replace")`; nested lists/dicts recursively; anything else → `str(value)`.
- `frame_to_result`: `total_rows=len(frame)`, `rows = frame.head(max_rows)`, `truncated = total_rows > max_rows`, `columns=[str(c) for c in frame.columns]`, `status="empty"` when `total_rows == 0`, `duration_ms=int((time.monotonic()-started)*1000)`.
- `multi_to_result`: single frame → `{"result": ExecutionResult}`; dict → one entry per key; status `"empty"` only if every frame is empty.
- Non-DataFrame inputs (list of dicts, dict, None) → convert with `pd.DataFrame(records)`; `None` → empty frame.

---

## Implementation Blueprint

### Steps (in order)
1. Write `results.py` — *why*: one place defines what "bounded, JSON-safe" means for both single and multi results (S8).
2. Complete `json_safe`; write the real-pandas contract tests (S9).

### `packages/ai-parrot-tools/src/parrot_tools/querysource/results.py` (CREATE)
```python
"""Shape QuerySource results into bounded, JSON-safe Pydantic models (spec §3 M5, S8/S9)."""
from __future__ import annotations

import math
import time
from datetime import date, datetime, time as dt_time
from decimal import Decimal
from typing import Any

import pandas as pd

from parrot_tools.querysource.models import ExecutionResult, MultiQueryResult


def json_safe(value: Any) -> Any:
    """Convert pandas/numpy/datetime scalars and containers into json.dumps-able Python values."""
    if value is None:
        return None
    if isinstance(value, (datetime, date, dt_time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(v) for v in value]
    # FILL IN: pd.isna(value) is True for NaT/NA scalars → None; numpy scalars via .item(); bytes.decode('utf-8','replace');
    #          bool/int/str pass through; fallback str(value) — bounded by AC "json.dumps succeeds"
    return value


def _as_frame(result: Any) -> pd.DataFrame:
    """Coerce QS outputs (DataFrame | list[dict] | dict | None) into a DataFrame without changing dtypes."""
    if isinstance(result, pd.DataFrame):
        return result
    if result is None:
        return pd.DataFrame()
    if isinstance(result, dict):
        return pd.DataFrame([result])
    return pd.DataFrame(list(result))


def frame_to_result(result: Any, *, slug: str | None, max_rows: int, applied: dict[str, Any],
                    rejected: list[str], started: float) -> ExecutionResult:
    """DataFrame → ExecutionResult: head(max_rows) rows, honest counts, status 'empty' for zero rows."""
    frame = _as_frame(result)
    total = int(len(frame))
    head = frame.head(max_rows)
    rows = [json_safe(rec) for rec in head.to_dict(orient="records")]
    return ExecutionResult(
        status="empty" if total == 0 else "success",
        slug=slug,
        rows=rows,
        returned_rows=len(rows),
        total_rows=total,
        truncated=total > max_rows,
        columns=[str(c) for c in frame.columns],
        applied_conditions=json_safe(applied) or {},
        rejected_inputs=list(rejected),
        duration_ms=int((time.monotonic() - started) * 1000),
    )


def multi_to_result(result: Any, *, max_rows: int, started: float) -> MultiQueryResult:
    """MultiQS output (DataFrame | dict[str, DataFrame]) → MultiQueryResult keyed by frame name ('result' when single)."""
    frames = result if isinstance(result, dict) else {"result": result}
    results = {str(name): frame_to_result(frame, slug=None, max_rows=max_rows, applied={}, rejected=[], started=started)
               for name, frame in frames.items()}
    status = "empty" if results and all(r.status == "empty" for r in results.values()) else "success"
    return MultiQueryResult(status=status, results=results, duration_ms=int((time.monotonic() - started) * 1000))
```
**Why this shape**: `total_rows` is the frame length before slicing so the LLM knows when it is looking at a
sample (S8); the multi helper mirrors `handlers/multi.py:305-308` (single-frame collapse) without changing semantics.

### FILL IN checklist
- [ ] `results.py::json_safe` — NaT/NA, numpy scalars, bytes, fallback; bounded by AC "json.dumps succeeds"

---

## Acceptance Criteria

- [ ] `json.dumps(frame_to_result(df, ...).model_dump())` succeeds for a frame with `datetime64`, `NaT`, `NaN`, `int64`, `category`, `Decimal` columns.
- [ ] 500-row frame with `max_rows=200` → `returned_rows=200`, `total_rows=500`, `truncated=True`; empty frame → `status="empty"`, `columns` still listed.
- [ ] `multi_to_result({"a": df, "b": empty})` → two entries, status `"success"`; both empty → `"empty"`; single frame → key `"result"`.
- [ ] `pytest packages/ai-parrot-tools/tests/querysource/test_results.py -v` passes; `ruff check` clean.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/querysource/test_results.py
import json, time
from decimal import Decimal
import numpy as np, pandas as pd
from parrot_tools.querysource.results import frame_to_result, multi_to_result, json_safe

def _df(n=3):
    return pd.DataFrame({"ts": pd.to_datetime(["2026-08-09", None, "2026-08-11"][:n]), "qty": np.array([1, 2, 3][:n], dtype="int64"),
                         "amt": [Decimal("1.5"), float("nan"), 2.0][:n], "cat": pd.Categorical(["a", "b", "a"][:n])})

def test_json_safe_contract():
    r = frame_to_result(_df(), slug="s", max_rows=10, applied={"querylimit": 10}, rejected=[], started=time.monotonic())
    json.dumps(r.model_dump())
    assert r.rows[1]["ts"] is None and r.rows[0]["ts"].startswith("2026-08-09") and r.rows[0]["amt"] == 1.5

def test_truncation_and_counts():
    big = pd.DataFrame({"x": range(500)})
    r = frame_to_result(big, slug="s", max_rows=200, applied={}, rejected=[], started=time.monotonic())
    assert (r.returned_rows, r.total_rows, r.truncated, r.status) == (200, 500, True, "success")

def test_empty_frame():
    r = frame_to_result(pd.DataFrame(columns=["a", "b"]), slug="s", max_rows=5, applied={}, rejected=[], started=time.monotonic())
    assert r.status == "empty" and r.columns == ["a", "b"] and r.rows == []

def test_multi_shapes():
    m = multi_to_result({"a": _df(), "b": pd.DataFrame()}, max_rows=10, started=time.monotonic())
    assert set(m.results) == {"a", "b"} and m.status == "success"
    assert multi_to_result(pd.DataFrame(), max_rows=10, started=time.monotonic()).status == "empty"
    assert "result" in multi_to_result(_df(), max_rows=10, started=time.monotonic()).results
```

---

## Agent Instructions

1. Read spec §3 Module 5 (`results.py`) and §7 Risks (S8/S9).
2. Verify TASK-3246 completed; update index → `in-progress`; implement; tests; `ruff`.
3. Move this file to `sdd/tasks/completed/`, update index → `done`, fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
