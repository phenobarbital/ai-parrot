# Feature Specification: Refactor WorkingMemoryToolkit

**Feature ID**: FEAT-064
**Date**: 2026-03-26
**Author**: Jesus Lara
**Status**: approved
**Target version**: next

---

## 1. Motivation & Business Requirements

### Problem Statement

The `WorkingMemoryToolkit` in `packages/ai-parrot/src/parrot/tools/working_memory/tool.py` was developed as a standalone prototype with stub imports. It is not usable within the ai-parrot framework because:

1. **Stub imports**: `AbstractToolkit` and `tool_schema` are redefined locally as stubs instead of importing from `parrot.tools`.
2. **Module-level logger**: Uses `logger = logging.getLogger(...)` instead of the framework-standard `self.logger` pattern.
3. **Monolithic file**: All enums, Pydantic models, internal classes, and the toolkit itself are in a single 900+ line `tool.py`.
4. **Underscore-prefixed public internals**: Classes like `_CatalogEntry`, `_OperationExecutor`, `_ShapeLimit`, `_WorkingMemoryCatalog` use leading underscores but are referenced across the module and tests — the naming is misleading.
5. **Empty `__init__.py`**: The package does not export anything; consumers cannot `from parrot.tools.working_memory import WorkingMemoryToolkit`.
6. **Empty `models.py` / `internals.py`**: Files exist but are empty — the intended separation was never completed.
7. **Tests co-located**: `tests.py` lives inside the package instead of under a proper `tests/` sub-package.

### Goals
- Make `WorkingMemoryToolkit` a first-class framework toolkit by using real imports from `parrot.tools`.
- Use class-based `self.logger` throughout.
- Split the monolith into `models.py`, `internals.py`, and `tool.py`.
- Remove misleading underscore prefixes from internal classes.
- Populate `__init__.py` with proper exports.
- Move tests into `tests/` sub-package with correct imports.
- All existing tests pass after refactor.

### Non-Goals (explicitly out of scope)
- Adding new DSL operations or features.
- Changing the public API surface (method signatures, return shapes).
- Changing test logic or adding new tests beyond import fixes.
- Integrating with external storage backends (Redis, DB).

---

## 2. Architectural Design

### Overview

Pure structural refactor: split `tool.py` into three modules, fix imports, rename internal classes, and relocate tests. No behavioral changes.

### Component Diagram
```
parrot/tools/working_memory/
├── __init__.py          # Public exports: WorkingMemoryToolkit, models, enums
├── models.py            # Enums (OperationType, JoinHow, AggFunc) + all Pydantic input models
├── internals.py         # CatalogEntry, OperationExecutor, ShapeLimit, WorkingMemoryCatalog
├── tool.py              # WorkingMemoryToolkit (imports from models.py & internals.py)
└── tests/
    ├── __init__.py
    └── test_working_memory.py   # Relocated from tests.py, imports fixed
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.tools.toolkit.AbstractToolkit` | inherits | Replace local stub with real import |
| `parrot.tools.decorators.tool_schema` | uses | Replace local stub with real import |
| `logging` | pattern change | Switch from module-level `logger` to `self.logger` |

### Data Models

No new models. Existing Pydantic models move from `tool.py` to `models.py` unchanged:
- `FilterSpec`, `JoinOnSpec`, `OperationSpecInput`
- `StoreInput`, `DropStoredInput`, `GetStoredInput`, `ListStoredInput`
- `ComputeAndStoreInput`, `MergeStoredInput`, `SummarizeStoredInput`
- `ImportFromToolInput`, `ListToolDataFramesInput`

### New Public Interfaces

No new interfaces. Existing public API preserved:
```python
from parrot.tools.working_memory import WorkingMemoryToolkit
```

---

## 3. Module Breakdown

### Module 1: Models (`models.py`)
- **Path**: `packages/ai-parrot/src/parrot/tools/working_memory/models.py`
- **Responsibility**: All enums (`OperationType`, `JoinHow`, `AggFunc`) and all Pydantic input models (`FilterSpec`, `JoinOnSpec`, `OperationSpecInput`, `StoreInput`, `DropStoredInput`, `GetStoredInput`, `ListStoredInput`, `ComputeAndStoreInput`, `MergeStoredInput`, `SummarizeStoredInput`, `ImportFromToolInput`, `ListToolDataFramesInput`)
- **Depends on**: `pydantic`, `enum` (standard lib only)

### Module 2: Internals (`internals.py`)
- **Path**: `packages/ai-parrot/src/parrot/tools/working_memory/internals.py`
- **Responsibility**: `CatalogEntry` (renamed from `_CatalogEntry`), `OperationExecutor` (renamed from `_OperationExecutor`), `ShapeLimit` (renamed from `_ShapeLimit`), `WorkingMemoryCatalog` (renamed from `_WorkingMemoryCatalog`). These are the data storage and execution engine classes.
- **Depends on**: Module 1 (models), `pandas`, `numpy`, `logging`
- **Logger**: `WorkingMemoryCatalog` should use `self.logger = logging.getLogger(__name__)` in `__init__`.

