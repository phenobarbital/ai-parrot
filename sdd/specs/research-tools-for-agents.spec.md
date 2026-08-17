---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: Research Tools for Agents — Direct Access to Authoritative Data Sources

**Feature ID**: FEAT-426
**Date**: 2026-08-17
**Author**: Jesus Lara + Claude (Opus 4.6, revised by Opus 5 after adversarial review)
**Status**: approved
**Target version**: ai-parrot-tools next minor

> **Prior exploration**: `sdd/proposals/research-tools-for-agents.brainstorm.md`
> (status: exploration, recommended Option A — Category-Based AbstractToolkit
> Subclasses with Shared Base). All resolved open questions from the brainstorm
> are carried forward below; none have been re-opened.
>
> **Revision 0.2 — post-review.** This spec was reviewed against the live
> codebase (empirical probes + `codex exec` adversarial pass). Five blocking
> defects were fixed and `MarketResearchToolkit` was dropped from v1. See
> §9 Review Log for the full disposition.

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot agents that need factual, citable data (economic indicators, academic
research) currently have **no direct path to authoritative sources**. The only
options are:

1. **Google/SerpAPI web search** — returns noisy results, requires filtering,
   costs per query, and the data is second-hand (news articles *about*
   World Bank data, not the data itself).
2. **DuckDuckGo search** (`DuckDuckGoToolkit`) — free but equally indirect;
   the agent still gets web pages, not structured data.
3. **Single-source tools** — `FredAPITool` (FRED economic data) and
   `ArxivTool` (arXiv papers) exist but are standalone, with no shared
   citation model or cross-source query capability.

### Goals

- **G1**: Two category-based toolkits (`OpenDataToolkit`,
  `AcademicResearchToolkit`) that give agents direct, structured access to
  authoritative data sources without web-search intermediaries.
- **G2**: A shared `ResearchResult` / `Citation` Pydantic model enforced across
  both toolkits — every **successful** result carries a `Citation` with
  `source_name`, `source_url`, `access_date`, and `formatted_citation`
  populated. `data_vintage` is best-effort (populated when the source
  exposes it).
- **G3**: A `ResearchRouter` tool that classifies a natural-language query
  into categories using an **explicitly injected** LLM client and dispatches
  to the relevant toolkit method(s).
- **G4**: Existing `ArxivTool` logic migrated into `AcademicResearchToolkit`
  as a `search_arxiv()` method (resolved in brainstorm).
- **G5**: Redis-backed `ToolCache` integration for all API calls with
  configurable per-toolkit TTLs.
- **G6**: Fixture-based tests — no live API calls in CI.
- **G7**: **No research tool ever raises into the agent loop.** Failures are
  returned as data (see §2 "Error Contract").

### Non-Goals (explicitly out of scope)

- **`MarketResearchToolkit` is deferred out of v1.** Gallup and Gartner have
  no public API and no viable scraping path; Statista's legal notice
  prohibits crawler access, and its only sanctioned programmatic path
  ("Statista Connect" REST API + MCP server) is contract-gated with no
  self-serve signup. A toolkit of one ToS-questionable scraper plus two
  stubs is not worth shipping. Revisit if a Statista Connect contract is
  acquired — the `BaseResearchToolkit` seam makes it additive.
- **No paid or contract-gated integrations.** Optional *free* API keys that
  merely raise rate limits (PubMed `api_key`, Semantic Scholar `x-api-key`)
  ARE supported — they are never required for correct operation.
- No modification to existing `FredAPITool` or standalone `ArxivTool` — the
  latter's logic is re-implemented inside the academic toolkit; the original
  class remains for backward compatibility (accepted duplication, see §7).
- No changes to core `parrot/tools/` — all new code lives in
  `parrot_tools/research/` (ai-parrot-tools satellite).
- No OpenAPI-based dynamic generation (brainstorm Option B rejected — most
  target APIs lack official OpenAPI specs).
- No use of `parrot.interfaces.HTTPService` (see §7 — it is `requests`/`httpx`
  backed and would introduce blocking I/O).

---

## 2. Architectural Design

### Overview

Two `AbstractToolkit` subclasses in `parrot_tools/research/`, each exposing
domain-specific async methods that automatically become agent tools, plus a
`ResearchRouter` standalone tool. A `BaseResearchToolkit` mixin provides
shared infrastructure: aiohttp session management (via `auto_open=True` /
`_open` / `_close` per FEAT-391), `ToolCache` integration, and citation
construction.

**Category 1 — Open Data (free REST APIs, no auth):**
- **World Bank Open Data** (`api.worldbank.org/v2/`) — indicator-code-based
  lookup (no server-side keyword search). Uses `wbgapi` via `run_in_executor`.
- **EU Open Data Portal** (`data.europa.eu/api/hub/search/`) — piveau platform
  (NOT CKAN) with full-text Elasticsearch search. Direct aiohttp calls.
- **OECD Data** (`sdmx.oecd.org/public/rest/v2/`) — SDMX 3.0 REST preferred.
  Uses `sdmx1` via `run_in_executor`.

**Category 2 — Academic Research (free APIs, optional free keys):**
- **Crossref** (`api.crossref.org`) — full keyword search, polite pool via
  `mailto`. Uses `habanero` via `run_in_executor`. Also covers Oxford
  Academic content (DOI prefix `10.1093`; OUP has no API of its own).
- **PubMed** (`eutils.ncbi.nlm.nih.gov`) — two-step search→fetch. Uses
  `Bio.Entrez` from Biopython via `run_in_executor` (**NOT** `pymed`,
  abandoned since 2019).
- **Semantic Scholar** (`api.semanticscholar.org/graph/v1`) — direct aiohttp;
  free tier with backoff.
- **ArXiv** — migrated from `ArxivTool`; uses `arxiv` via `run_in_executor`.

**Cross-category dispatch:**
- **`ResearchRouter`** — an `AbstractTool` constructed with toolkit instances
  and an **explicitly injected** LLM client for intent classification.

### Error Contract (normative — resolves the framework's raise-on-error path)

