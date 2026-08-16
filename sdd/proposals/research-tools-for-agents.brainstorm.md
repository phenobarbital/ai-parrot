---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: Research Tools for Agents — Direct Access to Authoritative Data Sources

**Date**: 2026-08-17
**Author**: Jesus Lara + Claude (Opus 4.6)
**Status**: exploration
**Recommended Option**: Option A

---

## Problem Statement

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

**Who is affected**: Any agent performing research, analysis, report
generation, or decision support where data provenance and citation matter —
finance agents, policy analysts, due-diligence bots, academic assistants.

**Why now**: The framework already has the toolkit/tool infrastructure, HTTP
clients, caching, and prior art (FredAPITool, ArxivTool, CompanyInfoToolkit).
Many target APIs are free and well-documented REST services that return
structured JSON — the integration cost is low relative to the value.

## Constraints & Requirements

- **Async-first**: All network I/O must be async (aiohttp / `HTTPService`);
  no blocking calls in async methods.
- **Mandatory citations**: Every result must include `source_url`,
  `access_date`, `data_vintage`, and a formatted citation string.
- **No paid API keys required for core functionality**: Free-tier APIs for
  Open Data and academic sources. Proprietary sources (Gallup, Gartner,
  Statista) scrape publicly available content only.
- **Category-based toolkits**: Three toolkit classes, independently usable,
  plus an optional cross-category router.
- **Structured Pydantic output**: All tools return Pydantic models with
  typed fields (not raw dicts), wrapped in `ToolResult`.
- **ToolCache integration**: Expensive API calls cached via the existing
  `ToolCache` (Redis-backed, configurable TTL).
- **No breaking changes**: Existing `FredAPITool` and `ArxivTool` are
  unmodified; new toolkits complement them.
- **Fixture-based tests**: No live API calls in CI; recorded responses
  for unit tests.

---

## Options Explored

### Option A: Category-Based AbstractToolkit Subclasses with Shared Base

Three `AbstractToolkit` subclasses — `OpenDataToolkit`, `AcademicResearchToolkit`,
`MarketResearchToolkit` — each exposing domain-specific async methods that
automatically become agent tools. A thin `BaseResearchToolkit` mixin provides
shared infrastructure: the `ResearchResult` / `Citation` Pydantic models,
aiohttp session management (via `auto_open` / `_open` / `_close` lifecycle),
and `ToolCache` integration. A lightweight `ResearchRouter` standalone tool
dispatches cross-category queries.

**Architecture:**
```
BaseResearchToolkit (mixin)
├── ResearchResult / Citation models
├── aiohttp.ClientSession lifecycle (_open/_close, auto_open=True)
├── ToolCache integration
└── _make_api_request() helper

OpenDataToolkit(BaseResearchToolkit, AbstractToolkit)
├── search_world_bank(query, indicator?, country?, date_range?)
├── get_world_bank_indicator(indicator_id, country, year?)
├── search_eu_open_data(query, dataset_type?, publisher?)
├── search_oecd_data(query, dataset?, country?)
└── get_oecd_indicator(dataset_id, country, frequency?)

AcademicResearchToolkit(BaseResearchToolkit, AbstractToolkit)
├── search_crossref(query, author?, year_range?, journal?)
├── search_pubmed(query, mesh_terms?, date_range?, max_results?)
├── search_semantic_scholar(query, fields_of_study?, year?, open_access?)
└── get_paper_details(doi_or_id, source?)

MarketResearchToolkit(BaseResearchToolkit, AbstractToolkit)
├── search_gallup(query, topic?, region?)
├── search_gartner(query, research_type?)
└── search_statista(query, industry?, region?)

ResearchRouter(AbstractTool)
└── research(query, categories?, max_results?)  → dispatches to toolkits
```

✅ **Pros:**
- Matches user's requested architecture (category-based)
- Each toolkit is independently registrable with `ToolManager`
- Follows proven `AbstractToolkit` pattern (auto tool generation from methods)
- `auto_open=True` lifecycle cleanly manages aiohttp sessions (FEAT-391)
- Agent can use specific toolkits OR the router — maximum flexibility
- Clear separation of concerns: Open Data (REST APIs) vs Academic (search APIs)
  vs Market Research (scraping) have very different access patterns
