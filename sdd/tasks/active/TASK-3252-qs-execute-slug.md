# TASK-3252: `execute_slug` tool — typed conditions → QS payload → bounded result

**Feature**: FEAT-558 — QuerysourceToolkit — tenant-scoped query-slug and MultiQuery tools
**Spec**: `sdd/specs/querysource-toolkit-refactor.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3251
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 (goal G3) — the replacement for `QSourceTool._execute`. Typed arguments are validated against the
slug's declared placeholders and the WHERE grammar (S7), assembled by `build_conditions` with `querylimit` capped
(S8), the tenant check happens first, then `QS(slug=…, conditions=…).query(output_format="pandas")` runs and the
frame is shaped by `frame_to_result`. `DataNotFound` becomes `status="empty"`.

---

## Scope

- Add `execute_slug(...)` to `QuerysourceToolkit` (insert after `describe_slug`).
- Unit tests with a fake `QS` recording constructor kwargs and `query()` calls.

**NOT in scope**: MultiQuery execution (TASK-3254), raw SQL (never exposed).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py` | MODIFY | add `execute_slug` + imports |
| `packages/ai-parrot-tools/tests/querysource/test_execute_slug.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import time
from parrot_tools.querysource.dialect import build_conditions, validate_filter, validate_placeholders   # TASK-3247
from parrot_tools.querysource.models import ExecutionResult, FilterValue                                # TASK-3246
from parrot_tools.querysource.results import frame_to_result                                            # TASK-3250
```

### Existing Signatures to Use
```python
# querysource/queries/qs.py (installed 4.5.11)
class QS(BaseQuery):  def __init__(self, slug: str = '', conditions: dict = None, request=None, loop=None, **kwargs)   # :42
    async def query(self, output_format: Optional[str] = None)   # :363 → (result, error); lazily calls build_provider()
    async def close(self)                                        # :519
# querysource/exceptions.py: DataNotFound:48, SlugNotFound:34, QueryException:6  (via _qs.get_exceptions())
# pattern — parrot/tools/dataset_manager/sources/query_slug.py:151-155
qy = qs_cls(slug=self.slug, conditions=merged); df, error = await qy.query(output_format='pandas'); if error: raise ...
# TASK-3251 toolkit.py: async def describe_slug(self, slug: str, dry_run: bool = False) -> SlugDetail   (anchor)
```

### Does NOT Exist
- ~~`QS(query=...)` from this tool~~ — raw SQL is never exposed as a tool argument (spec §2).
- ~~`await qry.build_provider()` before `query()`~~ — optional; `query()` builds lazily (qs.py:369-370). Do not call it twice.
- ~~`conditions` free-form argument on the tool~~ — the old tool's shape is gone; only typed arguments.
- ~~`QuerySourceInput` / `QSourceTool`~~ — deleted by TASK-3255; never import.

---

## Implementation Notes

### Key Constraints
- Order inside the method: `_open` → `get_allowed(slug)` (tenant) → `validate_placeholders(placeholders, set(rec.placeholder_names))` → `validate_filter(filter)` → `build_conditions(...)` → construct QS → `query("pandas")` → shape. Nothing touches QS before validation passes (AC-4 of spec §5).
- Exceptions: `DataNotFound` → `ExecutionResult(status="empty", …)`; `SlugNotFound` → `SlugNotFoundError`; any other `QueryException` → `QuerysourceToolkitError(f"query failed: {exc}")`; `error` returned by `query()` non-empty → same error.
- Always `await qs.close()` in `finally`.
- Log `info` with slug and `querylimit`; never log row contents.

---

## Implementation Blueprint

### Steps (in order)
1. Add the imports to `toolkit.py` — *why*: every symbol must come from the contract.
2. Insert `execute_slug` after `describe_slug` — *why*: keeps the slug tools together; TASK-3253 anchors after this method.
3. Complete the two `FILL IN` markers; tests.

