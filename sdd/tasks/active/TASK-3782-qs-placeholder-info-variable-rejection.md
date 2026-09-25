# TASK-3782: PlaceholderInfo.required/accepts_keywords + reject_variable_values + lazy querysource accessors

**Feature**: FEAT-598 — A2UI Linked Surfaces
**Spec**: `sdd/specs/a2ui-linked-surfaces.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 (FEAT-558 toolkit changes) needs three small, dependency-free building blocks before the
toolkit itself changes (TASK-3783 catalog, TASK-3784 tenant plumbing, TASK-3785 the `qs_build_linked_surface` tool):

1. `PlaceholderInfo` gains `required` and `accepts_keywords` (AC6) and `SlugDetail` gains `variables_supported`
   so a linked descriptor's `params` can be built from `qs_describe_slug` (spec §3 M7 skeleton, §7 gotcha
   "JSON-dialect slugs → variables_supported=False (empty params)").
2. `reject_variable_values(conditions)` — the FEAT-558 `@variables` (e.g. `@today`) are deployment-local and
   non-portable, so they are rejected on the linked-surface wire (spec Non-Goals, AC3 "rejects any
   `@`-prefixed value").
3. Lazy accessors in `_qs.py` for the three QuerySource 5.1.1 modules the next tasks need
   (`querysource.queries.describe`, `querysource.tenants`, `Connection.get_definition_repository()`), keeping the
   toolkit's convention that `querysource` is imported only through `_qs` (spec §7 "lazy `_qs` accessors").

---

## Scope

- Add `required: bool = False` and `accepts_keywords: bool = False` to `PlaceholderInfo`.
- Add `variables_supported: bool = True` to `SlugDetail`.
- Add `reject_variable_values(conditions: Mapping[str, Any]) -> None` to `dialect.py`, directly after
  `check_version_compatibility`.
- Add `get_describe()`, `get_tenants()` and `async get_definition_repository()` accessors to `_qs.py`.
- Write unit tests for all of the above.

**NOT in scope**:
- Changing `describe_slug` to use `build_variables` (that is TASK-3784).
- Any `SlugCatalog` change (TASK-3783).
- Changing `check_version_compatibility` or `DIALECT_VERIFIED_AGAINST` (spec M7 NOTE: "enforces the floor as
  before"; floor bump in `pyproject.toml` is TASK-3772).
- A runtime tenant-MultiQuery gate — `supports_tenant_multiquery` / `TenantMultiQueryUnsupportedError` are NEVER
  built (AC5).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/querysource/models.py` | MODIFY | `PlaceholderInfo.required/accepts_keywords`; `SlugDetail.variables_supported` |
| `packages/ai-parrot-tools/src/parrot_tools/querysource/dialect.py` | MODIFY | `reject_variable_values` |
| `packages/ai-parrot-tools/src/parrot_tools/querysource/_qs.py` | MODIFY | `get_describe`, `get_tenants`, `get_definition_repository` lazy accessors |
| `packages/ai-parrot-tools/tests/querysource/test_linked_dialect_models.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.querysource import _qs                                   # _qs.py (module; _load L20, lazy slots L15-18)
from parrot_tools.querysource.errors import InvalidConditionsError         # errors.py:31
from parrot_tools.querysource.models import PlaceholderInfo, SlugDetail    # models.py:24, :32
from parrot_tools.querysource.dialect import reject_variable_values        # NEW in this task
# querysource 5.1.1 (/home/jesuslara/proyectos/querysource, tag 5.1.1) — ONLY through _qs._load:
#   querysource.queries.describe   -> build_variables L108, KEYWORD_TYPES L29, IMPLICIT_DEFAULTS L31, DescribeVariable L41
#   querysource.tenants            -> QueryIdentity L46, LoadedDefinition L54, TenantRegistry.resolve L402, TenantError (re-export)
#   querysource.interfaces.connections -> class Connection L46; async Connection.get_definition_repository() L439-454
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/querysource/models.py:24-29
class PlaceholderInfo(BaseModel):
    """A declared placeholder: name, cond_definition type, stored default."""
    name: str
    type: str | None = None
    default: Any = None

# models.py:32-45
class SlugDetail(SlugSummary):
    placeholders_detail: list[PlaceholderInfo] = Field(default_factory=list)
    ...
    rendered_query: str | None = None  # L44 (last field)

# packages/ai-parrot-tools/src/parrot_tools/querysource/dialect.py:195-204
def check_version_compatibility(installed: str) -> str | None: ...

# packages/ai-parrot-tools/src/parrot_tools/querysource/_qs.py
def _load(module_path: str) -> ModuleType:  # L20 — lazy_import with the `db` extra hint
def get_exceptions() -> ModuleType:          # L57 (module-returning accessor precedent)
def installed_version() -> str:              # L67 (last function in the file)

# querysource/interfaces/connections.py:439-454 (5.1.1)
class Connection:                            # L46; __init__(self, loop=None, **kwargs) never creates a loop
    async def get_definition_repository(self) -> "DefinitionRepository":
        # qs = QuerySource(); registry = await qs.initialize_tenants(); return DefinitionRepository(registry=…,
        #   connection_factory=qs.connection.definition_connection) — construction is stateless, no I/O
```