- Easy to extend: adding a new source = adding one async method to the
  right toolkit

❌ **Cons:**
- Three toolkit classes + one router = moderate amount of new code
- Shared base mixin adds a layer of abstraction
- Agent must know which toolkit to use (mitigated by the router tool)

📊 **Effort:** Medium-High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `wbgapi` | World Bank Indicators API Python client | MIT, well-maintained, sync (needs `run_in_executor`) |
| `sdmx1` | OECD/Eurostat SDMX data access | BSD, replaces `pandasdmx`, sync API |
| `habanero` | Crossref API Python client | MIT, async not native (use `run_in_executor`) |
| `pymed` | PubMed E-utilities wrapper | MIT, lightweight, sync |
| `semanticscholar` | Semantic Scholar API client | MIT, has async support via httpx |
| `beautifulsoup4` | HTML parsing for scraping market research | Already a dependency |
| `aiohttp` | Direct REST API calls (World Bank, EU Open Data) | Already a core dependency |
| `backoff` | Retry with exponential backoff for rate limits | Already a dependency (`backoff==2.2.1`) |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-tools/src/parrot_tools/fred_api.py` — HTTPService + ToolCache pattern for data APIs
- `packages/ai-parrot-tools/src/parrot_tools/arxiv_tool.py` — Academic search tool pattern
- `packages/ai-parrot-tools/src/parrot_tools/ddgo.py` — backoff + `run_in_executor` for sync libs
- `packages/ai-parrot-tools/src/parrot_tools/cache.py` — ToolCache (Redis-backed)
- `packages/ai-parrot-tools/src/parrot_tools/rss/fetcher.py` — aiohttp session + scraping fallback pattern
- `packages/ai-parrot/src/parrot/tools/toolkit.py` — AbstractToolkit base with auto_open lifecycle
- `packages/ai-parrot/src/parrot/tools/abstract.py` — AbstractTool, ToolResult

---

### Option B: OpenAPIToolkit Dynamic Generation + Custom Scrapers

Use `OpenAPIToolkit` to dynamically generate tools from the OpenAPI/Swagger
specs of sources that have them (World Bank v2 API has an informal spec,
OECD has SDMX, Crossref has a well-documented REST API). For sources
without OpenAPI specs (Gallup, Gartner, Statista), fall back to a custom
`MarketResearchToolkit`.

✅ **Pros:**
- Minimal custom code for API-based sources — schema drives everything
- Automatically adapts if the API adds new endpoints
- Demonstrates powerful OpenAPIToolkit reuse

❌ **Cons:**
- Most target APIs do NOT have official OpenAPI specs (World Bank's docs
  are informal; OECD uses SDMX, not OpenAPI; PubMed uses custom XML)
- OpenAPIToolkit generates generic tool names (`worldbank_get_v2_country`)
  that are opaque to the LLM vs. descriptive names like `search_world_bank`
- No control over response formatting — raw API responses go to the agent
  without structured summaries or citation enrichment
- Citation model would need a post-processing wrapper, defeating the
  automation benefit
- Harder to add caching (OpenAPIToolkit doesn't integrate with ToolCache)

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `prance` | OpenAPI spec resolution | Already used by OpenAPIToolkit |
| `aiohttp` | HTTP requests | Already a dependency |
| `beautifulsoup4` | Scraping fallback | Already a dependency |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/tools/openapitoolkit.py` — Dynamic tool generation from OpenAPI specs
- `packages/ai-parrot-tools/src/parrot_tools/company_info/tool.py` — Scraping pattern for market research

---

### Option C: Individual AbstractTool per Source (Plugin Architecture)

Each data source gets its own `AbstractTool` subclass (mirroring the existing
`FredAPITool` and `ArxivTool` pattern): `WorldBankTool`, `EUOpenDataTool`,
`OECDTool`, `CrossrefTool`, `PubMedTool`, `SemanticScholarTool`,
`GallupTool`, `GartnerTool`, `StatistaTool`. A `ResearchRegistry` class
collects tools and provides cross-source dispatch.

