# TASK-1954: `columnar` codec — Python reference implementation

**Feature**: FEAT-380 — Tool Result Compression Pipeline
**Spec**: `sdd/specs/tool-result-compression.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1947
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4. This is the codec that pays for the feature. The most
expensive known case is `DatabaseQueryToolkit`: `QueryResult.rows` is
`list[dict[str, Any]]`, so N column names repeat in each of M rows — for
500 rows × 12 columns that is ~6,000 repetitions of field names the model only
needs to see once.

The output shape is **deliberately identical to `PandasTable`**
(`parrot/bots/data.py:70`), which the `PandasAgentResponse` prompt already
teaches the LLM to read — no new prompt engineering needed.

This Python implementation is the **executable specification**: the Rust path
(TASK-1955) must pass this exact test suite.

---

## Scope

- Implement `ColumnarCodec` in `codecs/columnar.py`, registered via
  `@register_codec` with `codec_name = "columnar"`.
- Row-oriented `list[dict]` → split form:
  `{"columns": [...], "rows": [[...], ...], "constants": {...}}`.
- Transformations:
  - **Column extraction**: keys hoisted once into `columns`; values become
    positional lists aligned to `columns`.
  - **Constant-column factoring**: a column whose value is identical in every
    row moves to `constants` and drops out of `columns`/`rows`.
  - **Null-column elision**: an all-null column is dropped and recorded in the
    outcome metadata (so the report can attribute the gain and the LLM is not
    silently misled).
- Passthrough guards (each records "no gain" for discovery):
  - fewer than `min_rows` rows (default **20**, per-tool configurable via
    TOML `params`)
  - heterogeneous rows: key `union/intersection` ratio > **1.5**
    (configurable) → passthrough with null-elision only
  - deep nesting: any `dict`/`list` value → **no flattening**, null-elision
    only
  - non-`list[dict]` input → passthrough
- `lossy = True` whenever constant factoring or null elision dropped anything
  (that is what arms the tee); `lossy = False` for a pure shape change with
  no information dropped.
- Accept `QueryResult`-shaped input: if the payload is a dict with a `rows`
  key holding `list[dict]`, compress `rows` in place and leave the sibling
  fields (`driver`, `row_count`, `columns`, `execution_time_ms`) alone.

**NOT in scope**:
- The Rust path → TASK-1955.
- Wiring `execute_database_query` to this codec via a manifest entry — add the
  entry to the **core default manifest** (`compression/compressors.toml`) as
  part of this task, but do not touch `parrot/tools/databasequery/`.
- Budget routing → TASK-1950 already decides inline vs. executor.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/compression/codecs/columnar.py` | CREATE | `ColumnarCodec` |
| `packages/ai-parrot/src/parrot/tools/compression/codecs/__init__.py` | MODIFY | Import the module so `@register_codec` fires |
| `packages/ai-parrot/src/parrot/tools/compression/compressors.toml` | MODIFY | Add the `execute_database_query` → `columnar`/`normal`/`tee=true` default entry |
| `packages/ai-parrot/tests/tools/compression/test_columnar.py` | CREATE | Unit tests (the suite the Rust path must also pass) |
| `packages/ai-parrot/tests/tools/compression/conftest.py` | CREATE | Shared payload fixtures |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED against HEAD `024c21d44` on 2026-07-27.
> **Path mapping**: `parrot/...` means `packages/ai-parrot/src/parrot/...`.

### Verified Imports

```python
from datamodel.parsers.json import json_encoder      # verified: parrot/tools/abstract.py:13

# Created by TASK-1947:
from parrot.tools.compression import (
    FilterLevel, CompressionOutcome, register_codec,
)
```

### Existing Signatures to Use

```python
# parrot/tools/databasequery/base.py:148 — PRIMARY TARGET
class QueryResult(BaseModel):
    driver: str                     # line 159
    rows: list[dict[str, Any]]      # line 160 — keys repeated per row
    row_count: int                  # line 161
    columns: list[str]              # line 162
    execution_time_ms: float

# parrot/bots/data.py — TARGET OUTPUT FORMAT (the LLM already reads this shape)
Scalar = Union[str, int, float, bool, None]        # line 62
class PandasTable(BaseModel):                       # line 70
    columns: List[str]                              # line 72
    rows: List[List[Scalar]]                        # line 75
    @field_validator('rows')                        # line 85
    def validate_rows_alignment(cls, v, info): ...
    # ⚠️ pads short rows with None and TRUNCATES long ones; it does NOT raise.
    # Your codec must emit correctly aligned rows — do not rely on that
    # validator to fix misalignment, and do not import PandasTable here
    # (that would couple tools/ to bots/).
```

