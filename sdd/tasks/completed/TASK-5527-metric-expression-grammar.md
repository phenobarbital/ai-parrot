# TASK-5527: Metric expression grammar

**Feature**: FEAT-713 — Accounting Metrics Layer
**Spec**: `sdd/specs/accounting-metrics-layer.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5524
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 and AC6. The LLM never writes arithmetic: metric formulas live in the model YAML in a closed
grammar — `sum(set)`, `+ − × ÷`, unary minus, parentheses, numbers, metric references — and assertions add one
top-level `==`. This task writes the tokenizer and Pratt parser that produce a closed AST.

---

## Scope

- Create `grammar.py` with the AST node dataclasses `Sum`, `Ref`, `Num`, `Neg`, `BinOp`, the `Expr` alias, and
  `parse_expr`, `parse_assertion`, `references`.
- Create `tests/accounting/test_grammar.py` with `test_grammar_accepts_closed_language` and
  `test_grammar_rejects_everything_else`.

**NOT in scope**: cycle/dangling detection (TASK-5528 uses `references`); lowering to `PlanExpr` (TASK-5530).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/accounting/grammar.py` | CREATE | tokenizer + Pratt parser |
| `packages/ai-parrot-semantic/tests/accounting/test_grammar.py` | CREATE | grammar tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.semantic.accounting.errors import GrammarError   # created by TASK-5524; GrammarError(message, position)
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
```

### Does NOT Exist
- ~~a reusable expression parser elsewhere in `parrot.semantic`~~ — `NativeCompiler` parses YAML members, not
  expressions; do not import from `parrot.semantic.engines`.
- ~~`eval` / `ast.parse`~~ — never use Python's evaluator or AST for metric text.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-semantic/src/parrot/semantic/accounting/grammar.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-semantic/tests/accounting/test_grammar.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Grammar: `expr := term (("+"|"-") term)* ; term := factor (("*"|"/") factor)* ;
  factor := "sum" "(" SET ")" | METRIC | NUMBER | "(" expr ")" | "-" factor`.
- Identifiers: `[A-Za-z_][A-Za-z0-9_]*`; `sum` is a keyword only when followed by `(`.
- Numbers: decimal literals (`12`, `0.5`), parsed with `Decimal` — never float.
- Any other character or token (`%`, `if`, quotes, `;`, function calls other than `sum`) ⇒
  `GrammarError(message, position)` with the 0-based offset of the offending token.
- Standard library only (compile-path isolation).

---

## Implementation Blueprint

### Steps (in order)
1. Write the AST dataclasses and the tokenizer — *why*: positions come from tokens.
2. Write the Pratt parser (`_parse_expr(min_bp)`), then `parse_expr` / `parse_assertion` — *why*: one parser for both.
3. Write `references` and the tests.

### `packages/ai-parrot-semantic/src/parrot/semantic/accounting/grammar.py` (CREATE)
```python
"""Closed metric-expression grammar (FEAT-713 M3). Standard library only."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Union

from .errors import GrammarError


@dataclass(frozen=True)
class Sum:
    set_name: str


@dataclass(frozen=True)
class Ref:
    metric: str


@dataclass(frozen=True)
class Num:
    value: Decimal


@dataclass(frozen=True)
class Neg:
    operand: "Expr"


@dataclass(frozen=True)
class BinOp:
    op: Literal["+", "-", "*", "/"]
    left: "Expr"
    right: "Expr"


Expr = Union[Sum, Ref, Num, Neg, BinOp]

_TOKEN = re.compile(r"\s*(?:(?P<num>\d+(?:\.\d+)?)|(?P<name>[A-Za-z_][A-Za-z0-9_]*)|(?P<op>==|[-+*/()]))")


def _tokenize(text: str) -> list[tuple[str, str, int]]:
    """Return (kind, value, position) tokens plus a final ("end", "", len(text)).

    Raises:
        GrammarError: At the first character no token matches.
    """
    # FILL IN: scan with _TOKEN.match(text, pos); skip trailing whitespace; unknown char ⇒ GrammarError.
    raise NotImplementedError


class _Parser:
    def __init__(self, text: str) -> None:
        self.tokens = _tokenize(text)
        self.index = 0

    def expr(self, min_bp: int = 0) -> Expr:
        """Pratt loop: binding power 10 for + -, 20 for * /; unary minus binds tighter than * /."""
        # FILL IN: prefix — num ⇒ Num; name "sum" + "(" name ")" ⇒ Sum; other name ⇒ Ref; "(" expr ")";
        #   "-" factor ⇒ Neg. Infix loop over + - * / while bp > min_bp. Anything else ⇒ GrammarError(position).
        raise NotImplementedError


def parse_expr(text: str) -> Expr:
    """Parse a metric expression; raise GrammarError(position) on any token outside the grammar."""
    parser = _Parser(text)
    result = parser.expr()
    # FILL IN: require the end token; a stray "==" or ")" ⇒ GrammarError at its position.
    return result


def parse_assertion(text: str) -> tuple[Expr, Expr]:
    """Parse ``<expr> == <expr>``; raise GrammarError otherwise."""
    # FILL IN: parse lhs, require exactly one "==", parse rhs, require end.
    raise NotImplementedError


def references(expr: Expr) -> tuple[frozenset[str], frozenset[str]]:
    """Return (set_names, metric_names) referenced by *expr*."""
    # FILL IN: recursive walk.
    raise NotImplementedError
```

### `packages/ai-parrot-semantic/tests/accounting/test_grammar.py` (CREATE)
```python
"""FEAT-713 M3 — closed metric grammar."""

from __future__ import annotations

from decimal import Decimal

import pytest

from parrot.semantic.accounting.errors import GrammarError
from parrot.semantic.accounting.grammar import BinOp, Neg, Num, Ref, Sum, parse_assertion, parse_expr, references


def test_grammar_accepts_closed_language() -> None:
    # FILL IN: every production parses to the expected AST, e.g.
    #   parse_expr("sum(revenue) - sum(cogs)") == BinOp("-", Sum("revenue"), Sum("cogs"));
    #   precedence (a + b * c), parentheses, unary minus, Decimal literals, metric refs, parse_assertion, references.


@pytest.mark.parametrize("text", ["if(a)", "max(revenue)", "'x'", "a % b", "sum(a); drop", "select 1", "a ==", "a == b == c"])
def test_grammar_rejects_everything_else(text: str) -> None:
    # FILL IN: GrammarError with an integer position (use parse_assertion for the == cases).
    ...
```

### FILL IN checklist
- [ ] `_tokenize`, `_Parser.expr`, `parse_expr` end check, `parse_assertion`, `references` — AC6.
- [ ] Test bodies.

---

## Acceptance Criteria

- [ ] The grammar accepts exactly `sum(set)`, `+ − × ÷`, unary minus, parentheses, metric references, numbers,
  and a single top-level `==` in assertions (AC6).
- [ ] Every rejected input raises `GrammarError` with a position (AC6).
- [ ] `grammar.py` imports only the standard library and `.errors`.
- [ ] `ruff check` passes on both files.

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/accounting/test_grammar.py -q`

---

## Test Specification

See blueprint.

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
7. **Verify** — run the Validation Commands with absolute `PYTHONPATH` for both `packages/ai-parrot-semantic/src` and `packages/ai-parrot/src`
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `parrot sdd task close TASK-5527 accounting-metrics-layer verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker / native sonnet coder (attempt 5852d78036444a59a74d5ab9a983b84c), commit 4d8cde61a1
**Date**: 2026-11-12
**Notes**: Closed metric grammar (AST, tokenizer, Pratt parser, parse_expr, parse_assertion, references); 10 tests green, ruff clean.

**Deviations from spec**: none