✅ **Pros:**
- Maximum isolation — each tool is fully self-contained
- Matches the existing `FredAPITool` / `ArxivTool` precedent exactly
- Easy to add/remove individual sources without touching others
- Each tool can have its own `args_schema` optimized for that API

❌ **Cons:**
- **9 separate tool classes** (+ registry) — significant code duplication
  for shared concerns (citation, caching, HTTP session, error handling)
- Each tool is independently registered — agent sees 9+ tools for research
  alone, cognitive load for the LLM is high
- No natural grouping: agent can't say "search all academic sources" without
  calling each individually
- The registry adds a coordination layer that essentially recreates toolkit
  functionality but without the built-in `get_tools()` / lifecycle hooks

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| Same as Option A | Same libraries needed | No reduction in dependencies |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-tools/src/parrot_tools/fred_api.py` — Direct model to copy
- `packages/ai-parrot-tools/src/parrot_tools/arxiv_tool.py` — Direct model to copy

---

### Option D: RESTTool/DynamicRESTTool Configuration-Driven Approach

Use the existing `DynamicRESTTool` to configure endpoints for each API source
declaratively. Each source becomes a `DynamicRESTTool` instance with endpoint
definitions, API key mapping, and response formatting hooks.

✅ **Pros:**
- Minimal new code — configuration over implementation
- `RESTTool` already handles URL building, HTTP methods, error handling
- HTTPService integration comes for free

❌ **Cons:**
- `DynamicRESTTool` returns raw `ToolResult` — no structured Pydantic models
  per source, no citation enrichment
- Each source would be a separate tool instance (same LLM cognitive load as
  Option C)
- No support for non-REST protocols (SDMX for OECD, XML for PubMed E-utils)
- Cannot handle sync client libraries (wbgapi, pymed) that need `run_in_executor`
- Scraping sources (Gallup/Gartner/Statista) don't fit the REST paradigm
- Response transformation requires post-processing that defeats the
  "configuration-driven" benefit

📊 **Effort:** Low-Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiohttp` / `HTTPService` | HTTP requests | Already available via RESTTool |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-tools/src/parrot_tools/resttool.py` — DynamicRESTTool

---

## Recommendation

**Option A** is recommended because:

1. **Matches user intent**: Category-based toolkits with a cross-category
   router is exactly what was requested.
2. **Proven pattern**: `AbstractToolkit` with auto tool generation is the
   dominant pattern in `parrot_tools/` (DuckDuckGoToolkit, CompanyInfoToolkit,
   JiraToolkit, etc.) — well-understood by the framework and by agents.
3. **Clean lifecycle**: `auto_open=True` (FEAT-391) gives each toolkit
   an aiohttp session that opens lazily on first use and closes on cleanup —
   no manual session management.
4. **Citation as a first-class model**: A shared `Citation` Pydantic model
   enforced across all toolkits means every agent answer can cite its sources
   consistently, regardless of which toolkit provided the data.
5. **Scalable**: Adding a new data source is a single async method on the
   right toolkit — the `AbstractToolkit` machinery handles tool registration,
   schema generation, and lifecycle automatically.
6. **Balanced complexity**: More structured than Option C (individual tools)
   but less magical than Option B (OpenAPI auto-generation). The tradeoff
   is intentional: we want descriptive tool names, structured output, and
   citation guarantees, which require some custom code per source.

The main cost is medium-high effort, which is justified by the breadth of
sources and the importance of getting citations right. The effort can be
parallelized across the three toolkit classes.

---

## Feature Description

### User-Facing Behavior

An agent equipped with these toolkits can directly query authoritative data
sources without going through web search intermediaries. Example interactions:

```
User: "What is Brazil's GDP growth trend over the last 5 years?"
Agent: [calls search_world_bank(query="GDP growth", country="BRA", date_range="2021:2025")]
→ Returns structured indicator data with values, units, and a citation:
  "Source: World Bank Open Data, Indicator NY.GDP.MKTP.KD.ZG,
   accessed 2026-08-17, data vintage 2025-Q4"

