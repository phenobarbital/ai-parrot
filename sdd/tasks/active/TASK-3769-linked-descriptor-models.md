# TASK-3769: Linked descriptor & DSL op models + has_data_sources

**Feature**: FEAT-598 — A2UI Linked Surfaces
**Spec**: `sdd/specs/a2ui-linked-surfaces.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

FEAT-598 lets a TOOL-origin A2UI surface carry a **data-source descriptor** under
`createSurface.metadata.extensions.parrot_data_sources` instead of (or in addition to)
baked rows. This task creates the wire contract: the Pydantic v2 models for
`LinkedDataSource`, `SourceRequest`, `ParamSpec`, `RefreshPolicy`, `TransformRef`,
`TransformSpec`, the ten DSL op models and the `LinkedSources` root model, plus
`has_data_sources()`. Every later task (conditions, schema, DSL, validation, builder,
executor, service, server) imports from here. Implements spec §2 "Data Models" and
§3 Module 1 (models part).

---

## Scope

- Create `parrot/outputs/a2ui/linked/models.py` with every model of spec §2 Data Models,
  `extra="forbid"` everywhere, and the validators listed below.
- Create `parrot/outputs/a2ui/linked/__init__.py`: eager re-export of the models +
  `has_data_sources`, and a **lazy module `__getattr__`** for the names later tasks add
  (`derive_conditions`, `export_json_schema`, `apply_transform`, `TransformError`,
  `execute_sources`, `map_query_error`, `LinkedSurfaceService`, `LinkedGuardRequired`,
  `TransformManifest`, `load_manifest`, `resolve_ref`) so no later task edits this file.
- Re-export `LinkedDataSource`, `LinkedSources`, `TransformSpec`, `has_data_sources` from
  `parrot/outputs/a2ui/__init__.py`.
- Create the test package `tests/outputs/a2ui/linked/` with `__init__.py`, a `conftest.py`
  holding ONLY `activity_frame` and `linked_source`, and `test_linked_models.py`.

**NOT in scope**: `derive_conditions` (TASK-3770), JSON Schema export (TASK-3771), DSL execution
(TASK-3773/TASK-3774), manifest (TASK-3775), any `validate_envelope` change (TASK-3777). The
request→conditions equality check is M3's, not a model validator.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/__init__.py` | CREATE | eager model exports, `has_data_sources`, lazy `__getattr__` |
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/models.py` | CREATE | descriptor + DSL op models |
| `packages/ai-parrot/src/parrot/outputs/a2ui/__init__.py` | MODIFY | re-export 4 linked names |
| `packages/ai-parrot/tests/outputs/a2ui/linked/__init__.py` | CREATE | empty test package marker |
| `packages/ai-parrot/tests/outputs/a2ui/linked/conftest.py` | CREATE | `activity_frame`, `linked_source` fixtures |
| `packages/ai-parrot/tests/outputs/a2ui/linked/test_linked_models.py` | CREATE | model unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, ConfigDict, Field, RootModel, StrictFloat, StrictInt, field_validator, model_validator  # pydantic v2 (models.py:49 uses the same package)
from parrot.outputs.a2ui.models import CreateSurface, is_valid_pointer   # models.py:446, models.py:112
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/models.py
def is_valid_pointer(pointer: str) -> bool:        # L112 — RFC 6901 SHAPE check; "" is valid (whole doc) → you must also require a non-empty pointer
class Extensions(RootModel[dict[str, Any]]):       # L341 — keys isidentifier(); "a2ui_" prefix reserved (L338) → "parrot_data_sources" is legal
class ComponentMetadata(BaseModel):                # L364 — extensions: Extensions | None ; extra="forbid"
SurfaceMetadata = ComponentMetadata                # L378
class CreateSurface(A2UIMessageBase):              # L446; extra="forbid" L463
    surface_id: str = Field(alias="surfaceId")     # L465
    data_model: dict[str, Any] = Field(default_factory=dict, alias="dataModel")   # L469
    metadata: SurfaceMetadata | None = None        # L470

# packages/ai-parrot/src/parrot/outputs/a2ui/__init__.py
# L9-11: one-way import rule — this package MUST NEVER import parrot.bots/clients/agents/DatasetManager
# L19-37: `from parrot.outputs.a2ui.models import (...)` ; L38-44 serialization imports
__all__ = [   # L46 (alphabetical list, ends L72)
```

