---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: Research Tools for Agents — Direct Access to Authoritative Data Sources

**Feature ID**: FEAT-426
**Date**: 2026-08-17
**Author**: Jesus Lara + Claude (Opus 4.6)
**Status**: draft
**Target version**: ai-parrot-tools next minor

> **Prior exploration**: `sdd/proposals/research-tools-for-agents.brainstorm.md`
> (status: exploration, recommended Option A — Category-Based AbstractToolkit
> Subclasses with Shared Base). All resolved open questions from the brainstorm
> are carried forward below; none have been re-opened.

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot agents that need factual, citable data (economic indicators, academic
research, market statistics) currently have **no direct path to authoritative
sources**. The only options are:

1. **Google/SerpAPI web search** — returns noisy results, requires filtering,
   costs per query, and the data is second-hand (news articles *about*
   World Bank data, not the data itself).
2. **DuckDuckGo search** (`DuckDuckGoToolkit`) — free but equally indirect;
   the agent still gets web pages, not structured data.
3. **Single-source tools** — `FredAPITool` (FRED economic data) and
   `ArxivTool` (arXiv papers) exist but are standalone, with no shared
   citation model or cross-source query capability.

### Goals

- **G1**: Three category-based toolkits (`OpenDataToolkit`,
  `AcademicResearchToolkit`, `MarketResearchToolkit`) that give agents direct,
  structured access to authoritative data sources without web-search
  intermediaries.
- **G2**: A shared `ResearchResult` / `Citation` Pydantic model enforced across
  all toolkits — every result includes `source_url`, `access_date`,
  `data_vintage`, and a `formatted_citation` string.
- **G3**: A lightweight `ResearchRouter` tool that uses LLM-based intent
  classification to dispatch cross-category queries to the right toolkit(s).
- **G4**: Existing `ArxivTool` migrated into `AcademicResearchToolkit` as a
  method (resolved in brainstorm).
- **G5**: Redis-backed `ToolCache` integration for all API calls with
  configurable per-toolkit TTLs.
- **G6**: Fixture-based tests — no live API calls in CI.

### Non-Goals (explicitly out of scope)

- No paid/authenticated API integrations (Gallup Analytics subscription,
  Gartner enterprise portal, Statista Connect paid API). These are stubbed
  with clear interfaces for future integration. Research confirmed: Gallup
  has NO public API; Gartner has NO public API and aggressive bot protection;
  Statista has a contract-gated API ("Statista Connect") with no self-serve
  signup.
- No modification to existing `FredAPITool` or standalone `ArxivTool` — the
  latter is migrated (copied + adapted) into the academic toolkit, but the
  original remains for backward compatibility.
- No changes to core `parrot/tools/` — all new code lives in
  `parrot_tools/research/` (ai-parrot-tools satellite).
- No scraping of Gallup/Gartner — research confirmed both sites have no
  viable scraping path (no API, ToS prohibits, aggressive bot protection).
  Brainstorm Option A's `MarketResearchToolkit` scope is reduced to Statista
  public-page summaries only, plus stub interfaces.
- No OpenAPI-based dynamic generation (brainstorm Option B rejected — most
  target APIs lack official OpenAPI specs).

---

## 2. Architectural Design

### Overview

Three `AbstractToolkit` subclasses in `parrot_tools/research/`, each exposing
domain-specific async methods that automatically become agent tools. A
`BaseResearchToolkit` mixin provides shared infrastructure: the
`ResearchResult` / `Citation` Pydantic models, aiohttp session management
(via `auto_open=True` / `_open` / `_close` lifecycle per FEAT-391), and
`ToolCache` integration.

**Category 1 — Open Data (free REST APIs, no auth):**
- **World Bank Open Data** (`api.worldbank.org/v2/`) — indicator-code-based
  lookup (no server-side keyword search). Uses `wbgapi` library via
  `run_in_executor` to avoid blocking the event loop (resolved in brainstorm).
- **EU Open Data Portal** (`data.europa.eu/api/hub/search/`) — piveau platform
  (NOT CKAN) with full-text Elasticsearch search. Direct aiohttp calls.
- **OECD Data** (`sdmx.oecd.org/public/rest/v2/`) — SDMX 3.0 REST API
  preferred (resolved in brainstorm). Uses `sdmx1` library via
  `run_in_executor`.

**Category 2 — Academic Research (free APIs, optional keys):**
- **Crossref** (`api.crossref.org`) — full keyword search, polite pool
  (mailto). Uses `habanero` library via `run_in_executor`. Also covers
  Oxford Academic content via DOI prefix `10.1093` (Oxford Academic has no
  public API of its own).
- **PubMed** (`eutils.ncbi.nlm.nih.gov`) — two-step search→fetch workflow.
  Uses `Bio.Entrez` from Biopython via `run_in_executor` (**NOT** `pymed`,
  which is abandoned since 2019).
- **Semantic Scholar** (`api.semanticscholar.org/graph/v1`) — full search,
  default free tier with backoff (resolved in brainstorm). Direct aiohttp
  calls (response is JSON, fields must be explicitly requested).
- **ArXiv** — migrated from existing `ArxivTool` into this toolkit as
  `search_arxiv()` method (resolved in brainstorm). Uses `arxiv` library.

**Category 3 — Market Research (limited free access):**
- **Statista** — scrape publicly available statistic page summaries only
  (chart title, key value, source citation). Full data requires Statista
  Connect paid API.
