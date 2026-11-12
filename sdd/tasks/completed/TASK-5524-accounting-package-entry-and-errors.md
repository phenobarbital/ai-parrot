# TASK-5524: Accounting package entry, lazy `parrot.semantic` exports and error taxonomy

**Feature**: FEAT-713 — Accounting Metrics Layer
**Spec**: `sdd/specs/accounting-metrics-layer.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (first half) and AC1. `parrot/semantic/__init__.py` imports `SemanticLayerToolkit` eagerly, so any
`parrot.semantic.accounting` import loads the whole governed stack. The owner decided (spec §8 "Independently
importable") that the accounting compile path must import on its own. This task makes the package `__init__` lazy,
creates the `parrot.semantic.accounting` package with its error taxonomy, and the first import-isolation tests.
Every later accounting task imports from this package.

---

## Scope

- Replace the eager imports in `parrot/semantic/__init__.py` with a module `__getattr__`, keeping the four public
  names and `__all__` unchanged.
- Create `parrot/semantic/accounting/__init__.py` that resolves every public name lazily (see Implementation Notes).
- Create `parrot/semantic/accounting/errors.py` with the full hierarchy of spec §3 M2.
- Create `tests/accounting/__init__.py` and `tests/accounting/test_import_isolation.py` with
  `test_semantic_package_exports_unchanged` and `test_accounting_import_is_isolated` (import only).

**NOT in scope**: data models (TASK-5525/5526); the compile-and-check isolation test (TASK-5531 extends the same
file once `compile_metric` exists); `tests/accounting/conftest.py` (TASK-5525).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/__init__.py` | MODIFY | lazy `__getattr__` exports |
| `packages/ai-parrot-semantic/src/parrot/semantic/accounting/__init__.py` | CREATE | lazy public surface |
| `packages/ai-parrot-semantic/src/parrot/semantic/accounting/errors.py` | CREATE | error taxonomy + `Problem` |
| `packages/ai-parrot-semantic/tests/accounting/__init__.py` | CREATE | test package marker |
| `packages/ai-parrot-semantic/tests/accounting/test_import_isolation.py` | CREATE | export + isolation tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.semantic.models import SemanticQuery, SemanticQueryResult   # SL/models.py (imported at SL/__init__.py:4)
from parrot.semantic.toolkit import SemanticLayerToolkit                # SL/toolkit.py:38 (imported at SL/__init__.py:5)
from parrot.semantic.version import __version__                         # SL/__init__.py:3
from pydantic import BaseModel                                          # Pydantic v2
```
`SL` = `packages/ai-parrot-semantic/src/parrot/semantic`.

### Existing Signatures to Use
```python
# SL/__init__.py — whole file today (lines 1-7)
"""Governed semantic queries using the native sqlglot compiler."""

from .version import __version__
from .models import SemanticQuery, SemanticQueryResult
from .toolkit import SemanticLayerToolkit

__all__ = ["__version__", "SemanticQuery", "SemanticQueryResult", "SemanticLayerToolkit"]
```
- `packages/ai-parrot-semantic/tests/conftest.py` puts `packages/ai-parrot-semantic/src` and
  `packages/ai-parrot/src` on `sys.path` and extends `parrot.__path__`; a subprocess must do the same through
  `PYTHONPATH` (absolute paths) — see the test block.
- `pytest.ini:3` sets `asyncio_mode = auto`.

### Does NOT Exist
- ~~`parrot.semantic.accounting`~~ — this task creates it; no `accounting/` directory exists today.
- ~~`AccountingError`, `GrammarError`, `Problem`, …~~ in `parrot.semantic.errors` — the shipped hierarchy is
  `SemanticError` and its subclasses (`SL/errors.py:8-39`); accounting errors are a separate hierarchy and do
  **not** subclass `SemanticError`.
- ~~fixtures in `packages/ai-parrot-semantic/tests/conftest.py`~~ — that file only sets up paths.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-semantic/src/parrot/semantic/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-semantic/src/parrot/semantic/accounting/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-semantic/src/parrot/semantic/accounting/errors.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-semantic/tests/accounting/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-semantic/tests/accounting/test_import_isolation.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py#SemanticLayerToolkit",
    "sym:packages/ai-parrot-semantic/src/parrot/semantic/models.py#SemanticQuery",
    "sym:packages/ai-parrot-semantic/src/parrot/semantic/models.py#SemanticQueryResult"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Decision (this task)**: `accounting/__init__.py` resolves *every* public name of spec §2 "New Public
  Interfaces" through a name → module map in `__getattr__`, instead of importing the compile path eagerly. Do it
  this way because the modules do not exist yet and an eager import would force every later task to edit this
  file; AC1 (no governed-stack import) holds either way. A name whose module is not yet written raises
  `AttributeError` naming the module.
- `errors.py` may import only the standard library and `pydantic` — it is part of the import-isolated compile path.
- Error constructors keep `str(exc)` meaningful and store extra data as attributes.

---

## Implementation Blueprint

### Steps (in order)
1. Edit `SL/__init__.py` — *why*: AC1; importing a sub-package must not import `toolkit.py`.
2. Create `accounting/errors.py` — *why*: grammar (TASK-5527) and validation (TASK-5528) raise these.
3. Create `accounting/__init__.py` with the lazy map — *why*: a stable public surface no later task edits.
4. Write the two tests and run them.

### `packages/ai-parrot-semantic/src/parrot/semantic/__init__.py` (MODIFY)
```python
# REPLACE lines 3-7 — anchor `from .toolkit import SemanticLayerToolkit` (verified: SL/__init__.py:5)
# occurrences: 1 (verified: grep -c 'from .toolkit import SemanticLayerToolkit' SL/__init__.py)
from typing import Any

