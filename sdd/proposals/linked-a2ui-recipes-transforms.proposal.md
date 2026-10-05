---
id: FEAT-628
title: Linked A2UI surfaces gain server-executed Python recipe transformers (optional server fetch lane)
slug: linked-a2ui-recipes-transforms
type: feature
mode: enrichment
status: review
provisional_id: true  # 628 taken from the ledger counter; reserve via reserve_ids.py at /sdd-spec time
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-10-06
  summary_oneline: Linked surfaces should optionally fetch via a server endpoint that runs the slug then a recipe transformer
overall_confidence: medium
base_branch: dev
projects: [ai-parrot, ai-parrot-server, admin-ui]
tags: [a2ui, linked-surfaces, querysource, recipes, transformers, ui-surfaces]
research_state: sdd/state/FEAT-628/
created: 2026-10-06
updated: 2026-10-06
---

# FEAT-628 — Linked A2UI surfaces gain server-executed Python recipe transformers

> **Mode**: enrichment
> **Confidence**: medium
> **Source**: `inline`
> **Audit**: [`sdd/state/FEAT-628/`](../state/FEAT-628/)

---

## 0. Origin

The original request, preserved verbatim (Spanish). The full source is at
`sdd/state/FEAT-628/source.md`.

> las surfaces a2ui estáticas pueden hacer agregación con transformadores en
> python, pero las linked surfaces no (dependen de la invocación del query
> slug) llaman a la URL de querysource, pero y si al definir la surface se
> puede invocar o la URL del querysource o llaman a una URL dónde se decide
> ejecutar el slug y luego pasar la data por un transformer, con lo cual los
> linked surfaces ganan la flexibilidad de ganar data de manera dinámica y a
> su vez de invocar transformaciones de las recipes (tal y como las static y
> recipe definitions)

**Initial signals** (extracted, not interpreted):
- Verbs: "pueden / no pueden", "invocar", "pasar la data por" → capability-parity enhancement, not a bug
- Named entities: "surfaces a2ui estáticas", "linked surfaces", "query slug", "querysource", "transformer", "recipes"
- Components / labels: A2UI, QuerySource, recipe transformers
- Acceptance criteria provided: no

---

## 1. Synthesis Summary

Static/recipe A2UI surfaces aggregate data with Python transformers through
`RecipeRunner`, but linked surfaces (FEAT-598) fetch rows client-side straight
from QuerySource (`fetch.ts::fetchSource`) and their `TransformSpec` only
admits the inline DSL v1 or renderer-side `transform.ref` modules — no Python
path exists. The proposal: let a linked data-source descriptor declare a
registered Python transformer; such a source fetches through a new per-source
parrot-server endpoint on `UISurfacesHandler` (which already hosts both
`_recipe_runner` and `_linked_service`) that executes the slug via the
existing linked executor under the data-plane guard and applies the named
transformer from `transformer_registry`. The Python bake/persist/refresh lane
(`executor.py::execute_sources`) applies the same transformer, so Python-lane
parity is intrinsic. Recommended next step: `/sdd-spec` — localization is
high-confidence and the design decisions were resolved in Q&A (§5).

---

## 2. Codebase Findings

