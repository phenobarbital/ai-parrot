# TASK-2238: AcademicResearchToolkit — Crossref search

**Feature**: FEAT-426 — Research Tools for Agents
**Spec**: `sdd/specs/research-tools-for-agents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2234
**Assigned-to**: unassigned

---

## Context

First slice of spec §3 Module 3. Creates `AcademicResearchToolkit` (the class
shell) plus its Crossref method. Tasks 2239-2241 add methods to the **same
file**, so they run after this one in the same worktree.

This chain (2238 → 2239 → 2240 → 2241) is independent of the open-data chain
(2235 → 2237) and may run in a parallel worktree.

Crossref also covers **Oxford Academic** content (OUP DOI prefix `10.1093`) —
OUP has no API of its own, so there is no separate Oxford source anywhere in
this feature.

---

## Scope

- Create `parrot_tools/research/academic.py` with
  `class AcademicResearchToolkit(BaseResearchToolkit, AbstractToolkit)`.
- Implement `search_crossref(query, author=None, year_range=None,
  journal=None, max_results=10) -> ResearchResult`.
- Wrap `habanero` in `run_in_executor`; use the polite pool; map hits into
  `PaperResult`; attach a `Citation`; cache.
- Recorded fixture + unit tests.

**NOT in scope**: PubMed (2239), Semantic Scholar / arXiv (2240),
`get_paper_details` (2241), exports (2243).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/research/academic.py` | CREATE | `AcademicResearchToolkit` + Crossref method |
| `packages/ai-parrot-tools/tests/research/test_academic_crossref.py` | CREATE | Unit tests |
| `packages/ai-parrot-tools/tests/research/fixtures/crossref_works.json` | CREATE | Recorded `/works` payload |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.tools.toolkit import AbstractToolkit
from parrot_tools.research.base import BaseResearchToolkit          # TASK-2234
from parrot_tools.research.models import ResearchResult, PaperResult, Citation
from navconfig import config          # env access, e.g. CROSSREF_MAILTO
import asyncio, backoff

try:
    from habanero import Crossref
except ImportError:
    Crossref = None
```

`habanero` ships in the `research` extra (TASK-2234). PyPI latest at spec
time: **2.9.2**.

### Existing Signatures to Use

```python
# From TASK-2234 — parrot_tools/research/base.py
async def _run_sync_in_executor(self, func, *args, **kwargs) -> Any
def _build_citation(self, source_name, source_url, data_vintage=None,
                    doi=None, license=None) -> Citation
def _failure(self, query, source, result_type, status, message) -> ResearchResult
self._cache: ToolCache

# From TASK-2234 — parrot_tools/research/models.py
class PaperResult(BaseModel):
    title: str
    authors: List[str] = []
    abstract: Optional[str] = None
    published_date: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    journal: Optional[str] = None
    citation_count: Optional[int] = None
    fields_of_study: Optional[List[str]] = None
    open_access: Optional[bool] = None
    source: str
```

### API Facts (verified during spec research)

| Fact | Value |
|---|---|
| Base URL | `https://api.crossref.org` |
| Auth | none; **polite pool** via `mailto` (no registration) |
| Rate limit | dynamic, advertised in `X-Rate-Limit-Limit` / `X-Rate-Limit-Interval` |
| Envelope | `{status, message-type, message: {total-results, items[]}}` |
| `offset` cap | **10,000** on `/works` — deep paging needs `cursor=*` |
| Relevance tip | prefer `query.bibliographic` over generic `query` |

### Does NOT Exist

- ~~An Oxford Academic API~~ — `academic.oup.com` has **no public API and no
  OAI-PMH feed**. Reach OUP content via Crossref DOI prefix `10.1093`.
- ~~A fixed numeric Crossref rate limit~~ — read the response headers; do not
  hardcode.
- ~~Cursor pagination outside the `/works` family~~
- ~~`HTTPService`~~ — forbidden in this feature

---

## Implementation Notes

### Pattern to Follow

```python
@backoff.on_exception(backoff.expo, Exception, max_tries=3)
def _fetch():
    cr = Crossref(mailto=config.get("CROSSREF_MAILTO", "noreply@example.com"))
    return cr.works(query_bibliographic=query, limit=max_results, filter=filters)

payload = await self._run_sync_in_executor(_fetch)
items = payload.get("message", {}).get("items", [])
```

### Polite pool is required

Always pass `mailto`. Read it from `CROSSREF_MAILTO` with a safe default.
Crossref routes `mailto` traffic to a better-served pool, and its docs ask
for either `mailto` or an identifying User-Agent.