User: "Find recent papers on transformer architectures for time series"
Agent: [calls search_semantic_scholar(query="transformer time series forecasting",
        year="2024-2026", fields_of_study=["Computer Science"])]
→ Returns paper titles, authors, abstracts, citation counts, and DOIs

User: "What does Gartner say about the AI agent market?"
Agent: [calls search_gartner(query="AI agent market", research_type="magic-quadrant")]
→ Returns publicly available summaries with source URLs
```

The **ResearchRouter** tool lets the agent query across categories in one call:

```
Agent: [calls research(query="renewable energy investment trends",
        categories=["open_data", "academic"])]
→ Dispatches to OpenDataToolkit + AcademicResearchToolkit, returns merged results
```

### Internal Behavior

**Data flow:**

```
Agent calls toolkit method
  → Input validated by auto-generated Pydantic schema
  → ToolCache checked (Redis, keyed by tool+method+params hash)
  → If cache hit: return cached ResearchResult
  → If cache miss:
      → For REST APIs (World Bank, EU, OECD, Crossref, Semantic Scholar):
          aiohttp GET → JSON parse → field extraction → ResearchResult
      → For sync client libraries (wbgapi, pymed):
          asyncio.run_in_executor() → library call → ResearchResult
      → For scraping sources (Gallup, Gartner, Statista):
          aiohttp GET → BeautifulSoup parse → text extraction → ResearchResult
  → Citation object built (source_url, access_date, data_vintage, formatted_citation)
  → Result cached in ToolCache
  → Wrapped in ToolResult(status="success", result=ResearchResult)
```

**Toolkit lifecycle (per FEAT-391):**

```python
class OpenDataToolkit(BaseResearchToolkit, AbstractToolkit):
    auto_open = True  # lazy aiohttp session

    async def _open(self):
        self._session = aiohttp.ClientSession(headers={"User-Agent": "..."})

    async def _close(self):
        await self._session.close()
        await super()._close()
```

**ResearchRouter dispatch:**

The `ResearchRouter` is a standalone `AbstractTool` that holds references to
the three toolkit instances. When called, it identifies the most relevant
category(ies) based on the query or explicit `categories` parameter, calls
the appropriate toolkit method(s), and merges results into a ranked list.

### Edge Cases & Error Handling

- **API rate limits**: All external calls wrapped with `backoff` decorator
  (exponential backoff on 429/rate-limit exceptions). After max retries,
  return `ToolResult(status="error", error="rate_limited: ...")`.
- **API downtime**: Timeout after 30s per request. Return partial results
  if some sources succeed while others fail.
- **No results**: Return empty `ResearchResult` list with a helpful message,
  not an exception. Never raise into the agent loop.
- **Stale cache**: `ToolCache` TTL configurable per toolkit (default 5min for
  market research, 1 hour for indicators, 24 hours for academic papers).
- **Invalid indicators/queries**: Validate known indicator IDs and country
  codes before making API calls. Return clear error messages for unknown IDs.
- **Scraping failures** (market research): BeautifulSoup extraction may fail
  on site changes. Return `scrape_status="no_data"` with error details —
  never crash.
- **Missing optional dependencies**: Use try/except imports with clear error
  messages (like ArxivTool pattern). Core aiohttp-based sources work without
  optional packages.

---

## Capabilities

### New Capabilities
- `open-data-toolkit`: Query World Bank, EU Open Data, and OECD for economic
  indicators, country statistics, and public datasets.
- `academic-research-toolkit`: Search Crossref, PubMed, and Semantic Scholar
  for academic papers with structured citation data.
- `market-research-toolkit`: Extract publicly available research summaries
  from Gallup, Gartner, and Statista.
- `research-router`: Cross-category query dispatch that routes to the most
  relevant toolkit(s) and merges results.

### Modified Capabilities
- None — existing tools (FredAPITool, ArxivTool, DuckDuckGoToolkit) are
  unchanged. The new toolkits complement them.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot_tools/` (ai-parrot-tools) | extends | New toolkit modules under `parrot_tools/research/` |