Verified framework behavior (`manager.py:1594` → `:1614`): `ToolManager.execute_tool()`
**raises `ValueError(result.error)`** whenever a tool yields a `ToolResult`
with `status == "error"`. Therefore G7 ("never raise into the agent loop")
requires the following rules:

1. **Toolkit methods return `ResearchResult` — never a `ToolResult`, never an
   exception.** `AbstractTool.execute()` wraps the raw return into a
   successful `ToolResult` automatically (verified empirically: a method
   returning `ResearchResult` yields `ToolResult(success=True,
   status="success", result=<ResearchResult>)`).
2. **Failures are encoded as data** in `ResearchResult.status` /
   `.error_message`, not as an error `ToolResult`. Valid `status` values:
   `success`, `partial`, `no_data`, `error`.
3. **`ResearchRouter._execute()` returns `ToolResult(success=True,
   status="success", result=...)`** even when some categories fail; per-
   category failures live in the payload.
4. `ToolResult(success=False, status="error", ...)` is **reserved** for
   genuinely unrecoverable conditions where raising into the agent loop is
   the *intended* behavior. If used, `success=False` MUST be passed
   explicitly — `ToolResult(status="error")` alone leaves `success=True`
   (verified: the field defaults to `True` independently of `status`).

### Component Diagram

```
Agent
  │
  ├──→ ResearchRouter.research(query, categories?, max_results?)
  │        │  (injected LLM classifies → dispatch; heuristic fallback)
  │        ├──→ OpenDataToolkit
  │        └──→ AcademicResearchToolkit
  │
  ├──→ OpenDataToolkit (direct)
  │        ├── search_world_bank(query, indicator?, country?, date_range?)
  │        ├── get_world_bank_indicator(indicator_id, country, year?)
  │        ├── search_eu_open_data(query, dataset_type?, publisher?)
  │        ├── search_oecd_data(query, dataset?, country?)
  │        └── get_oecd_indicator(dataset_id, country, frequency?)
  │
  └──→ AcademicResearchToolkit (direct)
           ├── search_crossref(query, author?, year_range?, journal?)
           ├── search_pubmed(query, mesh_terms?, date_range?, max_results?)
           ├── search_semantic_scholar(query, fields_of_study?, year?, ...)
           ├── search_arxiv(query, max_results?, sort_by?, category?)
           └── get_paper_details(doi_or_id, source?)

Shared base:
  BaseResearchToolkit (cooperative mixin — see §7 MRO rules)
  ├── aiohttp.ClientSession lifecycle (_open/_close, auto_open=True)
  ├── ToolCache integration (Redis, per-toolkit TTL)
  └── _make_api_request() / _run_sync_in_executor() / _build_citation()
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.tools.toolkit.AbstractToolkit` | inherits | Base for both category toolkits |
| `parrot.tools.abstract.AbstractTool` | inherits | Base for `ResearchRouter` |
| `parrot.tools.abstract.ToolResult` | produced indirectly | Framework wraps toolkit returns; router returns it directly |
| `parrot_tools.cache.ToolCache` | uses | Redis-backed response caching via `.get()` / `.set()` |
| `parrot.clients.factory.LLMFactory` | uses | Resolves a string model spec for the router's classifier |
| `parrot.clients.base.AbstractClient` | uses | Injected classifier client type |
| `parrot_tools.arxiv_tool.ArxivTool` | pattern reference | ArXiv logic re-implemented; original untouched |
| `parrot_tools.ddgo.DuckDuckGoToolkit` | pattern reference | backoff + `run_in_executor` for sync libraries |
| `parrot_tools.__init__.TOOL_REGISTRY` | **regenerated** | Auto-generated; CI fails if stale (Module 5) |
| `scripts/generate_tool_registry.py` | **must be run** | `--check` runs in CI (`.github/workflows/ci.yml:30`) |
| `packages/ai-parrot-tools/pyproject.toml` | modifies | New `research` extra (Module 1) |
| `parrot.interfaces.http.HTTPService` | **NOT used** | `requests`/`httpx` backed — would block the loop |

### Data Models

```python
# NEW — parrot_tools/research/models.py

class Citation(BaseModel):
    """Machine-readable citation. Present on every successful result."""
    source_name: str          # "World Bank Open Data", "Crossref", ...
    source_url: str           # Direct URL to the data/paper
    access_date: str          # ISO-8601 date of the API call
    formatted_citation: str   # Human-readable citation string
    data_vintage: Optional[str] = None  # Best-effort: source publish/update date
    doi: Optional[str] = None
    license: Optional[str] = None

class IndicatorValue(BaseModel):
    indicator_id: str         # e.g. "NY.GDP.MKTP.KD.ZG"
    indicator_name: str
    country: str              # ISO-3166 code
    country_name: str
    year: str
    value: Optional[float]    # None for missing observations
    unit: Optional[str] = None
    source_note: Optional[str] = None

class PaperResult(BaseModel):
    title: str
    authors: List[str] = Field(default_factory=list)
    abstract: Optional[str] = None
    published_date: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    journal: Optional[str] = None
    citation_count: Optional[int] = None
    fields_of_study: Optional[List[str]] = None
    open_access: Optional[bool] = None
    source: str               # "crossref" | "pubmed" | "semantic_scholar" | "arxiv"

class DatasetResult(BaseModel):
    title: str
    description: Optional[str] = None
    publisher: Optional[str] = None
    url: Optional[str] = None
    keywords: Optional[List[str]] = None
    format: Optional[str] = None
    last_modified: Optional[str] = None
    source: str               # "eu_open_data" | "oecd"

class ResearchResult(BaseModel):
    """Unified container returned by every research toolkit method.

    Failures are represented here as DATA — never as an exception and never
    as ToolResult(status="error"). See §2 Error Contract.
    """
    query: str
    source: str               # toolkit + method identifier
    result_type: str          # "indicators" | "papers" | "datasets"
    status: str = "success"   # "success" | "partial" | "no_data" | "error"
    error_message: Optional[str] = None
    total_results: Optional[int] = None
    indicators: Optional[List[IndicatorValue]] = None
    papers: Optional[List[PaperResult]] = None
    datasets: Optional[List[DatasetResult]] = None
    # Required in practice for status="success" (enforced by test, not by the
    # type) — Optional so that no_data/error results need not fabricate one.
    citation: Optional[Citation] = None
    raw_metadata: Optional[Dict[str, Any]] = None
```

