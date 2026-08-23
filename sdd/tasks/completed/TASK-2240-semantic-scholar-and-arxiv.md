# TASK-2240: AcademicResearchToolkit — Semantic Scholar & arXiv

**Feature**: FEAT-426 — Research Tools for Agents
**Spec**: `sdd/specs/research-tools-for-agents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2239
**Assigned-to**: unassigned

---

## Context

Third slice of spec §3 Module 3. Adds the last two search sources to
`AcademicResearchToolkit`. They are grouped because both are small: Semantic
Scholar is a plain aiohttp GET, and arXiv is a port of logic that already
exists in `parrot_tools/arxiv_tool.py`.

Completing this task leaves only `get_paper_details` (TASK-2241) in the
academic chain.

---

## Scope

- Add `search_semantic_scholar(query, fields_of_study=None, year=None,
  open_access_only=False, max_results=10) -> ResearchResult` — direct aiohttp
  GET via `self._make_api_request()`.
- Add `search_arxiv(query, max_results=10, sort_by="relevance",
  category=None) -> ResearchResult` — `arxiv` library via `run_in_executor`.
- Recorded fixtures + unit tests for both.

**NOT in scope**: Crossref (2238), PubMed (2239), `get_paper_details` (2241),
exports (2243). **Do not modify `parrot_tools/arxiv_tool.py`** — the original
`ArxivTool` must stay behaviourally unchanged (spec §1 Non-Goals).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/research/academic.py` | MODIFY | Add two methods |
| `packages/ai-parrot-tools/tests/research/test_academic_s2.py` | CREATE | Semantic Scholar tests |
| `packages/ai-parrot-tools/tests/research/test_academic_arxiv.py` | CREATE | arXiv tests |
| `packages/ai-parrot-tools/tests/research/fixtures/semantic_scholar_search.json` | CREATE | Recorded S2 payload |
| `packages/ai-parrot-tools/tests/research/fixtures/arxiv_feed.xml` | CREATE | Recorded arXiv response |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot_tools.research.models import ResearchResult, PaperResult, Citation
from navconfig import config          # SEMANTIC_SCHOLAR_API_KEY (optional)
import asyncio, backoff

try:
    import arxiv                       # already an existing extra — see below
except ImportError:
    arxiv = None
# Semantic Scholar needs NO library — plain aiohttp via the mixin.
```

### Existing Signatures to Use

```python
# From TASK-2234 — parrot_tools/research/base.py
async def _make_api_request(self, url, params=None, headers=None
                            ) -> tuple[Optional[dict], Optional[str]]   # never raises
async def _run_sync_in_executor(self, func, *args, **kwargs) -> Any
def _build_citation(self, source_name, source_url, data_vintage=None,
                    doi=None, license=None) -> Citation
def _failure(self, query, source, result_type, status, message) -> ResearchResult

# packages/ai-parrot-tools/src/parrot_tools/arxiv_tool.py — PORT FROM, DO NOT EDIT
class ArxivTool(AbstractTool):
    def _format_paper(self, paper: arxiv.Result) -> Dict[str, Any]
        # maps: title, authors[].name, published, updated, summary,
        #       entry_id -> arxiv_id, pdf_url, categories, primary_category
    # uses: arxiv.Client(), arxiv.Search(query, max_results, sort_by, sort_order)
    #       arxiv.SortCriterion.{Relevance,LastUpdatedDate,SubmittedDate}
    #       arxiv.SortOrder.{Ascending,Descending}
```

### API Facts (verified during spec research)

**Semantic Scholar**

| Fact | Value |
|---|---|
| Endpoint | `https://api.semanticscholar.org/graph/v1/paper/search` |
| Auth header | **`x-api-key`** (NOT `Authorization: Bearer`), optional |
| Default response | **only `paperId` + `title`** — `fields=` is mandatory |
| `limit` max | 100 per page; `/paper/search` caps at 1,000 total |
| Rate limit | unauthenticated pool is **shared globally** → 429s are common |
| Envelope | `{total, offset, next, data: [...]}` |

**arXiv**

| Fact | Value |
|---|---|
| Library | `arxiv` — extra **already exists**: `arxiv = ["arxiv>=3.0.0"]` (`pyproject.toml:79`) |
| Latest | 4.0.1 |

### Does NOT Exist

- ~~A Semantic Scholar response that includes abstracts by default~~ —
  without `fields=` you get **only** `paperId` and `title`
- ~~`Authorization: Bearer <key>` for Semantic Scholar~~ — the header is
  **`x-api-key`**
- ~~Working hyphenated Semantic Scholar queries~~ — hyphenated terms return
  **zero** matches; replace hyphens with spaces
- ~~`paperId` and `corpusId` being interchangeable~~ — distinct identifiers
- ~~A required Semantic Scholar API key~~ — free tier works; key only raises limits
- ~~`HTTPService`~~ — forbidden in this feature

---

## Implementation Notes

### Semantic Scholar — `fields` is mandatory

```python
S2_FIELDS = ("title,abstract,authors,year,venue,citationCount,"
             "openAccessPdf,externalIds,fieldsOfStudy")

params = {"query": query.replace("-", " "),   # hyphens kill matching
          "fields": S2_FIELDS,
          "limit": min(max_results, 100)}
headers = {}
if (key := config.get("SEMANTIC_SCHOLAR_API_KEY")):
    headers["x-api-key"] = key
payload, err = await self._make_api_request(S2_SEARCH_URL, params=params,
                                            headers=headers)
```
`_make_api_request` already retries with backoff — critical here because the
unauthenticated pool is shared globally and 429s are routine.

Map `externalIds.DOI` → `PaperResult.doi`; `openAccessPdf` truthy →
`open_access=True`; `venue` → `journal`; `source="semantic_scholar"`.

