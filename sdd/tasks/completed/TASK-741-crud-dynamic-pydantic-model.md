# TASK-741: Dynamic per-table Pydantic model builder (lru_cache)

**Feature**: FEAT-106 — NavigatorToolkit ↔ PostgresToolkit Interaction
**Spec**: `sdd/specs/navigatortoolkit-postgrestoolkit-interaction.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-740
**Assigned-to**: unassigned

---

## Context

`PostgresToolkit.insert_row` / `upsert_row` / `update_row` (TASK-743)
validate their `data: dict` argument against a Pydantic model that is
built dynamically from `TableMetadata.columns`. The builder must be a
pure function (so `functools.lru_cache` is trivially applicable) and
live at module level, outside any class. This task delivers that
builder plus the `ColumnsKey` hashable shape it consumes.

Implements **Module 3** of the spec (lives in the same new module as Module 4 → TASK-742).

---

## Scope

- Create the new module `packages/ai-parrot/src/parrot/bots/database/toolkits/_crud.py`.
  (If TASK-742 is executed before this one, append instead of create — verify.)
- Add at module level:
  ```python
  ColumnsKey = tuple[tuple[str, type, bool, bool], ...]
  # Each tuple: (column_name, python_type, is_nullable, is_json)
  ```
- Add `_columns_key_from_metadata(meta: TableMetadata) -> ColumnsKey`.
  Map PG `data_type` strings to Python types via
  `datamodel.types.MODEL_TYPES`; fall back to `str` for unknown types.
  Mark `is_json=True` for types in `{"json", "jsonb", "hstore"}`.
  Use `col.get("nullable", True)` — default nullable-True for safety.
- Add `_build_pydantic_model(model_name: str, columns_key: ColumnsKey) -> Type[BaseModel]`.
  - Decorate with `@functools.lru_cache(maxsize=None)` (per spec Q5: unbounded).
  - Use `pydantic.create_model` with
    `__config__=ConfigDict(extra="forbid")`.
  - Every field is Optional with default `None` — the CRUD layer decides
    which columns are required per operation (INSERT requires PK for
    non-serial PKs; UPDATE/DELETE only require WHERE columns).
  - For `is_json=True` columns, the field type is `Union[dict, list]`
    (not `Any` — we want the LLM to pass structured JSON payloads).
- Log cache invalidations (when `reload_metadata` calls
  `_build_pydantic_model.cache_clear()` in TASK-743) at INFO — but the
  log call lives in TASK-743, not here.

**NOT in scope**:
- SQL template builders — TASK-742.
- Wiring into `PostgresToolkit` — TASK-743.
- Replacing `navigator/schemas.py` Pydantic models — explicit Non-Goal.
- Adding TTL or manual eviction — the cache is cleared wholesale via
  `_build_pydantic_model.cache_clear()`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/database/toolkits/_crud.py` | CREATE (or APPEND if TASK-742 already created it) | `ColumnsKey` alias, `_columns_key_from_metadata`, `_build_pydantic_model` |
| `tests/unit/test_crud_helpers.py` | CREATE (or extend if TASK-742 created it) | Test the builder — see Test Specification |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from __future__ import annotations
from typing import Type, Optional, Any, Union, List, Dict
import functools
from dataclasses import dataclass

from pydantic import BaseModel, create_model, ConfigDict, Field
# verified: pydantic 2.12.5 installed

from datamodel.types import MODEL_TYPES
# verified at: .venv/lib/python3.11/site-packages/datamodel/types.py
# MODEL_TYPES maps PG type strings → Python types, e.g.:
#   "integer" → int
#   "character varying" / "varchar" / "text" → str
#   "jsonb" / "json" → dict  (verify — could be Any)
#   "uuid" → uuid.UUID
#   "timestamp with time zone" → datetime

from parrot.bots.database.models import TableMetadata
# verified at: packages/ai-parrot/src/parrot/bots/database/models.py:106
```

### Existing Signatures to Use

```python
# pydantic 2.12.5
from pydantic import create_model, ConfigDict, BaseModel
# create_model(model_name, __base__=None, __config__=None, __doc__=None,
#              __validators__=None, **fields) -> type[BaseModel]
# Each field: (type_annotation, default_or_Field)
# For extra="forbid": pass __config__=ConfigDict(extra="forbid")

