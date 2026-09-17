# TASK-3251: QuerysourceToolkit class — lifecycle, `get_dialect_reference`, `list_slugs`, `describe_slug`, package exports

**Feature**: FEAT-558 — QuerysourceToolkit — tenant-scoped query-slug and MultiQuery tools
**Spec**: `sdd/specs/querysource-toolkit-refactor.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3245, TASK-3246, TASK-3247, TASK-3248, TASK-3250
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 (toolkit part 1) and §2 New Public Interfaces. Creates the `AbstractToolkit` subclass that every
later tool method hangs off: configuration (`programs`, `allow_write`, `allow_raw_sql`, `allow_external_sources`,
`include_sql`, `max_rows`, `forced_conditions`, `dsn`, `multiquery_timeout`), lazy lifecycle (`auto_open` →
`_open`/`_close`), result dumping, and the three catalog-facing tools (G1, G2, G4). Also publishes the package
exports.

---

## Scope

- Implement `toolkit.py` with `QuerysourceToolkit`: class attributes, `__init__`, `_open`, `_close`, `_post_execute`, `get_dialect_reference`, `list_slugs`, `describe_slug`.
- Fill `parrot_tools/querysource/__init__.py` exports (spec §2 New Public Interfaces).
- Unit tests: tool names (7 without write), config gating of `save_multiquery` exclusion (method added later — test asserts on `exclude_tools`), redaction, multi-query labelling, dry-run path.

**NOT in scope**: `execute_slug` (TASK-3252), MultiQuery tools (TASK-3253/3254), registry/hard cut (TASK-3255).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py` | CREATE | toolkit class + 3 tools |
| `packages/ai-parrot-tools/src/parrot_tools/querysource/__init__.py` | MODIFY | exports |
| `packages/ai-parrot-tools/tests/querysource/test_toolkit_core.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.toolkit import AbstractToolkit              # verified: packages/ai-parrot/src/parrot/tools/toolkit.py:206 (also parrot/tools/__init__.py:143)
from parrot_tools.querysource import _qs                      # TASK-3245
from parrot_tools.querysource.catalog import SlugCatalog, SlugRecord, TenantGuard   # TASK-3248
from parrot_tools.querysource.dialect import DIALECT_REFERENCE, check_version_compatibility, load_variables   # TASK-3247
from parrot_tools.querysource.errors import QuerysourceToolkitError   # TASK-3245
from parrot_tools.querysource.models import DialectReference, PlaceholderInfo, SlugDetail, SlugSummary   # TASK-3246
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):                                   # :206
    exclude_tools: tuple[str, ...] = ()                       # :243
    tool_prefix: str | None = None                            # :257
    confirming_tools: frozenset = frozenset()                 # :275  → routing_meta["requires_confirmation"]=True (:687-689)
    auto_open: bool = False                                   # :319  → _ensure_open() calls _open() once before the first tool call
    def __init__(self, **kwargs)                              # :321  sets self.logger = logging.getLogger(cls name) (:353)
    async def _open(self) -> None                             # :390
    async def _close(self) -> None                            # :406
    async def _post_execute(self, tool_name, result, /, **kwargs) -> Any   # :470
    def _generate_tools(self) -> None                         # :539  public coroutine methods not in exclude_tools → tools
    def list_tool_names(self) -> list[str]                    # :625
# packages/ai-parrot/src/parrot/tools/databasequery/toolkit.py  (shape to mirror)
    tool_prefix: Optional[str] = "dq"                         # :147
    exclude_tools = ("get_source", "cleanup", "start", "stop")   # :152
    if self._output_dir is None: self.exclude_tools = self.exclude_tools + ("save_result",)   # :167-170
    async def _post_execute(...): return result.model_dump() if isinstance(result, BaseModel) else result   # :180-199
# querysource/queries/qs.py: QS(slug=...) :42 ; async def dry_run(self) → [result, error] :529 (calls build_provider) ; async def close(self) :519
```

### Does NOT Exist
- ~~`AbstractToolkit.register_tool()`~~ / ~~`.tools` list~~ — tools are generated from public async methods only.
- ~~`self.name`/`self.description` on a toolkit~~ — those belong to `AbstractTool`; the toolkit docstring is documentation only.
- ~~`QueryToolkit` as base~~ — not used (spec §6 Does NOT Exist).
- ~~`describe_slug` returning `source`, `params`, `attributes`, `dwh_info`~~ — redacted by construction (`SlugDetail` has no such fields).

---

## Implementation Notes

