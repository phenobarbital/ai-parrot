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
class CompanyInfoToolkit(AbstractToolkit):           # line 163
    async def scrape_zoominfo(self, company_name, return_json=False)  # line 429, @tool_schema(CompanyInput) at 428  (COPY THIS SHAPE)
    def _parse_address(self, address_text) -> Dict   # line 371 (reuse for address parsing)
    def _standardize_name(self, name) -> str         # line 405 (reuse)
# NEW from sibling tasks (must exist before this task runs):
    def _search_company_url(self, company_name, site_config) -> Optional[str]   # TASK-1760
    async def _fetch_page(self, url) -> Optional[BeautifulSoup]                  # TASK-1761

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

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