### New Public Interfaces

```python
# parrot_tools/research/base.py
class BaseResearchToolkit:
    """Cooperative mixin. MUST be listed BEFORE AbstractToolkit in bases."""
    auto_open: bool = True

    def __init__(self, *, cache_ttl: int = 3600, **kwargs):
        # MUST forward to AbstractToolkit.__init__ or _opened/_open_lock/
        # logger/_tool_cache are never initialised.
        super().__init__(**kwargs)
        ...

    async def _open(self) -> None: ...          # creates aiohttp.ClientSession
    async def _close(self) -> None: ...         # closes session, then super()._close()
    async def _make_api_request(
        self, url: str, params: dict = None, headers: dict = None
    ) -> tuple[Optional[dict], Optional[str]]: ...   # (payload, error) — never raises
    async def _run_sync_in_executor(self, func, *args, **kwargs) -> Any: ...
    def _build_citation(
        self, source_name: str, source_url: str,
        data_vintage: str = None, doi: str = None, license: str = None
    ) -> Citation: ...
    def _failure(
        self, query: str, source: str, result_type: str,
        status: str, message: str
    ) -> ResearchResult: ...     # canonical no_data / error result factory

# parrot_tools/research/open_data.py
class OpenDataToolkit(BaseResearchToolkit, AbstractToolkit):
    async def search_world_bank(self, query: str, indicator: str = None,
        country: str = None, date_range: str = None,
        max_results: int = 10) -> ResearchResult: ...
    async def get_world_bank_indicator(self, indicator_id: str, country: str,
        year: str = None, date_range: str = None) -> ResearchResult: ...
    async def search_eu_open_data(self, query: str, dataset_type: str = None,
        publisher: str = None, max_results: int = 10) -> ResearchResult: ...
    async def search_oecd_data(self, query: str, dataset: str = None,
        country: str = None, max_results: int = 10) -> ResearchResult: ...
    async def get_oecd_indicator(self, dataset_id: str, country: str,
        frequency: str = None) -> ResearchResult: ...

# parrot_tools/research/academic.py
class AcademicResearchToolkit(BaseResearchToolkit, AbstractToolkit):
    async def search_crossref(self, query: str, author: str = None,
        year_range: str = None, journal: str = None,
        max_results: int = 10) -> ResearchResult: ...
    async def search_pubmed(self, query: str, mesh_terms: str = None,
        date_range: str = None, max_results: int = 10) -> ResearchResult: ...
    async def search_semantic_scholar(self, query: str,
        fields_of_study: str = None, year: str = None,
        open_access_only: bool = False, max_results: int = 10) -> ResearchResult: ...
    async def search_arxiv(self, query: str, max_results: int = 10,
        sort_by: str = "relevance", category: str = None) -> ResearchResult: ...
    async def get_paper_details(self, doi_or_id: str,
        source: str = None) -> ResearchResult: ...
        # Returns ResearchResult with result_type="papers" and exactly one
        # entry in .papers (or status="no_data").

# parrot_tools/research/router.py
class ResearchRouterArgs(AbstractToolArgsSchema):
    """REQUIRED — AbstractTool discards all kwargs without an explicit schema."""
    query: str = Field(description="Natural-language research question")
    categories: Optional[List[str]] = Field(
        default=None, description="Restrict to: open_data, academic")
    max_results: int = Field(default=10, ge=1, le=50)

class ResearchRouter(AbstractTool):
    name: str = "research"
    description: str = (
        "Answer a research question using authoritative sources: World Bank, "
        "EU Open Data, OECD (economic/statistical indicators) and Crossref, "
        "PubMed, Semantic Scholar, arXiv (academic literature). Returns "
        "structured results with citations."
    )
    args_schema: Type[BaseModel] = ResearchRouterArgs

    def __init__(
        self,
        open_data: Optional["OpenDataToolkit"] = None,
        academic: Optional["AcademicResearchToolkit"] = None,
        llm: Optional[Union["AbstractClient", str]] = None,
        **kwargs,
    ):
        """`llm` is the classifier client — a string spec is resolved via
        LLMFactory.create(). Tools have NO back-reference to the calling
        agent's LLM (framework invariant), so it must be injected here.
        When llm is None the router uses keyword heuristics only."""

    async def _execute(self, query: str, categories: List[str] = None,
        max_results: int = 10, **kwargs) -> ToolResult: ...
```

---

## 3. Module Breakdown

> **Each module ships its own unit tests** in `tests/research/test_<module>.py`
> plus its own fixtures under `tests/research/fixtures/<source>.*`. Only
> Module 1 creates the shared `conftest.py`; Module 5 owns every other
> shared-file edit.

### Module 1: Models, Base Toolkit & Packaging
- **Path**:
  `packages/ai-parrot-tools/src/parrot_tools/research/__init__.py` (stub),
  `.../research/models.py`, `.../research/base.py`,
  `packages/ai-parrot-tools/pyproject.toml`,
  `packages/ai-parrot-tools/tests/research/conftest.py`
- **Responsibility**: The five Pydantic models. `BaseResearchToolkit` as a
  **cooperative mixin** (`__init__` forwards via `super().__init__(**kwargs)`;
  `_close()` calls `await super()._close()`). aiohttp session lifecycle,
  `ToolCache` wiring via `.get()`/`.set()`, `_make_api_request()` returning
  `(payload, error)` and never raising, `_run_sync_in_executor()`,
  `_build_citation()`, `_failure()`. **Also adds the `research` extra to the
  satellite `pyproject.toml`** so Modules 2–4 can install and test their own
  dependencies. Shared test helpers (`mock_aiohttp_session`, fixture loader).
- **Depends on**: `parrot.tools.toolkit.AbstractToolkit`,
  `parrot_tools.cache.ToolCache`, `aiohttp`, `backoff`