### Key Constraints
- `auto_open = True`; `_open()` awaits `self._catalog.open()`; `_close()` awaits `self._catalog.close()`.
- `__init__` must extend `exclude_tools` with `("save_multiquery",)` when `allow_write` is False **even though the method does not exist yet** (TASK-3254 adds it) — a stale name in `exclude_tools` is harmless (`_generate_tools` only skips names it meets).
- `describe_slug(dry_run=True)`: `qs = _qs.get_qs()(slug=slug)`; `result, error = await qs.dry_run()`; `rendered_query = str(result) if result is not None else None`; ignore `error` into `rendered_query = f"dry_run error: {error}"`; always `await qs.close()` in `finally`.
- Version guard at init: `warning = check_version_compatibility(_qs.installed_version())` inside `try/except ImportError` (querysource may be absent at construction — do not fail); log at `warning`.
- `get_dialect_reference()` returns `DIALECT_REFERENCE.model_copy(update={"variables": load_variables()})`.

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/databasequery/toolkit.py:115-200`

---

## Implementation Blueprint

### Steps (in order)
1. Write `toolkit.py` (block 1: class header + init + lifecycle; block 2: three tools) — *why*: signatures are fixed by the spec skeleton; later tasks insert methods after `describe_slug`.
2. Replace `__init__.py` with the exports block — *why*: `TOOL_REGISTRY` and users import `QuerysourceToolkit` from the package.
3. Tests: tool names, exclusions, redaction, dry-run close.

### `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py` (CREATE — block 1)
```python
"""QuerysourceToolkit — tenant-scoped QuerySource tools for agents (spec FEAT-558 §3 M5/M6).

Generated tool names (tool_prefix 'qs'): qs_get_dialect_reference, qs_list_slugs, qs_describe_slug, qs_execute_slug,
qs_list_components, qs_validate_pipeline, qs_run_multiquery and — only when allow_write=True — qs_save_multiquery.
"""
from __future__ import annotations

from typing import Any

from parrot.tools.toolkit import AbstractToolkit  # verified: packages/ai-parrot/src/parrot/tools/toolkit.py:206

from parrot_tools.querysource import _qs
from parrot_tools.querysource.catalog import SlugCatalog, SlugRecord, TenantGuard
from parrot_tools.querysource.dialect import DIALECT_REFERENCE, check_version_compatibility, load_variables
from parrot_tools.querysource.models import DialectReference, PlaceholderInfo, SlugDetail, SlugSummary


class QuerysourceToolkit(AbstractToolkit):
    """Explain, list, describe and execute QuerySource query-slugs and MultiQuery pipelines, scoped to tenants."""

    tool_prefix: str | None = "qs"                                   # toolkit.py:257
    exclude_tools: tuple[str, ...] = ("open", "close")               # toolkit.py:243
    confirming_tools: frozenset[str] = frozenset({"save_multiquery"})  # toolkit.py:275
    auto_open: bool = True                                           # toolkit.py:319

    def __init__(self, programs: list[str] | None = None, allow_write: bool = False, allow_raw_sql: bool = False,
                 allow_external_sources: bool = True, include_sql: bool = True, max_rows: int = 200,
                 forced_conditions: dict[str, Any] | None = None, dsn: str | None = None,
                 multiquery_timeout: float = 600.0, **kwargs: Any) -> None:
        """Configure tenancy and gates; querysource itself is imported lazily on first use."""
        super().__init__(**kwargs)
        self.programs = list(programs) if programs is not None else None
        self.allow_write = allow_write
        self.allow_raw_sql = allow_raw_sql
        self.allow_external_sources = allow_external_sources
        self.include_sql = include_sql
        self.max_rows = int(max_rows)
        self.forced_conditions = dict(forced_conditions or {})
        self.multiquery_timeout = float(multiquery_timeout)
        self._dsn = dsn
        self.guard = TenantGuard(self.programs)
        self._catalog: SlugCatalog | None = None
        self._components_cache: list[Any] | None = None
        if not self.allow_write:
            self.exclude_tools = self.exclude_tools + ("save_multiquery",)  # pattern: databasequery/toolkit.py:167-170
        try:
            warning = check_version_compatibility(_qs.installed_version())
        except ImportError:
            warning = None
        if warning:
            self.logger.warning("%s", warning)

    @property
    def restricted(self) -> bool:
        return self.guard.restricted

    async def _open(self) -> None:
        """Build the catalog (AsyncDB over querysource's asyncpg_url unless dsn was given)."""
        if self._catalog is None:
            self._catalog = SlugCatalog(self._dsn or _qs.default_dsn(), self.guard)
        await self._catalog.open()

    async def _close(self) -> None:
        if self._catalog is not None:
            await self._catalog.close()

    async def _post_execute(self, tool_name: str, result: Any, /, **kwargs: Any) -> Any:
        """Pydantic → dict for the LLM (pattern: databasequery/toolkit.py:180-199)."""
        if hasattr(result, "model_dump"):
            return result.model_dump()
        if isinstance(result, list):
            return [r.model_dump() if hasattr(r, "model_dump") else r for r in result]
        return result