Target output shape (spec §2):

```json
{"columns": ["store_id", "revenue", "region", "active"],
 "rows": [["TCTX", 801467.93, "south", true],
          ["OMNE", 587654.26, "south", true]],
 "constants": {"region": "south", "active": true}}
```

### Does NOT Exist

- ~~A columnar/row-to-column helper in `parrot/`~~ — zero occurrences; write
  it.
- ~~`pandas` as a permitted dependency of this codec~~ — do NOT import pandas
  here. `parrot.tools.compression` must stay import-light and usable without
  the data extras. Pure Python only.
- ~~`PandasTable` as an import target for the codec~~ — match its *shape*, do
  not import it (`parrot.bots.data` is a heavier module and would invert the
  dependency direction).
- ~~A tokenizer~~ — `est_tokens_saved` is `bytes/4`.
- ~~`parrot_codec` (Rust)~~ — does not exist yet. This task is the pure-Python
  path only; do not add dispatch stubs for it (TASK-1955 adds them).
- ~~`ToolResult` involvement~~ — codecs receive the unwrapped payload.

---

## Implementation Notes

### Pattern to Follow

```python
def compress(self, result, *, level, params):
    min_rows = int(params.get("min_rows", 20))
    het_ratio = float(params.get("heterogeneity_ratio", 1.5))
    rows, container = self._locate_rows(result)        # handles QueryResult shape
    if rows is None or len(rows) < min_rows:
        return self._no_gain(result, reason="min_rows")
    keys = [set(r) for r in rows]
    union, inter = set().union(*keys), set.intersection(*keys)
    if inter and len(union) / len(inter) > het_ratio:
        return self._null_elision_only(result, reason="heterogeneous")
    if any(isinstance(v, (dict, list)) for r in rows for v in r.values()):
        return self._null_elision_only(result, reason="nested")
    ...
```

### Key Constraints

- **Determinism (G4)**: column order must be stable and derived from the data
  (first-seen order across rows), never from `set` iteration order. Assert it
  in a test — this is the single easiest way to accidentally violate G4.
- Alignment: every row list must have exactly `len(columns)` entries, with
  explicit `None` for missing keys.
- `constants` is only populated when a column is constant across **all** rows
  AND there is more than one row.
- Null-elision must be recorded: put the dropped column names into the
  outcome so the LLM/report can see what happened. A silently vanished column
  is a correctness bug, not a compression win.
- `lossy=True` arms the tee (TASK-1953). Be honest about it: if you dropped
  or factored anything, it is lossy, even if you believe it is recoverable
  from `constants`.
- Never raise — internal failure returns a passthrough outcome.
- Synchronous, no `await`, no I/O.
- Sub-millisecond budget for payloads under the threshold (TASK-1950 handles
  the routing; TASK-1959 measures it).

### References in Codebase

- `parrot/tools/databasequery/base.py:148` — the input shape.
- `parrot/bots/data.py:70` — the output shape to mirror.
- `parrot/clients/google/client.py:1199` `_truncate_large_result()` — the
  positional truncation this codec replaces semantically.

---

## Acceptance Criteria

- [ ] `test_columnar_shape_matches_pandastable`: output is the
      `columns`/`rows` split form with `PandasTable` semantics.
- [ ] `test_columnar_constants_and_null_elision`: constant columns factored to
      `constants`; all-null columns dropped and recorded in metadata.
- [ ] `test_columnar_min_rows_passthrough`: < 20 rows → passthrough, recorded
      as "no gain".
- [ ] `test_columnar_heterogeneous_passthrough`: union ≫ intersection →
      passthrough with null-elision only.
- [ ] `test_columnar_nested_values_passthrough`: dict/list values → no
      flattening, null-elision only.
