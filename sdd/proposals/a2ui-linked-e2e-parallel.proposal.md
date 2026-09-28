---
id: FEAT-611
title: A2UI Linked Surfaces E2E — parallel track (server lane + share/PBAC, join/DSL/FilterBar params, multiquery, admin-UI chat wiring) over Epson slugs on staging
slug: a2ui-linked-e2e-parallel
type: feature
mode: enrichment
status: accepted
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-09-28
  summary_oneline: Parallel A2UI linked-surfaces E2E examples reusing FEAT-610 infrastructure to exercise other FEAT-598 capabilities/datasets
overall_confidence: medium
base_branch: dev
# projects: parts of the codebase this doc concerns. Use `packages/*` dir names
#   (ai-parrot, ai-parrot-server, parrot-formdesigner, …) or an area
#   (sdd-tooling, dev-loop, admin-ui, docs, ci). Unknown values warn, not fail.
projects: [ai-parrot, ai-parrot-tools, ai-parrot-server, admin-ui, docs]
# tags: free-form kebab-case keywords for organizing specs (e.g. memory, mcp).
tags: [a2ui, linked-surfaces, querysource, e2e-example, pbac, multiquery]
research_state: sdd/state/FEAT-611/
related: [FEAT-598, FEAT-610]
created: 2026-09-28
updated: 2026-09-28
---

# FEAT-611 — A2UI Linked Surfaces E2E (parallel track)

> **Mode**: enrichment
> **Confidence**: medium
> **Source**: `inline`
> **Audit**: [`sdd/state/FEAT-611/`](../state/FEAT-611/)
> **Sibling**: [FEAT-610](a2ui-linked-e2e-test.proposal.md) (Jesús Lara)

---

## 0. Origin

FEAT-598 (A2UI Linked Surfaces) has landed on `dev`, but nobody has tested it end to end yet. Jesús Lara is building FEAT-610, an E2E example over `polestar_graduates_directory`. It is a static renderer (echarts + grid.js) that refreshes each widget with a `POST /api/v3/queries/{slug}`. Jesús asked for an alternative E2E test, because "two people test better than one".

This proposal is **parallel and independent**. It reuses what FEAT-610 builds as a base: the aiohttp server with QuerySource and AuthHandler, the login pattern, and the renderer. With that base it builds **other examples** that cover the parts of FEAT-598 that FEAT-610 leaves out. The raw source is in `sdd/state/FEAT-611/source.md`.

---

## 1. Synthesis Summary

FEAT-610 covers the **browser lane over public slugs**. It uses only `fields`/`filter`/`group_by`, its own renderer, and independent sources. By design it leaves out the following, all of which exist in FEAT-598 code and are untested against real services (F010, F013):

- the server lane (persistence, `/refresh` with params, share tokens, the PBAC guard);
- sources linked to each other (join/union) and the `transform.ops` DSL;
- the `FilterBar` with `parrot_param`;
- multiquery slugs;
- declared/locked params;
- refresh policies.

The research surfaced three things that change the approach:

1. **The Svelte linked lane cannot be reached from a real agent chat.** There are five chained blockers (F014):
   - the tool's envelope is never lifted into `response.a2ui_envelope`;
   - the shape does not match: the tool emits the inner `CreateSurface`, while Svelte expects `{version:"v1.0", createSurface}`;
   - the canvas opens no tab when the root is not Infographic/Report;
   - the canvas never passes `persistedSurfaceId`;
   - everything sits behind a build flag.

   Without fixing these, FEAT-598 in the admin UI is only reachable from vitest.
2. **Hidden TS↔Python drift** (F015):
   - `conditions.ts` emits `limit` and `_offset: 0`;
   - `setParam` does not validate declared params;
   - `serverRefresh` discards the response;
   - failure notices say "data as of never".

   On top of that, the existing E2E test fakes all of Postgres, QS, QueryModel and the guard, and the vitest suites have never run.
3. **The environment differs from what FEAT-610 assumes** (F003):
   - `querysource` 4.5.11 is installed (no JSONB `@>` and no tenants);
   - `QS_PBAC_ENABLED` is not defined;
   - `env/.env` points at the **production** database.

   This proposal runs against **staging**.