```
### `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py` (CREATE — block 2, same class)
```python
    def _summary(self, rec: SlugRecord) -> SlugSummary:
        return SlugSummary(slug=rec.slug, description=rec.description, program_slug=rec.program_slug,
                           provider=rec.provider, is_multiquery=rec.is_multiquery, placeholders=rec.placeholder_names)

    async def get_dialect_reference(self) -> DialectReference:
        """Return the QuerySource conditions dialect: which keys are options, which become placeholders, which
        become WHERE filters, the WHERE value grammar with examples, and the '@variables' this deployment
        accepts as values (e.g. '@today'). Call this before building conditions."""
        return DIALECT_REFERENCE.model_copy(update={"variables": load_variables()})

    async def list_slugs(self, search: str | None = None, program: str | None = None, limit: int = 50) -> list[SlugSummary]:
        """List query-slugs visible to this toolkit (allowlist-filtered). `search` matches slug or description."""
        await self._open()
        records = await self._catalog.list(search=search, program=program, limit=max(1, min(int(limit), 500)))
        return [self._summary(r) for r in records]

    async def describe_slug(self, slug: str, dry_run: bool = False) -> SlugDetail:
        """Explain a slug: placeholders and types, stored defaults, filtering/fields/ordering/grouping, provider,
        program, and — when the toolkit is configured with include_sql — the SQL or pipeline JSON. dry_run=True also
        returns the rendered query via QS.dry_run() (this performs provider setup, not a pure catalog read)."""
        await self._open()
        rec = await self._catalog.get_allowed(slug)
        detail = SlugDetail(
            **self._summary(rec).model_dump(),
            placeholders_detail=[PlaceholderInfo(name=n, type=rec.cond_definition.get(n), default=rec.conditions.get(n))
                                 for n in rec.placeholder_names],
            filtering=rec.filtering, fields=rec.fields, ordering=rec.ordering, grouping=rec.grouping,
            is_cached=rec.is_cached, cache_timeout=rec.cache_timeout,
            sql=rec.query_raw if (self.include_sql and not rec.is_multiquery) else None,
            pipeline=rec.pipeline if self.include_sql else None,
        )
        if dry_run and not rec.is_multiquery:
            qs = _qs.get_qs()(slug=slug)                    # qs.py:42
            try:
                # FILL IN: result, error = await qs.dry_run() (qs.py:529); detail.rendered_query = str(result) or f"dry_run error: {error}"
                pass
            finally:
                await qs.close()                            # qs.py:519
        return detail
```
**Why this shape**: the three tools are the read-only catalog surface; every read goes through `get_allowed`, so
tenancy is enforced before anything else (spec §2). Later tasks append methods after `describe_slug`.

### `packages/ai-parrot-tools/src/parrot_tools/querysource/__init__.py` (MODIFY — replace the empty module from TASK-3245)
```python
# occurrences: 1 (verified after TASK-3245: the file holds only a module docstring)
# REPLACE the whole file with:
"""QuerysourceToolkit — tenant-scoped QuerySource query-slug and MultiQuery tools (FEAT-558)."""
from .errors import (InvalidConditionsError, QuerysourceToolkitError, RawSqlForbiddenError, SlugNotFoundError,
                     TenantDeniedError, WriteDisabledError)
from .models import (ComponentDoc, DialectReference, ExecutionResult, MultiQueryResult, PipelineValidation, SavedSlug,
                     SlugDetail, SlugSummary)
from .toolkit import QuerysourceToolkit

__all__ = ["QuerysourceToolkit", "ComponentDoc", "DialectReference", "ExecutionResult", "MultiQueryResult",
           "PipelineValidation", "SavedSlug", "SlugDetail", "SlugSummary", "QuerysourceToolkitError",
           "InvalidConditionsError", "RawSqlForbiddenError", "SlugNotFoundError", "TenantDeniedError", "WriteDisabledError"]
