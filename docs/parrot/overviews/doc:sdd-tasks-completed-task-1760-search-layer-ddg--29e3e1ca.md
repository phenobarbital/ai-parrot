---
type: Wiki Overview
title: 'TASK-1760: Search layer — SourceConfig registry, DDG-first `_search_company_url`,
  hit validation'
id: doc:sdd-tasks-completed-task-1760-search-layer-ddg-first-validation-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Add to `packages/ai-parrot-tools/src/parrot_tools/company_info/tool.py`:'
relates_to:
- concept: mod:parrot_tools.company_info
  rel: mentions
---

# TASK-1760: Search layer — SourceConfig registry, DDG-first `_search_company_url`, hit validation

**Feature**: FEAT-305 — CompanyResearch — extend CompanyInfoToolkit
**Spec**: `sdd/specs/companyresearch-tool.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1759
**Assigned-to**: unassigned

---

## Context

> Implements spec Module 1 (§3) and acceptance-criterion "DDG-first with Google
> CSE fallback; hit accepted only after title-keyword + name validation (fuzzy
> threshold 85)". This is the search-and-validate substrate every per-source
> scrape method will call instead of hitting Google directly.

---

## Scope

Add to `packages/ai-parrot-tools/src/parrot_tools/company_info/tool.py`:

- **`SourceConfig` model** (internal Pydantic model, NOT a tool schema):
  `name`, `site`, `search_template`, `title_keywords: List[str]`.
- **Source registry**: a class-level (or module-level) mapping of all 6 sources
  — `leadiq`, `rocketreach`, `explorium`, `siccode`, `visualvisitor`,
  `zoominfo` — each with its `site`, `search_template` (`"site:{site} {}"`),
  and `title_keywords` ported from the flowtask per-source parsers (see
  Codebase Contract for line refs).
- **`_search_company_url(self, company_name, site_config) -> Optional[str]`**:
  1. DDG search first via `ddgs.DDGS` (run the sync client in an executor;
     wrap with `backoff` on `RatelimitException` — mirror `ddgo.py`).
  2. On DDG ratelimit/failure, fall back to the existing `_google_site_search`.
  3. Validate each candidate hit with `_validate_search_hit` before accepting;
     return the first accepted URL (cleaned).
  4. Log at INFO when falling back to Google CSE (it costs quota).
- **`_validate_search_hit(self, title, url, company_name, keywords) -> bool`**:
  title must contain at least one of `keywords`; company name must match via
  flowtask `_check_company_name` semantics — exact match → first-token match →
  `rapidfuzz` ratio > 85.
- **URL cleanup helper**: strip trailing `/employee-directory` and
  `/email-format` suffixes (flowtask `scrapper.py:919-922`).

**NOT in scope**: switching the existing `scrape_*` methods to call the new
search (that is TASK-1763 wiring); the Playwright fetch layer (TASK-1761);
`scrape_visualvisitor` (TASK-1762). Leave `_google_site_search` in place — it
becomes the fallback.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/company_info/tool.py` | MODIFY | Add `SourceConfig`, registry, `_search_company_url`, `_validate_search_hit`, URL cleanup |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-07-13 on `dev`.

### Verified Imports
```python
from ddgs import DDGS                                   # ddgo.py:11
from ddgs.exceptions import RatelimitException          # ddgo.py:12-14
import backoff                                          # core dep (backoff==2.2.1)
from rapidfuzz import fuzz                              # ADDED by TASK-1759 (fuzz.ratio)
from pydantic import BaseModel                          # already used in tool.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/company_info/tool.py
class CompanyInfoToolkit(AbstractToolkit):              # line 163
    async def _google_site_search(self, company_name: str, site: str,
        additional_terms: str = "", max_results: int = 5
    ) -> GoogleSearchResult:                            # line 266  (KEEP — becomes fallback)
class GoogleSearchResult(BaseModel):                    # line 149  (return type of the fallback)

# DDG usage pattern to mirror (backoff + run_in_executor for the sync client):
#   packages/ai-parrot-tools/src/parrot_tools/ddgo.py:90 (backoff decorator), :124 (DDGS()), :97 (.text)

# flowtask reference (READ-ONLY, /home/jesuslara/proyectos/flowtask/flowtask/components/CompanyScraper/):
#   scrapper.py:741-770  _check_company_name  -> exact / first-token / fuzz.ratio > 85
#   scrapper.py:919-922  URL suffix cleanup (/employee-directory, /email-format)
#   parsers/leadiq.py:12-18, rocket.py:12-17, zoominfo.py:20-23,
#   parsers/siccode.py:20-23, visualvisitor.py:12-15, explorium.py:12-14  -> title_keywords
```

