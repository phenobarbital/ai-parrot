# TASK-3245: QuerySource lazy import accessors and toolkit error hierarchy

**Feature**: FEAT-558 — QuerysourceToolkit — tenant-scoped query-slug and MultiQuery tools
**Spec**: `sdd/specs/querysource-toolkit-refactor.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. Every other module imports `querysource` only through this seam so the toolkit imports without
the optional dependency installed and tests can patch one place. Mirrors the `QS = None` + `_get_qs()` pattern of
`parrot/tools/dataset_manager/sources/query_slug.py:20-33`. Also defines the LLM-readable error hierarchy the
tools raise (spec §3 M1 skeleton).

---

## Scope

- Create the package `packages/ai-parrot-tools/src/parrot_tools/querysource/` (empty `__init__.py` for now — TASK-3251 fills the exports).
- Implement `_qs.py` with module-level patchable slots and accessor functions `get_qs`, `get_multiqs`, `get_query_model`, `get_component_registry`, `get_exceptions`, `default_dsn`, `installed_version`.
- Implement `errors.py` with `QuerysourceToolkitError(ToolError)` and its five subclasses.
- Write unit tests.

**NOT in scope**: any tool logic, models, dialect content (TASK-3246/3247), exports in `__init__.py` (TASK-3251).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/querysource/__init__.py` | CREATE | empty module docstring only |
| `packages/ai-parrot-tools/src/parrot_tools/querysource/_qs.py` | CREATE | lazy accessors |
| `packages/ai-parrot-tools/src/parrot_tools/querysource/errors.py` | CREATE | error hierarchy |
| `packages/ai-parrot-tools/tests/querysource/__init__.py` | CREATE | empty |
| `packages/ai-parrot-tools/tests/querysource/test_qs_imports_and_errors.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot._imports import lazy_import   # verified: packages/ai-parrot/src/parrot/_imports.py:110
from parrot.exceptions import ToolError   # verified: packages/ai-parrot/src/parrot/exceptions.py:57  (class ToolError(ParrotError))
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/_imports.py:110
def lazy_import(module_path: str, package_name: str | None = None, extra: str | None = None) -> ModuleType:
    """Imports module_path via importlib; raises ImportError with an install hint when missing."""

# installed querysource 4.5.11 (.venv/lib/python3.12/site-packages/querysource/) — targets of the accessors
class QS(BaseQuery)                       # queries/qs.py:36
class MultiQS(BaseQuery)                  # queries/multi/__init__.py:56
class QueryModel(Model)                   # models.py:48
class ComponentRegistry                   # queries/multi/registry.py:72
# exceptions.py: QueryException:6, SlugNotFound:34, EmptySentence:40, QueryError:44, DataNotFound:48, DriverError:58
asyncpg_url: str                          # conf.py:44
__version__: str                          # version.py  (== "4.5.11")

# pattern to mirror — packages/ai-parrot/src/parrot/tools/dataset_manager/sources/query_slug.py:20-33
QS = None
def _get_qs():
    global QS
    if QS is not None: return QS
    try:
        _qs_mod = lazy_import("querysource.queries.qs", package_name="querysource", extra="db")
        QS = _qs_mod.QS; return QS
    except ImportError: return None
```

### Does NOT Exist
- ~~`parrot_tools.querysource`~~ — does not exist yet; this task creates it.
- ~~`querysource.QS`~~ at package top level — import from `querysource.queries.qs`.
- ~~`querysource.queries.multi.MultiQS` exported from `querysource.queries.multi.multi`~~ — the class lives in `querysource/queries/multi/__init__.py`.
- ~~`querysource.conf.default_dsn` as the catalog DSN~~ — exists (conf.py:32) but the catalog uses `asyncpg_url` (conf.py:44), the DSN `get_query_slug` uses.
- ~~`parrot.exceptions.ToolException`~~ — the class is `ToolError`.

---

## Implementation Notes