- **Blocks**: Modules 2, 3, 4

### Module 2: OpenDataToolkit
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/research/open_data.py`
- **Responsibility**: `OpenDataToolkit` with 5 async methods:
  - `search_world_bank` — `wbgapi` via `run_in_executor`; no server-side
    keyword search, so indicator-metadata search / client-side filtering.
  - `get_world_bank_indicator` — direct indicator+country time series.
  - `search_eu_open_data` — aiohttp GET to
    `data.europa.eu/api/hub/search/search` with `q=`. Multilingual metadata:
    fall back to the first available language when `en` is absent.
  - `search_oecd_data` — `sdmx1` (`OECD3` source) via `run_in_executor`;
    dataflow catalog browse.
  - `get_oecd_indicator` — `sdmx1` data series fetch; fetch the DSD first
    (dimension order is positional).
- **Depends on**: Module 1, `wbgapi`, `sdmx1`, `aiohttp`

### Module 3: AcademicResearchToolkit
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/research/academic.py`
- **Responsibility**: `AcademicResearchToolkit` with 5 async methods:
  - `search_crossref` — `habanero` via `run_in_executor`; polite pool via
    `mailto`; prefer `query.bibliographic` over generic `query`.
  - `search_pubmed` — `Bio.Entrez` via `run_in_executor`; two-step
    `esearch`→`efetch`; set `Entrez.email` (required by NCBI) and optional
    `Entrez.api_key`; throttle to ≤3 req/s unkeyed, ≤10 req/s keyed.
  - `search_semantic_scholar` — aiohttp GET with explicit `fields=`;
    replace hyphens with spaces in query terms; backoff on 429.
  - `search_arxiv` — `arxiv` library via `run_in_executor`.
  - `get_paper_details` — auto-detects DOI / PMID / arXiv-ID format (or uses
    explicit `source`) and returns a single-entry `papers` list.
- **Depends on**: Module 1, `habanero`, `biopython`, `arxiv`, `aiohttp`

### Module 4: ResearchRouter
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/research/router.py`
- **Responsibility**: `ResearchRouterArgs` schema (**mandatory** — without it
  the framework discards all parameters) and `ResearchRouter(AbstractTool)`.
  Constructor-injected toolkits and classifier `llm` (string spec resolved
  via `LLMFactory.create()`). Classifies the query into `open_data` /
  `academic`, dispatches concurrently to the selected toolkit methods,
  merges results. Falls back to keyword heuristics when `llm is None` or
  classification fails. Returns a **successful** `ToolResult` whose payload
  records any per-category failures.
- **Depends on**: Modules 1–3, `parrot.clients.factory.LLMFactory`

### Module 5: Integration & Discovery (shared-file owner)
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/research/__init__.py`
  (final exports), `packages/ai-parrot-tools/src/parrot_tools/__init__.py`
  (**regenerated**)
- **Responsibility**: Export `OpenDataToolkit`, `AcademicResearchToolkit`,
  `ResearchRouter`, and the models from `research/__init__.py`. Run
  `python scripts/generate_tool_registry.py` and commit the regenerated
  `TOOL_REGISTRY` so lazy discovery works and
  `generate_tool_registry.py --check` passes in CI. Cross-toolkit
  integration tests.
- **Depends on**: Modules 2, 3, 4
- **Note**: This module exists specifically so no two parallel worktrees
  edit the same file. Do not perform these edits inside Modules 2–4.

### Module 6: Documentation
- **Path**: `docs/research_tools.md`
- **Responsibility**: Usage guide — toolkit construction, router LLM
  injection, the `research` extra, per-source rate limits and caveats,
  worked examples.
- **Depends on**: Modules 1–5

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_citation_required_fields` | 1 | Citation requires source_name, source_url, access_date, formatted_citation |
| `test_research_result_defaults` | 1 | `status` defaults to "success"; `citation` may be None |
| `test_failure_factory` | 1 | `_failure()` yields status in {no_data,error} + error_message, citation None |
| `test_base_toolkit_mro_and_init` | 1 | `OpenDataToolkit()` constructs; `_opened`, `_open_lock`, `logger`, `_tool_cache` all initialised |
| `test_base_toolkit_session_lifecycle` | 1 | `auto_open` triggers `_open()` on first execute; `_close()` resets `_opened` to False |
| `test_no_private_helpers_exposed` | 1 | `get_tools()` exposes no name starting with `_` and no base-mixin helper |
| `test_make_api_request_success` | 1 | Returns `(payload, None)` on 200 |
| `test_make_api_request_error_returns_tuple` | 1 | 500/timeout returns `(None, "…")` — does NOT raise |
| `test_make_api_request_rate_limit_retry` | 1 | 429 triggers backoff retry |
| `test_cache_hit_skips_api` / `test_cache_miss_stores_result` | 1 | ToolCache `.get()`/`.set()` round-trip |
| `test_search_world_bank_fixture` | 2 | Mocked wbgapi → IndicatorValue list |
| `test_get_world_bank_indicator_fixture` | 2 | Direct lookup → time series |
| `test_search_eu_open_data_fixture` | 2 | Mocked aiohttp → DatasetResult list |
| `test_eu_open_data_multilingual_fallback` | 2 | Missing `en` title → first available language |
| `test_search_oecd_fixture` / `test_get_oecd_indicator_fixture` | 2 | Mocked sdmx1 → datasets / indicators |
| `test_search_crossref_fixture` | 3 | Mocked habanero → PaperResult list with DOIs |
| `test_crossref_uses_mailto` | 3 | Polite-pool `mailto` present in the request |
| `test_search_pubmed_fixture` | 3 | Mocked Entrez esearch+efetch → PaperResult list |
| `test_pubmed_sets_email` | 3 | `Entrez.email` set before any call |
| `test_search_semantic_scholar_fixture` | 3 | Mocked aiohttp → PaperResult list |
| `test_semantic_scholar_requests_fields` | 3 | Explicit `fields=` present in query string |
| `test_semantic_scholar_hyphen_fix` | 3 | Hyphens replaced with spaces |
| `test_search_arxiv_fixture` | 3 | Mocked arxiv → PaperResult list |
| `test_get_paper_details_doi` / `_pmid` / `_arxiv` | 3 | ID format auto-detected → correct source |
| `test_router_args_schema_receives_params` | 4 | **Regression**: `execute(query=…, max_results=3)` reaches `_execute` with values intact |
| `test_router_dispatches_open_data` / `_academic` | 4 | Classifier result routes to the right toolkit |
| `test_router_explicit_categories` | 4 | Explicit `categories` bypasses the LLM |
| `test_router_heuristic_fallback_without_llm` | 4 | `llm=None` → keyword heuristics, no crash |
| `test_router_partial_failure_is_success` | 4 | One toolkit raising → `ToolResult.success is True`, failure in payload |

### Integration Tests

| Test | Description |
|---|---|
| `test_toolkit_tools_exposed` | Each toolkit's `get_tools()` lists exactly its 5 expected tool names |
| `test_no_tool_raises_into_agent_loop` | **Contract test**: every toolkit method, forced to fail (network mocked to error), returns a `ResearchResult` and never raises through `ToolManager.execute_tool()` |
| `test_successful_results_carry_citation` | Every `status="success"` result has a fully populated `Citation` |
| `test_tool_registry_not_stale` | `python scripts/generate_tool_registry.py --check` exits 0 |
| `test_research_exports` | `from parrot_tools.research import OpenDataToolkit, AcademicResearchToolkit, ResearchRouter` resolves |

### Test Data / Fixtures

```python
# tests/research/conftest.py  (created by Module 1)
@pytest.fixture
def load_fixture():
    """Load a recorded API response from tests/research/fixtures/."""

