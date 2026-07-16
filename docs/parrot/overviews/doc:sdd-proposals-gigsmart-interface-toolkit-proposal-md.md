---
type: Wiki Overview
title: FEAT-253 — GigSmart Interface Toolkit
id: doc:sdd-proposals-gigsmart-interface-toolkit-proposal-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: GigSmart exposes a **GraphQL API** at `https://api.gigsmart.com/graphql`
  with **OAuth 2.1
---

---
id: FEAT-253
title: "GigSmart Interface Toolkit: aiohttp GraphQL client + LLM toolkit"
slug: gigsmart-interface-toolkit
type: feature
mode: enrichment
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-06-23
  summary_oneline: "GigSmart interface toolkit: aiohttp GraphQL client + GigSmartToolkit for LLM-driven API interaction"
overall_confidence: medium
base_branch: dev
research_state: sdd/state/FEAT-253/
created: 2026-06-23
updated: 2026-06-23
---

# FEAT-253 — GigSmart Interface Toolkit

> **Mode**: enrichment
> **Confidence**: medium
> **Source**: `inline` — develop an aiohttp interface for GigSmart REST/GraphQL API + GigSmartToolkit for LLM interaction
> **Brainstorm**: `sdd/proposals/GigSmartToolkit_SPEC.md` (draft, contains 8 incorrect assumptions corrected by this research)
> **Audit**: [`sdd/state/FEAT-253/`](../state/FEAT-253/)

---

## 0. Origin

> Develop an aiohttp interface (on parrot_tools/interfaces/gigsmart/api.py) to interact
> with REST API + creating a GigSmartToolkit for LLM interaction with Gigsmart API,
> documentation is on: https://developers.gigsmart.ninja/docs/reference and brainstorm
> at sdd/proposals/GigSmartToolkit_SPEC.md

**Initial signals**:
- Verbs: "develop", "interact", "creating" -> new feature / greenfield
- Named entities: GigSmart, GraphQL, aiohttp, GigSmartToolkit, WorkingMemoryToolkit
- Components: `parrot_tools/interfaces/gigsmart/`
- Existing brainstorm: 800-line SPEC doc (draft, many `[VERIFY]` markers)
- Acceptance criteria provided: yes (6 functional surfaces defined in brainstorm)

---

## 1. Synthesis Summary

GigSmart exposes a **GraphQL API** at `https://api.gigsmart.com/graphql` with **OAuth 2.1
authentication** (client_credentials for reads, auth_code+PKCE for writes). The brainstorm
SPEC (`GigSmartToolkit_SPEC.md`) provides a solid architectural vision but contains 8 incorrect
assumptions about the API shape, auth mechanism, and codebase patterns — all corrected by this
research. The implementation should be a two-layer architecture: (1) a `GigSmartClient` class
handling aiohttp-based GraphQL transport with OAuth token lifecycle, placed at
`parrot_tools/interfaces/gigsmart/`, and (2) a `GigSmartToolkit` extending `AbstractToolkit`
with `confirming_tools` for write mutation safety, exposing 6 functional surfaces (auth,
locations, positions, gigs/shifts, engagements, timesheets) as LLM-callable tools.

---

## 2. Codebase Findings

