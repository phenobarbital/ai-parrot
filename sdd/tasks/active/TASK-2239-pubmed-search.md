# TASK-2239: AcademicResearchToolkit — PubMed search

**Feature**: FEAT-426 — Research Tools for Agents
**Spec**: `sdd/specs/research-tools-for-agents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2238
**Assigned-to**: unassigned

---

## Context

Second slice of spec §3 Module 3. Adds PubMed to the `AcademicResearchToolkit`
created in TASK-2238. Same file → sequential.

PubMed is the only source in this feature with a **mandatory two-call
workflow** (`esearch` → `efetch`) and **hard documented rate limits**, so it
needs more care than the others.

---

## Scope

- Add `search_pubmed(query, mesh_terms=None, date_range=None,
  max_results=10) -> ResearchResult` to `AcademicResearchToolkit`.
- Two-step `Bio.Entrez.esearch` (query → PMIDs) then `Bio.Entrez.efetch`
  (PMIDs → records), both via `run_in_executor`.
- Set `Entrez.email` (required by NCBI) and optional `Entrez.api_key`.
- Throttle to NCBI's documented limits.
- Recorded fixtures + unit tests.

**NOT in scope**: Crossref (2238), Semantic Scholar / arXiv (2240),
`get_paper_details` (2241), exports (2243).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/research/academic.py` | MODIFY | Add one method (+ Entrez config helper) |
| `packages/ai-parrot-tools/tests/research/test_academic_pubmed.py` | CREATE | Unit tests |
| `packages/ai-parrot-tools/tests/research/fixtures/pubmed_esearch.xml` | CREATE | Recorded esearch response |
| `packages/ai-parrot-tools/tests/research/fixtures/pubmed_efetch.xml` | CREATE | Recorded efetch response |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot_tools.research.models import ResearchResult, PaperResult, Citation
from navconfig import config          # NCBI_EMAIL, NCBI_API_KEY
import asyncio, backoff

try:
    from Bio import Entrez            # distribution is `biopython`
except ImportError:
    Entrez = None
```

> **Name trap**: the pip package is **`biopython`**, the import is
> **`from Bio import Entrez`**. PyPI latest at spec time: **1.88**. Ships in
> the `research` extra (TASK-2234).

### Existing Signatures to Use

```python
# From TASK-2234 — parrot_tools/research/base.py
async def _run_sync_in_executor(self, func, *args, **kwargs) -> Any
def _build_citation(self, source_name, source_url, data_vintage=None,
                    doi=None, license=None) -> Citation
def _failure(self, query, source, result_type, status, message) -> ResearchResult
self._cache: ToolCache

# From TASK-2238 — the class this method is added to
class AcademicResearchToolkit(BaseResearchToolkit, AbstractToolkit): ...
```

### API Facts (verified during spec research)

| Fact | Value |
|---|---|
| Base URL | `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/` |
| Workflow | **two calls**: `esearch` → PMIDs, then `efetch` → records |
| Auth | none required; optional free `api_key` raises limits |
| Rate limit | **3 req/s** unkeyed, **10 req/s** keyed (documented, enforced) |
| `efetch` format | **XML or plain text only — no JSON for full records** |
| NCBI requirement | an identifying `email` (and ideally `tool`) must be set |

### Does NOT Exist

- ~~`pymed`~~ — **ABANDONED**, last release 2019. Do **not** use it.
- ~~A single-call PubMed search returning full records~~ — the two-step
  esearch→efetch workflow is mandatory.
- ~~JSON output from `efetch` for full article records~~ — XML only.
  (`esearch`/`esummary` do support `retmode="json"`.)
- ~~`HTTPService`~~ — forbidden in this feature

---

## Implementation Notes

### Pattern to Follow

```python
def _configure_entrez() -> None:
    Entrez.email = config.get("NCBI_EMAIL", "noreply@example.com")   # REQUIRED
    api_key = config.get("NCBI_API_KEY")
    if api_key:
        Entrez.api_key = api_key
    Entrez.tool = "ai-parrot-research"

@backoff.on_exception(backoff.expo, Exception, max_tries=3)
def _esearch():
    with Entrez.esearch(db="pubmed", term=term, retmax=max_results) as h:
        return Entrez.read(h)

@backoff.on_exception(backoff.expo, Exception, max_tries=3)
def _efetch(pmids):
    with Entrez.efetch(db="pubmed", id=",".join(pmids), retmode="xml") as h:
        return Entrez.read(h)