@pytest.fixture
def mock_aiohttp_session(monkeypatch):
    """Patch BaseResearchToolkit._session with a stub returning fixtures."""

# Per-module fixture files (no cross-module file conflicts):
#   fixtures/world_bank_indicator.json     (Module 2)
#   fixtures/eu_open_data_search.json      (Module 2)
#   fixtures/oecd_dataflows.xml            (Module 2)
#   fixtures/crossref_works.json           (Module 3)
#   fixtures/pubmed_esearch.xml            (Module 3)
#   fixtures/pubmed_efetch.xml             (Module 3)
#   fixtures/semantic_scholar_search.json  (Module 3)
#   fixtures/arxiv_feed.xml                (Module 3)
```

The `live` marker is already registered in the root `pytest.ini` — opt-in
smoke tests may use `@pytest.mark.live` without further configuration.

---

## 5. Acceptance Criteria

- [ ] `OpenDataToolkit.get_tools()` exposes exactly: `search_world_bank`,
      `get_world_bank_indicator`, `search_eu_open_data`, `search_oecd_data`,
      `get_oecd_indicator`.
- [ ] `AcademicResearchToolkit.get_tools()` exposes exactly: `search_crossref`,
      `search_pubmed`, `search_semantic_scholar`, `search_arxiv`,
      `get_paper_details`.
- [ ] Neither toolkit exposes any `BaseResearchToolkit` helper as a tool.
- [ ] `ResearchRouter` declares `name`, `description`, **and an explicit
      `args_schema`**; a call with `query`/`categories`/`max_results`
      delivers all three values into `_execute` (regression test required —
      without an explicit schema the framework silently drops them).
- [ ] `ResearchRouter` accepts an injected `llm` (client instance or string
      spec resolved via `LLMFactory.create()`) and degrades to keyword
      heuristics when it is `None`. It does **not** attempt to reach the
      calling agent's LLM.
- [ ] **No research tool raises into the agent loop.** With every network
      dependency mocked to fail, each toolkit method returns a
      `ResearchResult` with `status` in `{no_data, error}`, and
      `ToolManager.execute_tool()` completes without raising.
- [ ] Any `ToolResult` constructed with `status="error"` also passes
      `success=False` explicitly.
- [ ] Every `ResearchResult` with `status="success"` carries a `Citation`
      with non-empty `source_name`, `source_url`, `access_date`, and
      `formatted_citation`.
- [ ] Both toolkits set `auto_open=True` and manage an
      `aiohttp.ClientSession` via `_open`/`_close`; `_close()` calls
      `await super()._close()` so `_opened` resets.
- [ ] `BaseResearchToolkit.__init__` forwards through
      `super().__init__(**kwargs)` (verified by constructing each toolkit
      and asserting `_opened`, `_open_lock`, `logger`, `_tool_cache` exist).
- [ ] API responses are cached via `ToolCache.get()` / `.set()` (not
      `_build_key`) with configurable TTL — default 1 h indicators,
      24 h papers.
- [ ] Sync libraries (`wbgapi`, `sdmx1`, `habanero`, `Bio.Entrez`, `arxiv`)
      are called only through `run_in_executor`; no blocking call and no use
      of `HTTPService` in `parrot_tools/research/`.
- [ ] `packages/ai-parrot-tools/pyproject.toml` declares a `research` extra
      (added in **Module 1**, not at the end).
- [ ] **`python scripts/generate_tool_registry.py --check` exits 0** — the
      regenerated `TOOL_REGISTRY` is committed, so CI
      (`.github/workflows/ci.yml:30`) passes.
- [ ] `from parrot_tools.research import OpenDataToolkit,
      AcademicResearchToolkit, ResearchRouter` resolves.
- [ ] Missing optional libraries produce a clear actionable message naming
      the `ai-parrot-tools[research]` extra.
- [ ] `pytest packages/ai-parrot-tools/tests/research/ -v` passes offline
      (fixtures only); live tests opt-in via `-m live`.
- [ ] `docs/research_tools.md` exists and documents router LLM injection.
- [ ] No breaking change: `ArxivTool` and `FredAPITool` remain importable
      and behaviourally unchanged.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Re-verified 2026-08-17 on `dev`
> @ `1c48c4c`. Entries marked **[probe]** were confirmed by executing code in
> the project venv, not by reading alone.

### Verified Imports

```python
# Core toolkit/tool base classes
from parrot.tools.toolkit import AbstractToolkit        # [probe] instantiated OK
from parrot.tools.abstract import (
    AbstractTool, AbstractToolArgsSchema, ToolResult,
)                                                        # [probe]

