# TASK-3841: JSONB operators in the QuerysourceToolkit dialect

**Feature**: FEAT-610 — A2UI Linked Surfaces E2E example
**Spec**: `sdd/specs/a2ui-linked-e2e-test.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (FEAT-610). `validate_filter` rejects the JSONB `@>` operator
(`InvalidConditionsError: unknown dict operator '@>'`, verified live), which two dashboard KPIs need.
querysource ≥5.1 supports `@>`, `<@`, `@>|`, `->`, `->>` (`querysource/parsers/pgsql.pyx:29`).

---

## Scope

- Add `JSONB_OPERATORS: tuple[str, ...] = ("@>", "<@", "@>|", "->", "->>")` below `DICT_OPERATORS`.
- `validate_filter`: in the `{op: v}` branch accept `op in JSONB_OPERATORS` with any operand (dict, list, scalar,
  JSON text); keep `DICT_OPERATORS` for scalar operands; an unknown operator is still rejected.
- Bump `DIALECT_VERIFIED_AGAINST` to `"5.1.2"`.
- `DialectReference` gains `operators_jsonb: list[str] = Field(default_factory=list)`; the module-level reference
  instance fills it with `list(JSONB_OPERATORS)` and adds one `where_grammar` line for the JSONB form.
- Update the two pinned `"4.5.11"` asserts (`test_toolkit_core.py:79`, `test_models.py:40`).
- New `test_dialect_jsonb.py`.

**NOT in scope**: the dashboard tool (TASK-3847), docs (TASK-3853), the pyproject floor (TASK-3842).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/querysource/dialect.py` | MODIFY | JSONB_OPERATORS, validate_filter branch, version, reference |
| `packages/ai-parrot-tools/src/parrot_tools/querysource/models.py` | MODIFY | DialectReference.operators_jsonb |
| `packages/ai-parrot-tools/tests/querysource/test_dialect_jsonb.py` | CREATE | JSONB unit tests |
| `packages/ai-parrot-tools/tests/querysource/test_toolkit_core.py` | MODIFY | version assert :79 → 5.1.2 |
| `packages/ai-parrot-tools/tests/querysource/test_models.py` | MODIFY | verified_against :40 → 5.1.2 (+ operators_jsonb if required) |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `f20d82332` (dev, 2026-09-29). Re-check line numbers before editing — earlier tasks in this
> feature may have shifted them.

### Verified Imports
```python
from parrot_tools.querysource.dialect import validate_filter, DICT_OPERATORS, DIALECT_VERIFIED_AGAINST  # dialect.py:135,49,20
from parrot_tools.querysource.errors import InvalidConditionsError     # test_build_linked_surface_tool.py:12
from parrot_tools.querysource.models import DialectReference           # models.py:127
```
### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/querysource/dialect.py
DIALECT_VERIFIED_AGAINST: str = "4.5.11"                                        # line 20
DICT_OPERATORS: tuple[str, ...] = (">=", "<=", "<>", "!=", "<", ">")  # sql.pyx:25   # line 49
    operators_dict_form=list(DICT_OPERATORS),                                   # line 95 (module-level DialectReference(...))
def validate_filter(filter: dict[str, FilterValue], *, strict: bool = True) -> list[str]:  # line 135
                if op not in DICT_OPERATORS:                                    # line 148
                    reason = f"unknown dict operator {op!r}"                  # line 149
# packages/ai-parrot-tools/src/parrot_tools/querysource/models.py
class DialectReference(BaseModel):                                              # line 127
    operators_dict_form: list[str]                                              # line 134
    variables: dict[str, str] = Field(default_factory=dict)                     # line 136
```
### Does NOT Exist
- ~~`JSONB_OPERATORS`~~ / ~~`DialectReference.operators_jsonb`~~ — created here.
- ~~JSONB support in `validate_filter`~~ — rejected today.
- ~~A runtime querysource version gate in the toolkit~~ — FEAT-598 AC12 keeps it out; do not add one.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/querysource/dialect.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/querysource/models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/tests/querysource/test_dialect_jsonb.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/tests/querysource/test_toolkit_core.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/tests/querysource/test_models.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/dialect.py#validate_filter",
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/models.py#DialectReference"
  ]
}
```

---

## Implementation Notes

- Parallelism: no dependency; first writer of querysource/models.py (DialectReference) and test_toolkit_core.py (version assert) — TASK-3846/3847 serialize after it.
- Production data: any live query uses `ENV=prod`, read-only. Never commit tokens, passwords or DSNs.
- Worktree tests: prefix with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-visualizations/src:packages/ai-parrot-server/src`
  as needed; never `uv sync` inside a worktree.

---

## Implementation Blueprint

**Steps (in order)**
1. `dialect.py`: bump the version string — because the operators are verified against querysource 5.1.2.
2. Add `JSONB_OPERATORS` right below `DICT_OPERATORS` — so the reference and the validator share one tuple.
3. Change the `{op: v}` branch — JSONB operands are dicts/lists, so they must bypass the scalar-only rule.
4. Fill `operators_jsonb` in the module-level reference; add the field to `DialectReference`.
5. Update both `"4.5.11"` test asserts; write `test_dialect_jsonb.py`; run the validation commands.

```python
# packages/ai-parrot-tools/src/parrot_tools/querysource/dialect.py — MODIFY line 20
# occurrences: 1 (verified: grep -c 'DIALECT_VERIFIED_AGAINST: str = "4.5.11"' dialect.py)
DIALECT_VERIFIED_AGAINST: str = "5.1.2"
```
```python
# packages/ai-parrot-tools/src/parrot_tools/querysource/dialect.py — AFTER — insert below `DICT_OPERATORS: tuple[str, ...] = (">=", "<=", "<>", "!=", "<", ">")  # sql.pyx:25` (verified: dialect.py:49)
# occurrences: 1
JSONB_OPERATORS: tuple[str, ...] = ("@>", "<@", "@>|", "->", "->>")  # querysource/parsers/pgsql.pyx:29 (>=5.1)
```
```python
# packages/ai-parrot-tools/src/parrot_tools/querysource/dialect.py — AFTER — insert below `    operators_dict_form=list(DICT_OPERATORS),` (verified: dialect.py:95)
# occurrences: 1
    operators_jsonb=list(JSONB_OPERATORS),
