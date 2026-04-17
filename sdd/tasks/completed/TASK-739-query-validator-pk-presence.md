# TASK-739: QueryValidator PK-presence extension

**Feature**: FEAT-106 — NavigatorToolkit ↔ PostgresToolkit Interaction
**Spec**: `sdd/specs/navigatortoolkit-postgrestoolkit-interaction.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`PostgresToolkit`'s new `update_row` / `delete_row` tools (TASK-743) must
refuse DML that doesn't reference the target table's primary key in the
WHERE clause — our single strongest guardrail against "UPDATE/DELETE the
whole table". Today `QueryValidator.validate_sql_ast` enforces only the
weaker "WHERE must exist" rule in its DML-permitted branch
(`query_validator.py` lines 274–282).

Implements **Module 1** of the spec.

---

## Scope

- Extend `QueryValidator.validate_sql_ast` with two new keyword arguments:
  - `require_pk_in_where: bool = False`
  - `primary_keys: Optional[List[str]] = None`
- When `require_pk_in_where=True` AND the parsed root is an `exp.Update`
  or `exp.Delete`, AFTER the existing "WHERE must exist" branch:
  1. Walk `root.args["where"].find_all(exp.Column)`.
  2. Collect `col.name.lower()` for every column node.
  3. Lower-case `primary_keys` too.
  4. If the intersection is empty, reject with a clear message:
     `"WHERE clause must reference the primary key column(s): <cols>"`.
  5. "Any one of" counts as satisfied for composite PKs (non-empty
     intersection is the test).
- Default `require_pk_in_where=False` MUST preserve byte-identical behavior
  for all existing callers — no new fields in the returned dict, no new
  log lines on the default path.
- Update the docstring to describe the new kwargs (Google style).
- Add the new unit-test module listed below (Module 8 covers broader
  coverage; we wire in this task's narrow tests here to unblock TASK-743).

**NOT in scope**:
- Touching the regex-based `validate_sql_query` (line 33). That function
  stays a pure legacy fallback.
- Adding a new DML type guard beyond UPDATE/DELETE. INSERTs don't have
  WHERE — the existing branch already short-circuits.
- Returning the collected PK columns in the success dict. Keep the
  response shape frozen.
- Wiring CRUD methods to pass these kwargs — that's TASK-743.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/security/query_validator.py` | MODIFY | Add two kwargs to `validate_sql_ast`; extend DML-permitted branch |
| `tests/unit/test_query_validator_pk.py` | CREATE | Five test cases (see Test Specification) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.security import QueryValidator, QueryLanguage
# verified at: packages/ai-parrot/src/parrot/security/__init__.py:11, 12, 20, 21

import sqlglot
from sqlglot import exp
# already imported at query_validator.py — exp.Column, exp.Update, exp.Delete
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/security/query_validator.py
class QueryValidator:                                               # line 29
    @staticmethod
    def validate_sql_query(query: str) -> Dict[str, Any]: ...       # line 33 (legacy regex, DO NOT TOUCH)

    @classmethod
    def validate_sql_ast(                                           # line 165  (spec said 164 — verify)
        cls,
        query: str,
        dialect: Optional[str] = None,
        read_only: bool = True,
        # ADD:
        # require_pk_in_where: bool = False,
        # primary_keys: Optional[List[str]] = None,
    ) -> Dict[str, Any]: ...
    # DML-permitted branch is around lines 274-282:
    #   if isinstance(root, (exp.Update, exp.Delete)):
    #       if root.args.get('where') is None:
    #           return <reject "WHERE clause required">
    # The NEW logic inserts AFTER that check but BEFORE the success return:
    #   if require_pk_in_where and primary_keys:
    #       where_cols = {c.name.lower() for c in root.args['where'].find_all(exp.Column)}
    #       pk_set = {pk.lower() for pk in primary_keys}
    #       if not (where_cols & pk_set):
    #           return <reject "WHERE must reference PK: ...">
```

### Does NOT Exist

- ~~`QueryValidator.validate_sql_ast(require_pk_in_where=…, primary_keys=…)`~~ — these kwargs do not exist today; this task adds them.
- ~~`exp.Column.name` being a callable~~ — it's a property (string).
- ~~A `PKMissingError` exception class~~ — rejections are returned as dict payloads with `is_safe=False` (or however the existing branch communicates rejection; match the existing shape exactly).
- ~~A sibling helper `validate_dml_pk(…)`~~ — no new public API. All logic lives inside `validate_sql_ast`.

---

## Implementation Notes

### Pattern to Follow

```python
# Minimal sketch — keep the case-insensitivity (Postgres identifiers
# are case-folded unless quoted; our metadata stores them lowercase).
if require_pk_in_where and primary_keys and isinstance(root, (exp.Update, exp.Delete)):
    where_node = root.args.get('where')
    if where_node is not None:
        where_cols = {c.name.lower() for c in where_node.find_all(exp.Column)}
        pk_set = {pk.lower() for pk in primary_keys}
        if not (where_cols & pk_set):
            return {
                # ... match the exact existing rejection-shape in this file ...
                'error': f"WHERE clause must reference primary key column(s): {sorted(pk_set)}",
            }
