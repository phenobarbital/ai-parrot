---
type: Wiki Overview
title: FEAT-305 — CompanyResearchToolkit (port of flowtask CompanyScraper)
id: doc:sdd-proposals-companyresearch-tool-proposal-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The original request, preserved verbatim. Full source at
relates_to:
- concept: mod:parrot.conf
  rel: mentions
---

---
id: FEAT-305
title: CompanyResearchToolkit — structured company info from LeadIQ/RocketReach/SICCode/VisualVisitor/ZoomInfo/Explorium (port of flowtask CompanyScraper)
slug: companyresearch-tool
type: feature
mode: enrichment
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-07-13
  summary_oneline: CompanyResearchTool — agent tool to extract structured company info from six public sources; port of flowtask CompanyScraper.
overall_confidence: medium
base_branch: dev
research_state: sdd/state/FEAT-305/
created: 2026-07-13
updated: 2026-07-13
---

# FEAT-305 — CompanyResearchToolkit (port of flowtask CompanyScraper)

> **Mode**: enrichment
> **Confidence**: medium
> **Source**: `inline`
> **Audit**: [`sdd/state/FEAT-305/`](../state/FEAT-305/)

---

## 0. Origin

The original request, preserved verbatim. Full source at
`sdd/state/FEAT-305/source.md`.

> Create a CompanyResearchTool allow us to extract company information from
> several sources as RocketReach or ZoomInfo, using the code from flowtask as
> base for the component:
> `/home/jesuslara/proyectos/flowtask/flowtask/components/CompanyScraper`,
> current extractors included: LeadIQ, RocketReach, SICCode, VisualVisitor,
> Zoominfo, Explorium.ai.
> LLM will be able to send a company name and retrieve structured data for
> the company.

**Initial signals** (extracted, not interpreted):
- Verbs: "Create", "extract", "using the code from flowtask as base" → feature (port/adaptation)
- Named entities: CompanyResearchTool, flowtask CompanyScraper, LeadIQ, RocketReach, SICCode, VisualVisitor, ZoomInfo, Explorium.ai
- Interface requirement: LLM sends a company name → structured data back
- Acceptance criteria provided: no

---

## 1. Synthesis Summary

Port flowtask's `CompanyScraper` component into an ai-parrot toolkit so an
agent can call one tool with a company name and receive a structured
`CompanyProfile`. The port is smaller than the 2,000-line source suggests:
parrot's existing `HTTPService` (`parrot/interfaces/http.py`) already
provides the search-and-fetch layer the scraper depends on
(`_search_duckduckgo`, `_search_google`, proxy rotation, backoff), so the
work reduces to a new `CompanyResearchToolkit(AbstractToolkit)` under
`parrot/tools/`, a Pydantic `CompanyProfile` output model, and six extractors
re-parented from flowtask's `ScrapperBase` contract — dropping all
DataFrame/tqdm batch semantics. Per the resolved Q&A: first-success
aggregation, a single `research_company` tool, and a Playwright-based fetcher
for ZoomInfo's anti-bot wall.

---

## 2. Codebase Findings

> Grounded in `sdd/state/FEAT-305/findings/`. No fabricated paths or symbols.

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `flowtask/components/CompanyScraper/scrapper.py` (flowtask repo) | `CompanyScraper` | 28-1067 | source component: search→validate→fetch→parse pipeline | F001 |
| 2 | `flowtask/components/CompanyScraper/parsers/base.py` | `ScrapperBase` | 8-102 | per-source extractor contract to re-model | F002 |
| 3 | `flowtask/components/CompanyScraper/parsers/*.py` | 6 parser classes | — | BS4 selector walkers over public profile pages | F003 |
| 4 | `packages/ai-parrot/src/parrot/interfaces/http.py` | `HTTPService` | 126-1600 | existing parrot mixin: `_get`, `_search_duckduckgo` (L1327), `_search_google` (L1412), proxylists rotation — the reuse target | F005 |
| 5 | `packages/ai-parrot/src/parrot/tools/toolkit.py` | `AbstractToolkit` | 207-296 | base class; auto tool generation from async methods | F004 |
| 6 | `packages/ai-parrot/src/parrot/tools/workiq_tool.py` | `WorkIQTool`, `_WorkIQArgs` | 44-110 | house-style exemplar for args schema + docs | F008 |

### 2.2 Constraints Discovered