# FILL IN: append one `where_grammar` line such as
#   "col: {'@>': [{'course': 'X'}]} → col @> '[...]'::jsonb  (single key from operators_jsonb; operand may be dict/list)"
#   — bounded by: keep the existing list order, add at the end of the `where_grammar=[...]` list.
```
```python
# packages/ai-parrot-tools/src/parrot_tools/querysource/dialect.py — MODIFY line 148 (occurrences: 1)
                if op in JSONB_OPERATORS:
                    pass  # JSONB form: operand may be dict / list / scalar / JSON text (querysource >= 5.1)
                elif op not in DICT_OPERATORS:
                    reason = f"unknown dict operator {op!r}"
```
**Why**: the old branch made `@>` an unknown operator; JSONB operands are structured, so no scalar check applies.

```python
# packages/ai-parrot-tools/src/parrot_tools/querysource/models.py — AFTER — insert below `    operators_dict_form: list[str]` (verified: models.py:134)
# occurrences: 1 (verified: grep -c '    operators_dict_form: list\[str\]' models.py)
    operators_jsonb: list[str] = Field(default_factory=list)  # querysource >= 5.1 JSONB operators (FEAT-610)
```
```python
# packages/ai-parrot-tools/tests/querysource/test_dialect_jsonb.py — CREATE
"""FEAT-610 TASK-3841 — JSONB operators in the toolkit dialect (AC2, AC3)."""

from __future__ import annotations

import pytest

from parrot_tools.querysource.dialect import DIALECT_VERIFIED_AGAINST, JSONB_OPERATORS, REFERENCE, validate_filter
from parrot_tools.querysource.errors import InvalidConditionsError


def test_validate_filter_accepts_jsonb_operators() -> None:
    """@> list-of-dict, <@, @>| and ->> are accepted."""
    # FILL IN: assert validate_filter({...}) == [] for each operator — bounded by AC2
    #   (must include {"graduation_details": {"@>": [{"course": "Pilates Studio"}]}}).


def test_validate_filter_still_rejects_unknown_operator() -> None:
    with pytest.raises(InvalidConditionsError):
        validate_filter({"col": {"~~": 1}})


def test_dialect_reference_lists_jsonb_operators() -> None:
    assert DIALECT_VERIFIED_AGAINST == "5.1.2"
    # FILL IN: assert the module reference's operators_jsonb == list(JSONB_OPERATORS)
```
**Why**: `REFERENCE` above is a placeholder name — FILL IN: import the real module-level `DialectReference` instance
name from `dialect.py` (read the assignment above line 95); do not invent one.

```python
# packages/ai-parrot-tools/tests/querysource/test_toolkit_core.py — MODIFY line 79 (occurrences: 1 of '"4.5.11"')
    assert ref.verified_against == "5.1.2" and isinstance(ref.variables, dict)
# packages/ai-parrot-tools/tests/querysource/test_models.py — MODIFY line 40 (occurrences: 1)
        verified_against="5.1.2",
```

**FILL IN checklist**
- [ ] `where_grammar` JSONB line.
- [ ] real module-level reference name in the test import.
- [ ] test bodies for each accepted operator.

---

## Acceptance Criteria

- [ ] `validate_filter({"graduation_details": {"@>": [{"course": "Pilates Studio"}]}})` returns `[]` (AC2).
- [ ] `<@`, `@>|`, `->`, `->>` accepted; an unknown dict operator still raises `InvalidConditionsError`.
- [ ] `DIALECT_VERIFIED_AGAINST == "5.1.2"` and the reference exposes `operators_jsonb` (AC3).
- [ ] `ruff check` clean on touched files.

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/querysource/test_dialect_jsonb.py -q`
- `pytest packages/ai-parrot-tools/tests/querysource/test_dialect.py -q`
- `pytest packages/ai-parrot-tools/tests/querysource/test_models.py -q`
- `pytest packages/ai-parrot-tools/tests/querysource/test_toolkit_core.py -q`

---

## Test Specification

| Test | Covers |
|---|---|
| `test_validate_filter_accepts_jsonb_operators` | AC2 |
| `test_validate_filter_still_rejects_unknown_operator` | regression |
| `test_dialect_reference_lists_jsonb_operators` | AC3 |

---

## Agent Instructions

1. Verify the Codebase Contract anchors (`grep -c`) before editing; fix stale entries in this file first.
2. Implement exactly the files listed; no refactors outside scope.
3. `ruff check --fix` the touched Python files; run the Validation Commands.
4. Commit code only: `feat(a2ui-linked-e2e-test): TASK-3841 — JSONB operators in the QuerysourceToolkit dialect`.
5. Close with `scripts/sdd/close_task.sh TASK-3841 a2ui-linked-e2e-test verified` and fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*