> All entries are grounded in the digests at `sdd/state/FEAT-628/findings/`.

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot/src/parrot/outputs/a2ui/linked/models.py` | `TransformSpec` | 178-189 | `ops` XOR `ref` — the seam where a server-side transformer member is added | F002 |
| 2 | `packages/ai-parrot/src/parrot/outputs/a2ui/linked/models.py` | `LinkedDataSource` / `LinkedSource` | 192-264 | descriptor union (`kind=query_slug\|derived`); extension seam for fetch routing | F002 |
| 3 | `packages/ai-parrot/src/parrot/outputs/a2ui/linked/executor.py` | `_run_source` / `execute_sources` | 231-290 | Python lane: fetch + `apply_transform`; where the recipe transformer runs at bake/refresh | F005 |
| 4 | `packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py` | `UISurfacesHandler._refresh` / `_refresh_linked` / `_recipe_runner` / `_linked_service` | 346-734 | server lane that already hosts RecipeRunner AND LinkedSurfaceService; home of the new per-source endpoint | F003 |
| 5 | `packages/ai-parrot-server/src/parrot/manager/manager.py` | route registration | 2420-2423 | where `/api/v1/ui/surfaces/{id}/sources/{key}/data` registers | F003 |
| 6 | `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/transformers.py` | `transformer_registry` / `@infographic_transformer` / `validate_inputs` | module | the reusable Python transformer contract: name-registered pure `(inputs, params) -> dict` with manifests | F004 |
| 7 | `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/fetch.ts` | `fetchSource` | 61-83 | TS lane URL construction — must branch to the server endpoint when the descriptor declares a Python transformer | F005 |

### 2.2 Constraints Discovered

- **G1 invariant (never stored code).** Recipes reference transformations by
  **registered name only**; no dynamic import of user-supplied dotted paths.
  *Implication*: the linked descriptor carries `{transformer: <name>, params}`,
  resolved server-side against the in-process `transformer_registry`.
  *Evidence*: F004

- **Parity asymmetry precedent.** `transform.ref` is renderer-only — the
  Python executor skips it with a warning — and `DerivedDataSource` forbids
  `ref` outright "which would break Python ↔ renderer parity".
  *Implication*: the mirror rule holds here: a Python transformer is
  server-only, so a source declaring one must fetch through the server; the
  TS lane never attempts to run it.
  *Evidence*: F002, F005

- **Fail-closed trust model.** `LinkedSurfaceService` requires a data-plane
  guard (`LinkedGuardRequired` → 403); owner-check resource is `source:read`
  on `query_slug:<tenant|public>:<slug>`.
  *Implication*: the new endpoint sits behind the same guard; no new
  authorization surface is invented.
  *Evidence*: F001, F003

- **Identity semantics differ by lane.** Today's renderer fetch runs under
  the **viewer's JWT** (QuerySource PBAC); the surface-level server refresh
  runs under the **owner's** `PermissionContext` — "Share-bearer refresh runs
  with the OWNER's PermissionContext — never the bearer's identity".
  *Implication*: the per-source endpoint must define its identity model
  explicitly (resolved in §5, U1/U4).
  *Evidence*: F003

- **Row-bound invariants.** `querylimit` cap 5000 (`DEFAULT_MAX_FETCH_ROWS`),
  ≤500-row snapshots mandatory once persisted, `GET` never executes queries.
  *Implication*: unchanged; transformed sources must keep honoring them.
  *Evidence*: F001, F005

### 2.3 Recent History (Relevant)

Not sampled this run (0 of 10 git calls used). Known from the ledger and task
index: FEAT-598 tasks are completed and FEAT-611 validated linked surfaces
live end-to-end (fixes folded into `docs/outputs/a2ui-linked-surfaces.md`);
the surfaces code is active but stable. *Evidence*: F001

---

## 3. Probable Scope  *(mode = enrichment)*

### What's New

- **A Python-transformer transform member** *(shape decided — see §5 OQ-A/B/C)* —
  `TransformSpec.python: {transformer: <registered name>, params: {...},
  input_alias: <str, default "source">, output: <str | null>}` joining the
  existing `ops`/`ref` XOR (exactly-one-of-three). The server calls
  `registered({input_alias: frame}, params)` and reduces the returned dict to
  the source's frame with the existing multi-frame selection rule (`output`
  override → `result` key → sole key → error), mirroring
  `selectFrame`/`_select_multi_frame`.
- **Per-source server data endpoint** *(path decided — see §5 OQ-A)* —
  `POST /api/v1/ui/surfaces/{surface_id}/sources/{key}/data` on
  `UISurfacesHandler`: resolves the persisted descriptor, executes the slug
  via the linked executor machinery under the data-plane guard, applies the
  named transformer, returns rows (bounded by the existing caps).
- **TS fetch branch** — `fetchSource` (or a sibling) routes
  python-transformed sources to the server endpoint instead of QuerySource.

### What Changes

- **`linked/models.py`::`TransformSpec`** — third member + XOR validator
  update; `DerivedDataSource` validator extended to also reject `python`.
  *Evidence*: F002
- **`linked/executor.py`::`_run_source`** — after fetch, when
  `transform.python` is set, call the registered transformer (frame →
  `(inputs, params) -> dict` adaptation) instead of / before `apply_transform`
  per the terminal-in-v1 rule. *Evidence*: F005
- **`handlers/ui_surfaces.py`** — new dispatch for the per-source route;
  reuse `resolve_surface_access` (share tokens included) + guard + error
  mapping (404-as-unavailable). *Evidence*: F003
- **`manager/manager.py`** — one route registration. *Evidence*: F003
- **`ui/.../a2ui/linked/fetch.ts` (+ `types.ts`, `index.ts`)** — descriptor
  type gains the new member; fetch branches to the server URL; scheduler/
  dependency logic treats the source as terminal. *Evidence*: F005
- **`qs_build_linked_surface` toolkit lane** — the builder tool must accept
  and validate the transformer reference (via `TransformerManifest` /
  `validate_inputs`-style gate) at build time. *Evidence*: F001, F004

### What's Untouched (Non-Goals)

- Recipe surfaces (`recipe_name` lane) and `RecipeRunner` behavior.
- The DSL v1 operation set and `transform.ref` module lane.
- QuerySource itself and its PBAC; snapshot persistence semantics (AC16).
- v1 excludes: recipe references (`name@owner`) in descriptors (phase 2,
  per U2), DSL chaining after the transformer, and derived siblings
  referencing a python-transformed source (per U3).

### Patterns to Follow

- Lane-asymmetry handling à la `transform.ref`: explicit validator rejections
  and a documented "runs only in X lane" rule, never silent divergence.
  *Evidence*: F002, F005
- Transformer validation gate reuse: `TransformerManifest.requires_columns` +
  `validate_inputs`-style fail-fast before execution. *Evidence*: F004
- Error mapping discipline: denials surface as 404 "unavailable" (never
  "denied"); data-stage vs transform-stage errors map to 502 vs 422 as in
  `_refresh`. *Evidence*: F001, F003

### Integration Risks

- **Transformer availability in the server process.** Registration is an
  import side effect (`load_transformer_module` at boot/agent discovery); a
  descriptor naming an unregistered transformer must fail gracefully
  (persist-time gate + run-time 422), and operators need a documented wiring
  story. *Evidence*: F004
- **Identity duality.** Viewer-JWT execution (authenticated) vs owner-pctx
  execution (share tokens) in one endpoint doubles the auth paths to test;
  the share path must never leak beyond what the existing share refresh
  already allows. *Evidence*: F003
- **Dependency ordering.** `dependencies_of`/scheduler treat transforms as
  DSL op lists; the new member must not be misread as dependency-bearing
  (terminal in v1 keeps this contained). *Evidence*: F005

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | FEAT-598 is implemented, documented, e2e-validated; this is enrichment | F001 | high | authoritative doc + completed tasks + FEAT-611 |
| C2 | Linked transforms today are DSL v1 XOR renderer `ref`; no Python path | F001, F002 | high | direct read of `TransformSpec` + doc §5 |
| C3 | Renderer fetches directly from QuerySource with viewer JWT; no per-source server endpoint exists | F001, F003, F005 | high | `fetch.ts` read + route table read |
| C4 | The recipe transformer contract (name-registered pure functions + manifests) is reusable as-is | F004 | high | direct read of `transformers.py` |
| C5 | The server already executes slugs + DSL in Python (`LinkedSurfaceService.refresh` → `execute_sources`) | F003, F005 | high | handler + executor reads |
| C6 | Server-process transformer availability extends operationally from the recipes lane | F004 | medium | loader exists; boot wiring not traced this run |
| C7 | DSL chaining after a Python transformer is feasible in both lanes | F005 | low | not needed in v1 (terminal rule); unverified |

Distribution: **5** high, **1** medium, **1** low.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **U1 — Identity for the per-source endpoint?** — *Resolved*: **viewer
  identity (JWT)** — the slug executes under the viewer's QuerySource PBAC,
  preserving today's per-viewer scoping. Reconciliation with U4: share-token
  viewers have no JWT, so their requests run under the **owner's**
  `PermissionContext`, mirroring the existing share server-refresh semantics.
  *Resolves*: constraint "identity semantics differ by lane"
- [x] **U2 — Transformer name or recipe reference?** — *Resolved*: **both,
  phased** — v1 references a registered transformer by name (+params) against
  `transformer_registry` (G1 intact); a recipe (`name@owner`) reference is a
  planned later increment, explicitly out of v1 scope.
  *Resolves*: hypothesis 1 vs 2
- [x] **U3 — Chaining after the transformer?** — *Resolved*: **terminal in
  v1** — the transformer's output IS the source's frame; no inline DSL ops
  after it, and no derived/join/union sibling may reference a
  python-transformed source in v1. *Resolves*: C7 (deferred, not needed)
- [x] **U4 — Share-token viewers?** — *Resolved*: **included from day one** —
  the server executes slug + transformer on their behalf under the owner's
  pctx, consistent with the existing share refresh. *Resolves*: scope

- [x] **OQ-A — Exact wire shape and endpoint path** — *Resolved 2026-10-06*:
  **third `TransformSpec` member + per-source route** — `transform.python`
  joins the `ops`/`ref` XOR (exactly-one-of-three; `DerivedDataSource` also
  rejects it), and the renderer fetches python-transformed sources from
  `POST /api/v1/ui/surfaces/{surface_id}/sources/{key}/data`. A new source
  `kind` (field duplication, kind-dispatch churn) and a refresh-route
  query-param overload (mixes surface- and source-grain semantics) were
  both rejected. *Resolves*: hypothesis-1 shape
- [x] **OQ-B — Input adaptation** — *Resolved 2026-10-06*: **optional
  `python.input_alias`, default `"source"`** — the server calls
  `registered({input_alias: frame}, params)`. New transformers use the
  default; existing recipe transformers (whose `requires_columns` manifests
  name their own aliases, e.g. `"activity"`) are reusable by declaring the
  alias, and the `validate_inputs` gate works for both. v1 admits only
  single-input transformers (the source is terminal, no sibling frames).
  *Evidence*: F004; `runner.py:521-541` (inputs = `{alias: frame}`)
- [x] **OQ-C — Output adaptation** — *Resolved 2026-10-06*: **the existing
  multi-frame selection rule** — the transformer's returned dict is treated
  like a multi-frame payload: optional `python.output` override (analogous
  to `multi_output`) → `result` key → sole key → error if ambiguous. Same
  rule already proven in both lanes (`fetch.ts::selectFrame`,
  `QuerySlugSource._select_multi_frame`); the selected frame then behaves
  exactly like a fetched one (snapshot ≤500, querylimit caps, bindings).
  Verbatim-JSON output at `target` (non-tabular KPI payloads) was rejected
  for v1: it would need new snapshot/cap semantics. *Evidence*: F001, F005

### Unresolved (defer to spec / implementation)

- None. All open questions are resolved; `/sdd-spec` consumes §3 + §5 as-is.

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-628`** — *Rationale*: localization is high-confidence (C1–C5),
every primitive exists and converges on known seams (`TransformSpec`,
`execute_sources`, `UISurfacesHandler`, `transformer_registry`, `fetch.ts`),
and **all design decisions are resolved** (U1–U4 and OQ-A/B/C in §5): identity
model, reference grain, terminality, share-viewer scope, wire shape, endpoint
path, and the input/output adaptation conventions. No open fork remains.
Reserve the definitive FEAT id via `reserve_ids.py` at spec time
(`provisional_id: true` in this document's frontmatter).

### Alternatives

- **`/sdd-brainstorm FEAT-628`** — only if the recipe-reference variant
  (hypothesis 2) should be compared in depth before committing to the
  transformer-name shape.
- **Manual review** — not indicated; research completed within budget.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-628/state.json` |
| Source (raw) | `sdd/state/FEAT-628/source.md` |
| Research plan | `sdd/state/FEAT-628/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-628/findings/F001-*.md` … `F005-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-628/synthesis.json` |

**Budget consumed**:
- Files read: 6 / 40
- Grep calls: 10 / 25
- Git calls: 0 / 10
- Wall time: ~280s / 300s
- Truncated: **no** (wiki queries free: 4 queries + 3 full pages)

**Mode determination**: `auto` → resolved to `enrichment` (capability parity
on an implemented feature, no failure signal in source).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | jlara + Claude (Fable 5) |