- **Gallup** / **Gartner** — stub interfaces only (no API, no viable
  scraping path). Gallup partner-hosted datasets (World Bank Global Findex,
  FAO Voices of the Hungry, etc.) are reachable through `OpenDataToolkit`.

**Cross-category dispatch:**
- **`ResearchRouter`** — standalone `AbstractTool` that uses LLM-based intent
  classification (resolved in brainstorm) to route a natural-language query
  to the right toolkit method(s), then merges and ranks results.

### Component Diagram

```
Agent
  │
  ├──→ ResearchRouter.research(query, categories?, max_results?)
  │        │  (LLM intent classification → dispatch)
  │        ├──→ OpenDataToolkit
  │        ├──→ AcademicResearchToolkit
  │        └──→ MarketResearchToolkit
  │
  ├──→ OpenDataToolkit (direct)
  │        ├── search_world_bank(query, indicator?, country?, date_range?)
  │        ├── get_world_bank_indicator(indicator_id, country, year?)
  │        ├── search_eu_open_data(query, dataset_type?, publisher?)
  │        ├── search_oecd_data(query, dataset?, country?)
  │        └── get_oecd_indicator(dataset_id, country, frequency?)
  │
  ├──→ AcademicResearchToolkit (direct)
  │        ├── search_crossref(query, author?, year_range?, journal?)
  │        ├── search_pubmed(query, mesh_terms?, date_range?, max_results?)
  │        ├── search_semantic_scholar(query, fields_of_study?, year?, ...)
  │        ├── search_arxiv(query, max_results?, sort_by?, category?)
  │        └── get_paper_details(doi_or_id, source?)
  │
  └──→ MarketResearchToolkit (direct)
           ├── search_statista(query, industry?, region?)
           ├── search_gallup(query, topic?, region?)  [stub]
           └── search_gartner(query, research_type?)  [stub]

Shared base:
  BaseResearchToolkit (mixin)
  ├── ResearchResult / Citation / IndicatorValue (Pydantic models)
  ├── aiohttp.ClientSession lifecycle (_open/_close, auto_open=True)
  ├── ToolCache integration (Redis, per-toolkit TTL)
  └── _make_api_request() / _run_sync_in_executor() helpers
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.tools.toolkit.AbstractToolkit` | inherits | Base class for all three category toolkits |
| `parrot.tools.abstract.AbstractTool` | inherits | Base class for ResearchRouter |
| `parrot.tools.abstract.ToolResult` | uses | Standard return type from all tools |
| `parrot_tools.cache.ToolCache` | uses | Redis-backed response caching |
| `parrot.interfaces.http.HTTPService` | uses (selectively) | For REST calls where aiohttp.ClientSession is insufficient |
| `parrot_tools.arxiv_tool.ArxivTool` | migrates (copy+adapt) | ArXiv search logic moved into AcademicResearchToolkit |
| `parrot_tools.ddgo.DuckDuckGoToolkit` | pattern reference | backoff + run_in_executor pattern for sync libraries |
| `parrot_tools.fred_api.FredAPITool` | pattern reference | HTTPService + ToolCache pattern |
| Agent tool registration (ToolManager) | extends | New toolkits registered as additional tool sources |

### Data Models

```python
# NEW — parrot_tools/research/models.py

class Citation(BaseModel):
    """Machine-readable citation for every research result."""
    source_name: str          # "World Bank Open Data", "Crossref", etc.
    source_url: str           # Direct URL to the data/paper
    access_date: str          # ISO-8601 date of the API call
    data_vintage: Optional[str] = None  # When the data was published/updated
    formatted_citation: str   # Human-readable citation string
    doi: Optional[str] = None # For academic papers
    license: Optional[str] = None  # Data license if known

class IndicatorValue(BaseModel):
    """A single data point from an indicator/time-series source."""
    indicator_id: str         # e.g. "NY.GDP.MKTP.KD.ZG"
    indicator_name: str       # e.g. "GDP growth (annual %)"
    country: str              # ISO-3166 code
    country_name: str
    year: str                 # or date string
    value: Optional[float]    # null for missing observations
    unit: Optional[str] = None
    source_note: Optional[str] = None

class PaperResult(BaseModel):
    """A single academic paper result."""
    title: str
    authors: List[str]
    abstract: Optional[str] = None
    published_date: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    journal: Optional[str] = None
    citation_count: Optional[int] = None
    fields_of_study: Optional[List[str]] = None
    open_access: Optional[bool] = None
    source: str               # "crossref", "pubmed", "semantic_scholar", "arxiv"

class DatasetResult(BaseModel):
    """A dataset/statistic result from open data or market research."""
    title: str
    description: Optional[str] = None
    publisher: Optional[str] = None
    url: Optional[str] = None
    keywords: Optional[List[str]] = None
    format: Optional[str] = None      # "JSON", "CSV", "API", etc.
    last_modified: Optional[str] = None
    source: str               # "eu_open_data", "statista", etc.

class ResearchResult(BaseModel):
    """Unified result container returned by all research tools."""
    query: str
    source: str               # toolkit + method identifier
    result_type: str           # "indicators", "papers", "datasets"
    total_results: Optional[int] = None
    indicators: Optional[List[IndicatorValue]] = None
    papers: Optional[List[PaperResult]] = None
    datasets: Optional[List[DatasetResult]] = None
    citation: Citation
    raw_metadata: Optional[Dict[str, Any]] = None  # source-specific extras
```

