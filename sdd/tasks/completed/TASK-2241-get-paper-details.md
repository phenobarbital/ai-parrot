# TASK-2241: AcademicResearchToolkit — get_paper_details resolver

**Feature**: FEAT-426 — Research Tools for Agents
**Spec**: `sdd/specs/research-tools-for-agents.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2240
**Assigned-to**: unassigned

---

## Context

Final slice of spec §3 Module 3. Adds a single-paper lookup that dispatches
across the three identifier-addressable sources built in TASKs 2238-2240.
It is last in the chain because it calls into all of them.

Completing this task closes the academic chain; together with TASK-2237 it
unblocks the router (TASK-2242).

---

## Scope

- Add `get_paper_details(doi_or_id, source=None) -> ResearchResult` to
  `AcademicResearchToolkit`.
- Auto-detect the identifier format when `source` is not given; honour
  `source` when it is.
- Return a `ResearchResult` with `result_type="papers"` containing
  **exactly one** entry in `.papers` (or `status="no_data"`).
- Unit tests.

**NOT in scope**: the search methods (2238-2240), the router (2242),
exports (2243). Do not add new external dependencies.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/research/academic.py` | MODIFY | Add one method + an id-detection helper |
| `packages/ai-parrot-tools/tests/research/test_academic_details.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot_tools.research.models import ResearchResult, PaperResult, Citation
import re
# No new third-party imports — reuses habanero / Entrez / aiohttp already
# wired by TASK-2238, TASK-2239 and TASK-2240.
```

### Existing Signatures to Use

```python
# From TASK-2234 — parrot_tools/research/base.py
async def _make_api_request(self, url, params=None, headers=None
                            ) -> tuple[Optional[dict], Optional[str]]
async def _run_sync_in_executor(self, func, *args, **kwargs) -> Any
def _build_citation(self, source_name, source_url, data_vintage=None,
                    doi=None, license=None) -> Citation
def _failure(self, query, source, result_type, status, message) -> ResearchResult

# From TASKs 2238-2240 — same class, already implemented
class AcademicResearchToolkit(BaseResearchToolkit, AbstractToolkit):
    async def search_crossref(...) -> ResearchResult
    async def search_pubmed(...) -> ResearchResult
    async def search_semantic_scholar(...) -> ResearchResult
    async def search_arxiv(...) -> ResearchResult
```

### Identifier formats (for detection)

| Kind | Shape | Example | Route to |
|---|---|---|---|
| DOI | starts `10.` + `/` | `10.1093/nar/gkaa1100` | Crossref |
| PMID | all digits, ~7-8 chars | `33095870` | PubMed |
| arXiv | `NNNN.NNNNN`, opt. `vN`, or legacy `cs/0112017` | `2103.14030` | arXiv |
| S2 | 40-char hex `paperId`, or prefixed `DOI:`/`ARXIV:`/`PMID:`/`CorpusID:` | `649def34f8be52c8b66281af98ae884c09aef38b` | Semantic Scholar |

### Does NOT Exist

- ~~A universal cross-source paper-resolution API~~ — dispatch is our own logic
- ~~`paperId` == `corpusId`~~ — distinct, non-interchangeable Semantic Scholar ids
- ~~An Oxford Academic lookup path~~ — OUP DOIs (`10.1093/...`) resolve through
  **Crossref**, like any other DOI
- ~~A `PaperResult` list for this method~~ — it returns a `ResearchResult`
  whose `.papers` holds **one** element (spec §2 New Public Interfaces)
- ~~`HTTPService`~~ — forbidden in this feature

---

## Implementation Notes

### Detection helper

```python
_DOI_RE   = re.compile(r"^10\.\d{4,9}/\S+$", re.I)
_PMID_RE  = re.compile(r"^\d{6,9}$")
_ARXIV_RE = re.compile(r"^(\d{4}\.\d{4,5}(v\d+)?|[a-z-]+(\.[A-Z]{2})?/\d{7})$", re.I)
_S2_RE    = re.compile(r"^[0-9a-f]{40}$", re.I)

def _detect_source(self, ident: str) -> Optional[str]:
    """Return 'crossref' | 'pubmed' | 'arxiv' | 'semantic_scholar' | None."""
```
Also accept Semantic Scholar's explicit prefixes (`DOI:`, `ARXIV:`, `PMID:`,
`CorpusID:`) by stripping and re-routing on the bare value.

### Dispatch

Reuse the existing search methods with a tightly-scoped query rather than
writing new transport:

- `crossref` → Crossref works lookup by DOI
- `pubmed` → `efetch` for the single PMID
- `arxiv` → `arxiv.Search(id_list=[...])`
- `semantic_scholar` → `/paper/{paper_id}` with the same `fields=` set