# Satellite
from parrot_tools.cache import ToolCache, DEFAULT_TOOL_CACHE_TTL  # cache.py

# LLM injection for the router
from parrot.clients.base import AbstractClient           # db.py:29
from parrot.clients.factory import LLMFactory            # db.py:30 (LLMFactory.create)

# HTTP / retry / parsing
import aiohttp                                           # core dep
import backoff                                           # backoff==2.2.1

# External data libraries — ALL must be added to the `research` extra
import wbgapi                    # NOT installed — PyPI latest 1.0.14
import sdmx                      # package name is `sdmx1` — PyPI latest 2.27.0
from habanero import Crossref    # NOT installed — PyPI latest 2.9.2
from Bio import Entrez           # package `biopython` — PyPI latest 1.88
import arxiv                     # extra already exists (see below) — latest 4.0.1

# Config / logging / pydantic
from navconfig import config
from navconfig.logging import logging
from pydantic import BaseModel, Field
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/tools/abstract.py
class ToolResult(BaseModel):                     # line 199
    success: bool = True                         # line 201  ← INDEPENDENT of `status`
    status: str = "success"                      # line 202
    result: Any                                  # line 203
    error: Optional[str] = None                  # line 204
    metadata: Dict[str, Any] = {}                # line 205
    timestamp: str                               # line 206
    files / images / voice_text / display_data   # lines 209-218

class AbstractTool:
    args_schema: Type[BaseModel] = AbstractToolArgsSchema   # line ~249
    auto_open: bool = False                                  # line 274
    # line 265 (comment): "tools have no bot back-reference by design"
    async def execute(self, *args, **kwargs) -> ToolResult:  # line 778
    # line 629 — validation guard:
    #   if not self.args_schema or self.args_schema == AbstractToolArgsSchema:
    #       return AbstractToolArgsSchema()      ← ALL kwargs DISCARDED
    # line ~934 — non-ToolResult returns are wrapped: ToolResult(result=raw)

# packages/ai-parrot/src/parrot/tools/manager.py
class ToolManager:
    def register_toolkit(...)                    # line 920
    async def execute_tool(...)                  # line ~1566
        # line 1594: if result.status == "error":
        # line 1614:     raise ValueError(result.error)   ← RAISES into agent loop

# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):
    auto_open: bool = False
    exclude_tools: tuple[str, ...] = ()
    def __init__(self, **kwargs)                 # sets _opened, _open_lock,
                                                 # logger, _tool_cache, _tools_generated
    async def _open(self) / _close(self) / _ensure_open(self)
    def _generate_tools(self)                    # skips names starting with "_"
    def get_tools(...) -> List[AbstractTool]

# packages/ai-parrot-tools/src/parrot_tools/cache.py
class ToolCache:
    def __init__(self, prefix="tool_cache", ttl=300, redis_url=None)
    async def get(self, tool_name, method, **params) -> Optional[Any]
    async def set(self, tool_name, method, value, ttl=None, **params) -> None
    async def close(self) -> None
    # _build_key() is PRIVATE — call get()/set(), never _build_key() directly.

# packages/ai-parrot-tools/src/parrot_tools/db.py — LLM-injection pattern
    llm: Optional[Union[AbstractClient, str]] = None      # line 177
    self.llm = LLMFactory.create(llm) if isinstance(llm, str) else llm  # 196-199
```

### Verified Framework Behaviour **[probe]**

Executed against the real classes; these results are load-bearing for §2:

```text
MRO: OpenDataToolkit -> BaseResearchToolkit -> AbstractToolkit -> ABC -> object
  __init__ OK (mixin without its own __init__)   auto_open = True
  _opened present: True     logger present: True
  get_tools() -> ['search_world_bank']   leaked private tools: none
  execute() -> _open() fired -> ToolResult(result=<ResearchResult>)  _opened=True
  _close() -> _opened=False
A method returning ToolResult(status="error", error="boom") yields:
  outer.success = True   outer.status = "error"   (success NOT auto-derived)
```

### Packaging & Discovery Facts

| Fact | Location |
|---|---|
| `TOOL_REGISTRY` dict is **auto-generated** | `parrot_tools/__init__.py:7,34`; `__all__` at :152 |
| Generator scans `pkg_dir.rglob("*.py")`; no decorator needed | `scripts/generate_tool_registry.py:53,72` |
| CI fails when the registry is stale | `.github/workflows/ci.yml:30` → `--check` |
| An `arxiv` extra already exists: `arxiv = ["arxiv>=3.0.0"]` | `packages/ai-parrot-tools/pyproject.toml:79` |
| `beautifulsoup4>=4.12` already declared | `packages/ai-parrot-tools/pyproject.toml:48` |
| `live` pytest marker IS registered | root `pytest.ini` (`markers = … live: …`) |
| `HTTPService` is `requests`- and `httpx`-backed | `parrot/interfaces/http.py:15,31` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot_tools.research`~~ — created by this feature
- ~~`ResearchResult` / `Citation` / `BaseResearchToolkit`~~ — Module 1 creates them
- ~~`MarketResearchToolkit` / `parrot_tools/research/market.py`~~ — **dropped
  from v1** (§1 Non-Goals). Do NOT implement Statista/Gallup/Gartner.
- ~~`ResearchResult.scrape_status`~~ — no such field; use `.status`
- ~~`pymed`~~ — **ABANDONED** (last release 2019). Use `Bio.Entrez`.
- ~~Oxford Academic API~~ — no public API, no OAI-PMH. Reach OUP via Crossref.
- ~~Gallup / Gartner public APIs~~ — do not exist.
- ~~A tool's back-reference to the calling agent's LLM~~ — **does not exist by
  design** (`abstract.py:265`). Inject a client explicitly.
- ~~Automatic `args_schema` inference from `_execute`~~ — does NOT happen for
  `AbstractTool`; without an explicit schema all kwargs are dropped
  (`abstract.py:629`). (`ToolkitTool` DOES infer from method signatures —
  that is why toolkit methods need no schema.)
