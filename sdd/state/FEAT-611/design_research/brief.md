<!--
  sdd/templates/design_research.prompt.md — neutral design-research brief (FEAT-545).
  Rendered by /sdd-spec section 3b and piped to `codex exec ... --output-schema
  design_research.schema.json`.
  FORBIDDEN INPUTS: never paste the spec draft, the spec author's reasoning, a preferred
  conclusion, or any text written by the model that will author the spec. The brief carries
  ONLY the accepted exploration document (brainstorm/proposal) and verified code anchors.
  Placeholders (double-curly-brace tokens, deliberately NOT written with literal braces in
  this comment — a renderer that does a naive whole-document string replace must not also
  rewrite this sentence): problem_statement, constraints_and_goals,
  recommended_option_or_scope, code_context_paths, open_questions, question.
-->
# Independent design review — read-only

You are an independent design reviewer for **ai-parrot**, an async-first Python
framework for AI agents (aiohttp, Pydantic v2, `uv` workspace under `packages/`).
You have read-only access to the repository in your working directory.

## Rules
1. Read the code you cite. Every `affected_paths` entry must be a repo-relative
   path you actually opened; suggestions with unverifiable paths are discarded.
2. Judge the design intent below against what exists in the repository: what is
   missing, what is risky, what would be simpler, what the codebase already
   provides that the intent re-invents.
3. Do not restate the intent, do not praise it, do not write code. Propose at
   most 12 concrete, falsifiable suggestions, each tagged with a kind
   (`architecture` | `api` | `testing` | `risk` | `alternative`), a risk level and
   your confidence.
4. Output exactly ONE JSON object conforming to the schema you were given — no
   markdown fences, no prose before or after.

## Accepted design intent (verbatim from the exploration document)

### Problem statement
FEAT-598 (A2UI Linked Surfaces) has landed on `dev`, but nobody has tested it end to end yet. Jesús Lara is building FEAT-610, an E2E example over `polestar_graduates_directory`. It is a static renderer (echarts + grid.js) that refreshes each widget with a `POST /api/v3/queries/{slug}`. Jesús asked for an alternative E2E test, because "two people test better than one".

This proposal is **parallel and independent**. It reuses what FEAT-610 builds as a base: the aiohttp server with QuerySource and AuthHandler, the login pattern, and the renderer. With that base it builds **other examples** that cover the parts of FEAT-598 that FEAT-610 leaves out. The raw source is in `sdd/state/FEAT-611/source.md`.

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

### Constraints and goals
- **The tool cannot compose a dashboard.** `qs_build_linked_surface` emits one component and one source, so a FilterBar plus a join needs a custom TOOL over `builders.build_linked_surface`. *Evidence*: F011. *Coordination*: FEAT-610 is adding a multi-widget helper to the toolkit, so this track **reuses** it if it lands first. Otherwise it uses its own example TOOL and does not modify the toolkit.
- **The server lane fails closed.** Without PBAC policies loaded there is no guard, and without a guard every request gets a 403. There is no `query_slug` policy in `policies/`. *Evidence*: F013.
- **Runtime version.** `querysource` was 4.5.11 in the venv (no tenants, no `@>`); it is now **5.1.2**, and every scenario must pass against 5.1.2. Tenant slugs stay **out of scope** (no demo tenant in staging). Epson only needs `{firstdate}/{lastdate}` placeholders and `fields`/`group_by`. *Evidence*: F003.
- **Slugs live in `public.queries`.** The only way to register a multiquery slug is to write to that table (`save_multiquery(allow_write=True)`), so any seed goes to **staging** and must be idempotent. *Evidence*: F004.
- **Python renderers ignore `parrot_data_sources`.** Live refresh can only be checked in the Svelte lane or in the FEAT-610 renderer. *Evidence*: F014.
- **Gitignore.** `examples/**/*.py` is ignored, and `examples/agents/a2ui/` is already whitelisted. The new examples should live there, or come with their own whitelist entry. *Evidence*: F002.

### Recommended option / probable scope
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

### Verified code anchors (paths only — open them yourself)
packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py
packages/ai-parrot-server/src/parrot/manager/manager.py
packages/ai-parrot-server/tests/integration/test_linked_surfaces_e2e.py
packages/ai-parrot-server/ui/src/lib/components/agents/canvas/InfographicCanvas.svelte
packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UISurface.svelte
packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/conditions.ts
packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/index.ts
packages/ai-parrot-server/ui/src/lib/components/agents/canvas/infographic-tab-builder.ts
packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py
packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py
packages/ai-parrot/src/parrot/auth/pbac.py
packages/ai-parrot/src/parrot/bots/base.py
packages/ai-parrot/src/parrot/outputs/a2ui/builders.py
packages/ai-parrot/src/parrot/outputs/a2ui/emission.py
packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/envelopes/linked_dashboard_join.json
packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/envelopes/linked_multiquery_public.json
packages/ai-parrot/src/parrot/outputs/a2ui/linked/executor.py
packages/ai-parrot/src/parrot/outputs/a2ui/linked/service.py

### Questions still open in the exploration document
- [ ] **The real definition of the `epson_*` slugs in staging**, and whether an Epson multiquery slug already exists or has to be seeded. *Owner*: the spec's first task. *Blocks*: C7
- [ ] **The PBAC policy for `query_slug:public:epson_*`** in staging. *Owner*: the spec's first task. *Blocks*: S1
- [ ] **Merge order with FEAT-610** for the multi-widget helper and `linked/index.ts`. *Owner*: Javier + Jesús.

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