### New Public Interfaces

```python
# parrot_tools/research/base.py
class BaseResearchToolkit:
    """Mixin providing shared infrastructure for research toolkits."""
    auto_open: bool = True
    _cache: ToolCache
    _session: aiohttp.ClientSession

    async def _open(self) -> None: ...
    async def _close(self) -> None: ...
    async def _make_api_request(
        self, url: str, params: dict = None, headers: dict = None
    ) -> dict: ...
    async def _run_sync_in_executor(self, func, *args, **kwargs) -> Any: ...
    def _build_citation(
        self, source_name: str, source_url: str,
        data_vintage: str = None, doi: str = None, license: str = None
    ) -> Citation: ...

# parrot_tools/research/open_data.py
class OpenDataToolkit(BaseResearchToolkit, AbstractToolkit):
    async def search_world_bank(
        self, query: str, indicator: str = None,
        country: str = None, date_range: str = None,
        max_results: int = 10
    ) -> ResearchResult: ...

    async def get_world_bank_indicator(
        self, indicator_id: str, country: str,
        year: str = None, date_range: str = None
    ) -> ResearchResult: ...

    async def search_eu_open_data(
        self, query: str, dataset_type: str = None,
        publisher: str = None, max_results: int = 10
    ) -> ResearchResult: ...

    async def search_oecd_data(
        self, query: str, dataset: str = None,
        country: str = None, max_results: int = 10
    ) -> ResearchResult: ...

    async def get_oecd_indicator(
        self, dataset_id: str, country: str,
        frequency: str = None
    ) -> ResearchResult: ...

# parrot_tools/research/academic.py
class AcademicResearchToolkit(BaseResearchToolkit, AbstractToolkit):
    async def search_crossref(
        self, query: str, author: str = None,
        year_range: str = None, journal: str = None,
        max_results: int = 10
    ) -> ResearchResult: ...

    async def search_pubmed(
        self, query: str, mesh_terms: str = None,
        date_range: str = None, max_results: int = 10
    ) -> ResearchResult: ...

    async def search_semantic_scholar(
        self, query: str, fields_of_study: str = None,
        year: str = None, open_access_only: bool = False,
        max_results: int = 10
    ) -> ResearchResult: ...

    async def search_arxiv(
        self, query: str, max_results: int = 10,
        sort_by: str = "relevance", category: str = None
    ) -> ResearchResult: ...

    async def get_paper_details(
        self, doi_or_id: str, source: str = None
    ) -> ResearchResult: ...

# parrot_tools/research/market.py
class MarketResearchToolkit(BaseResearchToolkit, AbstractToolkit):
    async def search_statista(
        self, query: str, industry: str = None,
        region: str = None, max_results: int = 10
    ) -> ResearchResult: ...

    async def search_gallup(
        self, query: str, topic: str = None,
        region: str = None, max_results: int = 10
    ) -> ResearchResult: ...  # stub — returns not_available status

    async def search_gartner(
        self, query: str, research_type: str = None,
        max_results: int = 10
    ) -> ResearchResult: ...  # stub — returns not_available status

# parrot_tools/research/router.py
class ResearchRouter(AbstractTool):
    async def _execute(
        self, query: str, categories: List[str] = None,
        max_results: int = 10
    ) -> ToolResult: ...
```

---

## 3. Module Breakdown

### Module 1: Shared Models & Base Toolkit
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/research/__init__.py`,
  `packages/ai-parrot-tools/src/parrot_tools/research/models.py`,
  `packages/ai-parrot-tools/src/parrot_tools/research/base.py`
- **Responsibility**: `Citation`, `IndicatorValue`, `PaperResult`,
  `DatasetResult`, `ResearchResult` Pydantic models.
  `BaseResearchToolkit` mixin with aiohttp session lifecycle
  (`_open`/`_close`, `auto_open=True`), `ToolCache` integration,
  `_make_api_request()` helper for GET requests with error handling and
  backoff, `_run_sync_in_executor()` helper for sync library wrappers,
  `_build_citation()` factory.
- **Depends on**: `parrot.tools.toolkit.AbstractToolkit`,
  `parrot_tools.cache.ToolCache`, `aiohttp`, `backoff`

### Module 2: OpenDataToolkit
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/research/open_data.py`
- **Responsibility**: `OpenDataToolkit` with 5 async methods:
  - `search_world_bank` — uses `wbgapi` via `run_in_executor` for indicator
    search/listing; no server-side keyword search, so client-side filtering
    against indicator metadata. Returns `IndicatorValue` list.
  - `get_world_bank_indicator` — direct indicator+country lookup via `wbgapi`.
    Returns `IndicatorValue` list with time series.
  - `search_eu_open_data` — direct aiohttp GET to
    `data.europa.eu/api/hub/search/search` with `q=` full-text Elasticsearch
    query. Handles multilingual metadata (fallback to first available
    language if `en` missing). Returns `DatasetResult` list.
  - `search_oecd_data` — uses `sdmx1` via `run_in_executor` to browse OECD
    dataflow catalog. SDMX 3.0 endpoint preferred. Returns `DatasetResult`
    list with dataflow metadata.
  - `get_oecd_indicator` — uses `sdmx1` via `run_in_executor` to fetch
    actual data series from a known dataflow. Returns `IndicatorValue` list.
- **Depends on**: Module 1, `wbgapi`, `sdmx1`, `aiohttp`