- ~~`ToolResult(status="error")` implying `success=False`~~ — it does not
  **[probe]**.
- ~~Returning `ToolResult(status="error")` as a "safe" error path~~ — it makes
  `ToolManager` raise (`manager.py:1614`).
- ~~`ToolCache._build_key()` as public API~~ — private; use `.get()`/`.set()`.
- ~~`wbgapi` / `sdmx1` / `habanero` / `biopython` in pyproject~~ — must be added.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Cooperative mixin (mandatory shape).** Declare
  `class X(BaseResearchToolkit, AbstractToolkit)` — mixin first.
  `BaseResearchToolkit.__init__` must call `super().__init__(**kwargs)`;
  `_close()` must `await super()._close()`. Skipping either leaves the
  toolkit half-initialised or permanently "open". **[probe]**-verified working.
- **Keep every helper underscore-prefixed.** `_generate_tools()` turns *any*
  public async method into an LLM-callable tool. A future public async helper
  on the mixin would silently become a tool on both toolkits; add it to
  `exclude_tools` if one is ever needed.
- **Sync library wrapping** (from `ddgo.py`):
  ```python
  loop = asyncio.get_running_loop()
  result = await loop.run_in_executor(None, _sync_call)
  ```
  with `backoff.on_exception(backoff.expo, …)` on the inner sync function.
- **Error handling** — see §2 Error Contract. Return `self._failure(...)`;
  do **not** return `ToolResult(status="error")` and do **not** let
  exceptions escape. If an error `ToolResult` is ever genuinely wanted,
  write `ToolResult(success=False, status="error", result=None, error=…)`
  with `success=False` explicit (`FredAPITool` does this correctly; the
  bare `status="error"` form does not).
- **Caching**: `await self._cache.get(tool_name, method, **params)` /
  `.set(...)`. Never call `_build_key()`. Exclude API keys from params.
- **Optional dependency imports** (ArxivTool pattern):
  ```python
  try:
      import wbgapi
  except ImportError:
      wbgapi = None
  # in the method:
  if wbgapi is None:
      return self._failure(..., status="error",
          message="World Bank support requires: pip install 'ai-parrot-tools[research]'")
  ```
  Note this returns a failure result rather than raising, per G7.
- **Do NOT use `parrot.interfaces.HTTPService`.** `.request()` is
  `requests`-backed and `.session()` is `httpx`-backed — both block the
  event loop and violate the repo's aiohttp-only rule. `FredAPITool` uses
  it; follow that file for *cache/result shape* only, never for transport.
- **Docstrings are the LLM's tool descriptions.** Write them for the model:
  state what the source is authoritative for, and give parameter guidance
  (e.g. for World Bank, that indicator codes beat free text).
- Async-first, Google-style docstrings, type hints, `self.logger`.

### Known Risks / Gotchas

- **World Bank**: default response format is XML — `format=json` required on
  raw calls (`wbgapi` handles it). No server-side keyword search; discovery
  is by indicator/topic code, so `search_world_bank` must filter
  client-side and say so in its docstring.
- **OECD**: two incompatible API versions live side by side; target SDMX 3.0
  (`/public/rest/v2/`). Dimension order is positional and dataflow-specific —
  fetch the DSD first. Data responses are unpaginated and can reach tens of
  MB; always bound with time/dimension filters.
- **PubMed**: two calls required (`esearch`→`efetch`); `efetch` returns XML
  only for full records. NCBI requires an identifying email and limits to
  3 req/s unkeyed, 10 req/s keyed.
- **Semantic Scholar**: `fields=` is mandatory (default returns only
  `paperId`+`title`); hyphenated terms return zero results; the
  unauthenticated pool is shared globally, so 429s are common — backoff is
  essential.
- **Crossref**: `offset` capped at 10 000 (use cursor pagination beyond
  that); send `mailto` for the polite pool.
- **EU Open Data**: multilingual metadata — `title["en"]` may be absent;
  `limit` caps at 1000 and returns plain-text HTTP 400 above it.
- **ArXiv duplication**: `search_arxiv` re-implements `ArxivTool` logic
  because the original returns a plain dict and must stay untouched for
  backward compatibility. Accepted debt — a future task may collapse
  `ArxivTool` into a thin wrapper over the toolkit method.
- **Registry staleness**: forgetting Module 5's regeneration step turns into
  a red CI run, not a local failure — run the generator before pushing.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `wbgapi` | `>=1.0` | World Bank indicators, country data, time series |
| `sdmx1` | `>=2.27` | OECD SDMX 3.0 dataflow catalog + data series |
| `habanero` | `>=2.9` | Crossref search / DOI resolution |
| `biopython` | `>=1.80` | PubMed E-utilities via `Bio.Entrez` |
| `arxiv` | `>=3.0.0` | ArXiv search — **matches the existing `arxiv` extra** (`pyproject.toml:79`); do not lower the bound |
| `aiohttp`, `backoff` | (existing) | Async transport, rate-limit retry |

Added in **Module 1** to `packages/ai-parrot-tools/pyproject.toml`:
```toml
research = [
    "wbgapi>=1.0", "sdmx1>=2.27", "habanero>=2.9",
    "biopython>=1.80", "arxiv>=3.0.0",
]
```
Also append `research` to the aggregate `all` extra (line ~88).

---

## 8. Open Questions

> **Resolved in brainstorm — carried forward, do NOT re-ask:**

- [x] **World Bank SDK?** — `wbgapi`, run via `run_in_executor`.
- [x] **OECD API version?** — SDMX 3.0 (`sdmx.oecd.org/public/rest/v2/`),
      `sdmx1` `OECD3` source.
- [x] **Semantic Scholar API key?** — free tier + backoff; optional
      `SEMANTIC_SCHOLAR_API_KEY` raises limits but is never required.
- [x] **ArxivTool integration?** — logic migrated into
      `AcademicResearchToolkit.search_arxiv()`; original class preserved.
- [x] **Router query classification?** — LLM-based, with keyword heuristic
      fallback.

> **Resolved during spec research:**