# datamodel.types.MODEL_TYPES
# A dict[str, type] — confirmed entries (sample):
#   "boolean", "integer", "bigint", "float", "character varying", "string",
#   "varchar", "byte", "bytea", "Array", "hstore", "character varying[]",
#   "numeric", "date", "timestamp with time zone", "time",
#   "timestamp without time zone", "uuid", "json", "jsonb", "text",
#   "serial", "bigserial", "inet"
```

```python
# packages/ai-parrot/src/parrot/bots/database/models.py
@dataclass
class TableMetadata:                                            # line 106
    # ... (see TASK-740 contract) ...
    columns: List[Dict[str, Any]] = field(default_factory=list) # line 113
    # Each column dict has keys: "name", "type", "nullable", "default"
    # (existing convention — verify by reading _build_table_metadata)
```

### Does NOT Exist

- ~~`parrot.bots.database.toolkits._crud`~~ — module does not exist; this task creates it.
- ~~`pydantic.create_model(..., config={"extra": "forbid"})`~~ — pydantic v2 rejects dict here; must use `__config__=ConfigDict(extra="forbid")`.
- ~~`datamodel.types.MODEL_TYPES["serial"]`~~ — maybe present; verify before relying. Default to `int` if missing.
- ~~`methodtools.lru_cache`~~ — not a project dependency; use `functools.lru_cache`.
- ~~`lru_cache(typed=True)`~~ — not needed since `ColumnsKey` captures types already.

---

## Implementation Notes

### Pattern to Follow

```python
# _crud.py (module-level)
import functools
from typing import Type, Optional, Union
from pydantic import BaseModel, create_model, ConfigDict
from datamodel.types import MODEL_TYPES
from parrot.bots.database.models import TableMetadata

ColumnsKey = tuple[tuple[str, type, bool, bool], ...]
# (column_name, python_type, is_nullable, is_json)

_JSON_TYPES = frozenset({"json", "jsonb", "hstore"})


def _columns_key_from_metadata(meta: TableMetadata) -> ColumnsKey:
    """Build a hashable cache key from TableMetadata.columns."""
    items = []
    for col in meta.columns:
        name = col["name"]
        pg_type = (col.get("type") or "text").lower()
        py_type = MODEL_TYPES.get(pg_type, str)
        is_nullable = bool(col.get("nullable", True))
        is_json = pg_type in _JSON_TYPES
        items.append((name, py_type, is_nullable, is_json))
    return tuple(items)


@functools.lru_cache(maxsize=None)
def _build_pydantic_model(
    model_name: str,
    columns_key: ColumnsKey,
) -> Type[BaseModel]:
    """Build (or return cached) Pydantic model for a table's columns.

    All fields are Optional — per-op required-ness is enforced by the
    caller (insert/update/delete). extra="forbid" rejects unknown keys
    so unknown LLM inputs fail fast.
    """
    fields: dict[str, tuple[type, Any]] = {}
    for name, py_type, _is_nullable, is_json in columns_key:
        if is_json:
            annotation: type = Optional[Union[dict, list]]  # type: ignore[assignment]
        else:
            annotation = Optional[py_type]  # type: ignore[assignment]
        fields[name] = (annotation, None)
    return create_model(
        model_name,
        __config__=ConfigDict(extra="forbid"),
        **fields,
    )