> All entries grounded in research findings at `sdd/state/FEAT-253/findings/`.

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot/src/parrot/tools/toolkit.py` | `AbstractToolkit` | 207-602 | Base class for all toolkits; GigSmartToolkit inherits this | F001 |
| 2 | `packages/ai-parrot/src/parrot/tools/decorators.py` | `tool_schema` | 37-52 | Decorator for Pydantic-validated tool method inputs | F002 |
| 3 | `packages/ai-parrot/src/parrot/interfaces/http.py` | `HTTPService` | 126-549 | aiohttp-based HTTP client with auth injection — reference pattern for transport | F004, F012 |
| 4 | `packages/ai-parrot-tools/src/parrot_tools/massive/client.py` | `MassiveAPIError` | 16-35 | Typed exception hierarchy + exponential backoff retry — best existing error handling pattern | F004 |
| 5 | `packages/ai-parrot-tools/src/parrot_tools/resttool.py` | `RESTTool` | 34-127 | Base REST tool wrapping HTTPService with base_url and auth | F004 |
| 6 | `packages/ai-parrot/src/parrot/tools/working_memory/tool.py` | `WorkingMemoryToolkit` | 43-500 | DataFrame spill pattern for large result sets — compose with, do NOT inherit | F001 |

### 2.2 Constraints Discovered

- **aiohttp mandated.** CLAUDE.md §CONTEXT says "Never use `requests` or `httpx` — use `aiohttp`".
  The brainstorm SPEC proposed `httpx.AsyncClient`; this must be corrected to `aiohttp.ClientSession`.
  *Evidence*: F004, F012

- **No DeterministicGuard in codebase.** The SPEC proposes a `DeterministicGuard` + `MutationMandate`
  pattern that does not exist. The codebase uses `confirming_tools: frozenset[str]` on `AbstractToolkit`
  subclasses (FEAT-235) for HITL-gated mutations, plus `GrantGuard` (FEAT-211) for bounded approval windows.
  *Evidence*: F003

- **OAuth 2.1, not API key auth.** GigSmart uses OAuth 2.1 with two grant types. Write scopes
  (`write:gigs`, `write:engagements`, etc.) are ONLY available via `auth_code+PKCE` grant — not
  `client_credentials`. This means server-to-server agents are read-only unless the user completes
  an OAuth authorization flow.
  *Evidence*: F006, F008

- **Relay conventions.** GigSmart uses Relay-style GraphQL: `edges { node { ... } }` pagination,
  single `$input` mutation arguments, global IDs. The SPEC's `Page[T]` with flat `nodes[]` must
  be corrected.
  *Evidence*: F007, F010

- **No existing GraphQL client.** This would be the first GraphQL client in ai-parrot. The transport
  layer must be built from scratch, but should follow `HTTPService` patterns for consistency.
  *Evidence*: F004

- **Tokens expire.** Access tokens expire after 1 hour (auth_code) or 15 minutes (client_credentials).
  The client needs auto-refresh logic with proactive renewal before expiry.
  *Evidence*: F006

### 2.3 Recent History (Relevant)

No existing GigSmart code in the codebase — this is entirely greenfield. The brainstorm SPEC
at `sdd/proposals/GigSmartToolkit_SPEC.md` was committed recently as a draft design document.

---

## 3. Probable Scope

### What's New

- **`parrot_tools/interfaces/gigsmart/`** — aiohttp-based GraphQL client module:
  - `client.py` — `GigSmartClient` class: `aiohttp.ClientSession` management, GraphQL `execute()`,
    error classification, retry with exponential backoff
  - `auth.py` — OAuth 2.1 token lifecycle: `client_credentials` grant, `auth_code+PKCE` flow,
    token caching, auto-refresh, scope management
  - `models/` — Pydantic v2 input/output models for all 6 API surfaces (corrected from SPEC to
    match actual API field names)
  - `exceptions.py` — Typed exception hierarchy following Massive client pattern
  - `queries/` — GraphQL query/mutation documents as `.graphql` files

- **`parrot_tools/gigsmart/toolkit.py`** — `GigSmartToolkit(AbstractToolkit)`:
  - `tool_prefix = "gigsmart"`
  - `confirming_tools` frozenset for write mutations (post_shift, hire_worker, etc.)
  - `@tool_schema` decorated methods for each API surface
  - WorkingMemory DataFrame integration for large result sets (>50 items)

### What Changes

No existing files change — this is entirely new code.

### What's Untouched (Non-Goals)

- **Webhooks / event subscriptions** — tracked as follow-up
- **Worker-side mutations** — toolkit is requester/employer-side only
- **GigSmart MCP endpoint** — `requester-mcp.prod.gigsmart.com/mcp` exists but user chose custom toolkit only
- **Onfleet integration** — position attribute only, not a separate client
- **Payment dispute initiation** — only requester-side response included

### Patterns to Follow

| Pattern | Source | What to replicate | Evidence |
|---------|--------|-------------------|----------|
| Toolkit structure | `WorkingMemoryToolkit` | `tool_prefix`, `@tool_schema`, async methods → auto-discovered tools | F001, F002 |
| Typed exceptions | `MassiveAPIError` hierarchy | `GigSmartError` base, `AuthError`, `RateLimitError`, `TransportError` subclasses | F004 |
| Retry + backoff | `massive/client.py` | Exponential backoff on 5xx, `Retry-After` header parsing for 429 | F004 |
| Auth header injection | `HTTPService` | Single method (`build_headers()`) for all auth logic | F012 |
| aiohttp session | `HTTPService.async_request()` | Context manager pattern for `aiohttp.ClientSession` | F004, F012 |
| HITL mutation safety | `confirming_tools` frozenset | Mark write mutations (`post_shift`, `hire_worker`, `cancel_gig`) as requiring confirmation | F003 |

### Integration Risks

- **OAuth PKCE for write scopes**: The `auth_code+PKCE` flow requires a browser redirect for user
  authorization. In headless agent scenarios, this may need a pre-authorized token or a separate
  auth step. Mitigation: support pre-configured refresh tokens via env vars for CI/agent use.
  *Evidence*: F006, F008

- **First GraphQL client**: No existing pattern to copy; must establish conventions (query file
  loading, variable serialization, error extraction from `data`+`errors` response shape) that
  future GraphQL toolkits can follow. Mitigation: keep transport generic and reusable.
  *Evidence*: F004

- **Token expiry in long-running agents**: Client-credentials tokens expire in 15 minutes. An
  agent session running multi-step operations may silently fail mid-flow. Mitigation: proactive
  token refresh (re-auth when <2 minutes remaining).
  *Evidence*: F006

- **Schema drift**: Exact enum values for gig state, engagement state, and timesheet state are
  not fully confirmed from docs. Some fields may differ from the brainstorm SPEC. Mitigation:
  run introspection query against sandbox and persist `schema.graphql` for diff tracking.
  *Evidence*: F007, F011

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | API is GraphQL at `https://api.gigsmart.com/graphql` | F007 | high | directly confirmed from live docs |
| C2 | Auth is OAuth 2.1 (PKCE + client_credentials), not API key | F006, F008 | high | directly confirmed with token endpoint, scopes, and expiry |
| C3 | Write scopes require `auth_code` grant (not client_credentials) | F008 | high | scope table from docs shows write scopes = auth_code only |
| C4 | Mutations: `addOrganizationLocation`, `postShift`, `transitionGig` | F007, F010, F011 | high | directly confirmed from mutation examples in guides |
| C5 | Relay connection pagination (`edges { node { ... } }`) | F007, F010 | high | all query examples use Relay connection pattern |
| C6 | Inherit `AbstractToolkit`, use `confirming_tools` for write safety | F001, F003 | high | `AbstractToolkit` is the base; `DeterministicGuard` does not exist |
| C7 | Use `aiohttp` for transport (not `httpx`) | F004, F012 | high | CLAUDE.md mandate; `HTTPService` uses aiohttp |
| C8 | Token refresh needed (1h auth_code, 15min client_credentials) | F006 | high | directly confirmed from auth docs |
| C9 | Rate limiting via `X-RateLimit-*` headers | F006 | high | confirmed from auth docs |
| C10 | Module location: `parrot_tools/interfaces/gigsmart/` | F005, F012 | high | user-confirmed in Q&A (U2) |
| C11 | Support both OAuth grant types | — | high | user-confirmed in Q&A (U1) |
| C12 | Timesheet operations exist but exact mutations/scopes not confirmed | F008 | low | no timesheet-specific scopes visible; may be under engagements |
| C13 | `postShift` creates gig series + gig in one call | F011 | high | directly confirmed from Post a Shift guide |
| C14 | `placeAutocomplete` query required before location creation | F010 | high | directly confirmed from Create Location guide |

