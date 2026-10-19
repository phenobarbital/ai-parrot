# TASK-4471: Governance: masking and positive SQL guard (M6c)

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents (`ai-parrot-semantic`)
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4469
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 (masking + guard) + §8 Q4 + AC6/AC7: projected masked columns are rewritten per strategy; the positive guard admits only a single SELECT over allowlisted tables/columns/functions, forbids DDL/DML/`exp.Command`, and injects or clamps LIMIT.

---

## Scope

- Implement `packages/ai-parrot-semantic/src/parrot/semantic/governance/masking.py`: `apply_masks`.
- Implement `packages/ai-parrot-semantic/src/parrot/semantic/governance/guard.py`: `DEFAULT_ALLOWED_FUNCTIONS`, `effective_allowed_functions`, `PositiveGuard.check_and_limit`.
- Write `test_masking.py` and `test_positive_guard.py` (incl. the adversarial matrix across postgres/bigquery/duckdb and the guard half of `test_policy_allowed_functions_additive`).

**NOT in scope**: pipeline ordering (TASK-4472); catalog hiding of hidden members (TASK-4473).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/governance/masking.py` | CREATE | mask rewrites |
| `packages/ai-parrot-semantic/src/parrot/semantic/governance/guard.py` | CREATE | positive guard + default allowlist |
| `packages/ai-parrot-semantic/tests/test_masking.py` | CREATE | strategy tests |
| `packages/ai-parrot-semantic/tests/test_positive_guard.py` | CREATE | guard + adversarial matrix |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (re-verified on `dev` @ 754878f67, 2026-10-19). Use these exact imports, class names and
> method signatures. **DO NOT** invent, guess or assume anything not listed here — verify first.
> `grep` in this repo is aliased to `ugrep` by RTK: use `grep -F` for anchors with `(`, `[`, `{`.

### Verified Imports
```python
from sqlglot import exp                                               # sqlglot 30.23.0
from parrot.semantic.governance.lineage import ColumnUse              # TASK-4469
from parrot.semantic.loader import PhysicalSchema                     # TASK-4467
from parrot.semantic.policy import ModelPolicy, MaskRule              # TASK-4465
from parrot.semantic.models import Limits                             # TASK-4464
from parrot.semantic.errors import SemanticValidationError            # TASK-4464
```

### Existing Signatures to Use
```python
# no core signature used directly; QueryValidator is invoked by the pipeline (TASK-4472)
```

### Column-key convention (added 2026-10-19, TASK-4469 review fix c42dcbcb0)
- `ModelPolicy.usage_allowed(roles, column)` and `ModelPolicy.mask_for(roles, column)` take the **physical**
  `<schema>.<table>.<column>` name (as produced by `governance/lineage.py` `ColumnUse`: `f"{use.table}.{use.column}"`).
  Mask keys (`<table>.<member>`) match as a dotted suffix; usage grants (bare member names) match the last segment.
  Do NOT pass bare names or re-implement key matching at the call site.

### Does NOT Exist
- ~~A positive table/column allowlist in core~~ — `QueryValidator.validate_sql_ast` and `SQLToolkit._check_query_safety` are negative guards.
- ~~`add_row_limit` for LIMIT injection~~ — string-level (base.py:213); the guard works on the AST.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/governance/masking.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/governance/guard.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_masking.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_positive_guard.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Operators (arithmetic/comparison/boolean) are expression nodes, not `exp.Func` — always allowed; check only `exp.Func` subclasses by their SQL name (`func.sql_name()`), plus `exp.Anonymous` by `.name`.
- `hash` strategy = MD5 of the column cast to text (dialect-aware rendering); `partial` = keep last 4 chars, mask the rest; `null` = `CAST(NULL AS <type>)` aliased to the column name.

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
1. Write `guard.py` with the §8 Q4 default set — *why*: fixed by the spec.
2. Write `masking.py` — *why*: AC6 masked projections.
3. Write tests incl. the adversarial matrix (AC18).

### `packages/ai-parrot-semantic/src/parrot/semantic/governance/guard.py` (CREATE)
```python
"""Positive SQL guard: single SELECT, allowlisted tables/columns/functions, forced LIMIT."""
from __future__ import annotations

from sqlglot import exp

from ..errors import SemanticValidationError
from ..loader import PhysicalSchema
from ..models import Limits
from ..policy import ModelPolicy

# §8 Q4 — COUNT DISTINCT is exp.Count(distinct); operators are nodes, always allowed
DEFAULT_ALLOWED_FUNCTIONS: frozenset[str] = frozenset(
    {"SUM", "COUNT", "AVG", "MIN", "MAX", "DATE_TRUNC", "EXTRACT", "COALESCE", "CAST", "LOWER", "UPPER"})


def effective_allowed_functions(policy: ModelPolicy, extra: frozenset[str] | None) -> frozenset[str]:
    """DEFAULT ∪ (extra or ∅) ∪ policy.allowed_functions — additive only (§8 Q4)."""
    return DEFAULT_ALLOWED_FUNCTIONS | (extra or frozenset()) | {f.upper() for f in policy.allowed_functions}


class PositiveGuard:
    def __init__(self, schema: PhysicalSchema, allowed_functions: frozenset[str], limits: Limits) -> None:
        self.schema = schema
        self.allowed_functions = allowed_functions
        self.limits = limits

    def check_and_limit(self, tree: exp.Expression, *, requested_limit: int | None = None) -> exp.Expression:
        """Exactly one exp.Select root (CTEs allowed); every table/column in schema; functions allowlisted;
        no exp.Command/DDL/DML; inject (policy default) or clamp (policy max) LIMIT.

        Raises:
            SemanticValidationError: codes "not_select", "unknown_table", "unknown_column",
                "function_not_allowed", "command_forbidden".
        """
        # FILL IN: root must be exp.Select (exp.Union etc. -> not_select); any exp.Command/Insert/Update/Delete/
        #   Create/Drop/Alter anywhere -> command_forbidden; physical tables (excluding CTE names) in
        #   self.schema.tables; qualified columns in that table's column map; functions by sql_name in the allowset;
        #   limit = min(requested_limit or existing LIMIT or limits.default, limits.max) -> tree.limit(limit, copy=False)
        raise NotImplementedError
```
**Why**: §8 Q4 fixes the default set and the additive rule; `requested_limit` lets the pipeline pass `SemanticQuery.limit` (keyword-only addition, record in Completion Note).

### `packages/ai-parrot-semantic/src/parrot/semantic/governance/masking.py` (CREATE)
```python
"""Rewrite projected masked columns per MaskRule.strategy (null / md5-hash / partial)."""
from __future__ import annotations

from sqlglot import exp

from ..policy import ModelPolicy
from .lineage import ColumnUse


def apply_masks(tree: exp.Expression, uses: list[ColumnUse], policy: ModelPolicy, roles: frozenset[str],
                dialect: str) -> tuple[exp.Expression, tuple[str, ...], set[int]]:
    """Returns (tree, masked column names "table.column", ids of injected trusted nodes)."""
    # FILL IN: for each projection use with policy.mask_for(roles, f"{u.table}.{u.column}") -> rule:
    #   replace the projected expression with the strategy expression aliased to the original output name;
    #   record id() of every injected node — bounded by AC6
    raise NotImplementedError
```

### FILL IN checklist
- [ ] `check_and_limit` — bounded by AC7 and the adversarial matrix (AC18).
- [ ] `apply_masks` strategies — bounded by AC6.

---

## Acceptance Criteria

- [ ] `test_positive_guard`, `test_positive_guard_adversarial_matrix` (3 dialects), `test_masking_strategies` pass (AC6, AC7, AC18).
- [ ] A policy adding `REGEXP_REPLACE` admits it; no policy can remove `SUM` (§8 Q4).

---

## Validation Commands

> File-level pytest only — no directories, no package roots. Run with `PYTHONPATH=packages/ai-parrot-semantic/src:packages/ai-parrot/src` in a worktree.

- `pytest packages/ai-parrot-semantic/tests/test_positive_guard.py -q`
- `pytest packages/ai-parrot-semantic/tests/test_masking.py -q`

---

## Test Specification

```python
# packages/ai-parrot-semantic/tests/test_positive_guard.py
import pytest
import sqlglot
from parrot.semantic.governance.guard import PositiveGuard, DEFAULT_ALLOWED_FUNCTIONS
from parrot.semantic.loader import PhysicalSchema
from parrot.semantic.models import Limits
from parrot.semantic.errors import SemanticValidationError

SCHEMA = PhysicalSchema(driver="duckdb", tables={"sales.orders": {"region": "TEXT", "amount": "DOUBLE"}})


@pytest.mark.parametrize("dialect", ["postgres", "bigquery", "duckdb"])
@pytest.mark.parametrize("sql", ["DELETE FROM sales.orders", "SELECT pg_sleep(10) FROM sales.orders",
                                 "SELECT secret FROM sales.orders", "SELECT 1 FROM other.t"])
def test_positive_guard_adversarial_matrix(dialect, sql):
    guard = PositiveGuard(SCHEMA, DEFAULT_ALLOWED_FUNCTIONS, Limits())
    with pytest.raises(SemanticValidationError):
        guard.check_and_limit(sqlglot.parse_one(sql, dialect=dialect))
    # FILL IN: extend with SELECT *, quoted/mixed-case identifiers, CTEs, nested subqueries, windows, comments, Command


def test_positive_guard():
    # FILL IN: missing LIMIT -> default injected; LIMIT 999999 -> clamped to max
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
7. **Commit** only the listed files: `feat(semantic-layer): TASK-4471 — Governance: masking and positive SQL guard (M6c)`.
8. **Close** with `scripts/sdd/close_task.sh TASK-4471 semantic-layer verified` and fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