```

### Key Constraints

- `columns_key` MUST be a `tuple` of hashable tuples — lists break
  `lru_cache`. Enforce in `_columns_key_from_metadata`.
- `model_name` drives the cache key together with `columns_key`. Pass
  something stable like `f"{schema}_{table}_model"` from the caller
  (TASK-743).
- Never mutate the `TableMetadata` passed in — read-only consumer.
- Keep the helper pure — NO class state, NO I/O, NO logging inside the
  cached function (logging inside a cached call fires only on miss,
  which is confusing). Log at the caller level (TASK-743).
- If Python-type resolution collapses two PG types (e.g. both `varchar`
  and `text` → `str`) the cache key still differentiates them via the
  type object — no extra work needed because the tuple includes the
  Python type.

### References in Codebase

- `packages/ai-parrot/src/parrot/bots/schemas.py` — existing hand-written Pydantic models (style guide, not inheritance)
- `.venv/lib/python3.11/site-packages/datamodel/types.py` — MODEL_TYPES source of truth

---

## Acceptance Criteria

- [ ] `_crud.py` exists at `packages/ai-parrot/src/parrot/bots/database/toolkits/_crud.py`
- [ ] `_columns_key_from_metadata(meta)` returns a `tuple` of `(str, type, bool, bool)` tuples
- [ ] `_build_pydantic_model("t_model", key)` returns a `Type[BaseModel]`
- [ ] Two calls with identical `columns_key` return the **same class** (`is` equality → `cache_info().hits >= 1`)
- [ ] Generated model rejects unknown fields (raises `pydantic.ValidationError` with `extra="forbid"` message)
- [ ] `jsonb` column accepts `{"k": "v"}` dict payload
- [ ] `jsonb` column accepts `[1, 2, 3]` list payload
- [ ] `_build_pydantic_model.cache_clear()` purges the cache (`cache_info().currsize` drops to 0)
- [ ] `pytest tests/unit/test_crud_helpers.py::TestBuildPydanticModel -v` passes

---

## Test Specification

```python
# tests/unit/test_crud_helpers.py
import pytest
from pydantic import ValidationError
from parrot.bots.database.toolkits._crud import (
    _build_pydantic_model,
    _columns_key_from_metadata,
)
from parrot.bots.database.models import TableMetadata


@pytest.fixture
def fixture_metadata() -> TableMetadata:
    return TableMetadata(
        schema="test",
        tablename="t",
        table_type="BASE TABLE",
        full_name='"test"."t"',
        columns=[
            {"name": "id", "type": "integer", "nullable": False, "default": None},
            {"name": "name", "type": "varchar", "nullable": False, "default": None},
            {"name": "data", "type": "jsonb", "nullable": True, "default": "'{}'"},
        ],
        primary_keys=["id"],
    )


class TestBuildPydanticModel:
    def test_columns_key_shape(self, fixture_metadata):
        key = _columns_key_from_metadata(fixture_metadata)
        assert isinstance(key, tuple)
        assert all(isinstance(x, tuple) and len(x) == 4 for x in key)

    def test_lru_hits(self, fixture_metadata):
        _build_pydantic_model.cache_clear()
        key = _columns_key_from_metadata(fixture_metadata)
        m1 = _build_pydantic_model("test_t", key)
        m2 = _build_pydantic_model("test_t", key)
        assert m1 is m2
        assert _build_pydantic_model.cache_info().hits >= 1

    def test_rejects_unknown_field(self, fixture_metadata):
        key = _columns_key_from_metadata(fixture_metadata)
        Model = _build_pydantic_model("test_t_unknown", key)
        with pytest.raises(ValidationError):
            Model(nope=1)

    def test_jsonb_accepts_dict(self, fixture_metadata):
        key = _columns_key_from_metadata(fixture_metadata)
        Model = _build_pydantic_model("test_t_json", key)
        instance = Model(data={"k": "v"})
        assert instance.data == {"k": "v"}

    def test_jsonb_accepts_list(self, fixture_metadata):
        key = _columns_key_from_metadata(fixture_metadata)
        Model = _build_pydantic_model("test_t_jsonlist", key)
        instance = Model(data=[1, 2, 3])
        assert instance.data == [1, 2, 3]

    def test_cache_clear(self, fixture_metadata):
        key = _columns_key_from_metadata(fixture_metadata)
        _build_pydantic_model("clearme", key)
        assert _build_pydantic_model.cache_info().currsize >= 1
        _build_pydantic_model.cache_clear()
        assert _build_pydantic_model.cache_info().currsize == 0
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** — especially Section 2 (Data Models) and Section 7 (Known Risks / Gotchas) re: `extra="forbid"` breaking `**kwargs` tolerance
2. **Check dependencies** — TASK-740 must be `done` (uses `TableMetadata`, though only existing `columns` attr — could proceed without it in a pinch)
3. **Verify the Codebase Contract** — confirm `datamodel.types.MODEL_TYPES` keys by opening the file; confirm pydantic version from `pyproject.toml`
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** per scope. Coordinate with TASK-742 on the `_crud.py` file — they both live there
6. **Verify** all acceptance criteria
7. **Move this file** to `tasks/completed/TASK-741-crud-dynamic-pydantic-model.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