- [ ] Determinism: 100 runs → byte-identical output, stable column order (G4).
- [ ] A 500 × 12 payload shows a measurable byte reduction.
- [ ] `min_rows` and `heterogeneity_ratio` are overridable via `params`.
- [ ] No pandas import: `grep -L pandas` on the codec file.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/tools/compression/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/tools/compression/`

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/compression/conftest.py
import pytest


@pytest.fixture
def row_oriented_payload():
    """500 rows x 12 cols, 2 constant columns, 1 all-null column, mixed types."""
    return [
        {
            "store_id": f"S{i:04d}", "revenue": 1000.0 + i, "region": "south",
            "active": True, "notes": None,
            **{f"c{j}": (i * j) % 7 for j in range(7)},
        }
        for i in range(500)
    ]


@pytest.fixture
def heterogeneous_payload():
    """Rows with mostly-disjoint key sets (union/intersection ratio high)."""
    return [{f"k{i}": i, "shared": 1} for i in range(30)]


# packages/ai-parrot/tests/tools/compression/test_columnar.py
import pytest
from parrot.tools.compression import FilterLevel, get_codec
import parrot.tools.compression.codecs  # noqa: F401


@pytest.fixture
def codec():
    return get_codec("columnar")()


class TestColumnar:
    def test_columnar_shape_matches_pandastable(self, codec, row_oriented_payload):
        out = codec.compress(row_oriented_payload, level=FilterLevel.NORMAL, params={})
        p = out.payload
        assert set(p) >= {"columns", "rows"}
        assert all(len(r) == len(p["columns"]) for r in p["rows"])
        assert out.bytes_after < out.bytes_before

    def test_columnar_constants_and_null_elision(self, codec, row_oriented_payload):
        out = codec.compress(row_oriented_payload, level=FilterLevel.NORMAL, params={})
        assert out.payload["constants"]["region"] == "south"
        assert out.payload["constants"]["active"] is True
        assert "notes" not in out.payload["columns"]
        assert out.lossy is True

    def test_columnar_min_rows_passthrough(self, codec, row_oriented_payload):
        small = row_oriented_payload[:19]
        out = codec.compress(small, level=FilterLevel.NORMAL, params={})
        assert out.payload is small
        assert out.bytes_after == out.bytes_before      # recorded as "no gain"

    def test_columnar_heterogeneous_passthrough(self, codec, heterogeneous_payload):
        out = codec.compress(heterogeneous_payload, level=FilterLevel.NORMAL, params={})
        assert "columns" not in (out.payload if isinstance(out.payload, dict) else {})

    def test_columnar_nested_values_passthrough(self, codec):
        rows = [{"a": {"nested": 1}, "b": None} for _ in range(30)]
        out = codec.compress(rows, level=FilterLevel.NORMAL, params={})
        assert isinstance(out.payload, list)             # not columnarized

    def test_determinism_and_stable_column_order(self, codec, row_oriented_payload):
        first = codec.compress(row_oriented_payload, level=FilterLevel.NORMAL, params={})
        for _ in range(99):
            again = codec.compress(row_oriented_payload, level=FilterLevel.NORMAL, params={})
            assert again.payload == first.payload

    def test_queryresult_shape(self, codec, row_oriented_payload):
        payload = {"driver": "pg", "rows": row_oriented_payload,
                   "row_count": 500, "columns": [], "execution_time_ms": 1.0}
        out = codec.compress(payload, level=FilterLevel.NORMAL, params={})
        assert out.payload["driver"] == "pg"
        assert "columns" in out.payload["rows"]

    def test_min_rows_configurable(self, codec, row_oriented_payload):
        out = codec.compress(row_oriented_payload[:5], level=FilterLevel.NORMAL,
                             params={"min_rows": 2})
        assert "columns" in out.payload
```

---

## Agent Instructions

1. **Read the spec** (§3 Module 4, §2 output shape, §7 risks).
2. **Check dependencies** — TASK-1947 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — re-read
   `parrot/tools/databasequery/base.py:148` and `parrot/bots/data.py:70`.
4. **Update status** in `sdd/tasks/index/tool-result-compression.json`.
5. **Implement** per scope. Remember: this suite is the executable spec for
   the Rust path — write it to be implementation-agnostic (no white-box
   assertions about internal helpers).
6. **Verify** acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