### Does NOT Exist
- ~~`PlaceholderInfo.required`, `PlaceholderInfo.accepts_keywords`, `SlugDetail.variables_supported`~~ — net-new here.
- ~~`reject_variable_values`~~ — net-new here.
- ~~`_qs.get_describe`, `_qs.get_tenants`, `_qs.get_definition_repository`~~ — net-new here.
- ~~`supports_tenant_multiquery`, `TenantMultiQueryUnsupportedError`, `TENANT_MULTIQUERY_UNSUPPORTED`~~ — NEVER built (AC5).
- ~~`QuerySource().get_definition_repository()`~~ — the accessor is a method of `querysource.interfaces.connections.Connection`
  (which internally uses the `QuerySource()` singleton); do not call it on `QuerySource`.
- ~~`ExecutionResult.dtypes`~~ — not added by this task (and not needed).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/querysource/models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/src/parrot_tools/querysource/dialect.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/src/parrot_tools/querysource/_qs.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/tests/querysource/test_linked_dialect_models.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/models.py#PlaceholderInfo",
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/models.py#SlugDetail",
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/dialect.py#check_version_compatibility",
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/_qs.py#_load",
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/errors.py#InvalidConditionsError"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- New model fields have defaults so every existing `PlaceholderInfo(...)` / `SlugDetail(...)` construction and
  `tests/querysource/test_models.py` keep passing unchanged.
- `reject_variable_values` walks nested values: a scalar string starting with `@` anywhere inside `conditions`
  (including inside `filter` dicts, `[op, value]` lists and IN lists) is rejected. Message lists every offending
  key path so the LLM can fix it in one retry (errors.py convention: "Messages are written for the LLM").
- `_qs` accessors never import `querysource` at module import time (same `_load` lazy pattern as `get_exceptions`).

### References in Codebase
- `_qs.get_exceptions()` (`_qs.py:57`) — module-returning accessor to copy.
- `dialect.validate_filter` (`dialect.py:134`) — walk/collect-then-raise style.

---

## Implementation Blueprint

### Steps (in order)
1. Add the two `PlaceholderInfo` fields and `SlugDetail.variables_supported` — *why*: TASK-3784 fills them from
   `build_variables`, TASK-3785 derives `params` from them (AC6).
2. Add `reject_variable_values` after `check_version_compatibility` — *why*: spec M7 skeleton fixes its location
   and contract; TASK-3785 calls it before any execution (AC3).
3. Add the three `_qs` accessors after `installed_version` — *why*: TASK-3783/TASK-3784 must reach QuerySource 5.1.1 APIs
   without a module-level import (toolkit convention, spec §7).
4. Write the tests.

### `packages/ai-parrot-tools/src/parrot_tools/querysource/models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'class PlaceholderInfo(BaseModel):' packages/ai-parrot-tools/src/parrot_tools/querysource/models.py)
# REPLACE the body of `class PlaceholderInfo(BaseModel):` (verified: models.py:24-29) with:
class PlaceholderInfo(BaseModel):
    """A declared placeholder: name, cond_definition type, stored default, and describe semantics.

    ``required`` / ``accepts_keywords`` mirror ``querysource.queries.describe.build_variables`` exactly
    (describe.py:154 and :163 — FEAT-598 AC6).
    """

    name: str
    type: str | None = None
    default: Any = None
    required: bool = False
    accepts_keywords: bool = False


# occurrences: 1 (verified: grep -c '    rendered_query: str | None = None  # QS.dry_run() output when dry_run=True' models.py)
# AFTER — insert below that line (verified: models.py:44), inside SlugDetail:
    variables_supported: bool = True  # False for JSON-dialect slugs (describe.py:116-118) — linked params stay empty
