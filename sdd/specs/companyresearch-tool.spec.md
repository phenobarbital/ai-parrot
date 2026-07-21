---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: CompanyResearch — extend CompanyInfoToolkit with VisualVisitor, first-success `research_company`, DDG-first search and result validation

**Feature ID**: FEAT-305
**Date**: 2026-07-13
**Author**: Jesus Lara (research + Q&A via /sdd-proposal, /sdd-spec)
**Status**: approved
**Target version**: ai-parrot-tools next minor

> **Prior exploration**: `sdd/proposals/companyresearch-tool.proposal.md`
> (FEAT-305, status: review) — research audit at `sdd/state/FEAT-305/`.
> **Scope pivot recorded**: the proposal recommended a new
> `CompanyResearchToolkit` in core `parrot/tools/`; spec-time research found
> `parrot_tools.company_info.CompanyInfoToolkit` (ai-parrot-tools) already
> implements 5 of the 6 requested sources. The user chose **"extend it"**
> over creating a duplicate toolkit. Related-but-different: FEAT-304 ports
> the LeadIQ **GraphQL API** (paid, authenticated) — this feature covers the
> public-page scraping path; both may coexist.

---

## 1. Motivation & Business Requirements

### Problem Statement

An LLM agent should be able to send a company name and retrieve structured
company data (address, phone, website, NAICS/SIC, employee count, revenue
range, industry, description, etc.) gathered from public company-profile
pages: LeadIQ, RocketReach, SICCode, VisualVisitor, ZoomInfo and
Explorium.ai. flowtask has a battle-tested `CompanyScraper` component with
six extractors, but it is a DataFrame-batch ETL component unusable from an
agent. ai-parrot-tools' existing `CompanyInfoToolkit` covers five sources but:
it lacks VisualVisitor; it exposes only per-source tools plus an
all-sources gather (no cheap "give me the first good profile" call, which is
what an agent conversation needs); it depends exclusively on Google CSE
(quota-billed) with **no DuckDuckGo-first strategy**; it blindly takes the
first search hit with **no title/keyword or fuzzy company-name validation**
(flowtask validates before scraping); and it fetches pages via Selenium
while the repo's scraping stack has moved to Playwright.

### Goals

- G1: Single agent-facing tool `research_company(company_name, sources?)`
  that tries sources in priority order and returns the **first successful**
  `CompanyInfo` (U1/U3 resolved in proposal).
- G2: Add the missing **VisualVisitor** extractor (port from flowtask,
  fixing its `source_platform` copy-paste mislabel).
- G3: **DDG-first search** with Google CSE fallback (flowtask strategy),
  cutting Google quota usage.
- G4: **Result validation** before scraping: title-keyword match per source
  + exact/first-token/fuzzy company-name check (flowtask
  `_check_company_name` semantics).
- G5: Page fetching via the repo's **Playwright** driver stack
  (`DriverConfig(driver_type="playwright")` + `driver_context`), replacing
  direct Selenium usage inside this toolkit.
- G6: Fixture-based tests (recorded HTML) — no live scraping in CI.

### Non-Goals (explicitly out of scope)

- No paid/official API integrations (RocketReach API, ZoomInfo API). The
  LeadIQ GraphQL API is FEAT-304's scope.
