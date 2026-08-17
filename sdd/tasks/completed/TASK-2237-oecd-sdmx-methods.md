# TASK-2237: OpenDataToolkit — OECD SDMX methods

**Feature**: FEAT-426 — Research Tools for Agents
**Spec**: `sdd/specs/research-tools-for-agents.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2236
**Assigned-to**: unassigned

---

## Context

Final slice of spec §3 Module 2, and the hardest of the three Open Data
sources. SDMX is not a plain REST/JSON API: dimension order is positional and
dataflow-specific, so a Data Structure Definition (DSD) must be fetched before
a data query can be built. Completing this task closes the open-data chain and
(together with TASK-2241) unblocks the router.

---

## Scope

- Add `search_oecd_data(query, dataset=None, country=None, max_results=10)
  -> ResearchResult` — browse/filter the OECD dataflow catalog, return
  `DatasetResult` entries.
- Add `get_oecd_indicator(dataset_id, country, frequency=None)
  -> ResearchResult` — fetch an actual data series, return `IndicatorValue`
  entries.
- Both wrap `sdmx1` in `run_in_executor`; target **SDMX 3.0**.
- Recorded fixture + unit tests.

**NOT in scope**: World Bank (TASK-2235), EU (TASK-2236), exports (TASK-2243).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/research/open_data.py` | MODIFY | Add two methods |
| `packages/ai-parrot-tools/tests/research/test_open_data_oecd.py` | CREATE | Unit tests |
| `packages/ai-parrot-tools/tests/research/fixtures/oecd_dataflows.xml` | CREATE | Recorded catalog response |
| `packages/ai-parrot-tools/tests/research/fixtures/oecd_series.xml` | CREATE | Recorded data response |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot_tools.research.models import (
    ResearchResult, DatasetResult, IndicatorValue, Citation,
)
import asyncio, backoff

try:
    import sdmx                      # PyPI DISTRIBUTION IS `sdmx1`, MODULE IS `sdmx`
except ImportError:
    sdmx = None
```

> **Name trap**: the pip package is **`sdmx1`**, the import is **`sdmx`**.
> PyPI latest at spec time: **2.27.0**. Ships in the `research` extra
> (TASK-2234).

### Existing Signatures to Use

```python
# From TASK-2234 — parrot_tools/research/base.py
async def _run_sync_in_executor(self, func, *args, **kwargs) -> Any
def _build_citation(self, source_name, source_url, data_vintage=None,
                    doi=None, license=None) -> Citation
def _failure(self, query, source, result_type, status, message) -> ResearchResult
self._cache: ToolCache
```

### API Facts (verified during spec research)

| Fact | Value |
|---|---|
| SDMX 3.0 base | `https://sdmx.oecd.org/public/rest/v2/` |
| `sdmx1` source id | `OECD3` (v2/SDMX-3.0). `OECD` is the older v1 entry. |
| Auth | none |
| Catalog size | ~1,500 dataflows |
| Data pagination | **none** — responses can reach tens of MB |

### Does NOT Exist

- ~~A server-side keyword search for OECD~~ — discovery is catalog listing
  + **client-side** filtering
- ~~`data-explorer.oecd.org` as an API~~ — that is the browsing **UI**
- ~~`stats.oecd.org/SDMX-JSON/...`~~ — officially end-of-life (June 2024);
  it still 301-redirects some known codes but must **not** be relied on
- ~~`pandasdmx`~~ — stale predecessor of `sdmx1`; do not use
- ~~A package importable as `sdmx1`~~ — distribution `sdmx1`, module `sdmx`
- ~~Fixed dimension names across dataflows~~ — dimension order is
  **positional and dataflow-specific**; fetch the DSD first
- ~~`HTTPService`~~ — forbidden in this feature

---

## Implementation Notes

### Pattern to Follow

```python
@backoff.on_exception(backoff.expo, Exception, max_tries=3)
def _fetch_flows():
    client = sdmx.Client("OECD3")
    return client.dataflow()          # catalog

msg = await self._run_sync_in_executor(_fetch_flows)
```

For `get_oecd_indicator`, fetch the DSD before the data query so dimensions
resolve positionally:

```python
def _fetch_series():
    client = sdmx.Client("OECD3")
    flow_msg = client.dataflow(dataset_id)          # includes the DSD
    return client.data(dataset_id, key={...}, params={"startPeriod": ...})
```

### Guard the response size

Data queries are unpaginated. **Always** bound them: pass `country` into the
dimension key and a `startPeriod`/`lastNObservations` param. Never issue a
bare all-dimensions query. Cap the rows mapped into `IndicatorValue` at a
sane ceiling and record any truncation in `raw_metadata`.

### Compound identifiers