from .version import __version__

__all__ = ["__version__", "SemanticQuery", "SemanticQueryResult", "SemanticLayerToolkit"]

_LAZY = {
    "SemanticQuery": ".models",
    "SemanticQueryResult": ".models",
    "SemanticLayerToolkit": ".toolkit",
}


def __getattr__(name: str) -> Any:
    """Resolve the public names on first use so sub-packages do not load the toolkit.

    Raises:
        AttributeError: For any name outside ``_LAZY``.
    """
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    value = getattr(importlib.import_module(module, __name__), name)
    globals()[name] = value
    return value
```
**Why**: `globals()[name] = value` caches the attribute so later lookups bypass `__getattr__`.

### `packages/ai-parrot-semantic/src/parrot/semantic/accounting/errors.py` (CREATE)
```python
"""Accounting-layer error taxonomy (FEAT-713 M2). Standard library and pydantic only."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel

ProblemCode = Literal[
    "unassigned_account", "empty_set", "overlap", "dangling_ref", "cycle", "nature_missing",
    "nature_ambiguous", "float_amount", "numeric_type", "column_missing", "interval_gap", "selector_no_match",
]


class AccountingError(Exception):
    """Base of every accounting-layer error."""


class Problem(BaseModel, frozen=True):
    """One load-time validation problem."""

    code: ProblemCode
    message: str
    interval: tuple[date | None, date | None] | None = None
    accounts: tuple[str, ...] = ()


class ModelValidationError(AccountingError):
    """Model failed load-time validation; ``problems`` carries EVERY problem, never only the first."""

    def __init__(self, problems: list[Problem], message: str | None = None) -> None:
        self.problems = list(problems)
        # FILL IN: default message "<N> model validation problem(s): <codes>" — bounded by AC4.
        super().__init__(message or "")


class GrammarError(AccountingError):
    """Expression syntax error at ``position`` (0-based character offset)."""

    def __init__(self, message: str, position: int) -> None:
        self.position = position
        super().__init__(f"{message} at position {position}")


class RequestValidationError(AccountingError):
    """Unknown metric/dimension/filter, cumulative/grain mismatch, bad assertion index."""


class PeriodSpansMembershipChange(RequestValidationError):
    """Requested period or cumulative window crosses a membership boundary."""

    def __init__(self, boundary: date, suggestion: str) -> None:
        self.boundary = boundary
        self.suggestion = suggestion
        super().__init__(f"period crosses a set-membership change on {boundary.isoformat()}; {suggestion}")


class AccountingExecutionError(AccountingError):
    """Runtime failed or the result was truncated; ``audit_id`` is set when the attempt was audited."""

    def __init__(self, message: str, *, audit_id: str | None = None) -> None:
        self.audit_id = audit_id
        super().__init__(message)


class AccountingAuditError(AccountingError):
    """Durable audit append failed under FINANCE_AUDIT_MODE=required."""
```

### `packages/ai-parrot-semantic/src/parrot/semantic/accounting/__init__.py` (CREATE)
```python
"""Accounting metrics layer: chart-of-accounts rollups compiled to deterministic queries (FEAT-713).

