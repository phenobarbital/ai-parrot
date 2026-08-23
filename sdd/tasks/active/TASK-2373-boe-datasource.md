# TASK-2373: BOEDataSource — ExtractDataSource implementation

**Feature**: FEAT-449 — Legal Norms Graph (BOE consolidated legislation with temporal validity)
**Spec**: `sdd/specs/legal-norms-graph-boe.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2372
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4. This is the adapter that lets BOE data enter the **existing**
`OntologyRefreshPipeline` without modifying it. The pipeline calls
`datasource_factory.get(entity_def.source, config).extract(fields=...)` and expects an
`ExtractionResult` back — nothing more.

This is also where spec §2's write-path decision materialises: BOE arrives as **structured
records**, so it enters through `ExtractDataSource` and never touches `GraphIndexBuilder` or
`UniversalNode` (whose `NodeKind` is a closed enum that cannot express `norma`/`articulo`).

---

## Scope

- Implement `BOEDataSource(ExtractDataSource)` with the two abstract methods:
  `extract(fields, filters)` and `list_fields()`.
- Fetch consolidated norms asynchronously with `aiohttp`; delegate all parsing to
  TASK-2372's `parse_consolidated`.
- Honour the `fields` projection (return only requested fields) and a `since` filter in
  `filters` for incremental runs.
- Surface parser errors in `ExtractionResult.errors`; populate `total`, `source_name`,
  `extracted_at`.
- Pace requests politely and send an identifying User-Agent.
- Write unit tests with `aiohttp` mocked — **no network in tests**.

**NOT in scope**: factory registration and the sync entrypoint (TASK-2374); any ontology or
graph writes; retry/circuit-breaker infrastructure (that belongs to the CENDOJ feature,
Sprint 3).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/legal/boe/datasource.py` | CREATE | `BOEDataSource` implementation |
| `packages/ai-parrot-tools/tests/legal/test_boe_datasource.py` | CREATE | Unit tests with mocked HTTP |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import aiohttp
from datetime import datetime, timezone
from typing import Any

from parrot_loaders.extractors.base import (
    ExtractDataSource,   # base.py:50  (ABC)
    ExtractionResult,    # base.py:30
    ExtractedRecord,     # base.py:18
)
# From TASK-2369 / TASK-2372:
from parrot_tools.legal.ids import normalize_boe_id
from parrot_tools.legal.boe.parser import parse_consolidated
```

### Existing Signatures to Use

```python
# packages/ai-parrot-loaders/src/parrot_loaders/extractors/base.py:50
class ExtractDataSource(ABC):
    def __init__(self, name: str, config: dict[str, Any] | None = None) -> None:   # line 62
        self.name = name
        self.config = config or {}
        self.logger = logging.getLogger(f"Parrot.Extractors.{self.__class__.__name__}")

    @abstractmethod
    async def extract(                                                              # line 70
        self,
        fields: list[str] | None = None,
        filters: dict[str, Any] | None = None,
    ) -> ExtractionResult: ...

    @abstractmethod
    async def list_fields(self) -> list[str]: ...                                   # line 91

    async def validate(...) -> Any: ...                                             # line 102
    def _apply_filters(...) -> Any: ...                                             # line 130
    def _project_fields(...) -> Any: ...                                            # line 150
    def _build_result(...) -> Any: ...                                              # line 170

# packages/ai-parrot-loaders/src/parrot_loaders/extractors/base.py:18
class ExtractedRecord(BaseModel):
    data: dict[str, Any]                                     # line 26
    metadata: dict[str, Any] = Field(default_factory=dict)   # line 27

# packages/ai-parrot-loaders/src/parrot_loaders/extractors/base.py:30
class ExtractionResult(BaseModel):
    records: list[ExtractedRecord]                           # line 42
    total: int                                               # line 43
    errors: list[str] = Field(default_factory=list)          # line 44
    warnings: list[str] = Field(default_factory=list)        # line 45
    source_name: str                                         # line 46
    extracted_at: datetime                                   # line 47