```

Both run through `self._run_sync_in_executor(...)`. Short-circuit: if
`esearch` returns an empty `IdList`, return `status="no_data"` **without**
calling `efetch`.

### Rate limiting

Respect 3 req/s unkeyed / 10 req/s keyed. A simple `asyncio.Semaphore(1)`
plus a small inter-call delay is sufficient at this scale — do not fire
esearch and efetch back-to-back without spacing when unkeyed.

### Query construction

Combine `query` with `mesh_terms` using PubMed field tags, e.g.
`f'{query} AND {mesh} [MeSH Terms]'`, and `date_range` via
`AND ("2020"[Date - Publication] : "2026"[Date - Publication])`.
Use `+` rather than raw spaces where the term is placed directly in a URL,
and percent-encode special characters.

### Field mapping notes

- Title: `MedlineCitation.Article.ArticleTitle`
- Authors: `AuthorList` entries → `"ForeName LastName"`
- Abstract: `Article.Abstract.AbstractText` (may be a list of labelled parts —
  join them)
- DOI: from `PubmedData.ArticleIdList` where `IdType == "doi"`
- Journal: `Article.Journal.Title`
- `source="pubmed"`; `url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"`

### Key Constraints

- **Never raise.** Missing `biopython` → `status="error"` naming the
  `research` extra. Empty IdList → `status="no_data"`.
- `result_type="papers"`; cache TTL 24h.
- Citation `source_name="PubMed"`.
- Async throughout; `self.logger` around both calls.

### References in Codebase

- `packages/ai-parrot-tools/src/parrot_tools/ddgo.py` — executor + backoff

---

## Acceptance Criteria

- [ ] `search_pubmed` present in `AcademicResearchToolkit.get_tools()`.
- [ ] `Entrez.email` is set before any Entrez call — asserted by test.
- [ ] `Entrez.api_key` is set when `NCBI_API_KEY` is present, and omitted when not.
- [ ] Two-step workflow: `esearch` then `efetch`, in that order — asserted by test.
- [ ] Empty `IdList` short-circuits to `status="no_data"` **without** calling
      `efetch` — asserted by test.
- [ ] Returns `ResearchResult` with `result_type="papers"`, entries carrying
      `source="pubmed"` and a PubMed `url`.
- [ ] Multi-part `AbstractText` is joined into a single string.
- [ ] Successful results carry a complete `Citation`.
- [ ] Entrez called only inside `run_in_executor`.
- [ ] Missing `biopython` → `status="error"` naming `ai-parrot-tools[research]`.
- [ ] `pytest packages/ai-parrot-tools/tests/research/test_academic_pubmed.py -v`
      passes offline with fixtures.
- [ ] `ruff check` clean.

---

## Test Specification

```python
import pytest
from parrot_tools.research.academic import AcademicResearchToolkit


class TestPubMed:
    async def test_two_step_workflow(self, mock_entrez, call_order):
        await AcademicResearchToolkit().search_pubmed("crispr")
        assert call_order == ["esearch", "efetch"]

    async def test_sets_email(self, mock_entrez):
        await AcademicResearchToolkit().search_pubmed("crispr")
        assert mock_entrez.email

    async def test_maps_papers(self, mock_entrez, load_fixture):
        r = await AcademicResearchToolkit().search_pubmed("crispr")
        assert r.status == "success" and r.result_type == "papers"
        p = r.papers[0]
        assert p.source == "pubmed" and p.title and p.url.startswith("https://pubmed")

    async def test_empty_idlist_skips_efetch(self, mock_entrez_empty, call_order):
        r = await AcademicResearchToolkit().search_pubmed("zzzz")
        assert r.status == "no_data" and "efetch" not in call_order

    async def test_multipart_abstract_joined(self, mock_entrez_multipart):
        r = await AcademicResearchToolkit().search_pubmed("x")
        assert isinstance(r.papers[0].abstract, str)

    async def test_missing_library_is_reported_not_raised(self, monkeypatch):
        monkeypatch.setattr("parrot_tools.research.academic.Entrez", None)
        r = await AcademicResearchToolkit().search_pubmed("x")
        assert r.status == "error" and "ai-parrot-tools[research]" in r.error_message
```

---

## Agent Instructions

1. **Read the spec** — §3 Module 3, §7 "PubMed" gotcha.
2. **Check** TASK-2238 is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — especially the `biopython`/`Bio` name trap
   and the "`pymed` is abandoned" entry.
4. Update the index → `"in-progress"`.
5. **Implement** exactly one method; leave Crossref untouched.
6. **Verify** acceptance criteria; move to `completed/`; update index.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