Normalise every branch down to **one** `PaperResult`.

### Key Constraints

- **Never raise.** Unrecognised identifier → `status="error"` with a message
  naming the accepted formats. Not found → `status="no_data"`.
- Explicit `source` wins over auto-detection; an invalid `source` value →
  `status="error"` listing the valid options.
- `result_type="papers"`; `len(result.papers) == 1` on success.
- Successful results carry a complete `Citation` (with `doi` set when known).
- Cache TTL 24h.
- The docstring should tell the LLM it accepts a DOI, PMID, arXiv id, or
  Semantic Scholar paperId.

### References in Codebase

- The three sibling methods added in TASKs 2238-2240 — mirror their
  error/citation shape exactly.

---

## Acceptance Criteria

- [ ] `get_paper_details` present in `AcademicResearchToolkit.get_tools()`.
- [ ] DOI, PMID, arXiv id and S2 paperId each route to the correct source —
      asserted by four tests.
- [ ] Prefixed forms (`DOI:10.1093/...`, `PMID:33095870`) are accepted.
- [ ] Explicit `source` overrides auto-detection.
- [ ] Invalid `source` → `status="error"` listing valid options.
- [ ] Unrecognised identifier → `status="error"` naming accepted formats.
- [ ] Not found → `status="no_data"`.
- [ ] On success `result_type == "papers"` and `len(papers) == 1`.
- [ ] Successful results carry a complete `Citation`.
- [ ] `pytest packages/ai-parrot-tools/tests/research/test_academic_details.py -v`
      passes offline.
- [ ] `ruff check` clean.

---

## Test Specification

```python
import pytest
from parrot_tools.research.academic import AcademicResearchToolkit


class TestGetPaperDetails:
    @pytest.mark.parametrize("ident,expected", [
        ("10.1093/nar/gkaa1100", "crossref"),
        ("33095870", "pubmed"),
        ("2103.14030", "arxiv"),
        ("649def34f8be52c8b66281af98ae884c09aef38b", "semantic_scholar"),
    ])
    def test_detects_source(self, ident, expected):
        assert AcademicResearchToolkit()._detect_source(ident) == expected

    def test_accepts_prefixed_ids(self):
        tk = AcademicResearchToolkit()
        assert tk._detect_source("DOI:10.1093/nar/gkaa1100") == "crossref"
        assert tk._detect_source("PMID:33095870") == "pubmed"

    async def test_returns_single_paper(self, mock_habanero):
        r = await AcademicResearchToolkit().get_paper_details("10.1093/nar/gkaa1100")
        assert r.result_type == "papers" and len(r.papers) == 1
        assert r.citation.doi == "10.1093/nar/gkaa1100"

    async def test_explicit_source_overrides(self, mock_all_sources, call_log):
        await AcademicResearchToolkit().get_paper_details("2103.14030", source="semantic_scholar")
        assert call_log[-1] == "semantic_scholar"

    async def test_invalid_source_is_error(self):
        r = await AcademicResearchToolkit().get_paper_details("10.1/x", source="bogus")
        assert r.status == "error" and "bogus" in r.error_message

    async def test_unrecognised_id_is_error(self):
        r = await AcademicResearchToolkit().get_paper_details("!!!")
        assert r.status == "error"

    async def test_not_found_is_no_data(self, mock_habanero_empty):
        r = await AcademicResearchToolkit().get_paper_details("10.9999/nope")
        assert r.status == "no_data"
```

---

## Agent Instructions

1. **Read the spec** — §2 New Public Interfaces (note the single-entry
   `.papers` contract) and §2 Error Contract.
2. **Check** TASK-2240 is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** before writing code.
4. Update the index → `"in-progress"`.
5. **Implement** one method + the detection helper. Reuse existing transport.
6. **Verify** acceptance criteria; move to `completed/`; update index.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-08-17
**Notes**: Added `get_paper_details` + `_detect_source`/`_strip_id_prefix`
helpers to `AcademicResearchToolkit`. Reuses existing transport rather
than adding new dependencies: Crossref via `cr.works(ids=doi)`, PubMed via
the existing `_pubmed_efetch([pmid])` (skips `esearch`), arXiv via
`arxiv.Search(id_list=[...])`, Semantic Scholar via `/paper/{paper_id}`
with the same `fields=` set as search. Explicit `source` overrides
auto-detection; prefixed ids (`DOI:`, `PMID:`, `ARXIV:`, `CorpusID:`) are
accepted. Closes the academic chain (2238-2241) — together with TASK-2237
this unblocks TASK-2242 (router). 11/11 new tests pass offline; full
research suite (70 tests) green; `ruff check` clean.
**Deviations from spec**: none