- **Reuse parrot's HTTPService, don't copy flowtask interfaces.** parrot
  already ships DuckDuckGo search, Google CSE (keys via
  `GOOGLE_SEARCH_API_KEY`/`GOOGLE_SEARCH_ENGINE_ID` in `parrot.conf`), proxy
  rotation (Oxylabs/Decodo/Geonode/FreeProxy), backoff and BS4.
  *Implication*: extractors inherit/consume `HTTPService` instead of
  flowtask's `HTTPService`/`SeleniumService`. *Evidence*: F005
- **No SeleniumService in parrot.** ZoomInfo's `get()` force-uses
  undetected-chromedriver; the Selenium Google-CSE fallback also has no
  parrot equivalent. `selenium`, `undetected-chromedriver` and `playwright`
  all live in the `agents` extra. *Implication*: browser fetching needs a new
  (Playwright) helper — resolved by U2. *Evidence*: F005, F007
- **`fuzzywuzzy` is not a parrot dependency.** Name validation
  (`fuzz.ratio > 85`) needs `rapidfuzz` (preferred) or stdlib `difflib`.
  *Evidence*: F007
- **Batch semantics must be dropped.** DataFrame in/out, tqdm, chunked
  gather are flowtask concerns; the tool is per-company async. Structured
  output must be a Pydantic model (project rule). *Evidence*: F001
- **VisualVisitor parser is a RocketReach copy-paste** and mislabels
  `source_platform: 'rocketreach'` — fix during port. *Evidence*: F003
- **Greenfield placement.** Zero matches for "company" under
  `parrot/tools/`; recent tools/ commits (credential broker, infographic,
  Bedrock adapters) don't collide. *Evidence*: F006, F008

### 2.3 Recent History (Relevant)

| Commit | Message | Relevance |
|--------|---------|-----------|
| `452c1cefa` | Merge feat-302-bedrock-client-llm into dev | latest tools-adjacent work, no overlap |
| `c76ee58a7` | feat(infographic): render_template tool | toolkit-style precedent |
| `793b3ca21` / `9f34ec2b9` | unified-credential-broker seams | pattern available if paid APIs come later |

No commits touch company-research functionality (F008).

---

## 3. Probable Scope  *(mode = enrichment)*

### What's New

- **`parrot/tools/company_research/`** package:
  - `toolkit.py` — `CompanyResearchToolkit(AbstractToolkit)` exposing a
    single tool `research_company(company_name: str, sources: list[str] | None)`
    (U3: single tool). Tries sources in priority order and returns the first
    successful profile (U1: first-success), with `sources` overriding order.
  - `models.py` — `CompanyProfile` Pydantic model: company_name, logo_url,
    website, address/city/state/zip_code/country/metro_area/headquarters,
    phone_number, stock_symbol, naics_code, sic_code, employee_count,
    revenue_range, industry, category, company_description, founded, funding,
    similar_companies, executives, source_platform, search_url, status.
  - `extractors/base.py` — `CompanyExtractor` base (port of `ScrapperBase`):
    `domain`, `search_template`, `keywords`, `define_search_term()`,
    `async extract(soup, profile)`; address parsing helper; fuzzy name check.
  - `extractors/{leadiq,rocketreach,siccode,visualvisitor,zoominfo,explorium}.py`
    — the six parsers ported from F003 selectors (VisualVisitor mislabel fixed).
  - `browser.py` — minimal Playwright page-fetcher used by ZoomInfo (U2),
    import-guarded so the toolkit works without the `agents` extra
    (ZoomInfo then reports unavailable).
- **Tests**: `tests/tools/company_research/` with recorded HTML fixtures per
  source (no live scraping in CI); unit tests for search-term building, name
  validation, each extractor, and first-success orchestration.

### What Changes

- **`packages/ai-parrot/pyproject.toml`** — add `rapidfuzz` (or use difflib
  and add nothing). *Evidence*: F007

### What's Untouched (Non-Goals)

- No DataFrame/batch API — flowtask keeps the bulk-enrichment role.
- No paid/official API integrations (RocketReach API, ZoomInfo API) — this
  ports the public-page scraping approach; credential-broker wiring is a
  possible follow-up.
- No changes to `parrot/interfaces/http.py` beyond consuming it.
- No changes to flowtask.

### Patterns to Follow

- `AbstractToolkit` auto-tool generation; docstring becomes the LLM tool
  description; optional `tool_prefix`. *Evidence*: F004