### Does NOT Exist
- ~~`parrot.outputs.a2ui.linked`~~ — this task creates it.
- ~~`parrot.outputs.a2ui.linked.conditions` / `.schema` / `.dsl` / `.executor` / `.service` / `.manifest`~~ — created by TASK-3770/TASK-3771/TASK-3773/TASK-3780/TASK-3781/TASK-3775; only referenced lazily here.
- ~~`TransformRef.url`~~ — the descriptor never carries a URL (S6).
- ~~a `kind` field on the surface / a `LinkedWidget` component~~ — rejected in the brainstorm.
- ~~`Filter.op` as the comparison operator~~ — `op` is the union discriminator; the comparison is `operator` (see Implementation Notes).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/linked/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/linked/models.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/outputs/a2ui/linked/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/outputs/a2ui/linked/conftest.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/outputs/a2ui/linked/test_linked_models.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/models.py#is_valid_pointer",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/models.py#CreateSurface",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/models.py#Extensions"
  ]
}
```

---

## Implementation Notes

### Wire shapes (binding — every executor and the JSON Schema derive from these)
- `ParamSpec {type: str|None, default: Any, required: bool=False, editable: bool=True, accepts_keywords: bool=False}`
- `SourceRequest {placeholders: dict={}, filter: dict={}, fields: list[str]=[], ordering: list[str]=[], grouping: list[str]=[], limit: int|None, offset: int|None}` — `refresh`/`querylimit` are NEVER fields.
- `RefreshPolicy {policy: "on_mount"|"manual"|"interval" = "on_mount", interval_seconds: int|None}` — when `policy == "interval"`, `interval_seconds` is REQUIRED and `>= 30`; otherwise it is ignored (spec §4 `test_refresh_interval_min_30`: 29 fails, 30 passes, `manual` ignores it).
- `TransformRef {name, integrity}` — `name` matches `^[a-z0-9_-]+@\d+\.\d+\.\d+$` (opaque id, never a URL); `integrity` starts with `sha384-`.
- DSL ops (discriminator `op`, spec §7 DSL v1):
  - `select {columns: list[str]}` · `rename {mapping: dict[str,str]}`
  - `filter {column: str, operator: eq|ne|gt|ge|lt|le|in|contains, value: Any}` — **decision**: the spec prose writes the comparison as `op`, which collides with the discriminator; the field is named `operator`. Record this in the Completion Note.
  - `group_by {by: list[str], aggregate: dict[str, sum|avg|count|min|max]}`
  - `sort {by: list[{column: str, direction: asc|desc = asc}]}` · `limit {n: int >= 0}`
  - `derive {name: str, expr: DeriveOperand}` where `DeriveOperand = DeriveBinary | StrictInt | StrictFloat | str` (a `str` operand is a column name, a number a constant) and `DeriveBinary {operator: "+"|"-"|"*"|"/", left: DeriveOperand, right: DeriveOperand}` (recursive → `model_rebuild()`).
  - `pivot {index: list[str], columns: str, values: str, aggregate: sum|avg|count|min|max}`
  - `join {with: str (sibling source key), how: inner|left, on: list[{left: str, right: str}]}` — `with` is a Python keyword: field `with_: str = Field(alias="with")`, `populate_by_name=True`; always dump with `by_alias=True`.
  - `union {sources: list[str]}` (min length 1)
- `TransformSpec {ops: list[TransformOp]|None, ref: TransformRef|None}` — exactly one of the two.
- `LinkedDataSource` — fields exactly as spec §2 (`kind` Literal `"query_slug"`, `slug`, `tenant`, `is_multiquery`, `multi_output`, `conditions` (required), `request` (required), `params`, `locked`, `transform`, `target` (required), `snapshot_at`, `snapshot_truncated`, `refresh`). Validators: `target` is a non-empty valid JSON pointer; every `locked` name ∈ `params`.
- `LinkedSources = RootModel[dict[str, LinkedDataSource]]` — keys are `dataModel` root keys: key must be a Python identifier AND each source's `target` first reference token must equal its key (spec G2: "keyed by the dataModel root key each source fills").

### Key Constraints
- Pydantic v2 only; `ConfigDict(extra="forbid", populate_by_name=True)` on every model.
- `linked/` imports **only** `parrot.outputs.a2ui.models` at module import time (spec §7 "one-way import rule"; nothing from `catalog/`, never pandas at import).
- The lazy `__getattr__` must raise `AttributeError` for unknown names (so `hasattr` works) and must import the submodule only on first access.
- `parrot/outputs/a2ui/__init__.py`: add the linked import **after** the existing `serialization` import — the models module is then already initialised, so `linked.models` importing `parrot.outputs.a2ui.models` cannot hit a partially-initialised package.

### References in Codebase
- `packages/ai-parrot/src/parrot/outputs/a2ui/models.py:341-378` — Extensions/metadata pattern and `ConfigDict` style.

---

## Implementation Blueprint

### Steps (in order)
1. Write `linked/models.py` (blocks A + B) — *why*: every other file imports it.
2. Write `linked/__init__.py` — *why*: fixes the public import surface once, lazily, so later tasks never touch it.
3. Append the re-export to `a2ui/__init__.py` after the serialization import and extend `__all__` alphabetically — *why*: G1 public surface; import order avoids a circular-init error.
4. Write the test package, conftest and tests; run the Validation Commands.

### `packages/ai-parrot/src/parrot/outputs/a2ui/linked/models.py` (CREATE) — block A (params, request, refresh, ref, ops)
```python
"""Wire models of ``parrot_data_sources`` and the transform DSL v1 (FEAT-598, spec §2 / §7)."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, RootModel, StrictFloat, StrictInt, field_validator, model_validator

from parrot.outputs.a2ui.models import is_valid_pointer

_CFG = ConfigDict(extra="forbid", populate_by_name=True)
_REF_NAME_RE = re.compile(r"^[a-z0-9_-]+@\d+\.\d+\.\d+$")
MIN_INTERVAL_SECONDS = 30
Aggregate = Literal["sum", "avg", "count", "min", "max"]


class ParamSpec(BaseModel):
    """One user-editable query parameter (placeholder) of a source."""

    model_config = _CFG
    type: str | None = None
    default: Any = None
    required: bool = False
    editable: bool = True
    accepts_keywords: bool = False


class SourceRequest(BaseModel):
    """Canonical, structured condition representation (S5); ``conditions`` is derived from it."""

    model_config = _CFG
    placeholders: dict[str, Any] = Field(default_factory=dict)
    filter: dict[str, Any] = Field(default_factory=dict)
    fields: list[str] = Field(default_factory=list)
    ordering: list[str] = Field(default_factory=list)
    grouping: list[str] = Field(default_factory=list)
    limit: int | None = None
    offset: int | None = None


class RefreshPolicy(BaseModel):
    """Renderer refresh policy: ``on_mount`` (default), ``manual`` or ``interval`` (>= 30 s)."""

    model_config = _CFG
    policy: Literal["on_mount", "manual", "interval"] = "on_mount"
    interval_seconds: int | None = None

    @model_validator(mode="after")
    def _check_interval(self) -> RefreshPolicy:
        # FILL IN: when policy == "interval" require interval_seconds is not None and >= MIN_INTERVAL_SECONDS
        #          (raise ValueError otherwise); other policies accept any value — bounded by spec §4 test_refresh_interval_min_30
        return self


class TransformRef(BaseModel):
    """Catalogued renderer-side transform: opaque ``name@semver`` id + SRI pin (S6). Never a URL."""

    model_config = _CFG
    name: str
    integrity: str

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        if not _REF_NAME_RE.match(value):
            raise ValueError(f"TransformRef.name {value!r} must match '<name>@<semver>' (never a URL)")
        return value

    @field_validator("integrity")
    @classmethod
    def _check_integrity(cls, value: str) -> str:
        if not value.startswith("sha384-"):
            raise ValueError("TransformRef.integrity must be a 'sha384-…' SRI hash")
        return value
```
**Why this shape**: field lists are fixed by spec §2; the 30 s floor and the opaque-id rule are AC10/AC17 (S6). Do not add fields.

### `linked/models.py` — block B (the ten ops, TransformSpec, LinkedDataSource, LinkedSources) — append to the same file
```python
class Select(BaseModel):
    model_config = _CFG
    op: Literal["select"] = "select"
    columns: list[str]


class Rename(BaseModel):
    model_config = _CFG
    op: Literal["rename"] = "rename"
    mapping: dict[str, str]


class Filter(BaseModel):
    model_config = _CFG
    op: Literal["filter"] = "filter"
    column: str
    operator: Literal["eq", "ne", "gt", "ge", "lt", "le", "in", "contains"]
    value: Any = None


class GroupBy(BaseModel):
    model_config = _CFG
    op: Literal["group_by"] = "group_by"
    by: list[str]
    aggregate: dict[str, Aggregate]


class SortKey(BaseModel):
    model_config = _CFG
    column: str
    direction: Literal["asc", "desc"] = "asc"


class Sort(BaseModel):
    model_config = _CFG
    op: Literal["sort"] = "sort"
    by: list[SortKey]


class Limit(BaseModel):
    model_config = _CFG
    op: Literal["limit"] = "limit"
    n: int = Field(ge=0)


class DeriveBinary(BaseModel):
    model_config = _CFG
    operator: Literal["+", "-", "*", "/"]
    left: DeriveOperand
    right: DeriveOperand


DeriveOperand = Union[DeriveBinary, StrictInt, StrictFloat, str]   # str = column name, number = constant
DeriveBinary.model_rebuild()


class Derive(BaseModel):
    model_config = _CFG
    op: Literal["derive"] = "derive"
    name: str
    expr: DeriveOperand


class Pivot(BaseModel):
    model_config = _CFG
    op: Literal["pivot"] = "pivot"
    index: list[str]
    columns: str
    values: str
    aggregate: Aggregate = "sum"


class JoinKey(BaseModel):
    model_config = _CFG
    left: str
    right: str


class Join(BaseModel):
    model_config = _CFG
    op: Literal["join"] = "join"
    with_: str = Field(alias="with")
    how: Literal["inner", "left"] = "inner"
    on: list[JoinKey] = Field(min_length=1)


class Union_(BaseModel):
    model_config = _CFG
    op: Literal["union"] = "union"
    sources: list[str] = Field(min_length=1)


TransformOp = Annotated[
    Union[Select, Rename, Filter, GroupBy, Sort, Limit, Derive, Pivot, Join, Union_], Field(discriminator="op")
]
```
**Why**: spec §2 lists the ten ops and §7 fixes their parameters. `Union_` avoids shadowing `typing.Union`; export it as `UnionOp` from `__init__`. Keep the op literals exactly as written (`group_by`, not `groupby`): they are the wire.

### `linked/models.py` — block C (TransformSpec, LinkedDataSource, LinkedSources) — append
```python
class TransformSpec(BaseModel):
    """Exactly one of ``ops`` (inline DSL) or ``ref`` (catalogued renderer module)."""

    model_config = _CFG
    ops: list[TransformOp] | None = None
    ref: TransformRef | None = None

    @model_validator(mode="after")
    def _xor(self) -> TransformSpec:
        if (self.ops is None) == (self.ref is None):
            raise ValueError("TransformSpec requires exactly one of 'ops' or 'ref'")
        return self


class LinkedDataSource(BaseModel):
    """One data source of a linked surface (spec §2 Data Models)."""

    model_config = _CFG
    kind: Literal["query_slug"] = "query_slug"
    slug: str
    tenant: str | None = None
    is_multiquery: bool = False
    multi_output: str | None = None
    conditions: dict[str, Any]
    request: SourceRequest
    params: dict[str, ParamSpec] = Field(default_factory=dict)
    locked: list[str] = Field(default_factory=list)
    transform: TransformSpec | None = None
    target: str
    snapshot_at: datetime | None = None
    snapshot_truncated: bool = False
    refresh: RefreshPolicy = Field(default_factory=RefreshPolicy)

    @field_validator("target")
    @classmethod
    def _check_target(cls, value: str) -> str:
        if not value or not is_valid_pointer(value):
            raise ValueError(f"target {value!r} must be a non-empty absolute JSON pointer")
        return value

    @model_validator(mode="after")
    def _check_locked(self) -> LinkedDataSource:
        # FILL IN: raise ValueError naming every locked name missing from self.params — bounded by spec M1 "locked ⊆ params"
        return self


class LinkedSources(RootModel[dict[str, LinkedDataSource]]):
    """Value of ``createSurface.metadata.extensions['parrot_data_sources']``; keys are dataModel root keys."""

    @model_validator(mode="after")
    def _check_keys(self) -> LinkedSources:
        # FILL IN: for each (key, src): key.isidentifier() and src.target's first reference token == key
        #          (split on "/" → index 1; unescape ~1→"/" then ~0→"~") else ValueError — bounded by spec G2
        return self
```

### `packages/ai-parrot/src/parrot/outputs/a2ui/linked/__init__.py` (CREATE)
```python
"""``parrot.outputs.a2ui.linked`` — linked-surface descriptors (FEAT-598).