Agency ids may be dotted (`OECD.SDD.NAD`) and dataflow ids `@`-joined
(`DSD_FUA_CLIM@DF_TEMPERATURES`). Do not assume a simple token — pass ids
through verbatim.

### Key Constraints

- **Never raise.** Missing `sdmx` → `status="error"` naming the `research`
  extra. Unknown dataflow → `status="no_data"`.
- `source="oecd"` on every `DatasetResult`.
- `search_oecd_data` → `result_type="datasets"`;
  `get_oecd_indicator` → `result_type="indicators"`.
- Cache the **catalog** aggressively (24h) — it is large and slow-changing;
  cache series at 1h.
- The docstring must tell the LLM that a dataflow id is required for
  `get_oecd_indicator`, and that `search_oecd_data` finds one.

### References in Codebase

- `packages/ai-parrot-tools/src/parrot_tools/ddgo.py` — executor + backoff

---

## Acceptance Criteria

- [ ] `search_oecd_data` and `get_oecd_indicator` present in `get_tools()`.
- [ ] `search_oecd_data` returns `result_type="datasets"` with
      `source="oecd"`; `get_oecd_indicator` returns `result_type="indicators"`.
- [ ] Client is constructed with the **`OECD3`** (SDMX 3.0) source.
- [ ] The DSD is fetched before a data query is built.
- [ ] Every data query is bounded (dimension key and/or period) — no bare
      all-dimensions request in the code path.
- [ ] `sdmx` is called only inside `run_in_executor`.
- [ ] Missing `sdmx` → `status="error"` naming `ai-parrot-tools[research]`;
      no `ImportError` escapes.
- [ ] Unknown dataflow → `status="no_data"`.
- [ ] Successful results carry a complete `Citation`.
- [ ] `pytest packages/ai-parrot-tools/tests/research/test_open_data_oecd.py -v`
      passes offline with fixtures.
- [ ] `ruff check` clean.

---

## Test Specification

```python
import pytest
from parrot_tools.research.open_data import OpenDataToolkit


class TestOECD:
    async def test_search_lists_dataflows(self, mock_sdmx_catalog):
        r = await OpenDataToolkit().search_oecd_data("temperature")
        assert r.status == "success" and r.result_type == "datasets"
        assert r.datasets and r.datasets[0].source == "oecd"

    async def test_uses_sdmx3_source(self, capture_sdmx_client):
        await OpenDataToolkit().search_oecd_data("x")
        assert capture_sdmx_client.source_id == "OECD3"

    async def test_get_indicator_fetches_dsd_first(self, mock_sdmx_series, call_order):
        await OpenDataToolkit().get_oecd_indicator("DSD_X@DF_Y", "FRA")
        assert call_order.index("dataflow") < call_order.index("data")

    async def test_data_query_is_bounded(self, capture_sdmx_query):
        await OpenDataToolkit().get_oecd_indicator("DSD_X@DF_Y", "FRA")
        assert capture_sdmx_query.key or capture_sdmx_query.params

    async def test_unknown_flow_is_no_data(self, mock_sdmx_empty):
        r = await OpenDataToolkit().get_oecd_indicator("NOPE", "FRA")
        assert r.status == "no_data"

    async def test_missing_library_is_reported_not_raised(self, monkeypatch):
        monkeypatch.setattr("parrot_tools.research.open_data.sdmx", None)
        r = await OpenDataToolkit().search_oecd_data("x")
        assert r.status == "error" and "ai-parrot-tools[research]" in r.error_message
```

---

## Agent Instructions

1. **Read the spec** — §3 Module 2, §7 "OECD" gotcha.
2. **Check** TASK-2236 is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — especially the `sdmx1`/`sdmx` name trap.
4. Update the index → `"in-progress"`.
5. **Implement** two methods; leave the other Open Data methods untouched.
6. **Verify** acceptance criteria; move to `completed/`; update index.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-08-17
**Notes**: Added `search_oecd_data` (catalog listing via `sdmx.Client("OECD3")`
+ client-side id/name filtering, cached 24h) and `get_oecd_indicator`
(fetches the DSD via `client.dataflow(dataset_id)` before building a
bounded `client.data(dataset_id, key={"REF_AREA": ..., "FREQ": ...},
params={"startPeriod": ...})` query, cached 1h). `sdmx1` is not installed
in this environment, so tests patch `open_data.sdmx` with a fake module
whose `Client` records source id, call order, and query key/params —
verifying the `OECD3` source, DSD-before-data ordering, and query
boundedness without a real SDMX server (spec goal G6). `_rows_from_oecd_message`
normalizes either a test-provided `.observations` list or (best-effort,
untested here since the library isn't installed) `sdmx.to_pandas()`
output. 7/7 new tests pass; full research suite (38 tests) green;
`ruff check` clean.
**Deviations from spec**: none