### Key Constraints
- Accessors return `None`-free values: raise `ImportError` (from `lazy_import`) when querysource is missing — unlike `query_slug._get_qs`, which swallows it. The toolkit wants the actionable install message.
- Keep the module-level slots (`QS`, `MultiQS`, `QueryModel`, `ComponentRegistry`) — tests monkeypatch them.
- No logging needed here; no I/O.

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/query_slug.py:20-33` — lazy slot pattern
- `packages/ai-parrot-tools/src/parrot_tools/querytoolkit.py:23` — `from parrot.exceptions import ToolError` in a sibling toolkit

---

## Implementation Blueprint

### Steps (in order)
1. Create the package dir with an empty `__init__.py` — *why*: TASK-3251 owns the real exports; an empty module keeps imports of `parrot_tools.querysource._qs` working now.
2. Write `_qs.py` from the block below — *why*: single patch point; `lazy_import` gives the install hint.
3. Write `errors.py` — *why*: tools raise these; `AbstractTool.execute` (abstract.py:872) turns them into error `ToolResult`s.
4. Write the tests, patching `parrot_tools.querysource._qs.lazy_import` and the slots.

### `packages/ai-parrot-tools/src/parrot_tools/querysource/_qs.py` (CREATE)
```python
"""Lazy, patchable access to the optional ``querysource`` dependency (spec §3 M1)."""
from __future__ import annotations

from types import ModuleType
from typing import Any

from parrot._imports import lazy_import  # verified: packages/ai-parrot/src/parrot/_imports.py:110

_PACKAGE = "querysource"
_EXTRA = "db"

# Module-level slots so tests can monkeypatch (pattern: dataset_manager/sources/query_slug.py:20).
QS: Any = None
MultiQS: Any = None
QueryModel: Any = None
ComponentRegistry: Any = None


def _load(module_path: str) -> ModuleType:
    """Import ``module_path`` lazily; ImportError carries the ``pip install querysource`` hint."""
    return lazy_import(module_path, package_name=_PACKAGE, extra=_EXTRA)


def get_qs() -> type:
    """Return ``querysource.queries.qs.QS`` (qs.py:36), caching it in the ``QS`` slot."""
    global QS
    if QS is None:
        QS = _load("querysource.queries.qs").QS
    return QS


def get_multiqs() -> type:
    """Return ``querysource.queries.multi.MultiQS`` (multi/__init__.py:56)."""
    global MultiQS
    if MultiQS is None:
        MultiQS = _load("querysource.queries.multi").MultiQS
    return MultiQS


def get_query_model() -> type:
    """Return ``querysource.models.QueryModel`` (models.py:48)."""
    global QueryModel
    if QueryModel is None:
        QueryModel = _load("querysource.models").QueryModel
    return QueryModel


def get_component_registry() -> type:
    """Return ``querysource.queries.multi.registry.ComponentRegistry`` (registry.py:72)."""
    global ComponentRegistry
    if ComponentRegistry is None:
        ComponentRegistry = _load("querysource.queries.multi.registry").ComponentRegistry
    return ComponentRegistry


def get_exceptions() -> ModuleType:
    """Return the ``querysource.exceptions`` module (SlugNotFound, DataNotFound, QueryException, DriverError)."""
    return _load("querysource.exceptions")


def default_dsn() -> str:
    """Return ``querysource.conf.asyncpg_url`` (conf.py:44) — the DSN ``get_query_slug`` uses for public.queries."""
    return _load("querysource.conf").asyncpg_url


def installed_version() -> str:
    """Return ``querysource.version.__version__`` ("4.5.11" at spec time)."""
    return _load("querysource.version").__version__
```
**Why this shape**: one import seam (spec §7 Patterns); accessors cache into the slots so a test that sets
`_qs.QS = FakeQS` short-circuits `lazy_import`. Do not add `try/except ImportError` — the install hint must propagate.

### `packages/ai-parrot-tools/src/parrot_tools/querysource/errors.py` (CREATE)
```python
"""Error hierarchy for QuerysourceToolkit (spec §3 M1). Messages are written for the LLM."""
from __future__ import annotations

from parrot.exceptions import ToolError  # verified: packages/ai-parrot/src/parrot/exceptions.py:57


class QuerysourceToolkitError(ToolError):
    """Base for all toolkit errors."""


class SlugNotFoundError(QuerysourceToolkitError):
    """The query-slug does not exist in public.queries (wraps querysource.exceptions.SlugNotFound)."""


class TenantDeniedError(QuerysourceToolkitError):
    """The slug's program_slug is outside this toolkit's allowlist.

    Message format: ``slug '<slug>' is not available for programs <programs>``.
    """


class RawSqlForbiddenError(QuerysourceToolkitError):
    """Inline query / raw_query pipeline nodes are not allowed for this instance."""


class WriteDisabledError(QuerysourceToolkitError):
    """save_multiquery or a destination step was requested while allow_write=False."""


class InvalidConditionsError(QuerysourceToolkitError):
    """Placeholder / filter validation failed; the message lists offending keys and the allowed set."""