Models are imported eagerly (pydantic only). Execution-side names (DSL, executor, service,
manifest, schema, conditions) resolve lazily so ``import parrot.outputs.a2ui`` never pulls
pandas or querysource (spec §7 one-way import rule).
"""
from __future__ import annotations

import importlib
from typing import Any

from parrot.outputs.a2ui.linked.models import (
    Derive, DeriveBinary, Filter, GroupBy, Join, JoinKey, Limit, LinkedDataSource, LinkedSources, ParamSpec,
    Pivot, RefreshPolicy, Rename, Select, Sort, SortKey, SourceRequest, TransformOp, TransformRef, TransformSpec,
)
from parrot.outputs.a2ui.linked.models import Union_ as UnionOp

DATA_SOURCES_EXTENSION = "parrot_data_sources"

_LAZY: dict[str, str] = {
    "derive_conditions": "conditions",
    "export_json_schema": "schema",
    "apply_transform": "dsl",
    "TransformError": "dsl",
    "execute_sources": "executor",
    "map_query_error": "executor",
    "SourceOutcome": "executor",
    "ExecutionOutcome": "executor",
    "LinkedSurfaceService": "service",
    "LinkedGuardRequired": "service",
    "TransformManifest": "manifest",
    "load_manifest": "manifest",
    "resolve_ref": "manifest",
}


def __getattr__(name: str) -> Any:
    """Resolve execution-side names on first access (PEP 562)."""
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(f"{__name__}.{module}"), name)


def has_data_sources(envelope: Any) -> bool:
    """True when ``metadata.extensions.parrot_data_sources`` is a non-empty mapping.

    Accepts a ``CreateSurface`` model, a bare createSurface dict, or a wrapped
    ``{"createSurface": {...}}`` message dict.
    """
    # FILL IN: CreateSurface → envelope.metadata.extensions.root ; dict → unwrap "createSurface" if present,
    #          then .get("metadata") → .get("extensions") ; None/non-mapping anywhere → False — bounded by M1 skeleton
    return False


__all__ = [
    "DATA_SOURCES_EXTENSION", "Derive", "DeriveBinary", "Filter", "GroupBy", "Join", "JoinKey", "Limit",
    "LinkedDataSource", "LinkedSources", "ParamSpec", "Pivot", "RefreshPolicy", "Rename", "Select", "Sort",
    "SortKey", "SourceRequest", "TransformOp", "TransformRef", "TransformSpec", "UnionOp", "has_data_sources",
    *_LAZY,
]
```
**Why**: the lazy map names every public symbol of spec §2 "New Public Interfaces" plus the executor/manifest
helpers, so TASK-3770..TASK-3781 never edit this file (no file-overlap edges). Do not import `CreateSurface` here at
module level for isinstance — use `getattr(envelope, "metadata", None)` duck-typing, or import inside the function.

### `packages/ai-parrot/src/parrot/outputs/a2ui/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^from parrot.outputs.a2ui.serialization import (' packages/ai-parrot/src/parrot/outputs/a2ui/__init__.py)
# AFTER — insert below the closing ")" of `from parrot.outputs.a2ui.serialization import (` (verified: __init__.py:38-44)
from parrot.outputs.a2ui.linked import LinkedDataSource, LinkedSources, TransformSpec, has_data_sources

# occurrences: 1 (verified: grep -c '__all__ = \[' packages/ai-parrot/src/parrot/outputs/a2ui/__init__.py) — __init__.py:46
# add to __all__ keeping alphabetical order: "LinkedDataSource", "LinkedSources", "TransformSpec", "has_data_sources"
```
**Why**: G1 public surface; placed last so `parrot.outputs.a2ui.models` is initialised first.

### `packages/ai-parrot/tests/outputs/a2ui/linked/__init__.py` (CREATE)
```python
```
(empty file — keeps test module names unique, like `tests/outputs/a2ui/__init__.py`.)

### `packages/ai-parrot/tests/outputs/a2ui/linked/conftest.py` (CREATE)
```python
"""Shared fixtures for linked-surface tests (FEAT-598). ONLY these two — other fixtures stay local."""
from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from parrot.outputs.a2ui.linked import LinkedDataSource, ParamSpec, SourceRequest


@pytest.fixture
def activity_frame() -> pd.DataFrame:
    """12 rows: day (date), visits (int), program (str)."""
    days = [dt.date(2026, 9, 1) + dt.timedelta(days=i) for i in range(12)]
    return pd.DataFrame({"day": days, "visits": [10 * (i + 1) for i in range(12)],
                         "program": ["epson" if i % 2 == 0 else "pokemon" for i in range(12)]})


@pytest.fixture
def linked_source() -> LinkedDataSource:
    """epson_field_activity, public tenant, placeholders firstdate=YESTERDAY lastdate=TODAY."""
    return LinkedDataSource(
        slug="epson_field_activity",
        tenant=None,
        conditions={"firstdate": "YESTERDAY", "lastdate": "TODAY"},
        request=SourceRequest(placeholders={"firstdate": "YESTERDAY", "lastdate": "TODAY"}),
        params={"firstdate": ParamSpec(type="date", accepts_keywords=True),
                "lastdate": ParamSpec(type="date", accepts_keywords=True)},
        target="/activity/rows",
    )
```

### `packages/ai-parrot/tests/outputs/a2ui/linked/test_linked_models.py` (CREATE)
```python
"""Unit tests for linked descriptor models (FEAT-598 M1)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from parrot.outputs.a2ui.linked import LinkedDataSource, LinkedSources, RefreshPolicy, TransformSpec, has_data_sources


