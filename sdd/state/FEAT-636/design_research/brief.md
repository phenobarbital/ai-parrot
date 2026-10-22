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

Original request (verbatim):
The original request, preserved verbatim (Spanish). The full source is at
`sdd/state/FEAT-636/source.md`.

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

### Constraints and goals
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

### Recommended option / probable scope
*(mode = enrichment)*

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

### Verified code anchors (paths only — open them yourself)
packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py
packages/ai-parrot-server/src/parrot/manager/manager.py
packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/fetch.ts
packages/ai-parrot/src/parrot/outputs/a2ui/linked/executor.py
packages/ai-parrot/src/parrot/outputs/a2ui/linked/models.py
packages/ai-parrot/src/parrot/outputs/a2ui/recipes/transformers.py

### Questions still open in the exploration document
none

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
