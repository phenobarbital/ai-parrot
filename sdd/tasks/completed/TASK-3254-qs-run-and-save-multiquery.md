# TASK-3254: `run_multiquery`, `save_multiquery` and the `_pre_execute` write gate

**Feature**: FEAT-558 — QuerysourceToolkit — tenant-scoped query-slug and MultiQuery tools
**Spec**: `sdd/specs/querysource-toolkit-refactor.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3253
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 (goals G6-run, G7). Executes a pipeline inline or by saved slug through `MultiQS` after
`_policy_check` passes, wrapped in `asyncio.wait_for(multiquery_timeout)` (§8 Q3 resolved: option a — the library
joins worker threads synchronously at `multi/__init__.py:315`, same as its REST handler). Persists a validated
pipeline as a `public.queries` row via `SlugCatalog.upsert` when `allow_write=True` (proposal U2, S5), as a
confirming tool. `_pre_execute` adds a defence-in-depth `WriteDisabledError`.

---

## Scope

- Add `run_multiquery(pipeline=None, slug=None, conditions=None)`, `save_multiquery(slug, pipeline, description, program=None, overwrite=False)`, `_pre_execute(tool_name, /, **kwargs)` to `QuerysourceToolkit`.
- Unit tests with fake `MultiQS`.

**NOT in scope**: hard cut / registry (TASK-3255).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py` | MODIFY | add 2 tools + hook |
| `packages/ai-parrot-tools/tests/querysource/test_multiquery_tools.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.querysource.errors import WriteDisabledError, QuerysourceToolkitError, RawSqlForbiddenError   # TASK-3245
from parrot_tools.querysource.models import MultiQueryResult, SavedSlug   # TASK-3246
from parrot_tools.querysource.results import multi_to_result             # TASK-3250
```

