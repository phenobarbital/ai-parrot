---
type: Wiki Overview
title: 'TASK-1762: `scrape_visualvisitor` per-source extractor'
id: doc:sdd-tasks-completed-task-1762-scrape-visualvisitor-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'In `packages/ai-parrot-tools/src/parrot_tools/company_info/tool.py`:'
relates_to:
- concept: mod:parrot.tools.decorators
  rel: mentions
- concept: mod:parrot_tools.company_info
  rel: mentions
- concept: mod:parrot_tools.decorators
  rel: mentions
---

# TASK-1762: `scrape_visualvisitor` per-source extractor

**Feature**: FEAT-305 — CompanyResearch — extend CompanyInfoToolkit
**Spec**: `sdd/specs/companyresearch-tool.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1760, TASK-1761
**Assigned-to**: unassigned

---

## Context

> Implements spec Module 3 (§3) and acceptance criterion "`scrape_visualvisitor`
> exists with `source_platform='visualvisitor'`". Adds the one missing source
> (VisualVisitor) to bring parity with flowtask's six extractors, fixing
> flowtask's copy-paste `source_platform` mislabel along the way.

---

## Scope

In `packages/ai-parrot-tools/src/parrot_tools/company_info/tool.py`:

- Add `async def scrape_visualvisitor(self, company_name, return_json=False)
  -> Union[CompanyInfo, str]`, decorated `@tool_schema(CompanyInput)`, following
  the exact shape of `scrape_zoominfo` (init `CompanyInfo(scrape_status="pending")`,
  never raise, set `scrape_status`/`error_message` on failure).
- Use `_search_company_url` (TASK-1760) with the `visualvisitor` `SourceConfig`
  to find the URL, and `_fetch_page` (TASK-1761) to fetch the page.
- Port selectors from flowtask `parsers/visualvisitor.py:32-125`
  (`.company-header`, `.headline-summary` table walk).
- Set `source_platform="visualvisitor"` (do NOT reproduce flowtask's mislabel
  of `"rocketreach"` at visualvisitor.py:42).
- Add/reuse a NAICS/SIC `_extract_codes` regex helper for code extraction.

**NOT in scope**: the search/fetch layers (TASK-1760/1761); wiring
`visualvisitor` into `research_company` (TASK-1763 — but ensure the method is
callable so 1763 can add it to the priority loop); tests (TASK-1764).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/company_info/tool.py` | MODIFY | Add `scrape_visualvisitor` + `_extract_codes` helper |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-07-13 on `dev`.

### Verified Imports
```python
from parrot_tools.decorators import tool_schema     # decorators.py:2 (re-export of parrot.tools.decorators)
from bs4 import BeautifulSoup                        # satellite dep
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/company_info/tool.py
class CompanyInput(BaseModel):                       # line 75  (company_name; return_json=False)
class CompanyInfo(BaseModel):                        # line 83  (fields 88-137)
    scrape_status: str = "pending"                   # line 92
    source_platform: str                             # set to "visualvisitor"
    def to_json(self, **kwargs) -> str               # line 139
class CompanyInfoToolkit(AbstractToolkit):           # line 163 (as landed by TASK-1760/1761)
    async def scrape_zoominfo(self, company_name, return_json=False)  # @tool_schema(CompanyInput)  (COPY THIS SHAPE)
    def _parse_address(self, address_text) -> Dict   # reuse for address parsing
    def _standardize_name(self, name) -> str         # reuse
# NEW from sibling tasks (verified present in this worktree — TASK-1760/1761 landed):
    async def _search_company_url(self, company_name: str, site_config: SourceConfig) -> Optional[str]   # TASK-1760 (ASYNC — contract corrected; must be awaited)
    async def _fetch_page(self, url: str, custom_user_agent: Optional[str] = None) -> Optional[bs]        # TASK-1761
# Module-level registry (NOT an instance attribute `self._sources` as originally drafted —
# contract corrected to match actual TASK-1760 implementation):
COMPANY_SOURCES: Dict[str, SourceConfig]             # module-level dict, keyed by source name incl. "visualvisitor"

# flowtask reference (READ-ONLY):
#   /home/jesuslara/proyectos/flowtask/flowtask/components/CompanyScraper/parsers/visualvisitor.py
#     :6-130   VisualVisitorScrapper (selectors to port)
#     :32-125  .company-header / .headline-summary table walk
#     :42      BUG — source_platform mislabeled 'rocketreach' (DO NOT copy)
#     :12-15   title keywords (already captured in TASK-1760 SourceConfig)
```

