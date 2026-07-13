# TASK-1763: `research_company` first-success aggregate + wire existing scrapers to new search

**Feature**: FEAT-305 — CompanyResearch — extend CompanyInfoToolkit
**Spec**: `sdd/specs/companyresearch-tool.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1760, TASK-1761, TASK-1762
**Assigned-to**: unassigned

---

## Context

> Implements spec Module 4 (§3) — the single agent-facing tool
> `research_company` (goal G1, acceptance criteria U1/U3) — and repoints the 5
> existing `scrape_*` methods onto the new `_search_company_url` so every source
> shares the DDG-first + validation path.

---

## Scope

In `packages/ai-parrot-tools/src/parrot_tools/company_info/tool.py`:

- Add **`ResearchCompanyInput`** Pydantic model: `company_name: str`,
  `sources: Optional[List[str]] = None`, `return_json: bool = False`.
- Add **`research_company(self, company_name, sources=None, return_json=False)
  -> Union[CompanyInfo, str]`**, `@tool_schema(ResearchCompanyInput)`:
  - Iterate sources in default priority order
    `["leadiq", "rocketreach", "explorium", "siccode", "visualvisitor", "zoominfo"]`
    (overridable via `sources`), calling the matching `scrape_<source>` method.
  - Return the FIRST `CompanyInfo` whose `scrape_status == "success"`; do NOT
    call later sources after a success (U1).
  - Validate `sources` entries: unknown name → return a `CompanyInfo`
    `error`/clean error message listing valid source names (do not raise).
  - If none succeeds, return `CompanyInfo` with `scrape_status="no_data"` and
    `error_message` aggregating the per-source failures. NEVER raise into the
    agent loop.
- **Wire existing scrapers**: switch `scrape_zoominfo`, `scrape_explorium`,
  `scrape_leadiq`, `scrape_rocketreach`, `scrape_siccode` from calling
  `_google_site_search` directly to `_search_company_url` (with each source's
  `SourceConfig`). `scrape_visualvisitor` already uses it (TASK-1762).
- Keep `scrape_all_sources` working (back-compat); its behavior is unchanged.
- `__init__.py` exports unchanged (`CompanyInfoToolkit`, `CompanyInfo`).

**NOT in scope**: tests/fixtures (TASK-1764); changing selector logic; removing
any existing per-source tool.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/company_info/tool.py` | MODIFY | Add `ResearchCompanyInput`, `research_company`; repoint 5 scrapers to `_search_company_url` |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-07-13 on `dev`.

### Verified Imports
```python
from parrot_tools.decorators import tool_schema     # decorators.py:2
from typing import Optional, List, Union            # already imported in tool.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/company_info/tool.py
class CompanyInfo(BaseModel):                        # line 83
    scrape_status: str = "pending"                   # line 92  (compare == "success")
    error_message: ...                               # (aggregate failures here)
    def to_json(self, **kwargs) -> str               # line 139
class CompanyInfoToolkit(AbstractToolkit):           # line 163
    async def scrape_zoominfo(self, company_name, return_json=False)     # line 429
    async def scrape_explorium(...)                  # line 554
    async def scrape_leadiq(...)                     # line 676
    async def scrape_rocketreach(...)                # line 836
    async def scrape_siccode(...)                    # line 966
    async def scrape_all_sources(self, company_name, return_json=False)  # line 1091 (KEEP)
    async def _google_site_search(...)               # line 266 (calls to REPLACE with _search_company_url)
# NEW from sibling tasks:
    def _search_company_url(self, company_name, site_config) -> Optional[str]  # TASK-1760
    async def scrape_visualvisitor(self, company_name, return_json=False)      # TASK-1762

# tool exposure inherited:
#   parrot/tools/toolkit.py:207  AbstractToolkit.get_tools()  (public async methods -> tools)
```

### Does NOT Exist
- ~~`CompanyResearchToolkit`~~ — NOT created; the tool surface is
  `CompanyInfoToolkit.research_company`.
- ~~a separate aggregator module~~ — `research_company` is a method on the
  existing toolkit.

---

## Implementation Notes

### Pattern to Follow
```python
DEFAULT_PRIORITY = ["leadiq", "rocketreach", "explorium", "siccode", "visualvisitor", "zoominfo"]

@tool_schema(ResearchCompanyInput)
async def research_company(self, company_name, sources=None, return_json=False):
    """Return the first successful CompanyInfo across sources in priority order."""
    order = sources or DEFAULT_PRIORITY
    unknown = [s for s in order if s not in self._sources]
    if unknown:
        info = CompanyInfo(search_term=company_name, scrape_status="error",
                           error_message=f"unknown sources {unknown}; valid: {list(self._sources)}")
        return info.to_json() if return_json else info
    failures = {}
    for name in order:
        result = await getattr(self, f"scrape_{name}")(company_name)
        if result.scrape_status == "success":
            return result.to_json() if return_json else result
        failures[name] = result.scrape_status
    info = CompanyInfo(search_term=company_name, scrape_status="no_data",
                       error_message=f"all sources failed: {failures}")
    return info.to_json() if return_json else info
```

### Key Constraints
- Never raise into the agent loop.
- After a success, later sources MUST NOT be called (short-circuit the loop).
- Google-style docstring (LLM tool description); `self.logger`; async throughout.

---

## Acceptance Criteria

- [ ] `research_company` returns first success in default order
      `leadiq → rocketreach → explorium → siccode → visualvisitor → zoominfo`;
      later sources not called after success.
- [ ] `sources` subset/order respected; unknown source → clean error (no raise).
- [ ] All-fail → `scrape_status="no_data"` with per-source failures in
      `error_message`; no exception.
- [ ] `get_tools()` includes `research_company` AND `scrape_visualvisitor`; all
      existing per-source tools remain (back-compat); `scrape_all_sources` works.
- [ ] The 5 existing scrapers now call `_search_company_url` (not
      `_google_site_search` directly).
- [ ] `ruff check ...company_info/tool.py` clean; module imports.

---

## Test Specification

```python
# test_research_company_first_success: source 1 fails, source 2 succeeds ->
#   source 2 returned, source 3 never called (assert mock not called)
# test_research_company_sources_param: explicit subset/order respected; unknown -> clean error
# test_research_company_all_fail: scrape_status == "no_data", failures in error_message, no raise
# test_toolkit_tools_exposed: get_tools() includes research_company + scrape_visualvisitor
```

---

## Agent Instructions

1. Read spec §2 (research_company) and §5 acceptance criteria.
2. Verify TASK-1760/1761/1762 are in `sdd/tasks/completed/`.
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
