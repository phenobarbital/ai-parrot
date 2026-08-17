# Research Tools for Agents

Direct, structured access to authoritative data sources — economic and
statistical indicators (World Bank, EU Open Data, OECD) and academic
literature (Crossref, PubMed, Semantic Scholar, arXiv) — without a
web-search intermediary. Every result carries a machine-readable
`Citation`, and no research tool ever raises into the agent loop:
failures are returned as data.

## 1. Overview

AI-Parrot agents that need factual, citable data previously had two
options: web search (noisy, second-hand, costs per query) or a handful
of standalone single-source tools (`FredAPITool`, `ArxivTool`) with no
shared citation model or cross-source query capability.

`parrot_tools.research` adds two category-based toolkits —
`OpenDataToolkit` and `AcademicResearchToolkit` — plus a `ResearchRouter`
dispatch tool that classifies a natural-language question and queries the
right source(s) directly. Ten tools in total, sharing one result model
(`ResearchResult`) and one citation model (`Citation`).

```
Agent
  ├──→ ResearchRouter.research(query, categories?, max_results?)
  │        ├──→ OpenDataToolkit
  │        └──→ AcademicResearchToolkit
  ├──→ OpenDataToolkit (direct)         — 5 tools
  └──→ AcademicResearchToolkit (direct) — 5 tools
```

## 2. Installation

The concrete data-source libraries (`wbgapi`, `sdmx1`, `habanero`,
`biopython`, `arxiv`) ship in the `research` extra of `ai-parrot-tools`:

```bash
pip install 'ai-parrot-tools[research]'
```

**If the extra is not installed**, every affected toolkit method still
works — it does not crash. Instead it returns a `ResearchResult` with
`status="error"` and an `error_message` naming the missing extra, e.g.:

```
"World Bank support requires: pip install 'ai-parrot-tools[research]'"
```

This is easy to misread as "the API is down" — check `error_message`
before assuming a transport failure. `search_eu_open_data` and
`search_semantic_scholar` need no extra library (plain `aiohttp`), so
they work with just the base `ai-parrot-tools` install.

## 3. Quick Start

**Open data** — a World Bank indicator lookup:

```python
import asyncio
from parrot_tools.research import OpenDataToolkit

async def main():
    toolkit = OpenDataToolkit()
    result = await toolkit.get_world_bank_indicator("NY.GDP.MKTP.KD.ZG", "BRA")
    print(result.status)                    # "success" | "no_data" | "error"
    if result.status == "success":
        for indicator in result.indicators:
            print(indicator.year, indicator.value)
        print(result.citation.formatted_citation)

asyncio.run(main())
```

**Academic literature** — a Crossref search:

```python
import asyncio
from parrot_tools.research import AcademicResearchToolkit

async def main():
    toolkit = AcademicResearchToolkit()
    result = await toolkit.search_crossref("transformer time series forecasting")
    if result.status == "success":
        for paper in result.papers:
            print(paper.title, paper.doi)

asyncio.run(main())
```

## 4. The Result Model

Every toolkit method returns a single `ResearchResult` — never an
exception, never a raw error `ToolResult`:

```python
from parrot_tools.research import ResearchResult, Citation
```

```python
class ResearchResult:
    query: str
    source: str                 # e.g. "open_data.search_world_bank"
    result_type: str             # "indicators" | "papers" | "datasets"
    status: str = "success"      # "success" | "partial" | "no_data" | "error"
    error_message: str | None = None
    total_results: int | None = None
    indicators: list[IndicatorValue] | None = None
    papers: list[PaperResult] | None = None
    datasets: list[DatasetResult] | None = None
    citation: Citation | None = None
    raw_metadata: dict | None = None
```

`Citation` is populated on **every** `status="success"` result:

```python
class Citation:
    source_name: str            # "World Bank Open Data", "Crossref", ...
    source_url: str
    access_date: str            # ISO-8601, the date the call was made
    formatted_citation: str
    data_vintage: str | None    # best-effort — populated when the source exposes it
    doi: str | None
    license: str | None
```

## 5. Error Contract