### Field mapping notes

- `title` arrives as a **list** — take the first element, guard against empty.
- `author` entries are `{given, family}` dicts — join into `"Given Family"`.
- `container-title` is also a list → `journal`.
- `issued.date-parts` is a nested list → `published_date`.
- `source="crossref"` on every `PaperResult`.

### Key Constraints

- **Never raise.** Missing `habanero` → `status="error"` naming the
  `research` extra. No items → `status="no_data"`.
- `result_type="papers"`; cache TTL 24h (papers are slow-changing).
- Citation: `source_name="Crossref"`, `source_url=f"https://doi.org/{doi}"`
  for a single work, or the query URL when summarising a set; set
  `citation.doi` when available.
- Async throughout; `self.logger` around the fetch.

### References in Codebase

- `packages/ai-parrot-tools/src/parrot_tools/ddgo.py` — executor + backoff
- `packages/ai-parrot-tools/src/parrot_tools/arxiv_tool.py` — paper-mapping shape

---

## Acceptance Criteria

- [ ] `AcademicResearchToolkit` subclasses `(BaseResearchToolkit,
      AbstractToolkit)` in that order and constructs without error.
- [ ] `get_tools()` includes `search_crossref`.
- [ ] Returns `ResearchResult` with `result_type="papers"`, entries carrying
      `source="crossref"` and a `doi` when present.
- [ ] The request includes a `mailto` (polite pool) — asserted by test.
- [ ] `query.bibliographic` is used rather than the generic `query` param.
- [ ] List-valued `title` / `container-title` handled without IndexError on
      empty lists.
- [ ] Successful results carry a complete `Citation`.
- [ ] `habanero` called only inside `run_in_executor`.
- [ ] Missing `habanero` → `status="error"` naming `ai-parrot-tools[research]`.
- [ ] Empty results → `status="no_data"`.
- [ ] `pytest packages/ai-parrot-tools/tests/research/test_academic_crossref.py -v`
      passes offline.
- [ ] `ruff check` clean.

---

## Test Specification

```python
import pytest
from parrot_tools.research.academic import AcademicResearchToolkit


class TestCrossref:
    async def test_search_maps_papers(self, mock_habanero, load_fixture):
        r = await AcademicResearchToolkit().search_crossref("transformer time series")
        assert r.status == "success" and r.result_type == "papers"
        assert r.papers and r.papers[0].source == "crossref"
        assert r.papers[0].doi and r.papers[0].title
        assert r.citation.source_name == "Crossref"

    async def test_uses_polite_pool(self, capture_crossref_kwargs):
        await AcademicResearchToolkit().search_crossref("x")
        assert capture_crossref_kwargs["mailto"]

    async def test_uses_bibliographic_query(self, capture_crossref_call):
        await AcademicResearchToolkit().search_crossref("x")
        assert "query_bibliographic" in capture_crossref_call.kwargs

    async def test_empty_title_list_does_not_raise(self, mock_habanero_empty_title):
        r = await AcademicResearchToolkit().search_crossref("x")
        assert r.status in {"success", "no_data"}

    async def test_missing_library_is_reported_not_raised(self, monkeypatch):
        monkeypatch.setattr("parrot_tools.research.academic.Crossref", None)
        r = await AcademicResearchToolkit().search_crossref("x")
        assert r.status == "error" and "ai-parrot-tools[research]" in r.error_message
```

---

## Agent Instructions

1. **Read the spec** — §2 Error Contract, §3 Module 3, §7 gotchas.
2. **Check** TASK-2234 is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** before writing code.
4. Update the index → `"in-progress"`.
5. **Implement** the class shell + Crossref only.
6. **Verify** acceptance criteria; move to `completed/`; update index.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-08-17
**Notes**: `AcademicResearchToolkit(BaseResearchToolkit, AbstractToolkit)`
with `search_crossref`, using `query_bibliographic` (not the generic
`query` param), always passing `mailto` (polite pool, from
`CROSSREF_MAILTO` via `navconfig.config.get(..., fallback=...)` — note
`config.get`'s 2nd positional arg is `section`, not a default; caught this
via a failing test and fixed to the `fallback=` keyword). List-valued
`title`/`container-title` and nested `issued.date-parts` handled
defensively (no IndexError on empty lists). Cached 24h (papers are
slow-changing). 5/5 new tests pass offline against a fake `Crossref`
class; full research suite (43 tests) green; `ruff check` clean.
**Deviations from spec**: none
