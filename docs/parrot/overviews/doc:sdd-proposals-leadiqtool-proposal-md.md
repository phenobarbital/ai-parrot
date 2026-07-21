---
type: Wiki Overview
title: FEAT-304 — LeadIQ toolkit for ai-parrot-tools
id: doc:sdd-proposals-leadiqtool-proposal-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The request is to port an existing flowtask ETL component
relates_to:
- concept: mod:parrot.interfaces.http
  rel: mentions
- concept: mod:parrot_tools.leadiq.tool
  rel: mentions
---

---
id: FEAT-304
title: Port flowtask's LeadIQ GraphQL component into ai-parrot-tools as a LeadIQ toolkit
slug: leadiqtool
type: feature
mode: enrichment
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-07-13
  summary_oneline: Create a LeadIQTool in ai-parrot-tools to extract company info via the LeadIQ GraphQL API, porting flowtask's LeadIQ component.
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-304/
created: 2026-07-13
updated: 2026-07-13
---

# FEAT-304 — LeadIQ toolkit for ai-parrot-tools

> **Mode**: enrichment
> **Confidence**: high
> **Source**: `inline`
> **Audit**: [`sdd/state/FEAT-304/`](../state/FEAT-304/)

---

## 0. Origin

> In ai-parrot-tools, create a LeadIQTool, allow us to extract company
> information using the LeadIQ API, taking code from:
> `/home/jesuslara/proyectos/flowtask/flowtask/components/LeadIQ.py`

**Initial signals** (extracted, not interpreted):
- Verbs: "create", "extract" → additive/enrichment, not a bug.
- Named entities: "LeadIQTool", "LeadIQ API", flowtask `LeadIQ.py`.
- Components / labels: `ai-parrot-tools` package.
- Acceptance criteria provided: no.

---

## 1. Synthesis Summary

The request is to port an existing flowtask ETL component
(`flowtask/components/LeadIQ.py`) into the `ai-parrot-tools` package as an
agent-usable tool that queries the **LeadIQ GraphQL API** for company and
employee data. The source is a `FlowComponent`/`HTTPService` that runs three
GraphQL query types (`company`, `employees`, `flat`) against
`https://api.leadiq.com/graphql` and flattens the JSON into a pandas
DataFrame (F001). The clean landing spot is a new `parrot_tools/leadiq/`
module exposing a `LeadIQToolkit(AbstractToolkit)` — mirroring the existing
`CompanyInfoToolkit` (F004) — that reuses the GraphQL queries and response
transforms verbatim but swaps the DataFrame/flow plumbing for structured,
LLM-consumable output over the in-repo async `HTTPService` (F005). This is a
well-bounded enrichment; the only real forks are the tool *shape* and the
*return contract* (§5).

---

## 2. Codebase Findings

> All entries below are grounded in the findings persisted at
> `sdd/state/FEAT-304/findings/`. No fabricated paths or symbols.

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `flowtask/components/LeadIQ.py` | GraphQL query consts + `_process_*_response` | 56-617 | **source to port** — queries + response flatteners | F001 |
| 2 | `packages/ai-parrot-tools/src/parrot_tools/leadiq/tool.py` | `LeadIQToolkit` *(new)* | new | **target** — new toolkit module | F002, F004 |
| 3 | `packages/ai-parrot-tools/src/parrot_tools/__init__.py` | `TOOL_REGISTRY` | 12-25 | register `"leadiq"` → dotted path | F002 |
| 4 | `packages/ai-parrot-tools/src/parrot_tools/company_info/tool.py` | `CompanyInfoToolkit`, `scrape_leadiq` | 163-693 | closest pattern analog + non-duplicate scraping variant | F004, F006 |
| 5 | `packages/ai-parrot/src/parrot/interfaces/http.py` | `HTTPService.session` | 126-258 | async GraphQL POST transport | F005 |

### 2.2 Constraints Discovered

- **Tool return contract ≠ DataFrame.** The source is DataFrame-in / DataFrame-out
  (flowtask pipeline semantics). Tools must return LLM-consumable structured
  data (`dict` / JSON / `ToolResult`). The `run()` DataFrame assembly and the
  `FlowComponent` input plumbing (`self.previous`, `self.input`, column
  extraction) must be dropped. *Evidence*: F001, F003
- **Async, aiohttp-only transport.** Reuse `parrot.interfaces.http.HTTPService`
  — its `session(method="post", url, data, headers)` returning `(result, error)`
  matches the flowtask call exactly, so the GraphQL POST ports with no change.
  No `requests`/`httpx`. *Evidence*: F005, F001
- **Config + auth.** API key via `navconfig` `config.get("LEADIQ_API_KEY")`
  (FRED pattern); headers `Authorization: Basic {LEADIQ_API_KEY}`,
  `Content-Type: application/json`, `apollo-require-preflight: true`.
  *Evidence*: F001, F003
- **Registration is a manual registry line.** Add `"leadiq":
  "parrot_tools.leadiq.tool.LeadIQToolkit"` to `TOOL_REGISTRY`;
  `scripts/generate_tool_registry.py` preserves manual entries. *Evidence*: F002
- **Do not conflate with the scraping variant.** `CompanyInfoToolkit.scrape_leadiq`
  is Google-CSE + Selenium HTML scraping of leadiq.com — no API key, no GraphQL.
  The new API client is complementary and belongs in its own module.
  *Evidence*: F006

### 2.3 Recent History (Relevant)

No git history was queried for the target module because it does not yet exist,
and the flowtask source lives in a different repository. Absence of prior
LeadIQ **API** code in ai-parrot-tools is itself confirmed (F006): the only hit
is the scraping method. This rules out a collision or an in-flight parallel
effort.