| `parrot/tools/toolkit.py` | depends on | Uses AbstractToolkit base + auto_open lifecycle |
| `parrot/tools/abstract.py` | depends on | Uses AbstractTool for ResearchRouter |
| `parrot_tools/cache.py` | depends on | ToolCache for response caching |
| `parrot/interfaces/http.py` | depends on | HTTPService for REST API calls |
| Agent tool registration | extends | New toolkits registered via ToolManager |
| `pyproject.toml` (satellite) | modifies | New optional dependencies in extras |

---

## Code Context

### User-Provided Code
<!-- No code snippets provided by user during brainstorming. -->

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/tools/toolkit.py:line varies
class AbstractToolkit(ABC):
    auto_open: bool = False                          # FEAT-391
    exclude_tools: tuple[str, ...] = ()
    tool_prefix: Optional[str] = None
    credential_provider: Optional[str] = None

    async def _open(self) -> None: ...               # acquire resources
    async def _close(self) -> None: ...              # release resources
    async def _ensure_open(self) -> None: ...        # idempotent gate
    async def _pre_execute(self, tool_name, /, **kwargs) -> None: ...
    async def _post_execute(self, tool_name, result, /, **kwargs) -> Any: ...
    def get_tools(self, ...) -> List[AbstractTool]: ...

# From packages/ai-parrot/src/parrot/tools/abstract.py
class AbstractTool:
    name: str
    description: str
    args_schema: Type[BaseModel]
    async def _execute(self, **kwargs) -> Any: ...

class ToolResult:
    status: str          # "success" | "error"
    result: Any
    error: Optional[str]
    metadata: Optional[Dict[str, Any]]

# From packages/ai-parrot-tools/src/parrot_tools/cache.py
class ToolCache:
    def __init__(self, prefix="tool_cache", ttl=300, redis_url=None): ...
    async def get(self, tool_name, method, **params) -> Optional[Any]: ...
    async def set(self, tool_name, method, value, ttl=None, **params) -> None: ...

# From packages/ai-parrot-tools/src/parrot_tools/fred_api.py
class FredAPITool(AbstractTool):
    BASE_URL: str = "https://api.stlouisfed.org/fred"
    # Pattern: HTTPService + ToolCache + ToolResult

# From packages/ai-parrot-tools/src/parrot_tools/arxiv_tool.py
class ArxivTool(AbstractTool):
    name: str = "arxiv_search"
    # Pattern: sync library + structured dict return

# From packages/ai-parrot-tools/src/parrot_tools/ddgo.py
class DuckDuckGoToolkit(AbstractToolkit):
    # Pattern: sync DDGS + run_in_executor + backoff + ToolResult

# From packages/ai-parrot-tools/src/parrot_tools/rss/fetcher.py
class ArticleFetcher:
    # Pattern: aiohttp session + BeautifulSoup + fallback chain