### `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py` (MODIFY — imports)
```python
# occurrences: 1 (verified after TASK-3251: grep -c '^from parrot_tools.querysource.models import' toolkit.py)
# AFTER — insert below `from parrot_tools.querysource.models import DialectReference, PlaceholderInfo, SlugDetail, SlugSummary`
import time  # move to the stdlib import group at the top of the file
from parrot_tools.querysource.dialect import build_conditions, validate_filter, validate_placeholders
from parrot_tools.querysource.errors import QuerysourceToolkitError, SlugNotFoundError
from parrot_tools.querysource.models import ExecutionResult, FilterValue
from parrot_tools.querysource.results import frame_to_result
```
### `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py` (MODIFY — method)
```python
# occurrences: 1 (verified after TASK-3251: grep -c '    async def describe_slug(' toolkit.py)
# AFTER — insert below the end of `describe_slug` (its final `return detail`), same indentation as the other methods
    async def execute_slug(self, slug: str, placeholders: dict[str, Any] | None = None,
                           filter: dict[str, FilterValue] | None = None, fields: list[str] | None = None,
                           ordering: list[str] | None = None, grouping: list[str] | None = None,
                           limit: int | None = None, offset: int | None = None, refresh: bool = False) -> ExecutionResult:
        """Run a query-slug. `placeholders` fill the slug's declared conditions (see qs_describe_slug);
        `filter` adds WHERE clauses in the dialect grammar (see qs_get_dialect_reference); `fields`, `ordering`,
        `grouping` override the stored projection; `limit` is capped at the toolkit's max_rows; `refresh` bypasses
        the QuerySource cache. Returns bounded rows plus returned_rows/total_rows/truncated."""
        started = time.monotonic()
        await self._open()
        rec = await self._catalog.get_allowed(slug)                     # tenant check first (spec §2)
        placeholders = dict(placeholders or {})
        validate_placeholders(placeholders, set(rec.placeholder_names))
        rejected = validate_filter(dict(filter or {}))                   # raises when strict (default)
        conditions = build_conditions(placeholders=placeholders, filter=filter, fields=fields, ordering=ordering,
                                      grouping=grouping, limit=limit, offset=offset, refresh=refresh,
                                      max_rows=self.max_rows, forced=self.forced_conditions)
        self.logger.info("qs_execute_slug %s querylimit=%s", slug, conditions.get("querylimit"))
        exc_mod = _qs.get_exceptions()
        qs = _qs.get_qs()(slug=slug, conditions=conditions)              # qs.py:42
        try:
            result, error = await qs.query(output_format="pandas")      # qs.py:363
            # FILL IN: if error: raise QuerysourceToolkitError(f"query '{slug}' failed: {error}") — bounded by query_slug.py:154-155
        except exc_mod.DataNotFound:
            return frame_to_result(None, slug=slug, max_rows=self.max_rows, applied=conditions, rejected=rejected, started=started)
        except exc_mod.SlugNotFound as exc:
            raise SlugNotFoundError(f"slug '{slug}' not found") from exc
        except exc_mod.QueryException as exc:
            # FILL IN: wrap as QuerysourceToolkitError with the exception text — bounded by "LLM-readable message"
            raise QuerysourceToolkitError(str(exc)) from exc
        finally:
            await qs.close()                                             # qs.py:519
        return frame_to_result(result, slug=slug, max_rows=self.max_rows, applied=conditions, rejected=rejected, started=started)
```
**Why this shape**: validation precedes construction so a denied or malformed request never reaches the DB
(spec §5 AC-4/5); `applied_conditions` echoes exactly what QS received so the LLM can see the effective filter (S7).

### FILL IN checklist
- [ ] `toolkit.py::execute_slug` — `error` handling after `query()`; bounded by query_slug.py:154-155
- [ ] `toolkit.py::execute_slug` — `QueryException` message wrapping; bounded by spec §3 M1 error docstrings

---

## Acceptance Criteria