- No DataFrame/batch API — flowtask keeps the bulk-enrichment role.
- No changes to core `parrot/tools/` or `parrot/interfaces/http.py`.
- No new standalone toolkit — a fresh core-parrot `CompanyResearchToolkit`
  (proposal's original §3) was superseded by the "extend" decision.
- No removal of the existing per-source tools (`scrape_zoominfo`, …) or of
  `scrape_all_sources` — backwards compatible.

---

## 2. Architectural Design

### Overview

Evolve `parrot_tools/company_info/` in place:

1. **`research_company`** — new public async method on `CompanyInfoToolkit`
   (becomes a tool automatically via `AbstractToolkit`). Signature:
   `research_company(company_name: str, sources: Optional[List[str]] = None,
   return_json: bool = False)`. Iterates sources in priority order (default:
   `["leadiq", "rocketreach", "explorium", "siccode", "visualvisitor",
   "zoominfo"]` — cheap HTTP-friendly sources first, browser-heavy ZoomInfo
   last), calling each per-source scrape method; returns the first
   `CompanyInfo` whose `scrape_status == "success"`. If none succeeds,
   returns a `CompanyInfo` with `scrape_status="no_data"` and
   `error_message` listing per-source failures. Never raises into the agent
   loop.
2. **`scrape_visualvisitor`** — new per-source method following the existing
   `scrape_*` shape (`@tool_schema(CompanyInput)`), with selectors ported
   from flowtask's `VisualVisitorScrapper` and `source_platform`
   correctly set to `"visualvisitor"`.
3. **Search layer** — new `_search_company_url(company_name, site_config)`:
   DDG search first (`ddgs.DDGS`, same engine `DuckDuckGoToolkit` uses,
   wrapped with `backoff` on `RatelimitException`), falling back to the
   existing `_google_site_search`. Each candidate hit is validated by
   `_validate_search_hit(title, company_name, keywords)` (G4) before being
   accepted. Existing `scrape_*` methods switch from calling
   `_google_site_search` directly to `_search_company_url`.
4. **Fetch layer** — replace `_get_driver`/`_fetch_page_with_selenium`
   internals with the scraping stack:
   `driver_context(DriverConfig(driver_type="playwright", ...))` yielding an
   `AbstractDriver`; `await drv.navigate(url)`; `await
   drv.get_page_source()` → BeautifulSoup. ZoomInfo keeps
   headless-hardening options (custom UA); the old Selenium-specific ctor
   params (`browser`, `use_undetected`, `auto_install`, `mobile*`) remain
   accepted but map onto `DriverConfig` fields.

### Component Diagram

```
Agent ──→ research_company(company_name, sources?)
              │  (priority loop, first-success)
              ▼
        scrape_<source>()  ×6  (leadiq, rocketreach, explorium,
              │                 siccode, visualvisitor, zoominfo)
              ├─→ _search_company_url ──→ DDGS (ddgs)         [primary]
              │        │                  _google_site_search  [fallback]
              │        └─→ _validate_search_hit (keywords + fuzzy name)
              ├─→ driver_context(DriverConfig(playwright)) → AbstractDriver
              │        └─→ navigate(url) → get_page_source() → BeautifulSoup
              └─→ per-source selector extraction → CompanyInfo
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot_tools.company_info.CompanyInfoToolkit` | extends (in place) | new methods + refactored search/fetch internals |
| `parrot.tools.toolkit.AbstractToolkit` | inherits (unchanged) | auto tool generation; re-exported via `parrot_tools.toolkit` |
| `parrot_tools.scraping.driver_context.driver_context` | uses | per-fetch browser lifecycle |
| `parrot_tools.scraping.toolkit_models.DriverConfig` | uses | `driver_type="playwright"` |
| `parrot_tools.scraping.drivers.abstract.AbstractDriver` | uses | `navigate`, `get_page_source` |
| `ddgs.DDGS` (lib used by `parrot_tools.ddgo`) | uses | DDG-first search |
| `parrot_tools.decorators.tool_schema` | uses (unchanged) | `CompanyInput` schema on per-source tools |

### Data Models

```python
# EXISTING — parrot_tools/company_info/tool.py:83 (unchanged shape, reused)
class CompanyInfo(BaseModel):
    search_term/search_url/source_platform/scrape_status
    company_name/logo_url/company_description
    headquarters/address/city/state/zip_code/country/metro_area
    phone_number/website
    industry/industry_category/category/keywords/naics_code/sic_code
    stock_symbol/revenue_range/employee_count/number_employees/company_size
    founded/funding/years_in_business
    executives/similar_companies/social_media
    timestamp/error_message

# NEW — input schema for research_company
class ResearchCompanyInput(BaseModel):
    company_name: str
    sources: Optional[List[str]] = None   # subset + order override
    return_json: bool = False

# NEW — internal per-source search config (not a tool schema)
class SourceConfig(BaseModel):
    name: str                 # "leadiq"
    site: str                 # "leadiq.com"
    search_template: str      # "site:leadiq.com {}"
    title_keywords: List[str] # flowtask `keywords` per parser
```

### New Public Interfaces

```python
class CompanyInfoToolkit(AbstractToolkit):  # existing class — additions only
    async def research_company(
        self, company_name: str,
        sources: Optional[List[str]] = None,
        return_json: bool = False,
    ) -> Union[CompanyInfo, str]:
        """First successful CompanyInfo across sources in priority order."""

    async def scrape_visualvisitor(
        self, company_name: str, return_json: bool = False
    ) -> Union[CompanyInfo, str]:
        """Scrape company information from visualvisitor.com."""
```

---

## 3. Module Breakdown

### Module 1: Search layer — DDG-first + hit validation
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/company_info/tool.py`
- **Responsibility**: `SourceConfig` registry for the 6 sources
  (site, search template, title keywords from flowtask parsers);
  `_search_company_url` (DDG → Google CSE fallback);
  `_validate_search_hit` (keyword presence + exact/first-token/fuzzy
  name match, threshold 85). URL cleanup (`/employee-directory`,
  `/email-format` suffix strip — flowtask scrapper.py:919-922).
- **Depends on**: existing `_google_site_search`; `ddgs` lib; fuzzy dep (§7).

### Module 2: Playwright fetch layer
- **Path**: same file
- **Responsibility**: replace `_get_driver`/`_close_driver`/
  `_fetch_page_with_selenium` internals with
  `driver_context(DriverConfig(driver_type="playwright", ...))`;
  map legacy ctor kwargs onto `DriverConfig`; keep method name
  `_fetch_page` returning `Optional[BeautifulSoup]`.
- **Depends on**: `parrot_tools.scraping` (verified §6).

### Module 3: VisualVisitor extractor
- **Path**: same file
- **Responsibility**: `scrape_visualvisitor` per-source method; selectors
  ported from flowtask `visualvisitor.py:32-125` (`.company-header`,
  `.headline-summary` table walk), `source_platform="visualvisitor"`
  (fixing flowtask's mislabel), NAICS/SIC `_extract_codes` regex helper.
- **Depends on**: Modules 1-2.

### Module 4: `research_company` aggregate + wiring
- **Path**: same file
- **Responsibility**: priority-ordered first-success loop over per-source
  methods; `sources` param validation (unknown names → error listing valid
  ones); aggregate failure reporting; switch the 5 existing `scrape_*`
  methods to `_search_company_url`; export from `__init__.py` unchanged.
- **Depends on**: Modules 1-3.

### Module 5: Tests + fixtures + deps
- **Path**: `packages/ai-parrot-tools/tests/company_info/`
- **Responsibility**: recorded-HTML fixtures per source; unit tests
  (§4); add `playwright` + fuzzy dep to satellite pyproject (§7).
- **Depends on**: Modules 1-4.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_source_configs_complete` | 1 | all 6 sources present with site/template/keywords |
| `test_validate_hit_exact/fuzzy/reject` | 1 | name validation: exact, fuzzy>85, mismatch rejected |
| `test_search_ddg_first_google_fallback` | 1 | DDG mocked to ratelimit → Google CSE called |
| `test_url_suffix_cleanup` | 1 | `/employee-directory` stripped |
| `test_fetch_uses_playwright_config` | 2 | `DriverConfig.driver_type == "playwright"` passed to `driver_context` (mocked) |
| `test_scrape_visualvisitor_fixture` | 3 | fixture HTML → populated CompanyInfo, `source_platform="visualvisitor"` |
| `test_each_source_fixture` | 3/4 | existing 5 extractors still parse their fixture HTML |
| `test_research_company_first_success` | 4 | source 1 fails, source 2 succeeds → source 2 returned, source 3 never called |
| `test_research_company_sources_param` | 4 | explicit subset/order respected; unknown source → clean error |
| `test_research_company_all_fail` | 4 | `scrape_status="no_data"`, per-source errors in `error_message`, no exception |

### Integration Tests

| Test | Description |
|---|---|
| `test_toolkit_tools_exposed` | `get_tools()` includes `research_company` + `scrape_visualvisitor`; schemas valid |
| `test_live_smoke` (marked `@pytest.mark.live`, skipped in CI) | one real `research_company("PetSmart")` run for manual selector validation |

### Test Data / Fixtures

```python
# tests/company_info/conftest.py
@pytest.fixture
def leadiq_html() -> str: ...      # recorded page per source
@pytest.fixture
def mock_driver(monkeypatch): ...  # AbstractDriver stub returning fixture HTML
@pytest.fixture
def mock_search(monkeypatch): ...  # DDG/Google returning canned hits
```

---

## 5. Acceptance Criteria

- [ ] `research_company("X")` returns the first successful `CompanyInfo` in
      default priority order `leadiq → rocketreach → explorium → siccode →
      visualvisitor → zoominfo`; later sources are not called after success (U1).
- [ ] `research_company` is exposed as a single tool via `get_tools()` (U3);
      existing per-source tools remain (back-compat).
- [ ] `scrape_visualvisitor` exists with `source_platform="visualvisitor"`.
- [ ] Search is DDG-first with Google CSE fallback; a search hit is accepted
      only after title-keyword + name validation (fuzzy threshold 85).
- [ ] Page fetches go through `driver_context` with
      `DriverConfig(driver_type="playwright")` (U2 as amended); no direct
      `selenium.webdriver` usage remains in `company_info/tool.py`.
- [ ] All failures return `CompanyInfo` with `scrape_status` in
      `{"no_data","error: ..."}` — tool never raises to the agent.
- [ ] `pytest packages/ai-parrot-tools/tests/company_info/ -v` passes with
      fixtures only (no network); live test is opt-in via `-m live`.
- [ ] Satellite `pyproject.toml` declares the playwright + fuzzy deps (§7).
- [ ] No breaking changes: `CompanyInfoToolkit()` still constructs with the
      legacy kwargs; `scrape_all_sources` still works.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** All entries verified 2026-07-13
> on `dev` @ `f11d96b92`. Import of `parrot_tools.company_info` executed
> successfully in the project venv during spec research.

### Verified Imports

```python
from parrot_tools.company_info import CompanyInfoToolkit, CompanyInfo
    # verified: packages/ai-parrot-tools/src/parrot_tools/company_info/__init__.py:1-6; live import OK
from parrot_tools.toolkit import AbstractToolkit
    # verified: packages/ai-parrot-tools/src/parrot_tools/toolkit.py:2 — re-export of parrot.tools.toolkit
from parrot_tools.decorators import tool_schema
    # verified: packages/ai-parrot-tools/src/parrot_tools/decorators.py:2 — re-export of parrot.tools.decorators
from parrot_tools.scraping.driver_context import driver_context, DriverRegistry
    # verified: packages/ai-parrot-tools/src/parrot_tools/scraping/driver_context.py (registry at :21; factories 'selenium'+'playwright' registered at import — observed in DEBUG log)
from parrot_tools.scraping.toolkit_models import DriverConfig
    # verified: packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit_models.py:15
from parrot_tools.scraping.drivers.abstract import AbstractDriver
    # verified: packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py:11
from ddgs import DDGS
from ddgs.exceptions import RatelimitException
    # verified: used by packages/ai-parrot-tools/src/parrot_tools/ddgo.py:11-16
import backoff
    # verified: core dep, packages/ai-parrot/pyproject.toml:45 ("backoff==2.2.1")
from bs4 import BeautifulSoup
    # verified: satellite dep, packages/ai-parrot-tools/pyproject.toml:47 ("beautifulsoup4>=4.12")
```

### Existing Class Signatures

```python
# packages/ai-parrot-tools/src/parrot_tools/company_info/tool.py
class CompanyInput(BaseModel):                       # line 75
    company_name: str; return_json: bool = False
class CompanyInfo(BaseModel):                        # line 83 (fields at 88-137)
    scrape_status: str = "pending"                   # line 92
    def to_json(self, **kwargs) -> str               # line 139
class GoogleSearchResult(BaseModel):                 # line 149
class CompanyInfoToolkit(AbstractToolkit):           # line 163
    def __init__(self, google_api_key=None, google_cse_id=None,
                 browser='chrome', headless=True, timeout=30,
                 auto_install=True, mobile=False, mobile_device=None,
                 use_undetected=False, **kwargs)     # line 175
    async def _get_driver(self) -> webdriver.Chrome  # line 233  (to be replaced)
    async def _close_driver(self)                    # line 253  (to be replaced)
    async def _google_site_search(self, company_name, site,
        additional_terms="", max_results=5) -> GoogleSearchResult  # line 266 (kept as fallback)
    async def _fetch_page_with_selenium(self, url) -> Optional[bs] # line 334 (to be replaced)
    def _parse_address(self, address_text) -> Dict   # line 371
    def _standardize_name(self, name) -> str         # line 405
    async def scrape_zoominfo(self, company_name, return_json=False)   # line 429, @tool_schema(CompanyInput) at 428
    async def scrape_explorium(...)                  # line 554
    async def scrape_leadiq(...)                     # line 676
    async def scrape_rocketreach(...)                # line 836
    async def scrape_siccode(...)                    # line 966
    async def scrape_all_sources(self, company_name, return_json=False)  # line 1091 (asyncio.gather all 5)

# packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit_models.py
class DriverConfig(BaseModel):                       # line 15
    driver_type: Literal["selenium", "playwright"] = "selenium"   # line 36
    browser: Literal["chrome","firefox","edge","safari","undetected","webkit"] = "chrome"  # line 37
    headless: bool = True                            # line 40
    # also: mobile, mobile_device, auto_install, default_timeout,
    #       retry_attempts, custom_user_agent, disable_images (docstring 21-33)

# packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py
class AbstractDriver(ABC):                           # line 11
    async def start(self) -> None                    # line 37
    async def quit(self) -> None                     # line 41
    async def navigate(self, url: str, timeout: int = 30) -> None  # line 47
    async def get_page_source(self) -> str           # line 130
    async def wait_for_selector(...)                 # line 185

# packages/ai-parrot-tools/src/parrot_tools/scraping/driver_context.py
class DriverRegistry:                                # line 21 — factories "selenium", "playwright"
class _PlaywrightSetup:                              # line 161 — internal; do not import directly
# async context manager (used as in scraping/toolkit.py:750,765):
#   async with driver_context(config, session_driver=None) as drv:
#       await drv.navigate(url); html = await drv.get_page_source()

# flowtask reference sources (READ-ONLY, outside this repo):
# /home/jesuslara/proyectos/flowtask/flowtask/components/CompanyScraper/
#   scrapper.py:741-770  _check_company_name (keyword split + fuzz.ratio>85)
#   scrapper.py:919-922  URL suffix cleanup
#   parsers/visualvisitor.py:6-130  VisualVisitorScrapper (selectors to port;
#     NOTE bug at :42 — source_platform mislabeled 'rocketreach')
#   parsers/*.py — title keywords per source (leadiq.py:12-18, rocket.py:12-17,
#     zoominfo.py:20-23, siccode.py:20-23, visualvisitor.py:12-15, explorium.py:12-14)
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_search_company_url` | `DDGS().text(...)` | `ddgs` lib (pattern in `ddgo.py`) | `parrot_tools/ddgo.py:11,97` |
| `_search_company_url` | `_google_site_search()` | fallback call | `company_info/tool.py:266` |
| `_fetch_page` (new) | `driver_context(DriverConfig(...))` | async ctx manager | `scraping/toolkit.py:750` (usage pattern) |
| `research_company` | `scrape_<source>(company_name, return_json=False)` | method calls | `company_info/tool.py:429,554,676,836,966` |
| tool exposure | `AbstractToolkit.get_tools()` | inherited | `parrot/tools/toolkit.py:207` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot_tools.company_info.extractors`~~ — no extractor-class package;
  extraction lives as methods in `tool.py` (the proposal's extractor-class
  design was superseded by the "extend" decision).
- ~~`CompanyResearchToolkit`~~ — not created anywhere; the tool surface is
  `CompanyInfoToolkit.research_company`.
- ~~`parrot.interfaces.SeleniumService`~~ / ~~`parrot_tools.interfaces.SeleniumService`~~
  — flowtask-only class; does not exist in this monorepo.
- ~~`HTTPService._search_duckduckgo` reuse from `parrot_tools`~~ — core
  `parrot/interfaces/http.py:1327` exists but `CompanyInfoToolkit` does NOT
  inherit `HTTPService`; use `ddgs.DDGS` directly instead.
- ~~`from duckduckgo_search import DDGS`~~ in satellite code — the satellite
  uses the **`ddgs`** package (see `ddgo.py:11`), not `duckduckgo_search`
  (which core pins separately).
- ~~`fuzzywuzzy` / `rapidfuzz`~~ — not currently installed in either package
  (grep of both pyprojects); must be ADDED (§7) before importing.
- ~~`scrape_visualvisitor`~~ — does not exist yet (this spec adds it).
- ~~`SeleniumSetup` for new code~~ — exists at
  `parrot_tools/scraping/driver.py` but is the legacy path; new fetches must
  go through `driver_context`/`DriverConfig` (user decision, this spec).
- No tests exist under `packages/ai-parrot-tools/tests/` for company_info
  (verified via find) — Module 5 creates the directory.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Per-source method shape: copy `scrape_zoominfo` (tool.py:428-470) —
  `@tool_schema(CompanyInput)`, init `CompanyInfo(..., scrape_status='pending')`,
  never raise, set `scrape_status`/`error_message` on failure.
- DDG usage with backoff: `parrot_tools/ddgo.py` (backoff on
  `RatelimitException`, `asyncio.get_running_loop().run_in_executor` for the
  sync DDGS client).
- Browser lifecycle: `scraping/toolkit.py:750` — `async with
  driver_context(config, session_driver=...) as drv:`.
- Fuzzy matching semantics from flowtask `_check_company_name`
  (scrapper.py:741-770): exact match → first-token match → ratio > 85.
- Async-first, Google-style docstrings (they become LLM tool descriptions),
  `self.logger`, Pydantic models throughout (repo rules).

### Known Risks / Gotchas

- **Selector drift** (proposal C10, low confidence): ported/existing
  selectors may be stale vs live site markup. Mitigation: fixture tests
  protect code paths; `@pytest.mark.live` smoke test for manual validation;
  treat live failures as data (`no_data`), never exceptions.
- **Anti-bot walls**: ZoomInfo is aggressive; Playwright + custom UA may
  still be blocked where undetected-chromedriver succeeded. Mitigation:
  ZoomInfo last in default priority; per-source failure is non-fatal in
  `research_company`. If block rates prove unacceptable, a follow-up may
  re-introduce an undetected-selenium override per source (do NOT block this
  feature on it).
- **DDG rate limits**: backoff + fallback to Google CSE (which costs quota —
  log at INFO when falling back).
- **Back-compat**: legacy ctor kwargs (`browser`, `use_undetected`, …) must
  keep constructing; map them onto `DriverConfig` and log a deprecation
  notice for `use_undetected`.
- **`scrape_all_sources` cost**: unchanged behavior, but after the fetch
  refactor it opens up to 5 Playwright pages; keep sequential-per-source
  gather semantics as-is (no scope creep).

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `playwright` | `>=1.52` | add to satellite `scraping` extra — currently only in core `ai-parrot[agents]` (pyproject:224 area); `PlaywrightDriver` needs it at runtime |
| `rapidfuzz` | `>=3.0` | fuzzy name validation (replaces flowtask's fuzzywuzzy; maintained, MIT, no GPL levenshtein dep) |
| `ddgs` | (already required by `ddgo.py`) | DDG search — verify it is declared in satellite pyproject; add if missing |

---

## 8. Open Questions

> Resolved during proposal/spec Q&A — carried forward, do NOT re-ask:

- [x] **Aggregation strategy?** — *Resolved in proposal (U1)*: first-success
  in priority order (flowtask parity); `sources` param lets callers
  pick/restrict.
- [x] **Tool surface?** — *Resolved in proposal (U3)*: single
  `research_company(company_name, sources?)` agent tool (existing per-source
  tools remain for back-compat).
- [x] **Browser fetcher?** — *Resolved in proposal (U2), amended at
  spec time by user*: Playwright via the existing scraping stack
  (`DriverConfig(driver_type="playwright")` + `driver_context`), NOT
  Selenium/`SeleniumSetup`, NOT a new Playwright helper.
- [x] **New toolkit or extend existing?** — *Resolved at spec time*: extend
  `CompanyInfoToolkit` in place (user chose over superseding/duplicating).
- [x] **Default source priority order** — *Resolved at spec time (was
  unresolved in proposal)*: `leadiq → rocketreach → explorium → siccode →
  visualvisitor → zoominfo` (HTTP-friendly first, browser-heavy last),
  overridable via `sources`.

> Unresolved — defer to implementation:

- [ ] **Live-selector validity** — whether ported/existing selectors match
  today's site markup can only be confirmed by the `-m live` smoke test
  during implementation. *Owner: implementer.*
- [ ] **`ddgs` pin** — confirm the satellite pyproject declares `ddgs`
  explicitly (ddgo.py imports it); add pin if it arrives transitively.
  *Owner: implementer (Module 5).*

---

## Worktree Strategy

- **Isolation unit**: per-spec — one worktree, tasks sequential.
- **Rationale**: all five modules edit the same file
  (`company_info/tool.py`); parallel tasks would conflict constantly.
- **Cross-feature dependencies**: none hard. FEAT-304 (LeadIQ GraphQL
  toolkit) touches a different module (`parrot_tools/leadiq/` planned) — no
  file overlap; no merge ordering required. FEAT-303
  (ux-custom-engine-copilot) is unrelated.
- Worktree: `git worktree add -b feat-305-companyresearch-tool
  .claude/worktrees/feat-305-companyresearch-tool HEAD` (from `dev`, after
  /sdd-task).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-13 | Jesus Lara + Claude (Fable 5) | Initial draft from FEAT-305 proposal; scope pivoted to extending CompanyInfoToolkit after satellite-package discovery |