---

## 3. Probable Scope  *(mode = enrichment)*

### What's New

- **`parrot_tools/leadiq/tool.py`** — `LeadIQToolkit(AbstractToolkit)` with
  `tool_prefix = "leadiq"`, exposing three `@tool_schema`-decorated async
  tools: `search_company`, `search_employees`, `search_flat`.
- **Pydantic models** — a `LeadIQCompanyInput` (`company_name: str`) input and
  structured output model(s) homogenizing the flattened company/employee data.
- **`parrot_tools/leadiq/__init__.py`** — exports `LeadIQToolkit` (and models).

### What Changes

- **`packages/ai-parrot-tools/src/parrot_tools/__init__.py::TOOL_REGISTRY`** —
  add the `"leadiq"` entry.  *Evidence*: F002

### What's Untouched (Non-Goals)

- `CompanyInfoToolkit.scrape_leadiq` and the whole scraping path stay as-is.
- No pandas DataFrame return; no flowtask `FlowComponent` coupling.
- No batch DataFrame-column input plumbing (single `company_name` per call;
  the LLM/agent can loop).

### Patterns to Follow

- **`CompanyInfoToolkit`** for `__init__(**kwargs)` → `super().__init__(**kwargs)`
  and one `@tool_schema(Model)` async method per capability.  *Evidence*: F004
- **`FredAPITool`** for HTTP composition (`self.http_service =
  HTTPService(base_url=..., **kwargs)`), config resolution
  (`config.get("LEADIQ_API_KEY")`), and optional `ToolCache`.  *Evidence*: F003
- Reuse the three GraphQL query strings and the three `_process_*_response`
  transforms from the source verbatim.  *Evidence*: F001

### Integration Risks

- **Auth encoding ambiguity.** flowtask injects `LEADIQ_API_KEY` raw into
  `Basic {key}`, implying the env value is already Base64. If the raw API key
  is stored instead, the tool must encode `base64("{apiKey}:")`. Confirm before
  implementation (U3).  *Evidence*: F001
- **Return-shape drift.** `employees`/`flat` return many person rows; a naive
  giant JSON blob can blow the LLM context. Consider a `limit`/summary option.
  *Evidence*: F001

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | Source is a GraphQL client with 3 query types over `api.leadiq.com/graphql` | F001 | high | direct read of query consts + `_execute_query` |
| C2 | `AbstractToolkit` + `@tool_schema` is the right host pattern | F004 | high | `CompanyInfoToolkit` is a direct analog |
| C3 | `HTTPService.session` ports the POST transport verbatim | F005, F001 | high | identical signature already called by source |
| C4 | Auth is `Basic {LEADIQ_API_KEY}` (key already Base64) + `apollo-require-preflight` | F001 | high | encoding confirmed by user (U3 resolved) |
| C5 | Return contract is a structured `ToolResult` (no DataFrame) | F001, F003 | high | user-confirmed (U2 resolved) |
| C6 | `LeadIQToolkit` with 3 tools (not a single tool) | F004 | high | user-confirmed (U1 resolved) |
| C7 | No existing LeadIQ **API** client; only a scraping variant | F006 | high | exhaustive grep of `src/` |

Distribution: **7** high, **0** medium, **0** low.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **U1 — Tool shape.** — *Resolved*: **Toolkit.** Build
  `LeadIQToolkit(AbstractToolkit)` with three `@tool_schema` async tools
  (`search_company` / `search_employees` / `search_flat`).
  *Resolves*: C6
- [x] **U2 — Return contract.** — *Resolved*: **Structured `ToolResult`.**
  Each tool returns a `ToolResult` wrapping the homogenized dict (company) /
  list[dict] (people) — no pandas DataFrame.
  *Resolves*: C5
- [x] **U3 — Auth encoding.** — *Resolved*: **`LEADIQ_API_KEY` is already
  Base64-encoded**; inject it verbatim as `Authorization: Basic
  {LEADIQ_API_KEY}` (match flowtask). Key stored in the repo `.env`
  (gitignored) and read via `navconfig` `config.get("LEADIQ_API_KEY")`.
  *Resolves*: C4

### Unresolved (defer to spec / implementation)

- *(none — all open questions resolved.)*

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-304`** — *Rationale*: all claims are now high-confidence and
all three design forks are resolved (U1 toolkit, U2 `ToolResult`, U3 Base64
auth). The spec just needs to encode the settled decisions as acceptance
criteria and decompose into 2–3 tasks (module + models, registry wiring, tests).

### Alternatives

- **`/sdd-brainstorm FEAT-304`** — only if you want to weigh toolkit-vs-single-tool
  and the return contract as an open design exploration rather than settle them in a spec.
- **`/sdd-task FEAT-304`** — viable if U1–U3 are answered inline now; the
  implementation itself is small enough for a direct task queue.
- **Manual review** — not needed; no truncation, no contradictions.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-304/state.json` |
| Source (raw) | `sdd/state/FEAT-304/source.md` |
| Research plan | `sdd/state/FEAT-304/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-304/findings/F001..F006-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-304/synthesis.json` |

**Budget consumed**:
- Files read: 9 / 40
- Grep calls: 7 / 25
- Git calls: 0 / 10
- Truncated: **no**

**Mode determination**: forced `enrichment` (additive "create … taking code
from" — porting existing code, not investigating a defect).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md` |
| Plan prompt | `sdd/templates/research_plan.prompt.md` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | jesuslarag@gmail.com |
