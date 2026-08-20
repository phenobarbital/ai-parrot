# TASK-2235: OpenDataToolkit — World Bank methods

**Feature**: FEAT-426 — Research Tools for Agents
**Spec**: `sdd/specs/research-tools-for-agents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2234
**Assigned-to**: unassigned

---

## Context

First slice of spec §3 Module 2. Creates `OpenDataToolkit` (the class shell)
and its two World Bank methods. Tasks 2236 (EU) and 2237 (OECD) add methods to
the **same file**, so they run after this one in the same worktree.

This chain (2235 → 2236 → 2237) is independent of the academic chain
(2238 → 2241) and may run in a parallel worktree.

---

## Scope

- Create `parrot_tools/research/open_data.py` with
  `class OpenDataToolkit(BaseResearchToolkit, AbstractToolkit)`.
- Implement `search_world_bank(query, indicator=None, country=None,
  date_range=None, max_results=10) -> ResearchResult`.
- Implement `get_world_bank_indicator(indicator_id, country, year=None,
  date_range=None) -> ResearchResult`.
- Both wrap `wbgapi` in `run_in_executor`, populate `IndicatorValue` entries,
  attach a `Citation`, and cache via `ToolCache`.
- Recorded fixture + unit tests.

**NOT in scope**: EU Open Data (TASK-2236), OECD (TASK-2237), exports or
`TOOL_REGISTRY` (TASK-2243).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/research/open_data.py` | CREATE | `OpenDataToolkit` + 2 World Bank methods |
| `packages/ai-parrot-tools/tests/research/test_open_data_worldbank.py` | CREATE | Unit tests |
| `packages/ai-parrot-tools/tests/research/fixtures/world_bank_indicator.json` | CREATE | Recorded wbgapi payload |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.tools.toolkit import AbstractToolkit
from parrot_tools.research.base import BaseResearchToolkit      # TASK-2234
from parrot_tools.research.models import (                      # TASK-2234
    ResearchResult, IndicatorValue, Citation,
)
import asyncio
import backoff

try:
    import wbgapi as wb
except ImportError:
    wb = None
```

`wbgapi` is NOT installed by default — it ships in the `research` extra added
by TASK-2234. PyPI latest at spec time: **1.0.14**.

### Existing Signatures to Use

```python
# From TASK-2234 — parrot_tools/research/base.py
class BaseResearchToolkit:
    auto_open: bool = True
    async def _run_sync_in_executor(self, func, *args, **kwargs) -> Any
    def _build_citation(self, source_name, source_url,
                        data_vintage=None, doi=None, license=None) -> Citation
    def _failure(self, query, source, result_type, status, message) -> ResearchResult
    self._cache: ToolCache        # .get(tool, method, **params) / .set(...)

# From TASK-2234 — parrot_tools/research/models.py
class IndicatorValue(BaseModel):
    indicator_id: str; indicator_name: str
    country: str; country_name: str
    year: str; value: Optional[float]
    unit: Optional[str] = None; source_note: Optional[str] = None

class ResearchResult(BaseModel):
    query: str; source: str; result_type: str
    status: str = "success"; error_message: Optional[str] = None
    total_results: Optional[int] = None
    indicators: Optional[List[IndicatorValue]] = None
    citation: Optional[Citation] = None
    raw_metadata: Optional[Dict[str, Any]] = None
```

### Does NOT Exist

- ~~`parrot_tools.research.open_data`~~ — this task creates it
- ~~A World Bank keyword-search endpoint~~ — the v2 API has **no server-side
  full-text search**; discovery is by indicator/topic/country code only
- ~~`wbgapi` returning JSON by default from raw HTTP~~ — the raw v2 API
  defaults to **XML**; `wbgapi` handles this, but raw aiohttp calls would need
  `format=json`
- ~~`ToolCache._build_key()`~~ — private; use `.get()` / `.set()`
- ~~`HTTPService`~~ — forbidden in this feature (blocking)

---

## Implementation Notes

### Pattern to Follow — sync library via executor

```python
@backoff.on_exception(backoff.expo, Exception, max_tries=3)
def _fetch():
    return wb.data.DataFrame(indicator_id, economy=country, time=...)