- [ ] Fake `QS` receives `conditions == build_conditions(...)` output; `query` called with `output_format="pandas"`; `close()` awaited on success, on `DataNotFound`, and on error.
- [ ] `limit=5000`, `max_rows=200` → `conditions["querylimit"] == 200`.
- [ ] Unknown placeholder or invalid filter → `InvalidConditionsError` and `QS` never constructed; foreign slug on a restricted instance → `TenantDeniedError` and `QS` never constructed.
- [ ] `DataNotFound` → `status="empty"`; `error` string → `QuerysourceToolkitError`.
- [ ] `"qs_execute_slug" in tk.list_tool_names()`; `pytest packages/ai-parrot-tools/tests/querysource/test_execute_slug.py -v` passes; `ruff check` clean.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/querysource/test_execute_slug.py
import types, pytest, pandas as pd
from parrot_tools.querysource import _qs
from parrot_tools.querysource.toolkit import QuerysourceToolkit
from parrot_tools.querysource.errors import InvalidConditionsError, TenantDeniedError, QuerysourceToolkitError

class _Exc:  # stand-in for querysource.exceptions
    class QueryException(Exception): pass
    class SlugNotFound(QueryException): pass
    class DataNotFound(QueryException): pass

@pytest.fixture
def fake_qs(patched_qs, monkeypatch):
    state = {"init": None, "query": None, "closed": 0, "behaviour": "ok"}
    class FakeQS:
        def __init__(self, **kw): state["init"] = kw
        async def query(self, output_format=None):
            state["query"] = output_format
            if state["behaviour"] == "empty": raise _Exc.DataNotFound("no data")
            if state["behaviour"] == "error": return None, "boom"
            return pd.DataFrame({"a": range(3)}), None
        async def close(self): state["closed"] += 1
    monkeypatch.setattr(_qs, "QS", FakeQS)
    monkeypatch.setattr(_qs, "get_exceptions", lambda: _Exc)
    return state

async def test_payload_cap_and_close(fake_qs):
    tk = QuerysourceToolkit(dsn="postgres://fake", max_rows=200)
    r = await tk.execute_slug("epson_field_activity", placeholders={"firstdate": "2026-08-09", "lastdate": "2026-08-15"},
                              filter={"store": ["1", "2"]}, limit=5000)
    assert fake_qs["init"]["conditions"]["querylimit"] == 200 and fake_qs["init"]["conditions"]["firstdate"] == "2026-08-09"
    assert fake_qs["query"] == "pandas" and fake_qs["closed"] == 1 and r.returned_rows == 3

async def test_validation_before_qs(fake_qs):
    tk = QuerysourceToolkit(dsn="postgres://fake")
    with pytest.raises(InvalidConditionsError): await tk.execute_slug("epson_field_activity", placeholders={"nope": 1})
    with pytest.raises(InvalidConditionsError): await tk.execute_slug("epson_field_activity", filter={"a b": 1})
    with pytest.raises(TenantDeniedError): await QuerysourceToolkit(dsn="postgres://fake", programs=["pokemon"]).execute_slug("epson_field_activity")
    assert fake_qs["init"] is None

async def test_empty_and_error(fake_qs):
    tk = QuerysourceToolkit(dsn="postgres://fake")
    fake_qs["behaviour"] = "empty"
    assert (await tk.execute_slug("epson_field_activity")).status == "empty" and fake_qs["closed"] == 1
    fake_qs["behaviour"] = "error"
    with pytest.raises(QuerysourceToolkitError): await tk.execute_slug("epson_field_activity")
    assert fake_qs["closed"] == 2
```

---

## Agent Instructions

1. Read spec §3 Module 5 (`execute_slug`), §2 Overview (Dialect, Results), §5 AC 4–5.
2. Verify TASK-3251 completed and the two anchors occur once; update index → `in-progress`.
3. Implement; tests; `ruff`. Move this file to `sdd/tasks/completed/`, update index → `done`, fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