- [x] **PubMed library?** — `pymed` abandoned (2019); use `Bio.Entrez`.
- [x] **Oxford Academic?** — no public API; reached via Crossref (`10.1093`).

> **Resolved during review (rev 0.2):**

- [x] **Gallup / Gartner / Statista feasibility?** — none viable for v1.
      Gallup and Gartner have no public API; Statista's legal notice bars
      crawler access and its sanctioned API is contract-gated.
      `MarketResearchToolkit` is **dropped from v1** (§1 Non-Goals) rather
      than shipped as one fragile scraper plus two stubs.
- [x] **How does the router reach an LLM?** — constructor injection
      (`llm=` client or string spec via `LLMFactory.create()`). Tools have
      no bot back-reference by design.
- [x] **How do tools avoid raising into the agent loop?** — §2 Error
      Contract: return `ResearchResult` with a failure `status`; never an
      error `ToolResult`.

> **Unresolved — defer to implementation:**

- [ ] **Router classification prompt** — exact template and whether a single
      call can return both category selection and per-category sub-queries.
      Must stay small and provider-neutral. — *Owner: implementer (Module 4)*
- [ ] **Router classifier default** — whether `ResearchRouter` should default
      to a cheap model when `llm` is omitted, or stay heuristic-only. Current
      spec: heuristic-only. — *Owner: Jesus*
- [ ] **ToolCache TTL tuning** — starting values 1 h indicators / 24 h
      papers; revisit after real usage. — *Owner: implementer*

---

## 9. Review Log (rev 0.2)

Independent verification against the live codebase plus a `codex exec`
adversarial pass. Disposition of every finding:

| # | Finding | Disposition |
|---|---|---|
| B1 | `ResearchRouter` had no `args_schema` → framework drops all params (`abstract.py:629`) | **CONFIRM** — explicit `ResearchRouterArgs` added; regression test required |
| B2 | AC promised "never raises" while prescribing `ToolResult(status="error")`, which makes `ToolManager` raise (`manager.py:1594` → `:1614`) | **CONFIRM** — §2 Error Contract added; ACs rewritten |
| B3 | `ToolResult(status="error")` leaves `success=True` **[probe]** | **CONFIRM** — §7 corrected to require explicit `success=False` |
| B4 | Router specified to use "the agent's own LLM"; tools have no bot back-reference (`abstract.py:265`) | **CONFIRM** — constructor injection via `LLMFactory`, per `db.py:177` |
| B5 | `TOOL_REGISTRY` regeneration never mentioned; CI runs `--check` and fails when stale (`ci.yml:30`) | **CONFIRM** — Module 5 owns it; AC added |
| S1 | Parallelism claim ignored 3 shared files | **CONFIRM** — Module 5 owns all shared-file edits |
| S2 | Deps landed in the last module but were needed by earlier ones | **CONFIRM** — moved to Module 1 |
| S3 | Statista ToS bars crawlers | **CONFIRM** — module dropped from v1 |
| S4 | `arxiv>=2.0` regressed the existing `arxiv>=3.0.0` extra | **CONFIRM** — aligned to `>=3.0.0` |
| S5 | `scrape_status` field did not exist on the model | **CONFIRM** — moot (module dropped); `status` field added regardless |
| S6 | Required `citation` forced fabrication on error paths | **CONFIRM** — now `Optional`, enforced by test for `status="success"` |
| S7 | `data_vintage` required in G2 but Optional in the model | **CONFIRM** — G2 reworded to best-effort |
| S8 | Non-goals barred "authenticated" APIs while specifying optional keys | **CONFIRM** — reworded to "no paid or contract-gated" |
| S9 | `HTTPService` is `requests`/`httpx`-backed (blocking) | **CONFIRM** — explicitly forbidden in §1/§7 |
| S10 | `get_paper_details` return type inconsistent | **CONFIRM** — returns `ResearchResult` with one entry in `.papers` |
| S11 | §7 told implementers to call private `ToolCache._build_key` | **CONFIRM** — corrected to `.get()`/`.set()` |
| — | Codex: auto-generation may expose public async helpers as tools | **REJECT as defect** — **[probe]** shows no leakage with this design; retained as a forward-looking caution in §7 |
| — | Reviewer's own concern that the `live` marker was unregistered | **REJECT** — root `pytest.ini` registers it |
| — | Dependency versions (`wbgapi` 1.0.14, `sdmx1` 2.27.0, `habanero` 2.9.2, `biopython` 1.88, `arxiv` 4.0.1) | **VERIFIED** against PyPI — original research accurate |

---

## Worktree Strategy

- **Isolation unit**: `mixed`.
- **Task ordering**:
  1. **Module 1** (models, base mixin, `pyproject` extra, `conftest`) —
     sequential; blocks everything.
  2. **Modules 2 + 3** — **parallel** worktrees (disjoint files:
     `open_data.py` / `academic.py`, own test files, own fixtures).
  3. **Module 4** (router) — after 2 + 3.
  4. **Module 5** (exports + `TOOL_REGISTRY` regeneration + integration
     tests) — sequential, sole owner of shared files.
  5. **Module 6** (docs) — last, or parallel with 5.
- **Shared files** (never edited in a parallel worktree):
  `parrot_tools/research/__init__.py`, `parrot_tools/__init__.py`,
  `packages/ai-parrot-tools/pyproject.toml`.
- **Cross-feature dependencies**: none.
- Worktree base:
  ```bash
  git worktree add -b feat-426-research-tools-for-agents \
    .claude/worktrees/feat-426-research-tools-for-agents HEAD
  ```

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-17 | Jesus Lara + Claude (Opus 4.6) | Initial draft from FEAT-426 brainstorm; scope adjusted from API research (pymed→Biopython, Oxford Academic→Crossref) |
| 0.2 | 2026-08-17 | Claude (Opus 5) + codex adversarial pass | Fixed 5 blocking defects (router args_schema, error contract, `success=False`, router LLM injection, TOOL_REGISTRY/CI); dropped `MarketResearchToolkit` from v1; reworked module ordering so shared files have a single owner; added §9 Review Log and probe-verified framework behaviour |