df = await self._run_sync_in_executor(_fetch)
```
Mirror `parrot_tools/ddgo.py`, which wraps the sync `DDGS` client the same way.

### `search_world_bank` — no server-side search

Because the API cannot keyword-search, resolve `query` against indicator
metadata (e.g. `wb.series.info(q=query)`) and/or filter client-side, then
fetch observations for the best match. **State this plainly in the docstring**
— the docstring is the LLM's tool description, and the model needs to know
that indicator codes and topic terms work far better than prose.

### Citation

```python
citation = self._build_citation(
    source_name="World Bank Open Data",
    source_url=f"https://data.worldbank.org/indicator/{indicator_id}",
    data_vintage=<last-updated if available>,
    license="CC BY-4.0",
)
```

### Key Constraints

- **Never raise.** Missing `wbgapi` → `self._failure(..., status="error",
  message="... pip install 'ai-parrot-tools[research]'")`. No results →
  `status="no_data"`.
- Cache with a 1-hour TTL (indicators). Exclude nothing sensitive; params only.
- `value` may be `None` for missing observations — keep the row, don't drop it.
- Async throughout; `self.logger` at fetch boundaries.

### References in Codebase

- `packages/ai-parrot-tools/src/parrot_tools/ddgo.py` — executor + backoff
- `packages/ai-parrot-tools/src/parrot_tools/fred_api.py` — cache/result shape
  (**transport only for reference — do NOT copy its `HTTPService` usage**)

---

## Acceptance Criteria

- [ ] `OpenDataToolkit` subclasses `(BaseResearchToolkit, AbstractToolkit)` in
      that order and constructs without error.
- [ ] `get_tools()` includes `search_world_bank` and `get_world_bank_indicator`.
- [ ] Both methods return `ResearchResult` with `result_type="indicators"`.
- [ ] Successful results carry a complete `Citation`.
- [ ] `wbgapi` is called only inside `run_in_executor` — no blocking call.
- [ ] Missing `wbgapi` yields `status="error"` naming the `research` extra —
      no `ImportError` escapes.
- [ ] Empty result set yields `status="no_data"`, not an exception.
- [ ] `pytest packages/ai-parrot-tools/tests/research/test_open_data_worldbank.py -v`
      passes offline with the fixture.
- [ ] `ruff check` clean.

---

## Test Specification

```python
import pytest
from parrot_tools.research.open_data import OpenDataToolkit


class TestWorldBank:
    async def test_get_indicator_from_fixture(self, mock_wbgapi, load_fixture):
        r = await OpenDataToolkit().get_world_bank_indicator("NY.GDP.MKTP.KD.ZG", "BRA")
        assert r.status == "success" and r.result_type == "indicators"
        assert r.indicators and r.indicators[0].country == "BRA"
        assert r.citation.source_name == "World Bank Open Data"
        assert r.citation.source_url and r.citation.access_date

    async def test_search_returns_indicators(self, mock_wbgapi):
        r = await OpenDataToolkit().search_world_bank("GDP growth", country="BRA")
        assert r.status in {"success", "no_data"}

    async def test_no_results_is_no_data(self, mock_wbgapi_empty):
        r = await OpenDataToolkit().get_world_bank_indicator("BOGUS.CODE", "BRA")
        assert r.status == "no_data" and r.citation is None

    async def test_missing_library_is_reported_not_raised(self, monkeypatch):
        monkeypatch.setattr("parrot_tools.research.open_data.wb", None)
        r = await OpenDataToolkit().get_world_bank_indicator("X", "BRA")
        assert r.status == "error" and "ai-parrot-tools[research]" in r.error_message

    async def test_missing_observations_kept_as_none(self, mock_wbgapi_gaps):
        r = await OpenDataToolkit().get_world_bank_indicator("NY.GDP.MKTP.KD.ZG", "BRA")
        assert any(i.value is None for i in r.indicators)
```

---

## Agent Instructions

1. **Read the spec** — §2 Error Contract, §3 Module 2, §7 gotchas.
2. **Check** TASK-2234 is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** before writing code.
4. Update the index → `"in-progress"`.
5. **Implement** per scope. Do not add EU/OECD methods.
6. **Verify** acceptance criteria; move to `completed/`; update index.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-08-17
**Notes**: `OpenDataToolkit(BaseResearchToolkit, AbstractToolkit)` with
`search_world_bank` (resolves free text via `wb.series.info(q=...)` then
fetches observations; falls back to `no_data`) and
`get_world_bank_indicator` (direct indicator+country time series). Both
wrap `wbgapi` calls in `_run_sync_in_executor`, cache via `ToolCache`
(1h TTL), and attach a `Citation` (CC BY-4.0) on success. Missing
observations keep `value=None` rather than being dropped. 7/7 new tests
pass offline against a fixture-driven fake `wb` module; full research
suite (26 tests) green; `ruff check` clean.
**Deviations from spec**: none