```
**Why**: spec §2 New Public Interfaces; `scripts/generate_tool_registry.py` scans `parrot_tools.querysource.toolkit.QuerysourceToolkit` → key `querysource`.

### FILL IN checklist
- [ ] `toolkit.py::describe_slug` dry-run branch — unpack `[result, error]`; bounded by qs.py:529 and "always close()"

---

## Acceptance Criteria

- [ ] `sorted(QuerysourceToolkit(dsn="postgres://x").list_tool_names()) == ["qs_describe_slug", "qs_get_dialect_reference", "qs_list_slugs"]` at this task (later tasks add the rest); `"save_multiquery" in tk.exclude_tools` when `allow_write=False` and not when `True`.
- [ ] `describe_slug` on a restricted instance raises `TenantDeniedError` for a foreign slug before any `QS` is built; result never has `source/params/attributes/dwh_*`; multi-query slug → `is_multiquery=True`, `pipeline` set, `sql=None`; `include_sql=False` → `sql is None and pipeline is None`.
- [ ] dry-run path awaits `qs.close()` even when `dry_run()` raises.
- [ ] `from parrot_tools.querysource import QuerysourceToolkit` works; `pytest packages/ai-parrot-tools/tests/querysource/test_toolkit_core.py -v` passes; `ruff check` clean.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/querysource/test_toolkit_core.py  (uses conftest fakes from TASK-3248)
import pytest
from parrot_tools.querysource import _qs
from parrot_tools.querysource.toolkit import QuerysourceToolkit
from parrot_tools.querysource.errors import TenantDeniedError

@pytest.fixture
def tk(patched_qs):
    def make(**kw): return QuerysourceToolkit(dsn="postgres://fake", **kw)
    return make

def test_tool_names_and_write_gate(tk):
    assert sorted(tk().list_tool_names()) == ["qs_describe_slug", "qs_get_dialect_reference", "qs_list_slugs"]
    assert "save_multiquery" in tk().exclude_tools and "save_multiquery" not in tk(allow_write=True).exclude_tools

async def test_describe_redaction_and_multiquery(tk):
    d = await tk().describe_slug("pokemon_all_fso_odoo_new")
    assert d.is_multiquery and d.pipeline and d.sql is None and not {"source", "params", "attributes"} & set(d.model_dump())
    e = await tk(include_sql=False).describe_slug("epson_field_activity")
    assert e.sql is None and [p.name for p in e.placeholders_detail] == ["firstdate", "lastdate"]

async def test_describe_denied_before_qs(tk, monkeypatch):
    monkeypatch.setattr(_qs, "QS", lambda **kw: pytest.fail("QS must not be built"))
    with pytest.raises(TenantDeniedError):
        await tk(programs=["pokemon"]).describe_slug("epson_field_activity", dry_run=True)

async def test_dry_run_closes(tk, monkeypatch):
    closed = []
    class FakeQS:
        def __init__(self, **kw): pass
        async def dry_run(self): return ["SELECT 1", None]
        async def close(self): closed.append(True)
    monkeypatch.setattr(_qs, "QS", FakeQS)
    d = await tk().describe_slug("epson_field_activity", dry_run=True)
    assert d.rendered_query == "SELECT 1" and closed

async def test_dialect_reference_has_variables_field(tk):
    ref = await tk().get_dialect_reference()
    assert ref.verified_against == "4.5.11" and isinstance(ref.variables, dict)
```

---

## Agent Instructions

1. Read spec §2 (Overview, New Public Interfaces), §3 Module 5, §6 AbstractToolkit anchors.
2. Verify all `Depends-on` tasks completed; re-check `grep -n "auto_open: bool = False" packages/ai-parrot/src/parrot/tools/toolkit.py`.
3. Update index → `in-progress`; implement; tests; `ruff`.
4. Move this file to `sdd/tasks/completed/`, update index → `done`, fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5), manual fallback implementation
**Date**: 2026-09-17
**Notes**: Implemented `QuerysourceToolkit` per spec §3 Module 5 blueprint (blocks 1+2) and replaced
`__init__.py` with the spec §2 exports. Filled the one FILL IN marker (`describe_slug`'s dry-run branch:
unpack `result, error = await qs.dry_run()`, `rendered_query = str(result) if result is not None else
f"dry_run error: {error}"`, always `await qs.close()` in `finally`). `pytest
packages/ai-parrot-tools/tests/querysource/ -q` — 54 passed (includes `test_toolkit_core.py`'s 5 tests).
`ruff check` — clean. Also spot-verified `from parrot_tools.querysource import QuerysourceToolkit` resolves.
Implemented manually: same repo-wide `complex_model_unavailable` block (empty `strong_models` policy); user
authorized continuing the fallback loop for the rest of the feature.

**Deviations from spec**: none.