### Module 3: AcademicResearchToolkit
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/research/academic.py`
- **Responsibility**: `AcademicResearchToolkit` with 5 async methods:
  - `search_crossref` — uses `habanero` via `run_in_executor`. Polite pool
    via `mailto` parameter. Uses `query.bibliographic` for better relevance
    (per Crossref best practice). Cursor pagination for >10k results if
    needed. Returns `PaperResult` list. Also covers Oxford Academic content
    (DOI prefix `10.1093`).
  - `search_pubmed` — uses `Bio.Entrez` from Biopython via
    `run_in_executor`. Two-step: `esearch` (term→PMIDs) then `efetch`
    (PMIDs→records). Sets `Entrez.email` and optional `Entrez.api_key` from
    env vars. Returns `PaperResult` list.
  - `search_semantic_scholar` — direct aiohttp GET to
    `api.semanticscholar.org/graph/v1/paper/search` with explicit `fields=`
    param (default response only returns paperId+title). Handles hyphenated
    query terms (replace with spaces). Free tier with backoff on 429.
    Returns `PaperResult` list.
  - `search_arxiv` — migrated from existing `ArxivTool`. Uses `arxiv`
    library via `run_in_executor`. Returns `PaperResult` list.
  - `get_paper_details` — resolves a DOI or paper ID across Crossref,
    Semantic Scholar, or PubMed (auto-detect source from ID format, or
    explicit `source` param). Returns single `PaperResult`.
- **Depends on**: Module 1, `habanero`, `biopython` (Bio.Entrez), `arxiv`,
  `aiohttp`

### Module 4: MarketResearchToolkit
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/research/market.py`
- **Responsibility**: `MarketResearchToolkit` with 3 async methods:
  - `search_statista` — aiohttp GET to Statista's public statistics pages,
    BeautifulSoup parsing to extract statistic title, key value, source
    citation, chart description. Returns `DatasetResult` list. Best-effort:
    returns `scrape_status="no_data"` on extraction failure, never raises.
  - `search_gallup` — **stub**: returns `ResearchResult` with
    `result_type="not_available"` and a message directing to Gallup partner
    datasets accessible through `OpenDataToolkit` (World Bank Global Findex,
    FAO Voices of the Hungry, etc.).
  - `search_gartner` — **stub**: returns `ResearchResult` with
    `result_type="not_available"` and a message about Gartner enterprise
    subscription requirements.
- **Depends on**: Module 1, `aiohttp`, `beautifulsoup4`

### Module 5: ResearchRouter
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/research/router.py`
- **Responsibility**: `ResearchRouter(AbstractTool)` with LLM-based intent
  classification. Receives a natural-language query, uses the agent's own
  LLM (via a lightweight prompt template) to classify into categories
  (`open_data`, `academic`, `market`), dispatches to the appropriate
  toolkit method(s), merges results into a ranked `ToolResult`. Falls back
  to keyword heuristics if LLM classification fails or is unavailable.
- **Depends on**: Modules 2-4, `parrot.tools.abstract.AbstractTool`

### Module 6: Tests & Fixtures
- **Path**: `packages/ai-parrot-tools/tests/research/`
- **Responsibility**: Fixture-based unit tests for all modules. Recorded
  API responses stored as JSON/XML fixture files. Mocked `aiohttp` sessions,
  mocked sync library calls. Live smoke tests (`@pytest.mark.live`, skipped
  in CI) for manual validation. Dependencies declared in satellite
  `pyproject.toml` extras.
- **Depends on**: Modules 1-5

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_citation_model_required_fields` | 1 | Citation requires source_name, source_url, access_date, formatted_citation |
| `test_research_result_indicator_mode` | 1 | ResearchResult with indicators populated, papers/datasets None |
| `test_research_result_papers_mode` | 1 | ResearchResult with papers populated |
| `test_base_toolkit_session_lifecycle` | 1 | _open creates aiohttp session, _close closes it, auto_open triggers on first call |
| `test_make_api_request_success` | 1 | _make_api_request returns parsed JSON on 200 |
| `test_make_api_request_rate_limit_retry` | 1 | 429 response triggers backoff retry |
| `test_make_api_request_timeout` | 1 | Timeout returns error, not exception |
| `test_cache_hit_skips_api` | 1 | Cached response returned without API call |
| `test_cache_miss_stores_result` | 1 | API response cached after successful call |
| `test_search_world_bank_fixture` | 2 | Mocked wbgapi returns fixture data → IndicatorValue list |
| `test_get_world_bank_indicator_fixture` | 2 | Direct indicator lookup → time series |
| `test_search_eu_open_data_fixture` | 2 | Mocked aiohttp GET → DatasetResult list |
| `test_eu_open_data_multilingual_fallback` | 2 | Missing `en` title → falls back to first available language |
| `test_search_oecd_fixture` | 2 | Mocked sdmx1 → DatasetResult list |
| `test_get_oecd_indicator_fixture` | 2 | Mocked sdmx1 data fetch → IndicatorValue list |
| `test_search_crossref_fixture` | 3 | Mocked habanero → PaperResult list with DOIs |
| `test_search_pubmed_fixture` | 3 | Mocked Bio.Entrez esearch+efetch → PaperResult list |
| `test_search_semantic_scholar_fixture` | 3 | Mocked aiohttp GET → PaperResult list |
| `test_semantic_scholar_hyphen_fix` | 3 | Hyphenated query terms replaced with spaces |
| `test_search_arxiv_fixture` | 3 | Mocked arxiv library → PaperResult list |
| `test_get_paper_details_doi` | 3 | DOI format auto-detected → Crossref lookup |
| `test_get_paper_details_pmid` | 3 | PMID format auto-detected → PubMed lookup |
| `test_search_statista_fixture` | 4 | Mocked aiohttp + BeautifulSoup → DatasetResult |
| `test_search_gallup_stub` | 4 | Returns not_available with partner dataset message |
| `test_search_gartner_stub` | 4 | Returns not_available with subscription message |
| `test_router_dispatches_to_academic` | 5 | Academic query dispatched to AcademicResearchToolkit |
| `test_router_dispatches_to_open_data` | 5 | Economic query dispatched to OpenDataToolkit |
| `test_router_explicit_categories` | 5 | Explicit categories param overrides LLM classification |
| `test_router_merges_results` | 5 | Multi-category results merged and ranked |
| `test_all_citations_complete` | 1-4 | Every ResearchResult from every method has a complete Citation |