**No research tool ever raises into the agent loop.** Failures are
returned as data, in `ResearchResult.status`:

| `status` | Meaning |
|---|---|
| `success` | Results found; `citation` fully populated |
| `partial` | Some data found, but incomplete (router-level; individual toolkit methods use `success`/`no_data`/`error`) |
| `no_data` | The query legitimately returned nothing (`citation` is `None`) |
| `error` | The request could not be completed — check `error_message` (`citation` is `None`) |

Always check `.status` before reading `.indicators`/`.papers`/`.datasets`:

```python
result = await toolkit.search_arxiv("nonexistent topic xyz123")
if result.status == "no_data":
    print("No papers found.")
elif result.status == "error":
    print(f"Request failed: {result.error_message}")
else:
    ...  # result.papers is populated
```

## 6. `OpenDataToolkit` — 5 Tools

```python
from parrot_tools.research import OpenDataToolkit

toolkit = OpenDataToolkit()
```

| Tool | Signature | Notes |
|---|---|---|
| `search_world_bank` | `(query, indicator=None, country=None, date_range=None, max_results=10)` | **No server-side keyword search** — the World Bank v2 API has none. Prefer an indicator code (e.g. `"NY.GDP.MKTP.KD.ZG"`) or `indicator=` over free text. |
| `get_world_bank_indicator` | `(indicator_id, country, year=None, date_range=None)` | Direct indicator + country time series. |
| `search_eu_open_data` | `(query, dataset_type=None, publisher=None, max_results=10)` | The only Open Data source with genuine full-text search (piveau/DCAT-AP). |
| `search_oecd_data` | `(query, dataset=None, country=None, max_results=10)` | Browses the ~1,500-dataflow OECD catalog and filters client-side — also no server-side keyword search. Use this to find a `dataset_id`. |
| `get_oecd_indicator` | `(dataset_id, country, frequency=None)` | Needs a dataflow id from `search_oecd_data` (e.g. `"DSD_FUA_CLIM@DF_TEMPERATURES"`). Fetches the Data Structure Definition before the data query — data responses are unpaginated and can reach tens of MB, so always pass `country`. |

## 7. `AcademicResearchToolkit` — 5 Tools

```python
from parrot_tools.research import AcademicResearchToolkit

toolkit = AcademicResearchToolkit()
```

| Tool | Signature | Notes |
|---|---|---|
| `search_crossref` | `(query, author=None, year_range=None, journal=None, max_results=10)` | Also reaches **Oxford Academic (OUP)** content — OUP has no API of its own; its works are indexed in Crossref under DOI prefix `10.1093`. Set `CROSSREF_MAILTO` for the polite pool. |
| `search_pubmed` | `(query, mesh_terms=None, date_range=None, max_results=10)` | Mandatory two-step `esearch` → `efetch` workflow. Set `NCBI_EMAIL` (required by NCBI); `NCBI_API_KEY` is optional and raises the rate limit from 3 to 10 req/s. |
| `search_semantic_scholar` | `(query, fields_of_study=None, year=None, open_access_only=False, max_results=10)` | Hyphenated query terms are rewritten to spaces internally (they otherwise return zero matches). `SEMANTIC_SCHOLAR_API_KEY` is optional — the free pool is shared globally, so 429s happen; requests are retried automatically. |
| `search_arxiv` | `(query, max_results=10, sort_by="relevance", category=None)` | `sort_by` accepts `"relevance"`, `"lastUpdatedDate"`, `"submittedDate"`. Pass `category="cs.AI"` to prefix the query with `cat:cs.AI AND ...`. |
| `get_paper_details` | `(doi_or_id, source=None)` | Resolves a single paper by DOI, PubMed PMID, arXiv id, or Semantic Scholar paperId — auto-detected from the identifier's shape, or forced via `source=`. Returns a `ResearchResult` with **exactly one** entry in `.papers`. |

`get_paper_details` accepts prefixed identifiers too (`"DOI:10.1093/..."`,
`"PMID:33095870"`, `"ARXIV:2103.14030"`, `"CorpusID:..."`).

## 8. `ResearchRouter`

