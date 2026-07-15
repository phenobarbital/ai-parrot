---
type: Wiki Overview
title: Crew Tools Catalog Endpoint
id: doc:docs-superpowers-specs-2026-07-14-crew-tools-catalog-endpoint-design-md
tags:
- overview
timestamp: '2026-07-14T22:20:21+00:00'
summary: The frontend crew builder hardcodes the list of tools that can be assigned
  to
relates_to:
- concept: mod:parrot_tools.google.tools
  rel: mentions
- concept: mod:parrot_tools.ibisworld.tool
  rel: mentions
---

# Crew Tools Catalog Endpoint

**Date:** 2026-07-14
**Status:** Draft
**Package:** ai-parrot-server, ai-parrot-tools

## Problem

The frontend crew builder hardcodes the list of tools that can be assigned to
agents. Adding or removing a tool requires a frontend deployment. The backend
already has `GET /api/v1/tools/catalog` (FEAT-149), but it dumps all ~141
registry entries with minimal metadata — no display names, no categories
meaningful to the UI, and no config schemas for tools that need user input
(e.g. GoogleSiteSearchTool requires a `sites` list).

## Solution

A new **crew-specific** endpoint that returns a curated, frontend-ready list of
tools with rich metadata.

### Endpoint

```
GET /api/v1/crew/tools
```

Authentication: same as existing crew endpoints (`is_authenticated` /
`user_session`).

### Response Shape

```json
[
  {
    "slug": "google_site_search",
    "name": "GoogleSiteSearchTool",
    "display_name": "Google Site Search",
    "description": "Search within specific websites using Google Custom Search API",
    "category": "research",
    "type": "tool",
    "config_schema": {
      "sites": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Domains to restrict search to (e.g. 'ibisworld.com')",
        "examples": ["ibisworld.com", "statista.com"]
      }
    }
  },
  {
    "slug": "yfinance",
    "name": "YFinanceTool",
    "display_name": "Yahoo Finance",
    "description": "Financial data, stock prices, and market information",
    "category": "finance",
    "type": "tool",
    "config_schema": null
  }
]
```

Fields:

| Field | Type | Description |
|-------|------|-------------|
| `slug` | string | Registry key — matches `TOOL_REGISTRY` slug and the string agents use in their `tools` list |
| `name` | string | Python class name |
| `display_name` | string | Human-readable label for the UI |
| `description` | string | One-line description shown in the tool picker |
| `category` | string | Grouping key for the UI (see Categories below) |
| `type` | `"tool"` or `"toolkit"` | Whether it's a single tool or a multi-tool toolkit |
| `config_schema` | object or null | JSON Schema fragment for user-configurable parameters. `null` when no config is needed. |

### Categories

| Key | Label | Purpose |
|-----|-------|---------|
| `research` | Research | Web search, site search, scraping, papers |
| `finance` | Finance | Market data, financial analysis |
| `company_intel` | Company Intel | Company information, lead generation |
| `data_analysis` | Data & Analysis | Statistical tools, forecasting, scoring |
| `geolocation` | Geolocation | Maps, routes, geocoding |

### Curated Tool List (Initial)

| Slug | Display Name | Category | Type | Config Schema |
|------|-------------|----------|------|---------------|
| `ibisworld` | IBISWorld Research | research | tool | — |
| `google_site_search` | Google Site Search | research | tool | `sites: string[]` |
| `google_search` | Google Search | research | tool | — |
| `ddg_search` | DuckDuckGo Search | research | tool | — |
| `bing_search` | Bing Search | research | tool | — |
| `serpapi` | SerpAPI Search | research | tool | — |
| `sitesearch` | Site Search | research | toolkit | `sites: string[]` |
| `web_scraping` | Web Scraping | research | toolkit | — |
| `arxiv` | ArXiv Papers | research | tool | — |
| `product_info` | Product Information | research | tool | — |
| `product_list` | Product Listing | research | tool | — |
| `google_location` | Google Location | geolocation | tool | — |
| `google_routes` | Google Routes | geolocation | tool | — |
| `yfinance` | Yahoo Finance | finance | tool | — |
| `bloomberg` | Bloomberg | finance | tool | — |
| `fred_api` | FRED Economic Data | finance | tool | — |
| `technical_analysis` | Technical Analysis | finance | tool | — |
| `company_info` | Company Research | company_intel | toolkit | — |
| `correlation_analysis` | Correlation Analysis | data_analysis | tool | — |
| `composite_score` | Composite Scoring | data_analysis | tool | — |
| `statistical_tests` | Statistical Tests | data_analysis | tool | — |

### Architecture

1. **Catalog constant** — `CREW_TOOL_CATALOG`: a Python list of dicts in a new
   module `parrot/handlers/crew/tool_catalog.py`. Each dict matches the response
   shape above. Adding a tool = appending a dict.

2. **Handler** — `CrewToolCatalogHandler(BaseView)` in the same module.
   Single `GET` method, returns `CREW_TOOL_CATALOG` as JSON. Response is static
   (no DB, no imports of tool classes), so no caching needed beyond normal HTTP.

3. **Route** — registered alongside existing crew routes in the manager:
   `GET /api/v1/crew/tools -> CrewToolCatalogHandler`.

4. **Registry fix** — add two missing entries to `TOOL_REGISTRY` in
   `parrot_tools/__init__.py`:
   - `"ibisworld": "parrot_tools.ibisworld.tool.IBISWorldTool"`
   - `"google_site_search": "parrot_tools.google.tools.GoogleSiteSearchTool"`

### Files Changed

| File | Change |
|------|--------|
| `packages/ai-parrot-server/src/parrot/handlers/crew/tool_catalog.py` | **New** — catalog constant + handler |
| `packages/ai-parrot-server/src/parrot/handlers/crew/__init__.py` | Export `CrewToolCatalogHandler` |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | Register route |
| `packages/ai-parrot-tools/src/parrot_tools/__init__.py` | Add 2 missing registry entries |

### Non-Goals

- Replacing `GET /api/v1/tools/catalog` — it stays for general tool discovery.
- Dynamic tool registration via this endpoint — it's read-only.
- Frontend changes — out of scope for this spec.
