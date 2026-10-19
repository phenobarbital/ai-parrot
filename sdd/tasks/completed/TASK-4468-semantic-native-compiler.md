# TASK-4468: Native fallback compiler (M5)

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents (`ai-parrot-semantic`)
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4467
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 + Non-Goals: compile the v1 subset (simple aggregations, dimensions, DATE_TRUNC grains, declared one-to-many joins, filter tree, order/limit/offset) directly to a sqlglot AST, with row-for-row parity against sidemantic on DuckDB (AC11).

---

## Scope

- Implement `packages/ai-parrot-semantic/src/parrot/semantic/engines/native.py`: `NATIVE_AGGREGATIONS`, `NativeCompiler` (`compile`, `_grain_expr`).
- Many-to-many (fan-out) joins and non-subset metric types → `SemanticValidationError`.
- Write `test_native_compiler.py` (subset + parity + postgres/bigquery snapshots for the native engine).

**NOT in scope**: symmetric aggregates, cumulative/time-comparison metrics (spec Non-Goals); editing `engines/__init__.py` (its lazy import already targets this module).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/engines/native.py` | CREATE | native sqlglot compiler |
| `packages/ai-parrot-semantic/tests/test_native_compiler.py` | CREATE | subset + parity tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (re-verified on `dev` @ 754878f67, 2026-10-19). Use these exact imports, class names and
> method signatures. **DO NOT** invent, guess or assume anything not listed here — verify first.
> `grep` in this repo is aliased to `ugrep` by RTK: use `grep -F` for anchors with `(`, `[`, `{`.

### Verified Imports
```python
from sqlglot import exp                                              # sqlglot 30.23.0
from parrot.semantic.loader import LoadedModel                      # TASK-4467
from parrot.semantic.models import SemanticQuery, CompiledQuery, Grain   # TASK-4464
from parrot.semantic.errors import SemanticValidationError          # TASK-4464
```

### Existing Signatures to Use
```python
# TASK-4467 — parrot/semantic/engines/__init__.py calls: NativeCompiler(model).compile(query, dialect) under asyncio.to_thread
# TASK-4467 — LoadedModel.layer holds the sidemantic model objects; read metric/dimension DEFINITIONS only (no compile)
```

### Does NOT Exist
- ~~`exp.DateTrunc(this=..., unit='month')` accepting a bare str in every dialect~~ — pass `unit=exp.Var(this=grain.upper())` and check rendering per dialect in tests.
- ~~A relationship cardinality API in core~~ — cardinalities come from the sidemantic model objects (names confirmed in TASK-4467's Completion Note).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/engines/native.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_native_compiler.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Read TASK-4467's Completion Note for the confirmed sidemantic model-object attribute names before starting.
- WHERE gets dimension leaves; HAVING gets metric leaves (M2 already rejects mixed groups).

### Key Constraints
- Async-first; sync CPU-only work (sqlglot, sidemantic compile) runs under `asyncio.to_thread` at the call site.
- Pydantic v2 models; `logging.getLogger(__name__)` / `self.logger`, never `print`.
- Google-style docstrings, strict type hints, 120-column lines; `ruff check` clean (TID251 bans apply).
- Fail closed wherever governance is involved (spec §7 "Patterns to Follow").
- Worktree testing: prefix pytest with `PYTHONPATH=packages/ai-parrot-semantic/src:packages/ai-parrot/src` (add `:packages/ai-parrot-server/src` for server tests); never `uv sync` inside a worktree.

---

## Implementation Blueprint

> **Executor-ready starting point.** Write each block to its declared path nearly verbatim,
> then complete every `# FILL IN:` marker. Never change a signature, class name or path the
> blueprint fixes (they come from the spec §3 Interface Skeletons).

### Steps (in order)
1. Read the spike notes — *why*: metric/relationship definitions come from sidemantic objects.
2. Build the select: projections, joins, group by, where/having, order, limit/offset — *why*: AC11 subset.
3. Reject fan-out — *why*: only sidemantic handles many-to-many in v1.
4. Write parity tests against `engines.compile` with `engine: sidemantic` on DuckDB.

### `packages/ai-parrot-semantic/src/parrot/semantic/engines/native.py` (CREATE)
```python
"""Native fallback compiler: v1 subset straight to a sqlglot AST (spec §3 Module 5)."""
from __future__ import annotations

import logging

from sqlglot import exp

from ..errors import SemanticValidationError
from ..loader import LoadedModel
from ..models import CompiledQuery, Grain, SemanticQuery

NATIVE_AGGREGATIONS = ("sum", "count", "count_distinct", "avg", "min", "max")


class NativeCompiler:
    """Compile a SemanticQuery against one LoadedModel without sidemantic's compiler."""

    def __init__(self, model: LoadedModel) -> None:
        self.model = model
        self.logger = logging.getLogger(__name__)

    def compile(self, query: SemanticQuery, dialect: str) -> CompiledQuery:
        """Build exp.Select; raise SemanticValidationError for unsupported metrics or many-to-many joins."""
        # FILL IN: validate_against(member kinds); aggregation map (count_distinct -> exp.Count(distinct)),
        #   dimensions + _grain_expr for time dimensions, joins only along declared one-to-many paths
        #   (anything else -> SemanticValidationError("fan_out")), WHERE (dimension leaves) / HAVING (metric
        #   leaves) with typed literals, GROUP BY, ORDER BY, LIMIT/OFFSET; render .sql(dialect=dialect)
        raise NotImplementedError

    def _grain_expr(self, column: exp.Column, grain: Grain) -> exp.Expression:
        """exp.DateTrunc(unit=grain)."""
        return exp.DateTrunc(this=column, unit=exp.Var(this=grain.upper()))
```

### FILL IN checklist
- [ ] `NativeCompiler.compile` — bounded by the v1 subset (spec §2 Non-Goals) and AC11.

---

## Acceptance Criteria

- [ ] `test_native_compiler_subset` and `test_native_vs_sidemantic_parity` pass (AC11).
- [ ] Many-to-many on a native model raises `SemanticValidationError` (AC11).
- [ ] Native postgres/bigquery snapshots added and passing (AC18).

---

## Validation Commands

> File-level pytest only — no directories, no package roots. Run with `PYTHONPATH=packages/ai-parrot-semantic/src:packages/ai-parrot/src` in a worktree.

- `pytest packages/ai-parrot-semantic/tests/test_native_compiler.py -q`

---

## Test Specification

```python
# packages/ai-parrot-semantic/tests/test_native_compiler.py
import pytest
from ._models import models_dir, loaded_models, duckdb_warehouse  # noqa: F401
from parrot.semantic.engines.native import NativeCompiler
from parrot.semantic.models import SemanticQuery


def test_native_compiler_subset(loaded_models):
    cq = NativeCompiler(loaded_models["orders"]).compile(
        SemanticQuery(model="orders", metrics=["revenue"], dimensions=["region"]), "duckdb")
    assert "GROUP BY" in cq.sql.upper()
    # FILL IN: grains, 1:N join, many-to-many -> SemanticValidationError


async def test_native_vs_sidemantic_parity(loaded_models, duckdb_warehouse):
    # FILL IN: compile with both engines, execute both on duckdb_warehouse (duckdb.connect), compare sorted rows
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug semantic-layer --feature-id FEAT-704 --spec sdd/specs/semantic-layer.spec.md --index sdd/tasks/index/semantic-layer.json`).
2. **Read the spec** (`sdd/specs/semantic-layer.spec.md`), especially the sections named in Context.
3. **Check dependencies** — every `Depends-on` task is `done` in `sdd/tasks/index/semantic-layer.json`.
4. **Verify the Codebase Contract** before writing code; fix a stale entry in this file first.
5. **Implement** exactly the files above, following the blueprint; touch nothing else.
6. **Validate**: `ruff check --fix <files>`, then the Validation Commands.
7. **Commit** only the listed files: `feat(semantic-layer): TASK-4468 — Native fallback compiler (M5)`.
8. **Close** with `scripts/sdd/close_task.sh TASK-4468 semantic-layer verified` and fill in the Completion Note.

---

## Completion Note

- Task: TASK-4468
- Feature: semantic-layer
- Closed at (UTC): 2026-10-19
- Fix commits: none
- Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 425.4s · Tokens: n/a
- Validation: merge-tier ad0839b5:wave5:merge completed exit 0 (24 passed); full satellite suite after review fix 53 passed.
- Review: coder-review:22109f3b84b65e47c380652e — no corrections.