### Does NOT Exist
- ~~`scrape_visualvisitor`~~ — this task creates it.
- ~~`parrot_tools.company_info.extractors`~~ — no extractor package; extraction
  lives as methods in `tool.py`.

---

## Implementation Notes

### Pattern to Follow
```python
@tool_schema(CompanyInput)
async def scrape_visualvisitor(self, company_name: str, return_json: bool = False):
    """Scrape company information from visualvisitor.com."""
    info = CompanyInfo(search_term=company_name, source_platform="visualvisitor",
                       scrape_status="pending")
    try:
        url = self._search_company_url(company_name, self._sources["visualvisitor"])
        if not url:
            info.scrape_status = "no_data"; return info.to_json() if return_json else info
        soup = await self._fetch_page(url)
        # ... port selectors from flowtask visualvisitor.py:32-125 ...
        info.scrape_status = "success"
    except Exception as exc:
        info.scrape_status = f"error: {exc}"; self.logger.warning(...)
    return info.to_json() if return_json else info
```

### Key Constraints
- Never raise; set `scrape_status`/`error_message` on failure.
- `source_platform="visualvisitor"` exactly.
- Google-style docstring (becomes the LLM tool description).
- `self.logger`; async throughout.

---

## Acceptance Criteria

- [ ] `scrape_visualvisitor` exists, `@tool_schema(CompanyInput)`, returns
      `Union[CompanyInfo, str]`.
- [ ] Populated `CompanyInfo` has `source_platform == "visualvisitor"`.
- [ ] Uses `_search_company_url` + `_fetch_page`; never raises.
- [ ] `ruff check ...company_info/tool.py` clean; module imports.

---

## Test Specification

```python
# test_scrape_visualvisitor_fixture (TASK-1764):
#   recorded HTML -> populated CompanyInfo with source_platform == "visualvisitor"
```

---

## Agent Instructions

1. Read spec §2-§3; open the flowtask reference parser (read-only).
2. Verify TASK-1760 and TASK-1761 are in `sdd/tasks/completed/`.
3. Verify the Codebase Contract; update FIRST if drifted.
4. Implement per scope.
5. Verify acceptance criteria.
6. Move this file to `sdd/tasks/completed/`; update the per-spec index to `done`.
7. Fill in the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Sonnet 5)
**Date**: 2026-07-14
**Notes**: Corrected the Codebase Contract before implementing: TASK-1760's
registry landed as a module-level `COMPANY_SOURCES: Dict[str, SourceConfig]`
(not an instance attribute `self._sources` as originally drafted), and
`_search_company_url` is `async def` (must be awaited) — updated the
contract section above to match. Added `_extract_codes` (shared NAICS/SIC
helper, ported from flowtask's `rocket.py`/`visualvisitor.py` — both
sources use the identical regex) as a new toolkit method near
`_standardize_name`. Added `scrape_visualvisitor` right before
`scrape_all_sources`, using `COMPANY_SOURCES["visualvisitor"]` +
`_search_company_url` (TASK-1760) + `_fetch_page` (TASK-1761). Selectors
(`.company-header`, `.headline-summary table` walk) ported from flowtask
`parsers/visualvisitor.py:32-125`, which is byte-for-byte identical to
`parsers/rocket.py` (already ported into this file's `scrape_rocketreach`)
— confirming the spec's note that flowtask's VisualVisitor parser was a
rocket.py copy-paste. Set `source_platform="visualvisitor"` (NOT
flowtask's mislabeled `"rocketreach"` at visualvisitor.py:42). Verified
with an ad-hoc fixture-HTML smoke test (mocking `_search_company_url` and
`_fetch_page`): populated `CompanyInfo` has `source_platform ==
"visualvisitor"`, `scrape_status == "success"`, and correctly extracts
company_name/website/phone/naics_code/sic_code/employee_count/
headquarters; also verified the no-hit path returns `scrape_status ==
"no_data"` without raising. `ruff check` clean; `get_tools()` now lists
7 tools including `scrape_visualvisitor`.
**Deviations from spec**: none