### Does NOT Exist
- ~~`from duckduckgo_search import DDGS`~~ — satellite uses `ddgs`.
- ~~`fuzzywuzzy`~~ — use `rapidfuzz.fuzz` (installed by TASK-1759).
- ~~`CompanyInfoToolkit` inherits `HTTPService`~~ — it does NOT; call `ddgs.DDGS`
  directly, do not reach for `HTTPService._search_duckduckgo`.

---

## Implementation Notes

### Pattern to Follow
```python
# Mirror ddgo.py's backoff + executor wrapping of the sync DDGS client:
@backoff.on_exception(backoff.expo, RatelimitException, max_tries=3)
async def _ddg_search(self, query: str, max_results: int = 5) -> list[dict]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: list(DDGS().text(query, max_results=max_results)))
```

### Key Constraints
- Async throughout; never block the loop with the sync DDGS client.
- Never raise out of `_search_company_url` — return `None` on total failure so
  callers degrade to `no_data`.
- `self.logger` at key points (INFO on Google fallback).
- fuzzy threshold is **85** (strictly `> 85` per flowtask semantics).
- Google-style docstrings; Pydantic for `SourceConfig`.

---

## Acceptance Criteria

- [ ] `SourceConfig` defined; registry has all 6 sources with site/template/keywords.
- [ ] `_search_company_url` tries DDG first, falls back to `_google_site_search`.
- [ ] `_validate_search_hit` implements exact / first-token / fuzzy>85 name match
      plus title-keyword presence.
- [ ] URL suffix cleanup strips `/employee-directory` and `/email-format`.
- [ ] `_google_site_search` still present (unchanged) as fallback.
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/company_info/tool.py` clean.
- [ ] Import works: `from parrot_tools.company_info import CompanyInfoToolkit`.

---

## Test Specification

> Full tests live in TASK-1764; this task must at minimum leave the module
> importable and the helpers unit-testable in isolation. Suggested assertions
> the TASK-1764 suite will rely on:

```python
# test_source_configs_complete: all 6 names present with non-empty keywords
# test_validate_hit_exact/fuzzy/reject: exact ok; ratio>85 ok; mismatch rejected
# test_search_ddg_first_google_fallback: DDG mocked to RatelimitException -> _google_site_search called
# test_url_suffix_cleanup: ".../acme/employee-directory" -> ".../acme"
```

---

## Agent Instructions

1. Read the spec §2-§3 and §7; re-verify the tool.py line refs before editing.
2. Verify TASK-1759 is in `sdd/tasks/completed/` (rapidfuzz/ddgs installed).
3. Verify the Codebase Contract; update it FIRST if anything drifted.
4. Implement per scope.
5. Verify acceptance criteria.
6. Move this file to `sdd/tasks/completed/`; update the per-spec index to `done`.
7. Fill in the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Sonnet 5)
**Date**: 2026-07-14
**Notes**: Added `SourceConfig` (Pydantic, not a tool schema) and the
`COMPANY_SOURCES` registry with all 6 sources (site/search_template/
title_keywords ported verbatim from flowtask's per-source parsers). Added
`_ddg_search` (backoff-wrapped, run_in_executor, mirrors `ddgo.py`),
`_clean_search_url` (suffix strip for `/employee-directory` and
`/email-format`, mirrors `scrapper.py:919-922`), `_validate_search_hit`
(keyword-anchored title match + exact/first-token/`rapidfuzz` fuzzy>85,
mirrors `_check_company_name` scrapper.py:741-770), and
`_search_company_url` (DDG-first, Google CSE fallback via the existing
`_google_site_search`, INFO log on fallback). `_google_site_search` left
unchanged. Verified with ad-hoc smoke scripts (exact/fuzzy/reject
validation, URL cleanup, DDG-success-no-fallback and
DDG-ratelimit-triggers-fallback paths) — full pytest suite lands in
TASK-1764. `ruff check` shows the same 6 pre-existing F401 selenium-import
errors as before this change (unrelated to this task; TASK-1761 removes
the selenium imports).
**Deviations from spec**: none