```

> **Note**: the base class already provides `_apply_filters` (line 130), `_project_fields`
> (line 150) and `_build_result` (line 170). **Read them before writing your own** — reuse
> beats reimplementation, and `_build_result` likely handles the `total`/`extracted_at`
> bookkeeping for you.

### Does NOT Exist

- ~~`requests` or `httpx`~~ — **forbidden by CLAUDE.md**. Use `aiohttp` only.
- ~~An XML loader in `parrot_loaders`~~ — only `html.py`, `web.py`, `webscraping.py`.
- ~~`"boe"` as a builtin DataSourceFactory type~~ — the builtins are exactly
  `csv`, `json`, `sql`, `records` (`factory.py:26-30`). BOE must be **registered** — and
  that registration is TASK-2374, not this task.
- ~~A shared throttled HTTP client / CircuitBreaker for HTTP~~ — the repo's only
  `CircuitBreaker` (`parrot/tools/compression/budget.py:195`) is a compression-codec latency
  router, **not** an HTTP layer. Do not import it.
- ~~`ExtractionResult(records=[...])` alone~~ — `total`, `source_name` and `extracted_at`
  are required fields with no defaults.

---

## Implementation Notes

### Pattern to Follow

Study a shipped sibling before writing:

```python
# packages/ai-parrot-loaders/src/parrot_loaders/extractors/json_source.py
# (and csv_source.py) — canonical ExtractDataSource implementations showing
# how extract()/list_fields() are structured and how _build_result is used.
```

### Key Constraints

- **Async throughout** — `aiohttp`, never blocking I/O in an async method.
- Use `self.logger` (provided by the base `__init__`), never `print`.
- Google-style docstrings and strict type hints.
- `fields=None` means all fields; otherwise project to the requested subset — the pipeline
  passes `list(entity_def.get_property_names())`.
- The pipeline calls `extract()` **once per entity** (`Norma` and `Articulo` both have
  `source: boe`). Design so each call returns the records for the entity being refreshed —
  read `refresh.py:145-200` to see exactly how the result is consumed, and consider caching
  a parsed norm between the two calls rather than fetching twice.
- Pace requests: BOE bulk access is licensed, but do not parallelise aggressively. Send a
  User-Agent identifying the deployment.
- Errors from the parser go into `ExtractionResult.errors` — the pipeline logs them into
  `RefreshReport.errors` rather than aborting.

### References in Codebase

- `packages/ai-parrot-loaders/src/parrot_loaders/extractors/json_source.py` — reference implementation
- `packages/ai-parrot-loaders/src/parrot_loaders/extractors/base.py:130-190` — inherited helpers
- `packages/ai-parrot/src/parrot/knowledge/ontology/refresh.py:145-200` — how `extract()` output is consumed

---

## Acceptance Criteria

- [ ] `BOEDataSource` subclasses `ExtractDataSource` and implements both abstract methods
- [ ] `extract()` returns a well-formed `ExtractionResult` with `total`, `source_name`, `extracted_at` populated
- [ ] `extract(fields=[...])` returns only the requested fields
- [ ] `filters={"since": <date>}` restricts the fetch to norms changed since that date
- [ ] Parser errors appear in `ExtractionResult.errors`, and extraction does not raise
- [ ] Uses `aiohttp` — no `requests`/`httpx` anywhere
- [ ] Sends an identifying User-Agent
- [ ] **No network access in tests** — `aiohttp` is mocked
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/legal/test_boe_datasource.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-tools/src/parrot_tools/legal/`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/legal/test_boe_datasource.py
import pytest
from parrot_tools.legal.boe.datasource import BOEDataSource
from parrot_loaders.extractors.base import ExtractionResult


@pytest.fixture
def source():
    return BOEDataSource(name="boe", config={"base_url": "https://example.invalid"})


class TestBOEDataSource:
    async def test_extract_returns_extraction_result(self, source, monkeypatch):
        """extract() returns a well-formed ExtractionResult (HTTP mocked)."""
        # monkeypatch the fetch to return the checked-in fixture XML
        result = await source.extract()
        assert isinstance(result, ExtractionResult)
        assert result.source_name and result.extracted_at

    async def test_field_projection(self, source, monkeypatch):
        result = await source.extract(fields=["boe_id"])
        for rec in result.records:
            assert set(rec.data) <= {"boe_id"}

    async def test_parser_errors_surface(self, source, monkeypatch):
        """Malformed upstream payload populates errors instead of raising."""
        result = await source.extract()
        assert isinstance(result.errors, list)

    async def test_list_fields(self, source):
        fields = await source.list_fields()
        assert "boe_id" in fields
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/legal-norms-graph-boe.spec.md` (§2 Overview, §3 Module 4).
2. **Check dependencies** — TASK-2372 must be in `sdd/tasks/completed/`.
3. **Read `json_source.py` and `base.py:130-190` first** — reuse the inherited helpers.
4. **Verify the Codebase Contract** before writing code.
5. **Update status** in `sdd/tasks/index/legal-norms-graph-boe.json` → `"in-progress"`.
6. **Implement** the datasource and tests.
7. **Verify** all acceptance criteria.
8. **Move this file** to `sdd/tasks/completed/TASK-2373-boe-datasource.md`.
9. **Update index** → `"done"`.
10. **Fill in the Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