### Integration Tests

| Test | Description |
|---|---|
| `test_toolkit_tools_exposed` | Each toolkit's `get_tools()` includes all expected methods |
| `test_router_tool_schema` | ResearchRouter has valid args_schema with query, categories, max_results |
| `test_toolkit_cache_integration` | ToolCache correctly caches and returns results across calls |

### Test Data / Fixtures

```python
# tests/research/conftest.py
@pytest.fixture
def world_bank_indicator_response() -> dict:
    """Recorded JSON from api.worldbank.org/v2/ for GDP indicator."""
    ...

@pytest.fixture
def eu_open_data_search_response() -> dict:
    """Recorded JSON from data.europa.eu/api/hub/search/ for energy query."""
    ...

@pytest.fixture
def crossref_works_response() -> dict:
    """Recorded JSON from api.crossref.org/works for transformer papers."""
    ...

@pytest.fixture
def pubmed_esearch_response() -> str:
    """Recorded XML from eutils.ncbi.nlm.nih.gov esearch."""
    ...

@pytest.fixture
def pubmed_efetch_response() -> str:
    """Recorded XML from eutils.ncbi.nlm.nih.gov efetch."""
    ...

@pytest.fixture
def semantic_scholar_search_response() -> dict:
    """Recorded JSON from api.semanticscholar.org/graph/v1/paper/search."""
    ...

@pytest.fixture
def statista_page_html() -> str:
    """Recorded HTML from a Statista public statistics page."""
    ...

@pytest.fixture
def mock_aiohttp_session(monkeypatch):
    """Mock aiohttp.ClientSession returning fixture responses."""
    ...

@pytest.fixture
def mock_wbgapi(monkeypatch):
    """Mock wbgapi library calls."""
    ...
```

---

## 5. Acceptance Criteria

- [ ] `OpenDataToolkit` exposes 5 tools via `get_tools()`:
  `search_world_bank`, `get_world_bank_indicator`, `search_eu_open_data`,
  `search_oecd_data`, `get_oecd_indicator`.
- [ ] `AcademicResearchToolkit` exposes 5 tools via `get_tools()`:
  `search_crossref`, `search_pubmed`, `search_semantic_scholar`,
  `search_arxiv`, `get_paper_details`.
- [ ] `MarketResearchToolkit` exposes 3 tools via `get_tools()`:
  `search_statista`, `search_gallup` (stub), `search_gartner` (stub).
- [ ] `ResearchRouter` is a standalone `AbstractTool` with `_execute(query,
  categories?, max_results?)` that dispatches to the right toolkit(s).
- [ ] **Every** `ResearchResult` returned by any tool method includes a
  complete `Citation` with non-empty `source_name`, `source_url`,
  `access_date`, and `formatted_citation`.
- [ ] All three toolkits use `auto_open=True` and manage an
  `aiohttp.ClientSession` via `_open`/`_close` (FEAT-391 lifecycle).
- [ ] All API calls are cached via `ToolCache` with configurable TTL
  (default: 1 hour for indicators, 24 hours for papers, 5 minutes for
  market research).
- [ ] No tool method raises into the agent loop — all errors are returned
  as `ToolResult(status="error", error=...)` or `ResearchResult` with
  appropriate error metadata.
- [ ] Sync library calls (`wbgapi`, `sdmx1`, `habanero`, `Bio.Entrez`,
  `arxiv`) are wrapped in `asyncio.get_running_loop().run_in_executor(None, ...)`
  — no blocking the event loop.
- [ ] `pytest packages/ai-parrot-tools/tests/research/ -v` passes with
  fixtures only (no network); live tests opt-in via `-m live`.
- [ ] Satellite `pyproject.toml` declares new dependencies in a `research`
  optional extra.
- [ ] Missing optional libraries produce clear `ImportError` messages
  with install instructions (like ArxivTool pattern), not cryptic failures.
- [ ] Stub methods (`search_gallup`, `search_gartner`) return a structured
  `ResearchResult` with `result_type="not_available"` and a helpful message.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** All entries carried forward from
> brainstorm and re-verified 2026-08-17 on `dev` @ `e2694ea`. Key imports
> verified via live `python -c` execution in the project venv.

### Verified Imports