- Args-schema style from `_WorkIQArgs` (Pydantic Fields with rich
  descriptions). *Evidence*: F008
- Pipeline from `CompanyScraper._search_company`: site-scoped search (DDG →
  Google CSE fallback) → title-keyword validation → fuzzy name check → fetch
  with proxy → parse. *Evidence*: F001

### Integration Risks

- **Anti-bot walls / rate limits**: ZoomInfo needs Playwright; DDG ratelimits
  must degrade to Google CSE (as in flowtask). Live behavior is inherently
  flaky — tool must return a partial/failed status cleanly, never raise into
  the agent loop. *Evidence*: F001, F003
- **Selector drift**: all six parsers are selector-coupled to current site
  markup and may already be stale (C10, low confidence). Fixture-based tests
  protect the code, not the live sites. *Evidence*: F003

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | Flowtask pipeline is search(DDG→Google CSE)→validate title→fetch→BS4 parse | F001 | high | direct read |
| C2 | Per-source contract: domain, site: template, keywords, define_search_term(), scrapping() | F002, F003 | high | direct read of base + 6 parsers |
| C3 | parrot HTTPService already provides _get/_search_duckduckgo/_search_google/proxies | F005 | high | direct read |
| C4 | AbstractToolkit auto-converts async methods to tools; conventions from 16 existing toolkits | F004, F006, F008 | high | direct read + grep |
| C5 | All deps except fuzzy matching already in pyproject | F007 | high | grep of pyproject |
| C6 | No existing company-research capability in parrot | F006 | high | absence grep |
| C7 | First-success is flowtask's behavior; chosen as tool default | F001 | medium→resolved | U1 answered: first-success |
| C8 | ZoomInfo cannot work HTTP-only (anti-bot) | F003 | medium | inferred from forced undetected-chrome get(); U2 answered: Playwright |
| C9 | Single toolkit under parrot/tools/company_research/ is right placement | F006 | medium | conventions; U3 answered: single tool |
| C10 | Ported selectors may be stale vs live markup | F003 | low | unverifiable without live requests |

Distribution: **6** high, **3** medium, **1** low.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **U1 — Aggregation strategy?** — *Resolved*: first-success in priority
  order (flowtask parity); `sources` param lets callers pick/restrict.
  *Resolves claims*: C7
- [x] **U2 — ZoomInfo without SeleniumService?** — *Resolved*: Playwright
  fetcher (playwright already in the `agents` extra); ZoomInfo stays in v1.
  *Resolves claims*: C8
- [x] **U3 — Tool surface?** — *Resolved*: single
  `research_company(company_name, sources?)` tool. *Resolves claims*: C9

### Unresolved (defer to spec / implementation)

- [ ] **Source priority order for first-success** — *Owner*: tbd.
  *Plausible answers*: a) LeadIQ→RocketReach→Explorium→SICCode→VisualVisitor→ZoomInfo
  (cheapest/richest first, browser-based last) · b) configurable ctor arg with
  that default.
- [ ] **Live-selector validation** — C10: whether the ported selectors still
  match today's site markup can only be checked with live requests during
  implementation.

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-305`** — *Rationale*: localization and constraints are
high-confidence, all product forks (U1–U3) are resolved, and the architecture
has no real alternative to explore: port + adapt onto existing
`HTTPService`/`AbstractToolkit`.

### Alternatives

- **`/sdd-brainstorm FEAT-305`** — only if you want to explore paid-API-based
  sources (official RocketReach/ZoomInfo APIs + credential broker) as an
  alternative architecture to scraping.
- **`/sdd-task FEAT-305`** — not recommended; multi-file feature (toolkit +
  model + 6 extractors + browser fetcher + fixtures) warrants a spec.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-305/state.json` |
| Source (raw) | `sdd/state/FEAT-305/source.md` |
| Research plan | `sdd/state/FEAT-305/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-305/findings/F001-*.md` … `F008-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-305/synthesis.json` |

**Budget consumed** (profile: default):
- Files read: 14 / 40
- Grep calls: 9 / 25
- Git calls: 1 / 10
- Truncated: **no** (Q012 skipped — WorkIQTool already covered the pattern)

**Mode determination**: `auto` → resolved to `enrichment` (imperative
"Create …", external code base to port, no failure being investigated).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Jesus Lara + Claude (Fable 5) |