### Existing Signatures to Use
```python
# querysource/queries/multi/__init__.py (installed 4.5.11)
class MultiQS(BaseQuery):                                                                          # :56
    def __init__(self, slug=None, queries=None, files=None, query: dict|None=None, conditions=None, request=None, loop=None, user_session=None, **kwargs)   # :62
        # query= → pops queries/files/sources from the dict, rest are steps (:95-97); raises DriverError when all empty (:104-111)
    async def query(self)  → (result, options)                                                     # :166 ; slug path parses query_raw JSON (:171-200); t.join(timeout) :315 (blocking)
    async def execute(self)                                                                        # :553 alias of query()
# querysource/handlers/multi.py:223-230  qs = MultiQS(slug=slug, queries=_queries, files=_files, query=options, conditions=data, user_session=...)
# querysource/exceptions.py: DataNotFound:48, DriverError:58, QueryException:6
# TASK-3248 catalog.py: TenantGuard.resolve_write_program(requested) -> str ; SlugCatalog.upsert(*, slug, description, pipeline, program_slug, overwrite) -> SavedSlug
# TASK-3253 toolkit.py: async def _policy_check(self, pipeline) -> PipelineValidation ; anchor `    async def validate_pipeline(`
# parrot/tools/toolkit.py:455  async def _pre_execute(self, tool_name: str, /, **kwargs) -> None  (raising aborts the call)
```

### Does NOT Exist
- ~~`MultiQS.run()`~~ — use `query()`.
- ~~`MultiQS(pipeline=...)`~~ — the kwarg is `query=` (a dict) for inline pipelines, `slug=` for saved ones.
- ~~a `provider="multi"` marker when saving~~ — detection is by `query_raw` JSON; `upsert` writes only `query_slug, description, query_raw, program_slug, is_cached=False`.
- ~~`asyncio.to_thread(qs.query)`~~ — `query()` is a coroutine; v1 awaits it directly under `wait_for` (§8 Q3 option a).

---

## Implementation Notes

### Key Constraints
- `run_multiquery`: exactly one of `pipeline`/`slug` (else `QuerysourceToolkitError`). For `slug=`: `rec = await self._catalog.get_allowed(slug)`; if `rec.is_multiquery` → `_policy_check(rec.pipeline)`; else treat as single-slug MultiQS (still allowed). For `pipeline=`: `_policy_check(pipeline)`; if issues → raise `RawSqlForbiddenError` when any issue field is `"query"`, `WriteDisabledError` when field is `"Output"`, else `QuerysourceToolkitError` listing issues. Then `mq = MultiQS(query=copy.deepcopy(pipeline), conditions=conditions)` or `MultiQS(slug=slug, conditions=conditions)`; `result, _options = await asyncio.wait_for(mq.query(), self.multiquery_timeout)`; `DataNotFound` → empty `MultiQueryResult`; `asyncio.TimeoutError` → `QuerysourceToolkitError("multiquery timed out after …s")`.
- **Deep-copy the pipeline** before passing to MultiQS — its `__init__` pops keys from the dict (`:95-97`).
- `save_multiquery`: `if not self.allow_write: raise WriteDisabledError`; `program_slug = self.guard.resolve_write_program(program)`; `v = await self._policy_check(pipeline)`; also structural check via `validate_pipeline`; if not valid → `QuerysourceToolkitError`; `return await self._catalog.upsert(...)`.
- `_pre_execute`: `if tool_name.endswith("save_multiquery") and not self.allow_write: raise WriteDisabledError(...)` — `tool_name` arrives prefixed (`qs_save_multiquery`).

---

## Implementation Blueprint

### Steps (in order)
1. Add imports; insert the block after `validate_pipeline` — *why*: reuses `_policy_check` from TASK-3253.
2. Complete the `FILL IN` markers; tests (fake `MultiQS` recording kwargs; timeout via tiny `multiquery_timeout` and a sleeping fake).

### `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py` (MODIFY — imports)
```python
# occurrences: 1 (verified after TASK-3253: grep -c '^from parrot_tools.querysource.models import ComponentDoc' toolkit.py)
# AFTER — insert below `from parrot_tools.querysource.models import ComponentDoc, PipelineIssue, PipelineValidation`
import copy                          # move to the stdlib import group
from parrot_tools.querysource.errors import RawSqlForbiddenError, WriteDisabledError
from parrot_tools.querysource.models import MultiQueryResult, SavedSlug
from parrot_tools.querysource.results import multi_to_result
```
### `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py` (MODIFY — methods)
```python
# occurrences: 1 (verified after TASK-3253: grep -c '    async def validate_pipeline(' toolkit.py)
# AFTER — insert below the end of `validate_pipeline` (its final `return result`)
    def _raise_for_issues(self, validation: PipelineValidation) -> None:
        """Map policy issues to the toolkit error hierarchy (raw → RawSqlForbiddenError, Output → WriteDisabledError)."""
        if validation.valid:
            return
        fields = {i.field for i in validation.issues}
        msg = "; ".join(f"{i.step}.{i.field}: {i.message}" for i in validation.issues)
        if "query" in fields:
            raise RawSqlForbiddenError(f"pipeline rejected: {msg}")
        if "Output" in fields:
            raise WriteDisabledError(f"pipeline rejected: {msg}")
        raise QuerysourceToolkitError(f"pipeline rejected: {msg}")

    async def run_multiquery(self, pipeline: dict[str, Any] | None = None, slug: str | None = None,
                             conditions: dict[str, Any] | None = None) -> MultiQueryResult:
        """Run a MultiQuery pipeline inline (`pipeline`, the JSON with queries/Join/Concat/…/Output) or a saved
        multi-query slug (`slug`). Every referenced slug must be executable by this toolkit; raw SQL nodes, external
        sources and destination steps follow the instance configuration (see qs_validate_pipeline). Results are
        bounded per frame."""
        started = time.monotonic()
        if (pipeline is None) == (slug is None):
            raise QuerysourceToolkitError("pass exactly one of `pipeline` or `slug`")
        await self._open()
        if slug is not None:
            rec = await self._catalog.get_allowed(slug)
            if rec.is_multiquery:
                self._raise_for_issues(await self._policy_check(rec.pipeline))
            mq = _qs.get_multiqs()(slug=slug, conditions=dict(conditions or {}))            # multi/__init__.py:62
        else:
            self._raise_for_issues(await self._policy_check(pipeline))
            mq = _qs.get_multiqs()(query=copy.deepcopy(pipeline), conditions=dict(conditions or {}))  # deepcopy: __init__ pops keys (:95-97)
        exc_mod = _qs.get_exceptions()
        self.logger.info("qs_run_multiquery slug=%s inline=%s", slug, pipeline is not None)
        try:
            result, _options = await asyncio.wait_for(mq.query(), timeout=self.multiquery_timeout)   # :166 ; §8 Q3 option a
        except exc_mod.DataNotFound:
            return multi_to_result(None, max_rows=self.max_rows, started=started)
        except asyncio.TimeoutError as exc:
            raise QuerysourceToolkitError(f"multiquery timed out after {self.multiquery_timeout}s") from exc
        except exc_mod.QueryException as exc:
            # FILL IN: wrap DriverError/QueryException text into QuerysourceToolkitError — bounded by "LLM-readable message"
            raise QuerysourceToolkitError(str(exc)) from exc
        return multi_to_result(result, max_rows=self.max_rows, started=started)

    async def save_multiquery(self, slug: str, pipeline: dict[str, Any], description: str,
                              program: str | None = None, overwrite: bool = False) -> SavedSlug:
        """Persist a validated MultiQuery pipeline as a query-slug owned by `program` (forced to the single allowed
        program when this toolkit is tenant-restricted). Requires operator opt-in (allow_write) and user confirmation.
        Refuses to overwrite a slug owned by another program; set overwrite=True to update your own."""
        if not self.allow_write:
            raise WriteDisabledError("save_multiquery is disabled for this toolkit (allow_write=False)")
        program_slug = self.guard.resolve_write_program(program)
        validation = await self.validate_pipeline(pipeline)
        self._raise_for_issues(validation)
        # FILL IN: return await self._catalog.upsert(slug=slug, description=description, pipeline=pipeline,
        #          program_slug=program_slug, overwrite=overwrite) — bounded by S5 (cross-program refusal lives in upsert)
        raise QuerysourceToolkitError("not implemented")

    async def _pre_execute(self, tool_name: str, /, **kwargs: Any) -> None:
        """Defence in depth: block the write tool even if it were exposed (toolkit.py:455 hook)."""
        if tool_name.endswith("save_multiquery") and not self.allow_write:
            raise WriteDisabledError("save_multiquery is disabled for this toolkit (allow_write=False)")
```
**Why this shape**: policy runs before `MultiQS` is constructed so denied slugs never reach QuerySource; the
deepcopy protects the caller's dict from `MultiQS.__init__`'s pops; `wait_for` implements §8 Q3 option (a).

### FILL IN checklist
- [ ] `toolkit.py::run_multiquery` — `QueryException` wrapping; bounded by spec §3 M1 error docstrings
- [ ] `toolkit.py::save_multiquery` — delegate to `upsert`; bounded by S5

---

## Acceptance Criteria

- [ ] Restricted instance + pipeline referencing a foreign slug → `TenantDeniedError`-derived issue → `QuerysourceToolkitError`, and fake `MultiQS` never constructed; raw node → `RawSqlForbiddenError`; `tableOutput` without write → `WriteDisabledError`.
- [ ] Inline run passes `query=` a deep copy (caller's dict still has `queries`) and `conditions=`; saved run passes `slug=`; result is `MultiQueryResult`; `DataNotFound` → `status="empty"`; slow fake + `multiquery_timeout=0.01` → `QuerysourceToolkitError`.
- [ ] `save_multiquery` absent from `list_tool_names()` when `allow_write=False` and direct call raises `WriteDisabledError`; with `allow_write=True, programs=["pokemon"]` it upserts with `program_slug="pokemon"`; `qs_save_multiquery` tool has `routing_meta["requires_confirmation"] is True`.
- [ ] `pytest packages/ai-parrot-tools/tests/querysource/test_multiquery_tools.py -v` passes; `ruff check` clean.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/querysource/test_multiquery_tools.py
import asyncio, pytest, pandas as pd
from parrot_tools.querysource import _qs
from parrot_tools.querysource.toolkit import QuerysourceToolkit
from parrot_tools.querysource.errors import RawSqlForbiddenError, WriteDisabledError, QuerysourceToolkitError
from .conftest import PIPELINE
from .test_components_validate import fake_registry, _Exc if False else None  # reuse fixtures via conftest if preferred

@pytest.fixture
def fake_mq(fake_registry, monkeypatch):
    state = {"init": None, "delay": 0.0}
    class FakeMultiQS:
        def __init__(self, **kw): state["init"] = kw
        async def query(self):
            await asyncio.sleep(state["delay"]); return {"a": pd.DataFrame({"x": [1]})}, {}
    monkeypatch.setattr(_qs, "MultiQS", FakeMultiQS)
    return state

async def test_policy_blocks_before_multiqs(fake_mq):
    tk = QuerysourceToolkit(dsn="postgres://fake", programs=["pokemon"])
    raw = {"queries": {"n": {"query": "select 1", "driver": "pg"}}}
    with pytest.raises(RawSqlForbiddenError): await tk.run_multiquery(pipeline=raw)
    with pytest.raises(WriteDisabledError): await tk.run_multiquery(pipeline={"queries": {"a": {"slug": "pokemon_all_fso_odoo_new"}}, "Output": [{"tableOutput": {}}]})
    assert fake_mq["init"] is None

async def test_inline_run_deepcopies_and_shapes(fake_mq):
    tk = QuerysourceToolkit(dsn="postgres://fake", allow_raw_sql=True, allow_write=True)
    p = {"queries": {"a": {"slug": "epson_field_activity"}}, "Join": []}
    r = await tk.run_multiquery(pipeline=p, conditions={"refresh": True})
    assert "queries" in p and fake_mq["init"]["query"] is not p and fake_mq["init"]["conditions"] == {"refresh": True}
    assert r.results["a"].returned_rows == 1

async def test_timeout(fake_mq):
    fake_mq["delay"] = 0.2
    tk = QuerysourceToolkit(dsn="postgres://fake", allow_raw_sql=True, multiquery_timeout=0.01)
    with pytest.raises(QuerysourceToolkitError, match="timed out"):
        await tk.run_multiquery(pipeline={"queries": {"a": {"slug": "epson_field_activity"}}})

async def test_save_gated_and_confirming(fake_mq, patched_qs):
    tk = QuerysourceToolkit(dsn="postgres://fake")
    assert "qs_save_multiquery" not in tk.list_tool_names()
    with pytest.raises(WriteDisabledError): await tk.save_multiquery("mq1", {"queries": {"a": {"slug": "epson_field_activity"}}}, "d")
    tw = QuerysourceToolkit(dsn="postgres://fake", allow_write=True, programs=["pokemon"])
    saved = await tw.save_multiquery("mq1", {"queries": {"a": {"slug": "pokemon_all_fso_odoo_new"}}}, "d")
    assert saved.program_slug == "pokemon" and patched_qs["insert"]
    assert tw.get_tool("qs_save_multiquery").routing_meta["requires_confirmation"] is True
```
(Adjust the fixture import line to your conftest layout — move `fake_registry` and `_Exc` into `conftest.py` if not already there.)

---

## Agent Instructions

1. Read spec §3 Module 6, §7 Risks (blocking join, destinations), §8 Q3 resolution.
2. Verify TASK-3253 completed and anchors occur once; update index → `in-progress`.
3. Implement; tests; `ruff`. Move this file to `sdd/tasks/completed/`, update index → `done`, fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5), manual fallback implementation
**Date**: 2026-09-17
**Notes**: Added `_raise_for_issues`, `run_multiquery`, `save_multiquery`, `_pre_execute` to `toolkit.py` (plus
imports) per spec §3 Module 6. Filled the `save_multiquery` FILL IN marker (delegate to
`self._catalog.upsert(...)` after policy + structural validation pass); the `run_multiquery` `QueryException`
FILL IN comment already had its resolved code given verbatim in the blueprint (same pattern as TASK-3252),
so no further judgment call was needed there. Fixed the test spec's broken fixture-import line
(`from .test_components_validate import fake_registry, _Exc if False else None` is not valid Python) to a
plain `from .test_components_validate import fake_registry` — the task's own note explicitly authorized
adjusting this import. `pytest packages/ai-parrot-tools/tests/querysource/test_multiquery_tools.py -v` —
4 passed. `ruff check` — clean.

**Same recurring stale-snapshot fix**: this is the toolkit's FINAL tool set (spec §5 AC: 7 tools without
write, 8 with `qs_save_multiquery`), so `test_toolkit_core.py::test_tool_names_and_write_gate` now asserts
the complete final list for both `allow_write=False` and `allow_write=True`, replacing the incremental
snapshot. Full `packages/ai-parrot-tools/tests/querysource/` suite — 64 passed. Implemented manually: same
repo-wide `complex_model_unavailable` block (empty `strong_models` policy); user authorized continuing the
fallback loop for the rest of the feature.

**Deviations from spec**: fixed the test spec's invalid fixture-import expression (spec's own note permitted
this); updated `test_toolkit_core.py`'s tool-name snapshot to its final, complete form. No behavior deviation.