```python
# Core toolkit/tool base classes
from parrot.tools.toolkit import AbstractToolkit    # parrot/tools/toolkit.py
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema, ToolResult
    # parrot/tools/abstract.py — ToolResult has: status, result, error, metadata

# Satellite re-exports
from parrot_tools.toolkit import AbstractToolkit    # parrot_tools/toolkit.py:2 (re-export)
from parrot_tools.cache import ToolCache, DEFAULT_TOOL_CACHE_TTL
    # parrot_tools/cache.py — ToolCache(prefix, ttl, redis_url), .get(), .set()

# HTTP / networking
import aiohttp                                      # core dep
from parrot.interfaces.http import HTTPService      # parrot/interfaces/http.py
    # HTTPService(base_url=...) → .request(url, method) returns (response, error)
    # HTTPService(accept=..., headers=...) → .session(url, method) returns (result, error)

# Retry / backoff
import backoff                                      # pyproject.toml:45, backoff==2.2.1

# Parsing
from bs4 import BeautifulSoup                       # satellite dep, beautifulsoup4>=4.12

# External data libraries (to be added as deps)
import wbgapi                   # World Bank — NOT currently installed
import sdmx                     # sdmx1 package — NOT currently installed
from habanero import Crossref   # Crossref — NOT currently installed
from Bio import Entrez          # Biopython — NOT currently installed
import arxiv                    # Already used by ArxivTool (arxiv_tool.py:7)

# DuckDuckGo (pattern reference — NOT used directly)
from ddgs import DDGS                               # ddgo.py:11
from ddgs.exceptions import RatelimitException      # ddgo.py:14

# Config / logging
from navconfig import config                        # env var access
from navconfig.logging import logging               # logger

# Pydantic
from pydantic import BaseModel, Field
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):
    auto_open: bool = False
    exclude_tools: tuple[str, ...] = ()
    tool_prefix: Optional[str] = None
    credential_provider: Optional[str] = None

    def __init__(self, **kwargs): ...
    async def _open(self) -> None: ...               # acquire resources
    async def _close(self) -> None: ...              # release resources
    async def _ensure_open(self) -> None: ...        # idempotent gate (Lock-guarded)
    async def _pre_execute(self, tool_name, /, **kwargs) -> None: ...
    async def _post_execute(self, tool_name, result, /, **kwargs) -> Any: ...
    def get_tools(self, ...) -> List[AbstractTool]: ...
    def _generate_tools(self) -> None: ...           # auto-generates tools from async methods

# packages/ai-parrot/src/parrot/tools/abstract.py
class AbstractTool:
    name: str
    description: str
    args_schema: Type[BaseModel]
    return_direct: bool = False
    async def _execute(self, **kwargs) -> Any: ...

class ToolResult:
    # Fields: status (str), result (Any), error (Optional[str]), metadata (Optional[Dict])

# packages/ai-parrot-tools/src/parrot_tools/cache.py
class ToolCache:
    def __init__(self, prefix="tool_cache", ttl=300, redis_url=None): ...
    async def get(self, tool_name: str, method: str, **params) -> Optional[Any]: ...
    async def set(self, tool_name: str, method: str, value: Any,
                  ttl: int = None, **params) -> None: ...
    async def close(self) -> None: ...

# packages/ai-parrot-tools/src/parrot_tools/arxiv_tool.py
class ArxivTool(AbstractTool):
    name: str = "arxiv_search"
    description: str = "Search for academic papers on arXiv.org..."
    args_schema: Type[BaseModel] = ArxivSearchArgsSchema
    def _format_paper(self, paper: arxiv.Result) -> Dict[str, Any]: ...
    async def _execute(self, query, max_results=5, sort_by="relevance",
                       sort_order="descending", **kwargs) -> Any: ...

# packages/ai-parrot-tools/src/parrot_tools/ddgo.py (pattern reference)
class DuckDuckGoToolkit(AbstractToolkit):
    # Pattern: backoff.on_exception(backoff.expo, (RatelimitException,...), ...)
    # Pattern: loop.run_in_executor(None, _search)
    async def web_search(self, query, ...) -> ToolResult: ...

# packages/ai-parrot-tools/src/parrot_tools/fred_api.py (pattern reference)
class FredAPITool(AbstractTool):
    BASE_URL: str = "https://api.stlouisfed.org/fred"
    # Pattern: HTTPService + ToolCache + ToolResult
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `BaseResearchToolkit._open()` | `aiohttp.ClientSession()` | constructor | standard aiohttp API |
| `BaseResearchToolkit._close()` | `aiohttp.ClientSession.close()` | method call | standard aiohttp API |
| `BaseResearchToolkit._close()` | `AbstractToolkit._close()` | `await super()._close()` | toolkit.py `_close` resets `_opened` |
| `BaseResearchToolkit._cache` | `ToolCache(prefix, ttl)` | constructor | cache.py |
| `OpenDataToolkit.search_world_bank` | `wbgapi.economy.coder()` / `wbgapi.data.DataFrame()` | `run_in_executor` | to be installed |
| `OpenDataToolkit.search_eu_open_data` | `data.europa.eu/api/hub/search/search` | `_make_api_request()` GET | verified URL pattern |
| `OpenDataToolkit.search_oecd_data` | `sdmx.Client("OECD3")` | `run_in_executor` | to be installed |
| `AcademicResearchToolkit.search_crossref` | `habanero.Crossref().works()` | `run_in_executor` | to be installed |
| `AcademicResearchToolkit.search_pubmed` | `Bio.Entrez.esearch()` / `Bio.Entrez.efetch()` | `run_in_executor` | to be installed |
| `AcademicResearchToolkit.search_semantic_scholar` | `api.semanticscholar.org/graph/v1/paper/search` | `_make_api_request()` GET | verified URL |
| `AcademicResearchToolkit.search_arxiv` | `arxiv.Client().results()` | `run_in_executor` | arxiv_tool.py |
| `MarketResearchToolkit.search_statista` | `statista.com/statistics/` pages | aiohttp GET + BeautifulSoup | public pages |
| `ResearchRouter._execute` | toolkit instances | method dispatch | internal |
| Tool registration | `ToolManager.register_toolkit()` | toolkit.get_tools() | toolkit.py |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot_tools.research`~~ — package does not exist yet (this spec creates it)
- ~~`parrot_tools.worldbank`~~ — no World Bank tool/module exists
- ~~`parrot_tools.crossref`~~ — no Crossref tool/module exists
- ~~`parrot_tools.pubmed`~~ — no PubMed tool/module exists
- ~~`ResearchResult` model~~ — does not exist; Module 1 creates it
- ~~`Citation` model~~ — does not exist; Module 1 creates it
- ~~`BaseResearchToolkit`~~ — does not exist; Module 1 creates it
- ~~`pymed` package~~ — **ABANDONED** (last release 2019). Do NOT use.
  Use `Bio.Entrez` from Biopython instead.