```
**Why this shape**: fixed names from the spec skeleton — later tasks and tests reference them verbatim.

### FILL IN checklist
- [ ] none — this task is fully mechanical; only the tests need bodies (see Test Specification).

---

## Acceptance Criteria

- [ ] `from parrot_tools.querysource._qs import get_qs, get_multiqs, get_query_model, get_component_registry, get_exceptions, default_dsn, installed_version` works without querysource being imported at module load.
- [ ] `from parrot_tools.querysource.errors import QuerysourceToolkitError, SlugNotFoundError, TenantDeniedError, RawSqlForbiddenError, WriteDisabledError, InvalidConditionsError`; all subclass `parrot.exceptions.ToolError`.
- [ ] With `lazy_import` patched to raise `ImportError("no querysource")`, `get_qs()` raises `ImportError`.
- [ ] Setting `_qs.QS = object()` makes `get_qs()` return it without calling `lazy_import`.
- [ ] `pytest packages/ai-parrot-tools/tests/querysource/test_qs_imports_and_errors.py -v` passes; `ruff check packages/ai-parrot-tools/src/parrot_tools/querysource` clean.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/querysource/test_qs_imports_and_errors.py
import pytest
from parrot.exceptions import ToolError
from parrot_tools.querysource import _qs, errors


@pytest.fixture(autouse=True)
def reset_slots(monkeypatch):
    for name in ("QS", "MultiQS", "QueryModel", "ComponentRegistry"):
        monkeypatch.setattr(_qs, name, None)


def test_slot_short_circuits_lazy_import(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(_qs, "QS", sentinel)
    monkeypatch.setattr(_qs, "lazy_import", lambda *a, **k: pytest.fail("lazy_import must not be called"))
    assert _qs.get_qs() is sentinel


def test_missing_dependency_raises_import_error(monkeypatch):
    def boom(module_path, package_name=None, extra=None):
        raise ImportError(f"{package_name} missing; pip install {package_name}[{extra}]")
    monkeypatch.setattr(_qs, "lazy_import", boom)
    with pytest.raises(ImportError, match="querysource"):
        _qs.get_multiqs()


def test_accessor_caches_into_slot(monkeypatch):
    class FakeMod:  # stands in for querysource.models
        QueryModel = type("QueryModel", (), {})
    calls = []
    monkeypatch.setattr(_qs, "lazy_import", lambda mp, package_name=None, extra=None: calls.append(mp) or FakeMod)
    assert _qs.get_query_model() is FakeMod.QueryModel
    assert _qs.get_query_model() is FakeMod.QueryModel
    assert calls == ["querysource.models"]


@pytest.mark.parametrize("cls", [errors.SlugNotFoundError, errors.TenantDeniedError, errors.RawSqlForbiddenError,
                                 errors.WriteDisabledError, errors.InvalidConditionsError])
def test_error_hierarchy(cls):
    assert issubclass(cls, errors.QuerysourceToolkitError)
    assert issubclass(cls, ToolError)
```

---

## Agent Instructions

1. Read the spec §3 Module 1 and §6.
2. Verify the two imports in the contract still resolve (`grep -n "def lazy_import" packages/ai-parrot/src/parrot/_imports.py`, `grep -n "class ToolError" packages/ai-parrot/src/parrot/exceptions.py`).
3. Update the per-spec index status → `in-progress`.
4. Write the blueprint files verbatim; write tests; run `pytest` + `ruff`.
5. Move this file to `sdd/tasks/completed/`, update index → `done`, fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5), manual fallback implementation
**Date**: 2026-09-17
**Notes**: Implemented verbatim per the spec's Implementation Blueprint. All 5 files created exactly as
listed. `pytest packages/ai-parrot-tools/tests/querysource/test_qs_imports_and_errors.py -v` — 8 passed.
`ruff check packages/ai-parrot-tools/src/parrot_tools/querysource packages/ai-parrot-tools/tests/querysource`
— clean. Implemented manually (not via the `parrot-sdd-coder` MCP orchestrator): the task was classified
`complex` by the FEAT-561 complexity router purely on the `hard_limit_downstream_tasks` metric (8 transitive
descendants), and the deployed roster's `ComplexityPolicy.strong_models` is empty, so no seat is currently
eligible for any `complex`/`unknown` task repo-wide. User explicitly authorized manual implementation for
this task given its bounded, mechanical scope.

**Deviations from spec**: none