### Module 3: Toolkit (`tool.py`) — refactor
- **Path**: `packages/ai-parrot/src/parrot/tools/working_memory/tool.py`
- **Responsibility**: `WorkingMemoryToolkit` class only. Imports `AbstractToolkit` from `parrot.tools.toolkit`, `tool_schema` from `parrot.tools.decorators`. Uses `self.logger` (inherited or initialized in `__init__`).
- **Depends on**: Module 1 (models), Module 2 (internals), `parrot.tools.toolkit`, `parrot.tools.decorators`

### Module 4: Package init (`__init__.py`)
- **Path**: `packages/ai-parrot/src/parrot/tools/working_memory/__init__.py`
- **Responsibility**: Re-export `WorkingMemoryToolkit`, key enums (`OperationType`, `JoinHow`, `AggFunc`), and key input models for consumer convenience.
- **Depends on**: Module 1, Module 2, Module 3

### Module 5: Tests relocation (`tests/`)
- **Path**: `packages/ai-parrot/src/parrot/tools/working_memory/tests/`
- **Responsibility**: Move `tests.py` content to `tests/test_working_memory.py`. Fix all imports to use new module paths. Add `tests/__init__.py`.
- **Depends on**: Modules 1-4

---

## 4. Test Specification

### Unit Tests (migrated from existing `tests.py`)

| Test Class | Module | Description |
|---|---|---|
| `TestPydanticValidation` | models | Validates DSL contract rejects malformed inputs |
| `TestAsyncMethods` | tool | Tests async tool methods (list, get, drop, compute ops) |
| `TestErrorHandling` | tool | Missing source, bad column error handling |
| `TestMergeAndSummarize` | tool | Merge with key, concat, summarize workflows |
| `TestImportFromTool` | tool | Bridge import from external tool namespaces |
| `TestFullWorkflow` | tool | End-to-end census/sales analysis session |

### Integration Tests

| Test | Description |
|---|---|
| `test_import_from_parrot_tools` | Verify `from parrot.tools.working_memory import WorkingMemoryToolkit` works |
| `test_toolkit_inherits_abstract` | Verify `issubclass(WorkingMemoryToolkit, AbstractToolkit)` |

### Test Data / Fixtures
Existing fixtures (`census_df`, `sales_df`, `toolkit`) are preserved unchanged.

---

## 5. Acceptance Criteria

- [ ] `from parrot.tools.working_memory import WorkingMemoryToolkit` works
- [ ] `WorkingMemoryToolkit` inherits from the real `AbstractToolkit` (not a stub)
- [ ] `tool_schema` decorator is the real one from `parrot.tools.decorators`
- [ ] No stub classes remain in `tool.py`
- [ ] `self.logger` used throughout (no module-level `logger` variable)
- [ ] `models.py` contains all enums and Pydantic models
- [ ] `internals.py` contains `CatalogEntry`, `OperationExecutor`, `ShapeLimit`, `WorkingMemoryCatalog` (no leading underscores)
- [ ] `tool.py` contains only `WorkingMemoryToolkit`
- [ ] `__init__.py` exports `WorkingMemoryToolkit` and key types
- [ ] Tests live in `tests/test_working_memory.py`
- [ ] All existing tests pass: `pytest packages/ai-parrot/src/parrot/tools/working_memory/tests/ -v`
- [ ] No breaking changes to `WorkingMemoryToolkit` public method signatures
- [ ] Old `tests.py` file is removed

---

## 6. Implementation Notes & Constraints

### Patterns to Follow
- Use `from parrot.tools import AbstractToolkit, tool_schema` (framework convention)
- Class-based logger: `self.logger = logging.getLogger(__name__)` in `__init__`
- Google-style docstrings on all classes (no usage examples, just purpose/description)
- Strict type hints throughout

### Rename Map (underscore removal)

| Old Name | New Name | Location |
|---|---|---|
| `_CatalogEntry` | `CatalogEntry` | `internals.py` |
| `_OperationExecutor` | `OperationExecutor` | `internals.py` |
| `_ShapeLimit` | `ShapeLimit` | `internals.py` |
| `_WorkingMemoryCatalog` | `WorkingMemoryCatalog` | `internals.py` |

### Known Risks / Gotchas
- Tests reference `toolkit._catalog` directly — after renaming, internal attribute names on `WorkingMemoryToolkit` must stay consistent (e.g., `self._catalog` is fine as a private attribute on the toolkit, the rename is for the *class name*).
- `_OperationExecutor._AGG_MAP` is referenced by `summarize_stored` — after rename to `OperationExecutor`, update this reference.
- The `fillna` method uses deprecated `method=` parameter in pandas — this is pre-existing, not in scope to fix.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `pandas` | `>=1.5` | Core data operations |
| `numpy` | `>=1.23` | Numeric computations |
| `pydantic` | `>=2.0` | Input validation models |

---

## 7. Worktree Strategy

- **Isolation**: `per-spec` — all tasks run sequentially in one worktree.
- **Rationale**: Pure refactor within a single package, no cross-feature dependencies. Tasks are tightly coupled (each depends on the prior module being split).
- **Cross-feature dependencies**: None.

---

## 8. Open Questions

- [ ] Should `WorkingMemoryCatalog` log via `self.logger` or accept a logger parameter? — *Owner: Jesus Lara*: log via self.logger.
- [ ] Should the `tests/` sub-package use `conftest.py` for shared fixtures? — *Owner: Jesus Lara*: yes, use conftest.py

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-03-26 | Jesus Lara | Initial draft |