- ~~Oxford Academic API~~ — **does not exist**. Oxford Academic
  (`academic.oup.com`) has no public API and no OAI-PMH feed. OUP content
  (DOI prefix `10.1093`) is accessed through Crossref.
- ~~Gallup public API~~ — **does not exist**. Gallup has no developer
  portal or public API. `api.gallup.com` returns 403 on all paths.
- ~~Gartner public API~~ — **does not exist**. Enterprise subscription
  only, aggressive Cloudflare bot protection.
- ~~`duckduckgo_search` package in satellite~~ — the satellite uses
  `ddgs` (see `ddgo.py:11`), not `duckduckgo_search`.
- ~~`HTTPService.session()` as async context manager~~ — `session()` is a
  regular async method returning `(result, error)`, NOT a context manager.
- ~~`wbgapi` in pyproject.toml~~ — not currently a dependency; must be added
- ~~`sdmx1` in pyproject.toml~~ — not currently a dependency; must be added
- ~~`habanero` in pyproject.toml~~ — not currently a dependency; must be added
- ~~`biopython` in pyproject.toml~~ — not currently a dependency; must be added

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Toolkit lifecycle** (FEAT-391): `auto_open = True`, `_open()` creates
  `aiohttp.ClientSession`, `_close()` closes it and calls
  `await super()._close()` to reset `_opened`. See AbstractToolkit in
  `toolkit.py`.
- **Sync library wrapping** (from `ddgo.py`): For sync libraries (`wbgapi`,
  `sdmx1`, `habanero`, `Bio.Entrez`, `arxiv`), wrap calls in:
  ```python
  loop = asyncio.get_running_loop()
  result = await loop.run_in_executor(None, sync_function)
  ```
  Use `backoff.on_exception(backoff.expo, ...)` on the inner sync function
  for rate-limit retries.
- **Error handling**: Never raise into the agent loop. Return
  `ToolResult(status="error", error=str(e))` or populate
  `ResearchResult.raw_metadata["error"]`. Follow `FredAPITool._execute()`
  pattern.
- **Cache key construction**: Use `ToolCache._build_key(tool_name, method,
  **params)` — it hashes sorted params deterministically. Exclude API keys
  from cache params.
- **Optional dependency imports**: Use try/except pattern from `ArxivTool`:
  ```python
  try:
      import wbgapi
  except ImportError:
      wbgapi = None
  # ... in method:
  if wbgapi is None:
      raise ImportError("Install ai-parrot-tools[research] for World Bank support")
  ```
- **Docstrings become tool descriptions**: Every public async method's
  docstring is the LLM's tool description. Write them for the LLM, not for
  developers. Include example queries and parameter guidance.
- **Async-first, Google-style docstrings, type hints, `self.logger`**
  throughout (repo rules).

### Known Risks / Gotchas

- **World Bank API default format is XML** — must always pass `format=json`
  explicitly when using direct aiohttp calls. `wbgapi` handles this
  internally.
- **World Bank has no keyword search** — `search_world_bank` must use
  client-side filtering against indicator metadata or `wbgapi`'s built-in
  indicator search functions. The method's docstring must tell the agent
  that indicator codes or topic areas are more effective than free-text.
- **OECD dimension order is positional** — must fetch the Data Structure
  Definition (DSD) before constructing data queries. `sdmx1` handles this.
- **PubMed requires two API calls** — `esearch` (query→PMIDs) then `efetch`
  (PMIDs→records). Cannot get results in a single call.
- **Semantic Scholar `fields=` is mandatory** — default response returns
  only `paperId` + `title`. Must explicitly request `title,abstract,
  authors,year,citationCount,openAccessPdf,externalIds,fieldsOfStudy`.
- **Semantic Scholar hyphens** — hyphenated query terms return zero
  results. Replace hyphens with spaces before querying.
- **Semantic Scholar rate limits are shared globally** — unauthenticated
  pool (1000 req/sec) is shared across ALL users. Easy to get 429'd.
  Backoff is essential.