```

Read `query_validator.py` lines 270–295 first to copy the **exact**
rejection-dict shape used by its peers. Do NOT invent new keys.

### Key Constraints

- `sqlglot.exp.Column.name` returns an **unquoted** identifier already;
  still call `.lower()` defensively.
- Composite PKs: empty intersection → reject; any single PK col present → accept.
- Preserve backwards compatibility: all existing callers of
  `validate_sql_ast` pass only the first 3 positional args — nothing
  they do changes.
- When `require_pk_in_where=True` but `primary_keys` is `None` or empty,
  treat it as a misconfiguration and reject with
  `"require_pk_in_where=True requires non-empty primary_keys"` — this
  prevents silent acceptance of a caller who forgot to pass the PKs.

### References in Codebase

- `packages/ai-parrot/src/parrot/security/query_validator.py` — the file being edited
- `packages/ai-parrot/src/parrot/security/__init__.py` — re-export (no change here)

---

## Acceptance Criteria

- [ ] `validate_sql_ast` accepts `require_pk_in_where` and `primary_keys` kwargs
- [ ] Default values preserve pre-feature behavior (regression test passes)
- [ ] `UPDATE t SET x=1 WHERE id=5` accepted when `primary_keys=["id"]`
- [ ] `UPDATE t SET x=1 WHERE status='y'` rejected when `primary_keys=["id"]`
- [ ] Same policy applies to `DELETE`
- [ ] Composite PK `["a","b"]`: WHERE with only `a` → accepted; WHERE with neither → rejected
- [ ] `require_pk_in_where=True` with empty/None `primary_keys` → rejected with clear message
- [ ] `pytest tests/unit/test_query_validator_pk.py -v` passes
- [ ] No change to `validate_sql_query` (regex legacy path)

---

## Test Specification

```python
# tests/unit/test_query_validator_pk.py
import pytest
from parrot.security import QueryValidator


class TestValidateSqlAstPkPresence:
    def test_pk_presence_passes_with_pk_in_where(self):
        result = QueryValidator.validate_sql_ast(
            "UPDATE test.t SET x=1 WHERE id=5",
            dialect="postgres",
            read_only=False,
            require_pk_in_where=True,
            primary_keys=["id"],
        )
        assert result.get("is_safe") is True or result.get("valid") is True

    def test_pk_presence_rejects_non_pk_where(self):
        result = QueryValidator.validate_sql_ast(
            "UPDATE test.t SET x=1 WHERE status='y'",
            dialect="postgres",
            read_only=False,
            require_pk_in_where=True,
            primary_keys=["id"],
        )
        assert result.get("is_safe") is False or result.get("valid") is False
        assert "primary key" in result.get("error", "").lower()

    def test_pk_presence_accepts_any_pk_of_composite(self):
        result = QueryValidator.validate_sql_ast(
            "UPDATE test.t SET x=1 WHERE a=1",
            dialect="postgres",
            read_only=False,
            require_pk_in_where=True,
            primary_keys=["a", "b"],
        )
        assert result.get("is_safe") is True or result.get("valid") is True

    def test_pk_presence_backcompat_default_false(self):
        # Identical call without the new kwarg behaves exactly like before.
        baseline = QueryValidator.validate_sql_ast(
            "UPDATE test.t SET x=1 WHERE status='y'",
            dialect="postgres",
            read_only=False,
        )
        assert baseline.get("is_safe") is True or baseline.get("valid") is True

    def test_pk_presence_delete(self):
        result = QueryValidator.validate_sql_ast(
            "DELETE FROM test.t WHERE id=5",
            dialect="postgres",
            read_only=False,
            require_pk_in_where=True,
            primary_keys=["id"],
        )
        assert result.get("is_safe") is True or result.get("valid") is True
```

> Adjust the assertions (`is_safe` vs `valid`, rejection-dict shape) to
> match the current response format used by `validate_sql_ast` —
> `grep` the file before coding the assertions.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none (this is a leaf task)
3. **Verify the Codebase Contract** — confirm `validate_sql_ast` is still at/near line 165 and the DML-permitted branch is near lines 274–282. If drift > 20 lines, update the contract FIRST.
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria
7. **Move this file** to `tasks/completed/TASK-739-query-validator-pk-presence.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: claude-sonnet-4-6 (sdd-worker)
**Date**: 2026-04-17
**Notes**: Added `require_pk_in_where` and `primary_keys` kwargs to `validate_sql_ast`. Added `List` to typing imports. Inserted PK-presence check after the WHERE-exists check in the DML-permitted branch. All 10 unit tests pass.

**Deviations from spec**: none