Distribution: **11** high, **0** medium, **1** low, **2** user-confirmed.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **U1: Should the toolkit support both OAuth grant types?** — *Resolved*: Yes, both.
  Client_credentials for read-only agents, auth_code+PKCE for full-access agents.
  *Resolves claims*: C11

- [x] **U2: Where should the GigSmart module live?** — *Resolved*: `parrot_tools/interfaces/gigsmart/`
  as user specified, separating the interface/client layer from the toolkit layer.
  *Resolves claims*: C10

- [x] **U3: Also register native GigSmart MCP endpoint?** — *Resolved*: No. Custom toolkit only
  for full control over validation, guards, and WorkingMemory integration.

- [x] **U4: Are API credentials provisioned?** — *Resolved*: Yes, available for development.

### Unresolved (defer to spec / implementation)

- [ ] **Exact timesheet mutation names and scopes** — *Owner*: implementer (Phase 1 introspection)
  *Blocks claims*: C12
  *Plausible answers*: a) under `write:engagements` scope · b) separate `write:timesheets` scope (not yet published)

- [ ] **Exact enum values for gig/engagement/timesheet states** — *Owner*: implementer (sandbox introspection)
  *Blocks claims*: C4 (partially)
  *Plausible answers*: a) match brainstorm SPEC guesses · b) differ (confirmed states: UPCOMING, ACTIVE, IN_PROGRESS)