```
**Why this shape**: defaults keep FEAT-558 callers byte-compatible; the field names are fixed by the spec skeleton.

### `packages/ai-parrot-tools/src/parrot_tools/querysource/dialect.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def check_version_compatibility(' packages/ai-parrot-tools/src/parrot_tools/querysource/dialect.py)
# AFTER — insert below the end of `check_version_compatibility` (its `return None`, verified: dialect.py:204),
# before `def load_variables()` (dialect.py:207). Add `from collections.abc import Mapping` to the imports.


def reject_variable_values(conditions: Mapping[str, Any]) -> None:
    """Raise InvalidConditionsError when any scalar value in ``conditions`` starts with '@'.

    FEAT-558 deployment variables (``@today`` …) are resolved by the deploying app and are not portable on the
    linked-surface wire (FEAT-598 spec Non-Goals, AC3). Relative dates must use the closed UDF keyword
    vocabulary instead (TODAY, YESTERDAY, FDOM, LDOM, CURRENT_YEAR, CURRENT_MONTH, LAST_YEAR).
    """
    offending: list[str] = []

    def _walk(value: Any, path: str) -> None:
        # FILL IN: recurse into Mapping (path "<path>.<key>") and list/tuple (path "<path>[<i>]"); append `path`
        # when a str value startswith("@") — bounded by AC3 (every '@' scalar rejected, nested filter included)
        raise NotImplementedError

    for key, value in conditions.items():
        _walk(value, str(key))
    if offending:
        raise InvalidConditionsError(
            f"'@' variables are not allowed in linked surfaces: {offending}. "
            "Use a UDF keyword (TODAY, YESTERDAY, FDOM, LDOM, CURRENT_YEAR, CURRENT_MONTH, LAST_YEAR) or a literal."
        )
```
**Why**: location and name fixed by spec M7; collect-then-raise gives the LLM every offender at once.

### `packages/ai-parrot-tools/src/parrot_tools/querysource/_qs.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def installed_version() -> str:' packages/ai-parrot-tools/src/parrot_tools/querysource/_qs.py)
# AFTER — append below `installed_version` (verified: _qs.py:67-69, end of file)


def get_describe() -> ModuleType:
    """Return ``querysource.queries.describe`` (build_variables L108, KEYWORD_TYPES L29, IMPLICIT_DEFAULTS L31)."""
    return _load("querysource.queries.describe")


def get_tenants() -> ModuleType:
    """Return ``querysource.tenants`` (QueryIdentity L46, LoadedDefinition L54, TenantError re-export)."""
    return _load("querysource.tenants")


async def get_definition_repository() -> Any:
    """Return a loop-local ``DefinitionRepository`` (querysource/interfaces/connections.py:439-454).

    Connection ownership stays inside querysource: ``Connection().get_definition_repository()`` builds the
    repository over the ``QuerySource()`` singleton's tenant registry and definition connection factory.
    Tests monkeypatch this function.
    """
    connection_cls = _load("querysource.interfaces.connections").Connection
    return await connection_cls().get_definition_repository()
```
**Why**: one lazy seam per external module, patchable by TASK-3783/TASK-3784 tests exactly like `_qs.QS`.

### `packages/ai-parrot-tools/tests/querysource/test_linked_dialect_models.py` (CREATE)
```python
"""FEAT-598 TASK-3782 — PlaceholderInfo/SlugDetail additions, reject_variable_values, _qs accessors."""

from __future__ import annotations

import pytest

from parrot_tools.querysource import _qs
from parrot_tools.querysource.dialect import reject_variable_values
from parrot_tools.querysource.errors import InvalidConditionsError
from parrot_tools.querysource.models import PlaceholderInfo, SlugDetail


def test_placeholder_info_defaults_backward_compatible():
    info = PlaceholderInfo(name="firstdate", type="date")
    assert info.required is False and info.accepts_keywords is False


def test_slug_detail_variables_supported_default():
    # FILL IN: build a minimal SlugDetail (slug, program_slug, provider, is_multiquery, is_cached, cache_timeout)
    # and assert variables_supported is True — bounded by backward compatibility
    raise NotImplementedError


def test_reject_variable_values():
    with pytest.raises(InvalidConditionsError, match="firstdate"):
        reject_variable_values({"firstdate": "@today"})


def test_reject_variable_values_nested_filter():
    # FILL IN: '@x' inside filter dict and inside an IN list both reported in ONE error — bounded by AC3
    raise NotImplementedError


def test_reject_variable_values_accepts_keywords_and_literals():
    reject_variable_values({"firstdate": "YESTERDAY", "lastdate": "TODAY", "store": [1, 2], "filter": {"a": "x"}})


def test_qs_accessors_are_lazy(monkeypatch):
    # FILL IN: monkeypatch _qs._load to record module paths; assert get_describe/get_tenants request
    # 'querysource.queries.describe' / 'querysource.tenants' — bounded by the lazy-import convention
    raise NotImplementedError
```

### FILL IN checklist
- [ ] `dialect.py::reject_variable_values._walk` — recursion over Mapping/list/tuple; bounded by AC3.
- [ ] `test_slug_detail_variables_supported_default` body.
- [ ] `test_reject_variable_values_nested_filter` body.
- [ ] `test_qs_accessors_are_lazy` body (incl. an async test that `get_definition_repository` awaits
      `Connection().get_definition_repository()` via a patched `_load`).

---

## Acceptance Criteria

- [ ] `PlaceholderInfo(name=…)` still validates with only `name`; new fields default to `False`.
- [ ] `reject_variable_values({"firstdate": "@today"})` raises `InvalidConditionsError` (spec test `test_reject_variable_values`).
- [ ] UDF keywords and plain literals pass untouched.
- [ ] No module-level `import querysource` anywhere in the toolkit package.
- [ ] Existing `packages/ai-parrot-tools/tests/querysource/test_models.py` and `test_dialect.py` still pass.
- [ ] `ruff check` and `black --check` clean on the modified files.

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/querysource/test_linked_dialect_models.py -q`
- `pytest packages/ai-parrot-tools/tests/querysource/test_models.py -q`
- `pytest packages/ai-parrot-tools/tests/querysource/test_dialect.py -q`

---

## Test Specification

See the CREATE block above — the scaffold is the minimum; add cases as needed.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in the per-spec index → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