- **Crossref `offset` capped at 10,000** — for deep pagination use
  cursor-based pagination (`cursor=*` + `next-cursor`). For typical agent
  use (10-50 results), offset is sufficient.
- **EU Open Data multilingual metadata** — English title/description is
  NOT guaranteed. Must handle `title` as a dict with language keys and
  fall back to first available.
- **Statista selector drift** — public page structure may change. Extraction
  is best-effort; failures return empty results, never exceptions.
- **Missing optional deps** — all external libraries (`wbgapi`, `sdmx1`,
  etc.) are optional. Each toolkit must gracefully handle missing deps
  with clear import error messages.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `wbgapi` | `>=1.0` | World Bank Indicators API — indicator search, country data, time series |
| `sdmx1` | `>=2.27` | OECD/Eurostat SDMX data access — dataflow catalog, data series |
| `habanero` | `>=2.9` | Crossref API — academic paper search, DOI resolution |
| `biopython` | `>=1.80` | PubMed E-utilities via `Bio.Entrez` — biomedical paper search |
| `arxiv` | `>=2.0` | ArXiv paper search (already used by `ArxivTool`) |
| `beautifulsoup4` | `>=4.12` | Statista page scraping (already a satellite dependency) |
| `aiohttp` | (existing) | Direct REST API calls to EU Open Data, Semantic Scholar |
| `backoff` | (existing) | Exponential backoff for rate limits |

All new packages go into a `research` optional extra in the satellite
`pyproject.toml`:
```toml
[project.optional-dependencies]
research = ["wbgapi>=1.0", "sdmx1>=2.27", "habanero>=2.9", "biopython>=1.80", "arxiv>=2.0"]
```

---

## 8. Open Questions

> **Resolved in brainstorm — carried forward, do NOT re-ask:**

- [x] **Which Python SDK for World Bank?** — *Resolved in brainstorm*:
  Uses `wbgapi`, run in `asyncio.run_in_executor` to avoid blocking the
  event loop.
- [x] **OECD API version?** — *Resolved in brainstorm*: Preferable SDMX
  3.0 (`sdmx.oecd.org/public/rest/v2/`). `sdmx1` library supports both
  v1 and v2 via the `OECD3` source entry.
- [x] **Semantic Scholar API key?** — *Resolved in brainstorm*: Default
  free tier with backoff retry. API key support via env var
  (`SEMANTIC_SCHOLAR_API_KEY`) for higher limits but not required.
- [x] **ArxivTool integration?** — *Resolved in brainstorm*: Migrated
  into `AcademicResearchToolkit` as a `search_arxiv()` method. Original
  standalone `ArxivTool` preserved for backward compatibility.
- [x] **ResearchRouter query classification?** — *Resolved in brainstorm*:
  LLM-based intent classification with keyword heuristic fallback.

> **Resolved during spec research:**

- [x] **Gallup/Gartner scraping feasibility?** — *Resolved by API research*:
  NOT feasible. Gallup has no public API (partner datasets accessible via
  World Bank etc.). Gartner has no public API and aggressive bot protection.
  Both are stubbed with clear interfaces. Statista has a public page path
  for basic data but its full API ("Statista Connect") is contract-gated.
- [x] **PubMed Python library?** — *Resolved by API research*: `pymed` is
  abandoned (last release 2019). Use `Bio.Entrez` from Biopython (v1.88,
  actively maintained).
- [x] **Oxford Academic integration?** — *Resolved by API research*: Oxford
  Academic has no public API. OUP content is accessible through Crossref
  (DOI prefix `10.1093`) — no separate source needed.

> **Unresolved — defer to implementation:**

- [ ] **Statista page structure stability** — whether current public
  statistics pages have stable-enough structure for reliable scraping.
  The `-m live` smoke test will validate during implementation. If
  fragile, may need to be demoted to stub. — *Owner: implementer*
- [ ] **ResearchRouter LLM prompt design** — exact prompt template for
  query classification (category detection). Should be lightweight (few
  tokens) and work across providers. — *Owner: implementer*
- [ ] **ToolCache TTL tuning** — optimal TTLs per data type. Starting
  values: 1h indicators, 24h papers, 5min market research. May need
  adjustment based on usage patterns. — *Owner: implementer*

---

## Worktree Strategy

- **Isolation unit**: `mixed` — Module 1 (base models + mixin) must be
  implemented first; Modules 2, 3, and 4 can then run in parallel in
  separate worktrees since they are in different files within
  `parrot_tools/research/`. Module 5 (router) depends on 2-4. Module 6
  (tests) spans all.
- **Recommended task ordering**:
  1. Module 1 (base) — sequential, blocks everything
  2. Modules 2 + 3 + 4 (three toolkits) — **parallel** after Module 1
  3. Module 5 (router) — after 2 + 3 + 4
  4. Module 6 (tests) — throughout, per-module tests with each module
- **Cross-feature dependencies**: None. All files are new
  (`parrot_tools/research/`). No existing files are modified except the
  satellite `pyproject.toml` (Module 6, adding extras).
- Worktree base: `git worktree add -b feat-426-research-tools-for-agents
  .claude/worktrees/feat-426-research-tools-for-agents HEAD` (from `dev`,
  after `/sdd-task`).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-17 | Jesus Lara + Claude (Opus 4.6) | Initial draft from FEAT-426 brainstorm; scope adjusted based on API research (Gallup/Gartner stubbed, pymed→Biopython, Oxford Academic→Crossref) |