### arXiv — port, don't import ArxivTool

Re-implement the mapping in `_format_paper` (contract above) as a
`PaperResult` producer. Do **not** import or subclass `ArxivTool`, and do not
edit `arxiv_tool.py`. This duplication is deliberate and recorded as accepted
debt in spec §7.

```python
@backoff.on_exception(backoff.expo, Exception, max_tries=3)
def _fetch():
    search = arxiv.Search(query=q, max_results=max_results,
                          sort_by=criterion, sort_order=arxiv.SortOrder.Descending)
    return list(arxiv.Client().results(search))

results = await self._run_sync_in_executor(_fetch)
```
`sort_by` accepts `"relevance" | "lastUpdatedDate" | "submittedDate"` — map to
`arxiv.SortCriterion` exactly as `ArxivTool` does. When `category` is given,
prefix the query with `cat:<category> AND `.

Set `source="arxiv"`, `url = paper.pdf_url`, `published_date = published`.

### Key Constraints

- **Never raise.** Missing `arxiv` → `status="error"` naming the extra.
  Transport error → `status="error"` with the message. No hits →
  `status="no_data"`.
- `result_type="papers"` for both; cache TTL 24h.
- Citations: `source_name="Semantic Scholar"` / `"arXiv"`.
- Async throughout; `self.logger` at fetch boundaries.

### References in Codebase

- `packages/ai-parrot-tools/src/parrot_tools/arxiv_tool.py` — mapping to port
- `packages/ai-parrot-tools/src/parrot_tools/ddgo.py` — executor + backoff

---

## Acceptance Criteria

- [ ] Both `search_semantic_scholar` and `search_arxiv` appear in `get_tools()`.
- [ ] S2 request includes an explicit `fields=` parameter — asserted by test.
- [ ] S2 query has hyphens replaced with spaces — asserted by test.
- [ ] S2 API key, when configured, is sent as the **`x-api-key`** header (not
      `Authorization`) — asserted by test.
- [ ] S2 `limit` clamped to 100.
- [ ] Both return `result_type="papers"` with correct `source` values
      (`semantic_scholar` / `arxiv`).
- [ ] Successful results carry a complete `Citation`.
- [ ] `arxiv` called only inside `run_in_executor`.
- [ ] `packages/ai-parrot-tools/src/parrot_tools/arxiv_tool.py` is **unmodified**
      (`git diff --exit-code` on that path is clean).
- [ ] Missing `arxiv` → `status="error"`; transport error → `status="error"`;
      no hits → `status="no_data"`. No exception escapes.
- [ ] `pytest packages/ai-parrot-tools/tests/research/test_academic_s2.py
      packages/ai-parrot-tools/tests/research/test_academic_arxiv.py -v` passes offline.
- [ ] `ruff check` clean.

---

## Test Specification

```python
import pytest
from parrot_tools.research.academic import AcademicResearchToolkit


class TestSemanticScholar:
    async def test_requests_fields(self, capture_params):
        await AcademicResearchToolkit().search_semantic_scholar("graph nn")
        assert "fields" in capture_params and capture_params["fields"]

    async def test_hyphens_replaced(self, capture_params):
        await AcademicResearchToolkit().search_semantic_scholar("graph-neural-network")
        assert "-" not in capture_params["query"]

    async def test_api_key_header_name(self, monkeypatch, capture_headers):
        monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "k")
        await AcademicResearchToolkit().search_semantic_scholar("x")
        assert capture_headers.get("x-api-key") == "k"
        assert "Authorization" not in capture_headers

    async def test_maps_papers(self, mock_aiohttp_session, load_fixture):
        r = await AcademicResearchToolkit().search_semantic_scholar("x")
        assert r.papers[0].source == "semantic_scholar" and r.citation


class TestArxiv:
    async def test_maps_papers(self, mock_arxiv):
        r = await AcademicResearchToolkit().search_arxiv("transformers")
        assert r.status == "success" and r.papers[0].source == "arxiv"
        assert r.papers[0].url and r.citation.source_name == "arXiv"

    async def test_category_filter_applied(self, capture_arxiv_query):
        await AcademicResearchToolkit().search_arxiv("x", category="cs.AI")
        assert "cat:cs.AI" in capture_arxiv_query

    async def test_missing_library_is_reported_not_raised(self, monkeypatch):
        monkeypatch.setattr("parrot_tools.research.academic.arxiv", None)
        r = await AcademicResearchToolkit().search_arxiv("x")
        assert r.status == "error" and "ai-parrot-tools[research]" in r.error_message
```

---

## Agent Instructions

1. **Read the spec** — §3 Module 3, §7 "Semantic Scholar" and "ArXiv duplication".
2. **Check** TASK-2239 is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — especially the `x-api-key` header name
   and the mandatory `fields=` parameter.
4. Update the index → `"in-progress"`.
5. **Implement** two methods. Do **not** touch `arxiv_tool.py`.
6. **Verify** acceptance criteria; move to `completed/`; update index.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-08-17
**Notes**: Added `search_semantic_scholar` (explicit `fields=`, hyphens
rewritten to spaces, `x-api-key` header from `SEMANTIC_SCHOLAR_API_KEY`
— never `Authorization`, `limit` clamped to 100) and `search_arxiv`
(ported `ArxivTool._format_paper` mapping logic into a `PaperResult`
producer, `cat:<category> AND <query>` prefixing, `arxiv` called only via
`_run_sync_in_executor`). `arxiv_tool.py` is untouched — verified with
`git diff --exit-code` in a dedicated test and by hand. 10/10 new tests
pass offline (fake `arxiv` module, `_make_api_request` capture fixtures
for S2 params/headers); full research suite (59 tests) green; `ruff
check` clean.
**Deviations from spec**: none