- [ ] **Money type representation** — *Owner*: implementer (schema introspection)
  *Plausible answers*: a) cents integer · b) decimal string · c) `{ amount, currency }` object

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-253`** — Rationale: localization is high-confidence (11/14 claims at high),
the architecture is clear (two-layer: client + toolkit), and the 8 corrections to the brainstorm
SPEC are well-grounded. The spec should incorporate the corrected API shape, OAuth 2.1 auth
flow, and codebase patterns (AbstractToolkit, confirming_tools, aiohttp). The remaining unknowns
(timesheet mutations, exact enums, money type) can be resolved during Phase 1 implementation
via sandbox introspection.

### Alternatives

- **`/sdd-brainstorm FEAT-253`** — if you want to explore alternative architectures (e.g.,
  consuming GigSmart's native MCP endpoint instead of building a custom client, or using
  `OpenAPIToolkit` dynamic generation if GigSmart exposes an OpenAPI spec)
- **`/sdd-task FEAT-253`** — only if the spec from the brainstorm SPEC is considered sufficient
  after applying the 8 corrections documented here
- **Manual review** — to verify the 8 corrections against the live sandbox before proceeding

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-253/state.json` |
| Source (raw) | `sdd/state/FEAT-253/source.md` |
| Findings (digests) | `sdd/state/FEAT-253/findings/F001-*.md` through `F012-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-253/synthesis.json` |

**Budget consumed**:
- Files read: 28 / 40
- Grep calls: 18 / 25
- Git calls: 2 / 10
- Truncated: **no**

**Mode determination**: forced `enrichment` (greenfield feature with existing brainstorm doc).

---

## 8. Key Corrections to Brainstorm SPEC

This table summarizes the 8 corrections discovered during research. These MUST be incorporated
into the `/sdd-spec` to avoid building against incorrect assumptions.

| # | SPEC Section | SPEC Assumption | Corrected Reality | Evidence |
|---|-------------|-----------------|-------------------|----------|
| 1 | §3 Auth | `Authorization: Bearer <api_key>` | OAuth 2.1: `client_id` + `client_secret` → token exchange at `/oauth/token` | F006 |
| 2 | §2 Architecture | Inherit `WorkingMemoryToolkit` | Inherit `AbstractToolkit`; compose with WorkingMemory as needed | F001 |
| 3 | §8 Guard | `DeterministicGuard` + `MutationMandate` class | Use `confirming_tools: frozenset` + `_pre_execute()` validation | F003 |
| 4 | §4 Transport | `httpx.AsyncClient` | `aiohttp.ClientSession` per CLAUDE.md mandate | F004 |
| 5 | §7 Mutations | `createLocation` / `PostGigInput` | `addOrganizationLocation` / `PostShiftInput` (`postShift`) | F010, F011 |
| 6 | §6 Models | Flat `Address` input | API uses `placeId` from `placeAutocomplete` query | F010 |
| 7 | §6 Pagination | `Page[T]` with `nodes: list[T]` | Relay connection: `edges { node { ... } }` with `pageInfo` | F007 |
| 8 | §6.4 Gig | `workers_needed`, `time_window` | `slotsAvailable`, `startsAt`/`endsAt` directly on input | F011 |

---

## 9. Proposed Module Layout (Corrected)

```
packages/ai-parrot-tools/src/parrot_tools/
  interfaces/
    gigsmart/
      __init__.py
      client.py             # GigSmartClient (aiohttp GraphQL transport)
      auth.py               # OAuth 2.1 token lifecycle (both grant types)
      exceptions.py         # Typed exception hierarchy
      config.py             # GigSmartConfig (env-based settings)
      models/
        __init__.py
        common.py           # RelayConnection, RelayEdge, PageInfo, Money
        auth.py             # OAuthToken, AuthStatus, OAuthScopes
        location.py         # AddOrganizationLocationInput, OrganizationLocation
        position.py         # CreatePositionInput, Position
        gig.py              # PostShiftInput, Gig, GigState
        engagement.py       # Engagement, Worker, HireInput, EndInput
        timesheet.py        # Timesheet, EditTimesheetInput, ApproveInput
      queries/
        viewer.graphql
        locations.graphql
        positions.graphql
        gigs.graphql
        engagements.graphql
        timesheets.graphql
  gigsmart/
    __init__.py
    toolkit.py              # GigSmartToolkit(AbstractToolkit)
```

---

## 10. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Research agents | 4 parallel (toolkit patterns, HTTP clients, models/config, API docs) |
| Findings | 12 (F001–F012) |
| Operator | jlara@trocglobal.com |
