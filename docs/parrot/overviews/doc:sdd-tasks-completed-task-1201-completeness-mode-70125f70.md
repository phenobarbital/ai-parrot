---
type: Wiki Overview
title: 'TASK-1201: Completeness model & TableMetadata fields'
id: doc:sdd-tasks-completed-task-1201-completeness-model-and-metadata-fields-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Foundation for every other task in FEAT-178. The whole cache + tool
relates_to:
- concept: mod:parrot.bots.database.models
  rel: mentions
---

# TASK-1201: Completeness model & TableMetadata fields

**Feature**: FEAT-178 — Database Toolkit Cache Contract & Tool Semantics
**Spec**: `sdd/specs/database-toolkit-cache-contract.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Foundation for every other task in FEAT-178. The whole cache + tool
rework hinges on `TableMetadata` carrying a `completeness` level so
downstream code (cache reads, tool methods, YAML rendering) can
distinguish a `NAME_ONLY` stub from a fully-introspected entry.

Implements **Module 1** of the spec.

---

## Scope

- Add `Completeness` IntEnum (`NAME_ONLY=1`, `WITH_COLUMNS=2`,
  `FULL=3`) in `parrot/bots/database/models.py`.
- Add `MetadataSource` `Literal["frontend", "information_schema",
  "pg_catalog", "unknown"]`.
- Extend `TableMetadata` with three keyword-only fields (with
  defaults) — `completeness: Completeness = Completeness.FULL`,
  `loaded_at: datetime = field(default_factory=datetime.utcnow)`,
  `source: MetadataSource = "unknown"`.
- Add `TableMetadata.satisfies(self, required: Completeness) -> bool`.
- Update `to_yaml_context()` to emit `completeness` and `loaded_at`
  fields plus a `_warning` line when `completeness < FULL`
  (e.g. *"NAME_ONLY stub — call db_describe_table to load columns
  before generating SQL."*).
- Unit tests under `tests/bots/database/test_models.py`:
  `test_completeness_ordering`, `test_table_metadata_default_completeness`,
  `test_to_yaml_emits_warning_for_stubs`, `test_satisfies_*`.

**NOT in scope**: cache API changes, toolkit method changes,
PostgresToolkit query rewrites. All other modules consume this
foundation but live in their own tasks.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/database/models.py` | MODIFY | Add `Completeness`, `MetadataSource`, three fields, `satisfies()`, update `to_yaml_context()` |
| `packages/ai-parrot/tests/bots/database/test_models.py` | CREATE or MODIFY | Add unit tests for new types and behaviour |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# packages/ai-parrot/src/parrot/bots/database/models.py — module exists
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Any, Dict, List, Literal, Optional
import yaml
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/database/models.py:116-141
@dataclass
class TableMetadata:
    schema: str                                              # line 119
    tablename: str                                           # line 120
    table_type: str                                          # line 121
    full_name: str                                           # line 122
    comment: Optional[str] = None                            # line 123
    columns: List[Dict[str, Any]] = field(default_factory=list)         # line 124
    primary_keys: List[str] = field(default_factory=list)               # line 125
    foreign_keys: List[Dict[str, Any]] = field(default_factory=list)    # line 126
    indexes: List[Dict[str, Any]] = field(default_factory=list)         # line 127
    row_count: Optional[int] = None                          # line 128
    sample_data: List[Dict[str, Any]] = field(default_factory=list)     # line 129
    unique_constraints: List[List[str]] = field(default_factory=list)   # line 130
    last_accessed: Optional[datetime] = None                 # line 134
    access_frequency: int = 0                                # line 135
    avg_query_time: Optional[float] = None                   # line 136

    def __post_init__(self): ...                             # line 138
    def to_yaml_context(self) -> str: ...                    # line 142
    def to_dict(self) -> Dict[str, Any]: ...                 # line 170