The recommendation is four scenarios over the Epson slugs (`epson_field_activity` + `epson_program_targets`, the ones FEAT-598's own fixtures use, F001), plus the admin-UI chat wiring and the drift fixes.

---

## 2. Codebase Findings

> Every entry cites the digests in `sdd/state/FEAT-611/findings/`. `venv:` = installed package.

### 2.1 Localization

| # | Path | Symbol | Role | Evidence |
|---|------|--------|------|----------|
| 1 | `packages/ai-parrot/src/parrot/outputs/a2ui/builders.py` | `build_linked_surface` | Composes N components and N sources (the only way to get a FilterBar or join) | F011 |
| 2 | `packages/ai-parrot/src/parrot/outputs/a2ui/linked/executor.py` | `execute_sources` | Server lane: topological order, param overrides (locked/undeclared → `ignored_params`), DSL | F010, F012 |
| 3 | `packages/ai-parrot/src/parrot/outputs/a2ui/linked/service.py` | `LinkedSurfaceService` | Save and refresh; `_assert_sources_allowed`; per-source or broadcast params | F013 |
| 4 | `packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py` | refresh (l.617-736), `_pin_save`, GET `?format=html` | 409 / 403 / CAS / `X-Parrot-Refresh-Warnings` | F013 |
| 5 | `packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py` | `PublishSurfaceTool` | `guard=None` by default, so it fails closed | F013 |
| 6 | `packages/ai-parrot/src/parrot/auth/pbac.py` | `setup_dataplane_guard` | Resource `query_slug`, id `<tenant\|public>:<slug>`, action `source:read` | F013 |
| 7 | `packages/ai-parrot-server/src/parrot/manager/manager.py` | guard wiring, mirror route and share routes | Agent surface mirror and share token | F013 |
| 8 | `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py` | `QuerysourceToolkit.build_linked_surface`, `save_multiquery` | One component per call; `is_multiquery` without `multi_output`; returns a plain dict | F011, F012, F014 |
| 9 | `packages/ai-parrot/src/parrot/bots/base.py` (l.1476-1534) · `packages/ai-parrot/src/parrot/outputs/a2ui/emission.py` | `finalize_a2ui_response` | Does not lift the linked envelope from dict tool results | F014 |
| 10 | `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/infographic-tab-builder.ts` (l.60) · `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/InfographicCanvas.svelte` (l.353) | — | No tab for Chart/DataTable/KPICard/Column roots; no `persistedSurfaceId` | F014 |
| 11 | `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UISurface.svelte` | `serverRefresh` | Discards the refresh response | F014, F015 |
| 12 | `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/index.ts` · `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/conditions.ts` | `LinkedLane.setParam` | TS↔Python drift | F011, F015 |
| 13 | `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/envelopes/linked_dashboard_join.json` · `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/envelopes/linked_multiquery_public.json` | — | Existing Epson envelopes (join, multiquery), usable as goldens | F001, F012 |
| 14 | `packages/ai-parrot-server/tests/integration/test_linked_surfaces_e2e.py` | FakeQS, fake guard | Pattern to extend with a real run against staging | F015 |

### 2.2 Constraints Discovered

- **The tool cannot compose a dashboard.** `qs_build_linked_surface` emits one component and one source, so a FilterBar plus a join needs a custom TOOL over `builders.build_linked_surface`. *Evidence*: F011. *Coordination*: FEAT-610 is adding a multi-widget helper to the toolkit, so this track **reuses** it if it lands first. Otherwise it uses its own example TOOL and does not modify the toolkit.
- **The server lane fails closed.** Without PBAC policies loaded there is no guard, and without a guard every request gets a 403. There is no `query_slug` policy in `policies/`. *Evidence*: F013.
- **Runtime version.** `querysource` was 4.5.11 in the venv (no tenants, no `@>`); it is now **5.1.2**, and every scenario must pass against 5.1.2. Tenant slugs stay **out of scope** (no demo tenant in staging). Epson only needs `{firstdate}/{lastdate}` placeholders and `fields`/`group_by`. *Evidence*: F003.
- **Slugs live in `public.queries`.** The only way to register a multiquery slug is to write to that table (`save_multiquery(allow_write=True)`), so any seed goes to **staging** and must be idempotent. *Evidence*: F004.
- **Python renderers ignore `parrot_data_sources`.** Live refresh can only be checked in the Svelte lane or in the FEAT-610 renderer. *Evidence*: F014.
- **Gitignore.** `examples/**/*.py` is ignored, and `examples/agents/a2ui/` is already whitelisted. The new examples should live there, or come with their own whitelist entry. *Evidence*: F002.

### 2.3 Recent History (Relevant)

This is the same as FEAT-610 §2.3: PR #1513 merged FEAT-598 today (`80ed03909`, TASK-3795/3796). The TASK-3795 notes say vitest and svelte-check never ran (F015).

---

## 3. Probable Scope

### Scenarios (examples under `examples/agents/a2ui/linked_e2e/`)

**Dataset**: `epson_field_activity` (`day, visits, program, store_id`, placeholders `firstdate`/`lastdate`) and `epson_program_targets` (`program, target`), plus a multiquery slug derived from them.

| # | Scenario | What it validates | Evidence |
|---|---|---|---|
| S1 | **Server lane + share + PBAC** | Agent → `qs_build_linked_surface` → `publish_surface` (with `linked_service` injected) → GET JSON and `?format=html` (no execution) → `POST /refresh {params:{firstdate,lastdate}}` → share token → refresh as the bearer (owner pctx) → negative cases: no policy → 403; no guard → 403; `refreshable=false` → 409; concurrent refresh → 409 stale; a locked or undeclared param → warning in `X-Parrot-Refresh-Warnings` | F013, F010 |
| S2 | **Join + DSL + FilterBar** | "Activity vs target" dashboard: KPIs (total visits, stores visited, % attainment), a bar chart of visits by day, a table joining `activity` ⋈ `targets` on `program`, and `transform.ops` (`group_by` → `derive attainment` → `sort`). Two FilterBars: a date range with `parrot_param` (re-executes the source) and a program filter (local). **Parity**: `execute_sources` (Python) and `LinkedLane` (TS) return identical rows for the same params. | F011, F012, F010 |
| S3 | **Multiquery** | Seed `epson_activity_vs_targets_mq` in staging with `save_multiquery` (Join, 2 frames), then a linked DataTable with `is_multiquery`. Cases: with `multi_output`, without it (falls back to `result`), and an ambiguous frame (→ `[]` plus a notice). | F012, F004 |
| S4 | **Admin-UI chat** | A BotManager agent with QuerysourceToolkit. A chat with `output_mode=a2ui` renders the linked surface in `A2UISurface` (Svelte), the FilterBar re-queries, and the Refresh button goes through the server lane. | F014 |

### What's New

- **`examples/agents/a2ui/linked_e2e/`**:
  - `server.py`: aiohttp + QuerySource + AuthHandler + BotManager, using the FEAT-610 mount order; it reuses FEAT-610's `server.py` if that lands first.
  - `agent.py`: an Epson agent with QuerysourceToolkit and the dashboard TOOL.
  - `seed_staging.py`: idempotent. It creates the multiquery slug and a `query_slug:public:epson_*` policy in a demo policy directory.
  - `run_e2e.py`: an asserting HTTP client for S1–S3; the exit code is the verdict.
  - `README.md`: requirements (staging env, QS version, PBAC).
- **Example TOOL** `build_epson_activity_dashboard` over `builders.build_linked_surface` (S2), unless FEAT-610's helper is already available.
- **Tests**:
  - integration tests marked `staging`, one per scenario, skipped without `ENV=staging`;
  - a golden for the S2 envelope;
  - a Python↔TS parity test over the same fixture;
  - a **real** vitest run (install `node_modules` in CI or locally).

### What Changes (minimal core fixes that S4 and parity need)

- **Envelope lifting**: `bots/base.py` / `emission.finalize_a2ui_response` lift `a2ui_envelope` from dict tool results that carry the `a2ui_linked_surface` artifact. *Evidence*: F014
- **v1.0 shape**: normalize the inner `CreateSurface` into `{version:"v1.0", createSurface}`, either at emission or in `A2UISurface.svelte`. *Evidence*: F014
- **Canvas**: `infographic-tab-builder.ts` opens a tab for roots of type Chart/DataTable/KPICard/Column, and `InfographicCanvas.svelte` passes `persistedSurfaceId` when the surface is persisted. *Evidence*: F014
- **Drift fixes**:
  - `conditions.ts` stops emitting `limit` and `_offset: 0`, aligned with `conditions.py` and the `limit_offset.json` fixture;
  - `setParam` ignores undeclared or locked names;
  - `serverRefresh` applies the response to the dataModel;
  - notices use the descriptor's `snapshot_at`.
  *Evidence*: F015
- **Validation**: `_validate_linked_sources` checks that the FilterBar's `param.source` and `param.name` exist. *Evidence*: F011
- **`PublishSurfaceTool`**: document or inject `linked_service` with the guard (BotManager injects `bot._dataplane_guard`). *Evidence*: F013

### What's Untouched (Non-Goals)

- The **FEAT-610** scope: its renderer (echarts + grid.js), `polestar_graduates_directory`, grid paging, and the querysource pin.
- Tenant slugs (requires QS ≥5.1.1, not installed; F003) and `transform.ref` (the publisher has no wiring; F015). These stay candidates for a later FEAT.
- `interval` refresh policies, beyond one smoke case inside S2.
- Any write to the **production** DB.

### Patterns to Follow

- Mount order and login from FEAT-610 §3 (`app.py`, `admin_login_page`).
- The fakes in `test_linked_surfaces_e2e.py` for the offline tier of the same tests (F015).
- The Epson fixtures `linked_dashboard_join.json` / `linked_multiquery_public.json` as the starting shape (F001, F012).
- Idempotent seeding via `SlugCatalog.upsert` (`save_multiquery(overwrite=True)`) (F004).

### Integration Risks

- **Conflict with FEAT-610 in `linked/index.ts`.** FEAT-610 adds `refreshSource(key)`; this track touches `setParam` and `onUpdate`. *Mitigation*: agree on the order with Jesús; whichever merges second rebases.
- **Staging data.** It is not verified that `epson_*` exist in `navigator_staging` with the SQL and columns the fixtures assume (inferred columns, F001). *Mitigation*: the spec's first task runs `qs_describe_slug` against staging and records the definition.
- **PBAC.** The guard only exists if PBAC loads a policy directory. The seeded policy must not leak into `policies/` in the repo. *Mitigation*: a dedicated `PARROT_PBAC_POLICY_DIR` for the example.
- **Vitest has never run.** The drift fixes may break tests that were never really green. *Mitigation*: run vitest before touching anything and record the baseline.

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence |
|----|-------|----------|------------|
| C1 | FEAT-610 does not exercise tenant, multiquery, params/locked, DSL, refresh policies or the server lane | F010, F013 | high |
| C2 | FilterBar + join need a custom TOOL over `build_linked_surface` | F011 | high |
| C3 | The Svelte linked lane cannot be reached from agent chat (5 blockers) | F014 | high |
| C4 | `PublishSurfaceTool` defaults to `guard=None`; the guard only exists with PBAC policies | F013 | high |
| C5 | TS↔Python drift (`limit`, `offset:0`, `setParam`, `serverRefresh`, `snapshotAt`) | F015 | medium |
| C6 | The existing E2E fakes everything external; vitest has never run | F015 | high |
| C7 | The `epson_*` slugs are the ones FEAT-598 fixtures use; the real SQL is unverified | F001 | medium |
| C8 | QS 4.5.11 installed; `env/.env` = production; staging available | F003 | high |
| C9 | Slugs can only be registered via `public.queries`; `save_multiquery` upserts multiquery rows | F004 | high |
| C10 | Python renderers ignore `parrot_data_sources` | F014 | high |

Distribution: **8** high, **2** medium, **0** low.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **Which capabilities to cover?** *Resolved*: all four: the server lane with share and PBAC, join + DSL + FilterBar params, multiquery, and the admin-UI chat wiring. *Resolves*: C1, C3
- [x] **Dataset?** *Resolved*: Epson (`epson_field_activity` + `epson_program_targets`). *Resolves*: C7 (partially)
- [x] **Environment?** *Resolved*: staging (`env/staging`); no writes to production. *Resolves*: C8, C9
- [x] **querysource version?** *Resolved (2026-09-28, Javier)*: test against the **latest querysource, 5.1.2**. The parrot venv has already been upgraded (4.5.11 → 5.1.2, a targeted `uv pip install`). The pins go up to `>=5.1.2` in `ai-parrot[db,integrations]` and `ai-parrot-tools[db]`, and `uv.lock` is regenerated. *Resolves*: C8, U5 (partially)

### Unresolved (defer to spec / implementation)

- [ ] **The real definition of the `epson_*` slugs in staging**, and whether an Epson multiquery slug already exists or has to be seeded. *Owner*: the spec's first task. *Blocks*: C7
- [ ] **The PBAC policy for `query_slug:public:epson_*`** in staging. *Owner*: the spec's first task. *Blocks*: S1
- [ ] **Merge order with FEAT-610** for the multi-widget helper and `linked/index.ts`. *Owner*: Javier + Jesús.

---

## 6. Recommended Next Step

→ `/sdd-spec FEAT-611`. The scope is decided and the localization is precise. What remains is checking staging (slugs, policy, QS version), which is the first task. Rough task split:
1. Verify the `epson_*` slugs and the QS version in staging; seed the multiquery slug and the demo policy (idempotent).
2. Run vitest for real and record the baseline.
3. Drift fixes (TS `conditions`/`setParam`/`serverRefresh`/`snapshotAt`) + `param.source` validation.
4. Envelope lifting + v1.0 shape + canvas tab/`persistedSurfaceId` (S4).
5. The `build_epson_activity_dashboard` TOOL + golden + Python↔TS parity (S2).
6. `server.py`/`agent.py`/`run_e2e.py` for S1 and S3.
7. Staging tests, README, and a manual S4 run in the admin UI.

---

## 7. Research Audit

- Source: `sdd/state/FEAT-611/source.md`
- Plan: `sdd/state/FEAT-611/research_plan.json` (2 lanes: A datasets/slugs, B uncovered capabilities)
- Findings: `sdd/state/FEAT-611/findings/` (F001–F004, F010–F015)
- Synthesis: `sdd/state/FEAT-611/synthesis.json`
- State: `sdd/state/FEAT-611/state.json`
- Note: wikitoolkit is not available (`command not found`), so the research used grep and direct reads. The plan gate was not shown; it ran in auto mode. No DB was queried.