```

#### Verified Imports
```python
# These imports have been confirmed to work:
from parrot.tools.toolkit import AbstractToolkit        # toolkit.py
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema, ToolResult
from parrot_tools.toolkit import AbstractToolkit         # re-export
from parrot_tools.cache import ToolCache, DEFAULT_TOOL_CACHE_TTL
from parrot.interfaces.http import HTTPService
from ddgs import DDGS                                    # ddgo.py:11
from ddgs.exceptions import RatelimitException           # ddgo.py:14
import backoff                                           # pyproject.toml:45
from bs4 import BeautifulSoup                            # satellite dep
import aiohttp                                           # core dep
from pydantic import BaseModel, Field
from navconfig import config                             # env var access
from navconfig.logging import logging                    # logger
```

#### Key Attributes & Constants
- `AbstractToolkit.auto_open` → `bool` (parrot/tools/toolkit.py) — enables lazy _open()
- `AbstractToolkit.exclude_tools` → `tuple[str, ...]` — hide methods from tool generation
- `AbstractToolkit.tool_prefix` → `Optional[str]` — namespace tool names
- `ToolCache.DEFAULT_TOOL_CACHE_TTL` → `300` seconds (cache.py)
- `DuckDuckGoToolkit` backoff pattern → `backoff.on_exception(backoff.expo, (RatelimitException,), ...)`

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot_tools.research`~~ — package does not exist yet (this feature creates it)
- ~~`parrot_tools.worldbank`~~ — no World Bank tool exists
- ~~`parrot_tools.crossref`~~ — no Crossref tool exists
- ~~`parrot_tools.pubmed`~~ — no PubMed tool exists
- ~~`parrot.tools.research_router`~~ — no research router exists
- ~~`ResearchResult` model~~ — does not exist; must be created
- ~~`Citation` model~~ — does not exist; must be created
- ~~`BaseResearchToolkit`~~ — does not exist; must be created
- ~~`wbgapi` in pyproject.toml~~ — not a current dependency
- ~~`sdmx1` in pyproject.toml~~ — not a current dependency
- ~~`habanero` in pyproject.toml~~ — not a current dependency
- ~~`pymed` in pyproject.toml~~ — not a current dependency
- ~~`semanticscholar` in pyproject.toml~~ — not a current dependency
- ~~`ArxivTool` in `parrot_tools.research`~~ — ArxivTool lives at
  `parrot_tools/arxiv_tool.py`, not in a research package
- ~~`HTTPService.session()` async context manager~~ — `HTTPService.session()`
  is a regular async method returning `(result, error)`, NOT a context manager

---

## Parallelism Assessment

- **Internal parallelism**: **Yes** — the three category toolkits
  (`OpenDataToolkit`, `AcademicResearchToolkit`, `MarketResearchToolkit`)
  plus the `ResearchRouter` and shared models can be developed in parallel
  once the base mixin (`BaseResearchToolkit`) and Pydantic models
  (`ResearchResult`, `Citation`) are established. The base is a dependency
  for all three.
- **Cross-feature independence**: No conflict with in-flight features.
  Files are entirely new (`parrot_tools/research/`). Existing tools
  (`fred_api.py`, `arxiv_tool.py`) are NOT modified.
- **Recommended isolation**: `mixed` — base models + one toolkit per task,
  tasks 2-4 (one per category toolkit) can run in parallel worktrees after
  task 1 (base models) completes.
- **Rationale**: Each toolkit is a self-contained module in its own file
  within `parrot_tools/research/`. The only shared dependency is the base
  mixin and Pydantic models (task 1). After that, each toolkit can be
  implemented independently without file conflicts.

---

## Open Questions

- [ ] **Which Python SDK approach for World Bank?** `wbgapi` is the most
  maintained Python client but is sync-only. Alternative: direct aiohttp
  calls to `api.worldbank.org/v2/` (JSON format, no dependency). Trade-off:
  `wbgapi` has indicator search/resolution built in; raw aiohttp needs manual
  URL construction. — *Owner: implementer*
- [ ] **OECD API version**: OECD is transitioning from `stats.oecd.org`
  (SDMX 2.0) to `data-explorer.oecd.org` (SDMX 3.0 / REST). The `sdmx1`
  library supports both. Which endpoint to target? — *Owner: implementer*
- [ ] **Semantic Scholar API key**: Free tier is 100 requests/5min. The
  `semanticscholar` Python package supports API keys for higher limits.
  Should the toolkit require a key or default to free tier with backoff? —
  *Owner: Jesus*
- [ ] **Gallup/Gartner scraping feasibility**: Both sites may have
  anti-bot protections. Should the initial implementation include these
  sources or stub them with clear interfaces for later? Need to verify
  during implementation. — *Owner: implementer*
- [ ] **ArxivTool integration**: Should `ArxivTool` be migrated into
  `AcademicResearchToolkit` (becoming a method) or left standalone and
  simply referenced by the `ResearchRouter`? — *Owner: Jesus*
- [ ] **ResearchRouter query classification**: How should the router
  determine which category to dispatch to? Options: keyword-based heuristics,
  LLM-based intent classification, or always query all categories. —
  *Owner: implementer*