```python
from parrot_tools.research import ResearchRouter

router = ResearchRouter(
    open_data=None,       # constructs an OpenDataToolkit() if omitted
    academic=None,        # constructs an AcademicResearchToolkit() if omitted
    llm=None,             # see "LLM injection" below
)
```

`ResearchRouter` is a standalone `AbstractTool` (`name="research"`), not
a toolkit method — it is meant to be handed to an agent alongside, or
instead of, the two toolkits directly:

```python
from parrot.bots import Agent
from parrot_tools.research import OpenDataToolkit, AcademicResearchToolkit, ResearchRouter

router = ResearchRouter(
    open_data=OpenDataToolkit(),
    academic=AcademicResearchToolkit(),
    llm="openai:gpt-4o-mini",   # injected classifier client
)
agent = Agent(name="analyst", tools=[router])
```

### LLM injection — read this before using the router

**Tools cannot reach the calling agent's own LLM.** This is a documented
framework invariant, not an oversight — `ResearchRouter` classifies a
query by calling an LLM client that is **explicitly injected** through
the constructor. If you construct `ResearchRouter()` bare and expect it
to "just use the agent's model", it will not — it silently falls back to
keyword heuristics instead.

`llm=` accepts:

- An `AbstractClient` instance.
- A string model spec (e.g. `"openai:gpt-4o-mini"`), resolved via
  `LLMFactory.create()`.
- `None` (the default) — the router classifies using keyword heuristics
  only (no LLM call is made). This is a fully supported mode, not a
  degraded fallback path you need to avoid; it just means classification
  is less nuanced for ambiguous queries.

Explicit `categories=` on a call bypasses classification entirely — no
LLM call is made, regardless of what `llm=` is set to.

### Categories

Exactly two: `"open_data"` and `"academic"`. There is no `"market"`
category — see [§11](#11-not-covered-in-v1).

### Dispatch and result shape

The router dispatches to the selected categories **concurrently** and
always returns a **successful** `ToolResult` — per-category failures are
recorded in the payload, never raised:

```python
result = await router.execute(query="recent papers on CRISPR gene editing")
print(result.success)                      # always True
print(result.result["classification"])     # "llm" | "heuristic" | "explicit"
print(result.result["categories"])          # e.g. ["academic"]
print(result.result["results"])             # per-category ResearchResult payloads
print(result.result["failures"])            # per-category failure messages, if any
```

## 9. Configuration (Environment Variables)

All of the following are **optional** except the NCBI email, which NCBI
requires for identification (a placeholder default is used if unset, but
setting a real address is recommended):

| Variable | Used by | Effect when unset |
|---|---|---|
| `NCBI_EMAIL` | PubMed | A placeholder default is used — set a real address per NCBI's usage policy |
| `NCBI_API_KEY` | PubMed | Rate limit stays at 3 req/s instead of 10 req/s |
| `CROSSREF_MAILTO` | Crossref | Requests are not routed to Crossref's polite pool |
| `SEMANTIC_SCHOLAR_API_KEY` | Semantic Scholar | Requests use the shared, unauthenticated pool (more frequent 429s, automatically retried) |

No key is ever required for correct operation — every source here is
free and keyless by default.

## 10. Caching

API responses are cached via a Redis-backed `ToolCache`, keyed by tool +
method + call parameters:

| Data kind | Default TTL |
|---|---|
| Indicators (World Bank, OECD data queries) | 1 hour |
| OECD dataflow catalog | 24 hours (large, slow-changing) |
| Papers/datasets (Crossref, PubMed, Semantic Scholar, arXiv, EU Open Data) | 24 hours |

## 11. Not Covered in v1

A `MarketResearchToolkit` (Gallup, Gartner, Statista) was explored and
**deferred out of v1**: Gallup and Gartner have no public API, and
Statista's legal notice prohibits crawler access — its only sanctioned
programmatic path ("Statista Connect") is contract-gated with no
self-serve signup. Shipping one ToS-questionable scraper plus two stubs
was judged not worth it. The `BaseResearchToolkit` mixin this feature
introduces makes adding a market-research toolkit additive, should a
Statista Connect contract be acquired later.