```

### Does NOT Exist
- ~~`Completeness`~~ — introduced here. No existing enum with this name.
- ~~`MetadataSource`~~ — introduced here.
- ~~`TableMetadata.completeness` / `loaded_at` / `source`~~ — introduced here.
- ~~`TableMetadata.satisfies(...)`~~ — introduced here.

---

## Implementation Notes

### Why `IntEnum`
Spec §7 fixes the design: `Completeness` is `IntEnum` so
`meta.completeness >= required` is the canonical check. Do **not**
use `Set[Capability]` or string enums — strict numeric ordering
matches "strictly subsumes" semantics.

### Default value rationale
Default `completeness=Completeness.FULL` keeps backwards-compat:
every existing call site that constructs `TableMetadata` via
`_build_table_metadata` (sql.py:811) is in fact building a fully
introspected entry. Stubs that come from the frontend pre-warm
path (Module 8, downstream) must set `completeness` explicitly.

### `to_yaml_context()` warning shape
The serialised YAML for a non-FULL entry must include a `_warning`
key so the LLM cannot mistake it for full metadata. Example:

```yaml
table: '"pokemon"."stores"'
completeness: NAME_ONLY
loaded_at: 2026-05-15T12:34:56
_warning: "NAME_ONLY stub — call db_describe_table to load columns before generating SQL."
columns: []
```

### Redis deserialization safety
Old Redis entries (pre-FEAT-178) do not have these fields. The
`from_dict` / constructor path must default to `FULL` /
`datetime.utcnow()` / `"unknown"` so existing cached entries are
not retroactively flagged as stubs. This is handled by the
dataclass defaults — no extra code needed.

### Keyword-only fields
Place the new fields at the end of the dataclass with defaults so
positional `TableMetadata(schema=..., tablename=..., table_type=...,
full_name=...)` callers continue to work unchanged.

---

## Acceptance Criteria

- [ ] `Completeness` enum exists with values 1/2/3 in `models.py`
- [ ] `MetadataSource` Literal exists
- [ ] `TableMetadata` has `completeness`, `loaded_at`, `source` fields
      with the specified defaults
- [ ] `TableMetadata.satisfies(Completeness)` returns the expected
      boolean
- [ ] `to_yaml_context()` emits `completeness` + `loaded_at` fields
- [ ] `to_yaml_context()` emits a `_warning` field whenever
      `completeness < FULL`
- [ ] All existing tests in `tests/bots/database/` still pass
- [ ] New unit tests pass: `pytest packages/ai-parrot/tests/bots/database/test_models.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/database/test_models.py
import pytest
import yaml

from parrot.bots.database.models import (
    Completeness,
    TableMetadata,
)


class TestCompleteness:
    def test_completeness_ordering(self):
        assert Completeness.NAME_ONLY < Completeness.WITH_COLUMNS
        assert Completeness.WITH_COLUMNS < Completeness.FULL

    def test_satisfies(self):
        meta = TableMetadata(
            schema="s", tablename="t", table_type="BASE TABLE",
            full_name="s.t", completeness=Completeness.WITH_COLUMNS,
        )
        assert meta.satisfies(Completeness.NAME_ONLY)
        assert meta.satisfies(Completeness.WITH_COLUMNS)
        assert not meta.satisfies(Completeness.FULL)


class TestTableMetadataFields:
    def test_default_completeness_is_full(self):
        meta = TableMetadata(
            schema="s", tablename="t", table_type="BASE TABLE",
            full_name="s.t",
        )
        assert meta.completeness == Completeness.FULL
        assert meta.source == "unknown"
        assert meta.loaded_at is not None

    def test_to_yaml_emits_warning_for_stubs(self):
        meta = TableMetadata(
            schema="pokemon", tablename="stores",
            table_type="BASE TABLE", full_name='"pokemon"."stores"',
            completeness=Completeness.NAME_ONLY, source="frontend",
        )
        raw = meta.to_yaml_context()
        data = yaml.safe_load(raw)
        assert "_warning" in data
        assert "db_describe_table" in data["_warning"]

    def test_to_yaml_no_warning_for_full(self):
        meta = TableMetadata(
            schema="s", tablename="t", table_type="BASE TABLE",
            full_name="s.t",
            columns=[{"name": "id", "type": "int"}],
        )
        data = yaml.safe_load(meta.to_yaml_context())
        assert "_warning" not in data
```

---

## Agent Instructions

When you pick up this task:

1. Read the spec at `sdd/specs/database-toolkit-cache-contract.spec.md`
   (§2 Data Models, §3 Module 1, §7 Patterns to Follow).
2. Verify the Codebase Contract above by re-reading `models.py`.
3. Implement.
4. Run `pytest packages/ai-parrot/tests/bots/database/test_models.py -v`.
5. Run `ruff check packages/ai-parrot/src/parrot/bots/database/models.py`.
6. Move this file to `sdd/tasks/completed/` and update the
   per-spec index `sdd/tasks/index/database-toolkit-cache-contract.json`.
7. Fill in the Completion Note.

---

## Completion Note

Implemented on branch `feat-178-database-toolkit-cache-contract`.

- Added `Completeness(IntEnum)` with NAME_ONLY=1, WITH_COLUMNS=2, FULL=3.
- Added `MetadataSource = Literal["frontend", "information_schema", "pg_catalog", "unknown"]`.
- Extended `TableMetadata` with `completeness` (default FULL), `loaded_at` (default utcnow), `source` (default "unknown") — keyword-only with defaults, existing call sites unaffected.
- Added `TableMetadata.satisfies(required)` using `>=` comparison.
- Updated `to_yaml_context()` to emit `completeness`, `loaded_at`, and `_warning` for non-FULL entries.
- Pre-existing `E402` lint suppressed with `noqa` (import after module-level regex; not introduced here).
- 11/11 tests pass: `pytest packages/ai-parrot/tests/bots/database/test_models.py -v`.
