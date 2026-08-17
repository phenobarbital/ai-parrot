# TASK-2236: OpenDataToolkit — EU Open Data Portal search

**Feature**: FEAT-426 — Research Tools for Agents
**Spec**: `sdd/specs/research-tools-for-agents.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2235
**Assigned-to**: unassigned

---

## Context

Second slice of spec §3 Module 2. Adds the EU Open Data Portal method to the
existing `OpenDataToolkit` created in TASK-2235. Same file → sequential.

This is the only Open Data source with genuine server-side full-text search,
so it is the one an agent can query with prose.

---

## Scope

- Add `search_eu_open_data(query, dataset_type=None, publisher=None,
  max_results=10) -> ResearchResult` to `OpenDataToolkit`.
- Direct aiohttp GET via `self._make_api_request()` to the piveau search API.
- Map hits into `DatasetResult` entries; attach a `Citation`; cache the response.
- Handle multilingual metadata (see Implementation Notes).
- Recorded fixture + unit tests.

**NOT in scope**: World Bank (TASK-2235), OECD (TASK-2237), exports (TASK-2243).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/research/open_data.py` | MODIFY | Add one method |
| `packages/ai-parrot-tools/tests/research/test_open_data_eu.py` | CREATE | Unit tests |
| `packages/ai-parrot-tools/tests/research/fixtures/eu_open_data_search.json` | CREATE | Recorded search payload |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot_tools.research.models import ResearchResult, DatasetResult, Citation
# no new third-party dependency — uses aiohttp via the mixin
```

### Existing Signatures to Use

```python
# From TASK-2234 — parrot_tools/research/base.py
async def _make_api_request(self, url: str, params: dict = None,
                            headers: dict = None) -> tuple[Optional[dict], Optional[str]]
    # returns (payload, error); NEVER raises
def _build_citation(self, source_name, source_url, data_vintage=None,
                    doi=None, license=None) -> Citation
def _failure(self, query, source, result_type, status, message) -> ResearchResult

# From TASK-2234 — parrot_tools/research/models.py
class DatasetResult(BaseModel):
    title: str
    description: Optional[str] = None
    publisher: Optional[str] = None
    url: Optional[str] = None
    keywords: Optional[List[str]] = None
    format: Optional[str] = None
    last_modified: Optional[str] = None
    source: str
```

### API Facts (verified during spec research)

| Fact | Value |
|---|---|
| Endpoint | `https://data.europa.eu/api/hub/search/search` |
| Platform | **piveau** (Elasticsearch + DCAT-AP) — **NOT CKAN** |
| Auth | none for read/search |
| Query params | `q=` (full text), `limit` (**max 1000**), `page` (**0-indexed**) |
| Response shape | `{"result": {"count": N, "results": [...]}}` |
| Over-limit behavior | plain-text **HTTP 400**, not JSON |

### Does NOT Exist

- ~~CKAN endpoints on data.europa.eu~~ — legacy CKAN paths **404**; the portal
  runs piveau. (An undocumented CKAN-compat shim exists at
  `/api/hub/search/ckan/...` — do **not** rely on it.)
- ~~A guaranteed English title~~ — `title` is a **language-keyed dict** and
  `title["en"]` may be absent. See Implementation Notes.
- ~~Cursor pagination~~ — only `page` + `limit`.
- ~~`HTTPService`~~ — forbidden in this feature.

---

## Implementation Notes

### Multilingual metadata — required handling

`title` and `description` arrive as `{"en": "...", "de": "...", ...}` and
English is **not** guaranteed. Resolve with a fallback:

```python
def _pick_lang(value, preferred="en"):
    """Return preferred language, else the first available, else ''."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and value:
        return value.get(preferred) or next(iter(value.values()))
    return ""
```
A missing-`en` fixture case is an explicit acceptance criterion.

### Request shape

```python
params = {"q": query, "limit": min(max_results, 1000), "page": 0}
payload, err = await self._make_api_request(EU_SEARCH_URL, params=params)
if err:
    return self._failure(query, "eu_open_data", "datasets", "error", err)
hits = (payload or {}).get("result", {}).get("results", [])
```

### Key Constraints

- Clamp `limit` to 1000 — above it the API returns plain-text HTTP 400.
- Empty `results` → `status="no_data"`.
- `source="eu_open_data"` on every `DatasetResult`.
- `result_type="datasets"` on the `ResearchResult`.
- Citation `source_name="EU Open Data Portal"`, `source_url` = the dataset
  landing page (or the search URL when summarising the set).
- Cache TTL: 1 hour.

### References in Codebase

- `packages/ai-parrot-tools/src/parrot_tools/rss/fetcher.py` — aiohttp GET patterns

---

## Acceptance Criteria

- [ ] `search_eu_open_data` present in `OpenDataToolkit.get_tools()`.
- [ ] Returns `ResearchResult` with `result_type="datasets"` and populated
      `datasets` on success, each with `source="eu_open_data"`.
- [ ] Successful results carry a complete `Citation`.
- [ ] **Multilingual fallback**: a fixture whose `title` lacks `"en"` still
      produces a non-empty `DatasetResult.title`.
- [ ] `limit` is clamped to 1000.
- [ ] Transport error → `status="error"` with the message; no exception.
- [ ] Empty results → `status="no_data"`.
- [ ] `pytest packages/ai-parrot-tools/tests/research/test_open_data_eu.py -v` passes offline.
- [ ] `ruff check` clean.

---

## Test Specification

```python
import pytest
from parrot_tools.research.open_data import OpenDataToolkit


class TestEUOpenData:
    async def test_search_maps_datasets(self, mock_aiohttp_session, load_fixture):
        r = await OpenDataToolkit().search_eu_open_data("renewable energy")
        assert r.status == "success" and r.result_type == "datasets"
        assert r.datasets and r.datasets[0].source == "eu_open_data"
        assert r.citation.source_name == "EU Open Data Portal"

    async def test_multilingual_fallback(self, mock_aiohttp_session_de_only):
        """title has only a 'de' key — must not yield an empty title."""
        r = await OpenDataToolkit().search_eu_open_data("energie")
        assert r.datasets[0].title

    async def test_limit_clamped_to_1000(self, capture_params):
        await OpenDataToolkit().search_eu_open_data("x", max_results=5000)
        assert capture_params["limit"] <= 1000

    async def test_transport_error_is_data(self, mock_aiohttp_session_500):
        r = await OpenDataToolkit().search_eu_open_data("x")
        assert r.status == "error" and r.error_message

    async def test_empty_is_no_data(self, mock_aiohttp_session_empty):
        r = await OpenDataToolkit().search_eu_open_data("zzzz")
        assert r.status == "no_data"
```

---

## Agent Instructions

1. **Read the spec** — §3 Module 2, §7 "EU Open Data" gotcha.
2. **Check** TASK-2235 is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** before writing code.
4. Update the index → `"in-progress"`.
5. **Implement** exactly one method; do not touch the World Bank methods.
6. **Verify** acceptance criteria; move to `completed/`; update index.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