def test_linked_models_roundtrip(linked_source):
    # FILL IN: model_dump(mode="json", by_alias=True) → model_validate equals original; an unknown key raises
    ...


def test_refresh_interval_min_30():
    # FILL IN: interval+29 raises, interval+30 ok, interval+None raises, manual+5 ok
    ...


def test_transform_spec_ops_xor_ref():
    # FILL IN: neither → ValidationError; both → ValidationError; ops only / ref only ok
    ...
```
(FILL IN the remaining tests from the Test Specification below.)

### FILL IN checklist
- [ ] `RefreshPolicy._check_interval` — interval requires `>= 30`; bounded by spec §4 / AC10
- [ ] `LinkedDataSource._check_locked` — `locked ⊆ params`; bounded by M1
- [ ] `LinkedSources._check_keys` — identifier key == target root token; bounded by G2
- [ ] `has_data_sources` — model / bare dict / wrapped dict; bounded by M1 skeleton
- [ ] test bodies per Test Specification

---

## Acceptance Criteria

- [ ] All models of spec §2 exist with `extra="forbid"`; the ten ops discriminate on `op`; `join` round-trips `with` by alias.
- [ ] `TransformRef.name` rejects URLs (`https://…`, `/static/x.js`) — part of AC17 (S6).
- [ ] `interval_seconds` floor 30 enforced only for `interval` (AC10 server half).
- [ ] `from parrot.outputs.a2ui.linked import LinkedDataSource, has_data_sources` works; `import parrot.outputs.a2ui` does NOT import pandas (`"pandas" not in sys.modules` after a fresh import in a subprocess).
- [ ] Existing a2ui tests unchanged and green (AC11).
- [ ] `ruff check` + `black --check` clean on the new files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/outputs/a2ui/linked/test_linked_models.py -q`
- `pytest packages/ai-parrot/tests/outputs/a2ui/test_models.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/outputs/a2ui/linked/test_linked_models.py
def test_linked_models_roundtrip(linked_source): ...          # dump(mode="json", by_alias=True) → validate == original; extra key rejected
def test_refresh_interval_min_30(): ...                        # 29 fails, 30 passes, manual ignores
def test_transform_spec_ops_xor_ref(): ...                     # both / neither → ValidationError
def test_ref_name_is_opaque(): ...                             # "group_by_day@1.0.0" ok; "https://x/y.js", "a/b@1.0.0", "x@1.0" fail
def test_locked_must_be_subset_of_params(linked_source): ...
def test_target_must_be_nonempty_pointer(): ...                # "" and "activity/rows" fail
def test_linked_sources_key_matches_target_root(linked_source): ...   # {"activity": src} ok; {"other": src} fails
def test_join_with_alias_roundtrip(): ...                      # TransformSpec(ops=[{"op":"join","with":"b","on":[{"left":"k","right":"k"}]}]) dumps "with"
def test_derive_expr_recursive(): ...                          # {"operator":"/","left":"a","right":{"operator":"+","left":"b","right":1}}
def test_has_data_sources_variants(linked_source): ...         # CreateSurface model, bare dict, wrapped dict, empty mapping → False
def test_a2ui_import_is_pandas_free(): ...                     # subprocess: python -c "import parrot.outputs.a2ui, sys; assert 'pandas' not in sys.modules"
```

---

## Agent Instructions

1. Read the spec (§2 Data Models, §3 Module 1, §7 DSL v1).
2. Confirm dependencies: none.
3. Re-verify the Codebase Contract (`grep -n` the listed lines).
4. Update the per-spec index status → `in-progress`.
5. Implement from the blueprint; complete every `# FILL IN:`; never change a fixed name/path.
6. Run the Validation Commands (in a worktree prefix `PYTHONPATH=packages/ai-parrot/src`).
7. Move this file to `sdd/tasks/completed/`, set index → `done`, fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: `Filter` comparison field is `operator` (spec prose says `op`, which is the discriminator).
