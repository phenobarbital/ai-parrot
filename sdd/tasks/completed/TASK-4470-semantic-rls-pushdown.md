# TASK-4470: Governance: RLS push-down below aggregation (M6b)

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents (`ai-parrot-semantic`)
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4467, TASK-4469
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 (rls) + AC5 + §7 'Wrapping RLS is wrong for aggregates': RLS predicates rendered by the core `RlsRegistry` are injected as filtered base scans BELOW any aggregation, with values as typed literals; anything the rewrite cannot place deterministically denies.

---

## Scope

- Implement `packages/ai-parrot-semantic/src/parrot/semantic/governance/rls.py`: `RlsPushdown(registry)` with `apply(tree, ctx, driver, schema)`.
- Write `test_rls_pushdown.py` incl. the numeric parity check (SUM over filtered base scan == hand-computed subset).

**NOT in scope**: registering rules (TASK-4477); calling `inject_rls_sql` (forbidden); pipeline ordering (TASK-4472).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/governance/rls.py` | CREATE | RLS push-down |
| `packages/ai-parrot-semantic/tests/test_rls_pushdown.py` | CREATE | push-down + typed literal tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (re-verified on `dev` @ 754878f67, 2026-10-19). Use these exact imports, class names and
> method signatures. **DO NOT** invent, guess or assume anything not listed here — verify first.
> `grep` in this repo is aliased to `ugrep` by RTK: use `grep -F` for anchors with `(`, `[`, `{`.

### Verified Imports
```python
from parrot.auth import PermissionContext, RlsRegistry, RlsRule            # verified: auth/__init__.py lazy map (33, 46, 47)
from parrot.auth.rls_registry import RlsPredicate                         # verified: auth/__init__.py:48, rls_registry.py:70
from parrot.semantic.loader import PhysicalSchema                         # TASK-4467
from parrot.semantic.errors import SemanticAccessError                    # TASK-4464
import sqlglot; from sqlglot import exp                                   # sqlglot 30.23.0
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/rls_registry.py
class RlsPredicate(BaseModel):   # line 70 — table: str; sql_predicate: str; bound_params: dict[str, list[str]]  (lines 82-84)
class RlsRegistry:               # line 87
    def register(self, rule: RlsRule) -> None                          # line 112
    def lookup(self, driver: str, tables: set[str]) -> list[RlsRule]   # line 125
    def render(self, rule: RlsRule, ctx: PermissionContext) -> RlsPredicate   # line 150 — missing attribute → sql_predicate "1=0"
```

### Column-key convention (added 2026-10-19, TASK-4469 review fix c42dcbcb0)
- `ModelPolicy.usage_allowed(roles, column)` and `ModelPolicy.mask_for(roles, column)` take the **physical**
  `<schema>.<table>.<column>` name (as produced by `governance/lineage.py` `ColumnUse`: `f"{use.table}.{use.column}"`).
  Mask keys (`<table>.<member>`) match as a dotted suffix; usage grants (bare member names) match the last segment.
  Do NOT pass bare names or re-implement key matching at the call site.

### Does NOT Exist
- ~~RLS push-down below aggregation in core~~ — `inject_rls_sql` (rls.py:72) only WRAPS the statement; the semantic layer must NOT call it.
- ~~`RlsPredicate.to_sqlglot()`~~ — no such method; parse `sql_predicate` with sqlglot and substitute `bound_params` placeholders (`:p0`) with typed `exp.Literal`s yourself.
- ~~A fall back to wrapping the outer statement~~ — forbidden; unplaceable constructs deny.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/governance/rls.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_rls_pushdown.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/rls_registry.py#RlsRegistry",
    "sym:packages/ai-parrot/src/parrot/auth/rls_registry.py#RlsPredicate"
  ]
}
```

---

## Implementation Notes

- Spec skeleton signature is `apply(tree, ctx, driver)`; this task adds a keyword-only `schema: PhysicalSchema` parameter for literal typing (the schema map is the only type source) — record it in the Completion Note as a deviation.
- Render failure (exception from `registry.render`, or `1=0`) → deny (`1=0` keeps rows empty; an exception → `SemanticAccessError('rls_render_failed')`).
- Returns `(tree, applied_rule_descriptions, trusted_node_ids)`; descriptions never contain values.

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
1. Look up rules for the AST's physical tables — *why*: rules keyed by (driver, schema.table).
2. Render per subject, parse predicate, substitute typed literals — *why*: AC5 values only as typed literals.
3. Replace each base `exp.Table` scan with a filtered subquery keeping its alias — *why*: filter below aggregation.
4. Deny table functions / lateral / unnest / recursive CTEs — *why*: spec §3 M6 rls docstring.
5. Write tests incl. numeric parity on DuckDB.

### `packages/ai-parrot-semantic/src/parrot/semantic/governance/rls.py` (CREATE)
```python
"""RLS push-down: filtered base scans below aggregation, typed literals, fail closed."""
from __future__ import annotations

import logging

import sqlglot
from sqlglot import exp

from parrot.auth import PermissionContext, RlsRegistry

from ..errors import SemanticAccessError
from ..loader import PhysicalSchema


class RlsPushdown:
    def __init__(self, registry: RlsRegistry) -> None:
        self.registry = registry
        self.logger = logging.getLogger(__name__)

    def apply(self, tree: exp.Expression, ctx: PermissionContext, driver: str, *,
              schema: PhysicalSchema) -> tuple[exp.Expression, tuple[str, ...], set[int]]:
        """Wrap every RLS-governed base scan as a filtered subquery BELOW aggregation.

        Returns:
            (tree, applied rule descriptions — never values, ids of injected trusted nodes).
        Raises:
            SemanticAccessError: render failure or a construct the rewrite cannot place deterministically.
        """
        # FILL IN: reject exp.Lateral / exp.Unnest / table-valued functions / recursive CTEs -> "rls_unplaceable";
        #   tables = {f"{t.db}.{t.name}" for t in physical exp.Table nodes}; rules = self.registry.lookup(driver, tables)
        #   for each table node with rules: pred = self.registry.render(rule, ctx) (exception -> "rls_render_failed");
        #   cond = self._predicate_expr(pred, schema, table); replace node with
        #   exp.Subquery(SELECT * FROM <same table> WHERE cond) aliased with the original alias (or table name);
        #   collect id() of every injected node
        raise NotImplementedError

    def _predicate_expr(self, pred, schema: PhysicalSchema, table: str) -> exp.Expression:
        """Parse pred.sql_predicate and replace `:pN` placeholders with typed exp.Literal from bound_params."""
        # FILL IN: literal type from schema.tables[table][column] (number vs string); lists -> exp.Tuple of literals
        raise NotImplementedError
```
**Why**: spec §3 M6 rls skeleton (+ keyword `schema`, see Notes).

### FILL IN checklist
- [ ] `apply` rewrite — bounded by AC5 and the 'never wrap the outer statement' rule.
- [ ] `_predicate_expr` typed literal substitution — bounded by AC5.

---

## Acceptance Criteria

- [ ] `test_rls_pushdown_below_aggregation` and `test_rls_typed_literals_and_render_failure` pass (AC5).
- [ ] No code path calls `inject_rls_sql`.

---

## Validation Commands

> File-level pytest only — no directories, no package roots. Run with `PYTHONPATH=packages/ai-parrot-semantic/src:packages/ai-parrot/src` in a worktree.

- `pytest packages/ai-parrot-semantic/tests/test_rls_pushdown.py -q`

---

## Test Specification

```python
# packages/ai-parrot-semantic/tests/test_rls_pushdown.py
import pytest
from ._models import models_dir, duckdb_warehouse  # noqa: F401
from parrot.semantic.governance.rls import RlsPushdown


async def test_rls_pushdown_below_aggregation(duckdb_warehouse, pctx_factory):
    # FILL IN: registry with RlsRule(driver="duckdb", table="sales.orders",
    #   predicate_template="region IN (:subject.programs)", subject_attribute="programs");
    #   SELECT region, SUM(amount) FROM sales.orders GROUP BY region -> apply -> run on duckdb;
    #   equals SUM computed by hand over the subject's regions
    ...


def test_rls_typed_literals_and_render_failure(pctx_factory):
    # FILL IN: value "o'brien" becomes a quoted literal (no injection); registry.render raising -> SemanticAccessError
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
7. **Commit** only the listed files: `feat(semantic-layer): TASK-4470 — Governance: RLS push-down below aggregation (M6b)`.
8. **Close** with `scripts/sdd/close_task.sh TASK-4470 semantic-layer verified` and fill in the Completion Note.

---

## Completion Note

- Task: TASK-4470
- Feature: semantic-layer
- Closed at (UTC): 2026-10-19
- Fix commits: none
- Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 272.6s · Tokens: n/a
- Validation: merge-tier ad0839b5:wave6:merge completed exit 0 (41 passed); full satellite suite after review fixes 96 passed.
- Fix commits: ce31706da30ab84afef4dd9829d01537aacc2d9c — fix(semantic-layer): TASK-4470 review fixes.
- Review: coder-review:be92db4460f9fbd5c32b7b69. 🔴 CRITICAL fixed: _literal used exp.Literal.number(raw subject value), which renders verbatim → '1 OR 1=1' bypassed RLS on numeric columns. Now parsed int/float (finite) and re-rendered; empty subject values deny instead of 'IN (())'. Regression: test_rls_numeric_literal_rejects_injection.
- Model feedback recorded: coder-feedback:bba49d347820abe112a4be98 (pattern unvalidated-numeric-sql-literal).