Every public name resolves lazily; the compile path (models, grammar, loader, validation, compiler,
evaluation) never imports the governed semantic stack.
"""

from __future__ import annotations

import importlib
from typing import Any

_LAZY: dict[str, str] = {
    # errors (this task)
    "AccountingError": ".errors", "ModelValidationError": ".errors", "GrammarError": ".errors",
    "RequestValidationError": ".errors", "PeriodSpansMembershipChange": ".errors",
    "AccountingExecutionError": ".errors", "AccountingAuditError": ".errors", "Problem": ".errors",
    # compile path (TASK-5525..5531)
    "AccountingModel": ".models", "MetricRequest": ".models", "AssertionRequest": ".models",
    "MetricPlan": ".models", "CompiledMetricQuery": ".models", "Lineage": ".models", "MetricResult": ".models",
    "parse_expr": ".grammar", "load_model": ".loader", "plan_metric": ".compiler",
    "render_plan": ".compiler", "compile_metric": ".compiler", "evaluate_rows": ".evaluation",
    # runtime / governed side (TASK-5533..5537)
    "DuckDBRuntime": ".runtime.duckdb", "DatabaseRuntime": ".runtime.database",
    "AccountingAuditEntry": ".audit", "AccountingToolkit": ".toolkit",
}

__all__ = sorted(_LAZY)


def __getattr__(name: str) -> Any:
    """Import the defining module on first use.

    Raises:
        AttributeError: Unknown name, or its module is not importable yet.
    """
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    try:
        value = getattr(importlib.import_module(module, __name__), name)
    except ModuleNotFoundError as exc:
        raise AttributeError(f"{name!r} lives in {module!r}, which is not available: {exc}") from exc
    globals()[name] = value
    return value
```

### `packages/ai-parrot-semantic/tests/accounting/test_import_isolation.py` (CREATE)
```python
"""FEAT-713 AC1 — the accounting compile path imports without the governed stack."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PACKAGES = Path(__file__).resolve().parents[3]          # .../packages
SOURCE_PATH = os.pathsep.join(str(PACKAGES / name / "src") for name in ("ai-parrot-semantic", "ai-parrot"))
GOVERNED = ("parrot.semantic.toolkit", "parrot.semantic.governance", "parrot.tools.databasequery")


def _run(code: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": SOURCE_PATH}
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=120)


def test_semantic_package_exports_unchanged() -> None:
    from parrot.semantic import SemanticLayerToolkit, SemanticQuery, SemanticQueryResult

    assert SemanticQuery.__name__ == "SemanticQuery"
    assert SemanticQueryResult.__name__ == "SemanticQueryResult"
    assert SemanticLayerToolkit.tool_prefix == "sl"


def test_accounting_import_is_isolated() -> None:
    code = (
        "import sys, parrot.semantic.accounting as a\n"
        "from parrot.semantic.accounting import AccountingError\n"
        f"print([m for m in {GOVERNED!r} if m in sys.modules])\n"
    )
    result = _run(code)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"
```

### FILL IN checklist
- [ ] `ModelValidationError.__init__` default message; bounded by AC4.

---

## Acceptance Criteria

- [ ] `from parrot.semantic import SemanticQuery, SemanticQueryResult, SemanticLayerToolkit` still works (AC1).
- [ ] Importing `parrot.semantic.accounting` in a fresh interpreter loads none of `parrot.semantic.toolkit`,
  `parrot.semantic.governance`, `parrot.tools.databasequery` (AC1, import half).
- [ ] The existing satellite suite still passes: `test_toolkit.py`, `test_packaging.py`.
- [ ] `ruff check` passes on every touched file.

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/accounting/test_import_isolation.py -q`
- `pytest packages/ai-parrot-semantic/tests/test_toolkit.py -q`
- `pytest packages/ai-parrot-semantic/tests/test_packaging.py -q`

---

## Test Specification

The two tests in the blueprint. TASK-5531 later appends `test_import_isolation` (compile a metric in the
subprocess) to the same file.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug accounting-metrics-layer --feature-id FEAT-713`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/accounting-metrics-layer.json`
4. **Verify the Codebase Contract** before writing any code; update it first if anything moved
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a fixed signature or path
7. **Verify** — run the Validation Commands with `PYTHONPATH=<abs>/packages/ai-parrot-semantic/src:<abs>/packages/ai-parrot/src`
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `parrot sdd task close TASK-5524 accounting-metrics-layer verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker / native opus coder (attempt 874a0074992c4e20b72d41719240981b), commit b5bbac527b
**Date**: 2026-11-12
**Notes**: Lazy `parrot.semantic.__getattr__`, `accounting/errors.py` hierarchy, accounting package entry, isolation tests. Tests green.

**Deviations from spec**: none
