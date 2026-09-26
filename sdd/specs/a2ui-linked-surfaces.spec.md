---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-tools, ai-parrot-server, admin-ui, docs]
tags: [a2ui, querysource, linked-surfaces, ui-surfaces, transform-dsl, widgets]
---

# Feature Specification: A2UI Linked Surfaces (data-source descriptors instead of baked data)

**Feature ID**: FEAT-598
**Date**: 2026-09-24 (rev 0.2: 2026-09-25, re-verified against QuerySource 5.1.1)
**Author**: Jesus Lara (drafted with Claude)
**Status**: approved
**Target version**: ai-parrot 1.1.0 (ai-parrot / ai-parrot-tools / ai-parrot-server, next minor)
**Brainstorm**: `sdd/proposals/a2ui-linked-surfaces.brainstorm.md` (accepted 2026-09-24 after three revisions: FEAT-558 re-verification, FEAT-147/FEAT-148 cross-check, QuerySource 5.1.0 gate)

---

## 1. Motivation & Business Requirements

### Problem Statement

Every A2UI surface ai-parrot emits today is **baked**: the agent runs the data
(pandas, `qs_execute_slug`, a recipe transformer), copies the resulting rows
into `createSurface.dataModel`, and the renderer only *binds* to them. The
surface is a photograph. Refreshing it means either re-running an LLM turn or,
for recipe-backed surfaces, replaying the recipe server-side (`RecipeRunner`,
FEAT-324/326) through `POST /api/v1/ui/surfaces/{id}/refresh` (FEAT-492). A
surface without a `recipe_ref` cannot be refreshed at all
(`UISurfaceRecord.refreshable` is hard-wired to `recipe_name is not None`,
`handlers/models/ui_surfaces.py:84-86`; the handler answers **409**,
`handlers/ui_surfaces.py:590-597`).

Navigator already has the opposite model in production: a **widget** in the
(Vue 2, to be replaced) dashboard is a *structure plus a data reference* — it
POSTs a QuerySource slug with conditions, post-processes the rows client-side,
and renders a chart, a KPI hero row or a grid. Reloading a widget is just
re-issuing that call. Those widgets are hand-built by people; nothing lets an
agent *produce* one.

The gap this feature closes: an agent that has the FEAT-558
`QuerysourceToolkit` can already *replicate* how the data is obtained. It
should be able to emit an A2UI surface that carries **(1) the component and
its presentation props, (2) a data-source descriptor saying how to fetch the
rows, (3) an optional declarative transform, and (4) optionally the current
rows as a snapshot** — so the renderer registers a fully functional,
self-refreshing widget or dashboard, and the same descriptor lets the server
refresh the persisted surface without an LLM.

Who is affected: Navigator users (live agent-authored widgets/dashboards), the
`navigator-frontend-next` team (the descriptor is the contract their widget
runtime executes), agent authors (no more baking every number), and the
ui_surfaces plane (FEAT-492: refreshable by descriptor, not only by recipe).

### Goals

- G1 **One descriptor, one Python reference executor, N renderer executors,
  one set of golden fixtures.** ai-parrot publishes the descriptor/DSL JSON
  Schema, the Python executor and the JSON in/out fixtures; every renderer
  (`navigator-frontend-next`, the bundled `ai-parrot-server/ui`) implements
  its own executor against them. No TypeScript is shipped for third parties.
- G2 **Any surface, not only widgets**: a dashboard may declare several
  sources under `createSurface.metadata.extensions.parrot_data_sources`,
  keyed by the `dataModel` root key each source fills; components keep
  binding with ordinary `{"path": "/<key>/rows"}`. No new top-level component
  prop, no `kind` on the wire.
- G3 **The renderer fetches QuerySource directly with the viewer's JWT** on
  `POST /api/v3/queries/{slug}` (or `POST /api/v1/{tenant}/queries/{slug}`
  when `source.tenant` is set); ai-parrot-server never proxies the fetch.
- G4 **Server-side execution is the alternative lane** (FEAT-492 refresh,
  save-time snapshot, scheduled delivery): the Python executor runs the same
  descriptor in-process with tenant-aware plumbing and an explicit
  trusted-service model.
- G5 **Only TOOL-origin builders may emit a descriptor**; an LLM-origin
  envelope carrying `parrot_data_sources` fails `validate_envelope`.
- G6 **The builder always executes once**: axes/columns are validated against
  the real columns and dtypes of the fetched frame; `snapshot` only decides
  whether (≤500) rows are embedded.
- G7 **Transform DSL v1 is ten declarative operations, no code**; inline
  `ops` is the rule, `transform.ref` (catalogued, SRI-pinned, signed manifest)
  is supported.
- G8 **Tenant is descriptor content** (`tenant: str | null` per source); the
  FEAT-558 program allowlist and QuerySource PBAC remain the only gates.
- G9 **Additive**: baked surfaces, `bake_envelope`, the six satellite
  renderers and `lower()` are untouched — a linked surface with a snapshot is
  indistinguishable from a baked one for them.

### Non-Goals (explicitly out of scope)

- A component-level `LinkedWidget` (brainstorm Option B), recipes-as-descriptor
  (Option C) and SSE-pushed live surfaces (Option D) — rejected in the
  brainstorm; C stays the server lane inside this design.
- LLM-generated transform code (`transform.ref` modules are catalogued, never
  LLM-written); library input shapes (ECharts pie pairs, gauges) — renderer
  adapters' job.
- A TypeScript executor shipped from this repo for third parties.
- A DatasetManager-facing wrapper of the builder (follow-up).
- Relative-date offsets beyond QuerySource's closed 7-keyword vocabulary; the
  FEAT-558 `@variables` are rejected on the wire (non-portable).
- Tenant discovery, tenant-membership authorization, per-tenant credentials —
  none exist in QuerySource 5.1.1 and this feature does not add them
  (FEAT-150's `principal=` authorizes the *slug*, it adds no membership check
  and credentials stay trusted-service).
- `QSPrincipal` on the agent-tool lane (`qs_execute_slug`,
  `qs_build_linked_surface`'s mandatory execution): the toolkit has no
  per-user identity today; it stays behind the FEAT-558 `programs` allowlist +
  `forced_conditions`. Threading an acting-user principal into toolkits is a
  separate follow-up.
- QuerySource's `residual=` (FEAT-152 qsurl) and the jsonb OR/AND filter
  grammar — orthogonal 5.1.x additions, not consumed here.
- Any change to `UISurfaceKind`, the frontend `inferSurfaceKind` heuristic,
  the ui_surfaces DDL, or `clients/base.py`.

---

## 2. Architectural Design

### Overview

Four additive pieces (brainstorm Option A, recommended and accepted):

1. **Descriptor models + surface-level validation.** `parrot/outputs/a2ui/linked/`
   gains Pydantic v2 models for `LinkedDataSource` (`kind: "query_slug"`,
   `slug`, `tenant`, `is_multiquery`, `conditions` raw + `request`
   structured, `params`, `locked`, `transform`, `target`, `snapshot_at`,
   `snapshot_truncated`, `refresh`), the ten DSL ops and `TransformRef`, with
   a JSON Schema export. `validate_envelope` grows a **surface-level pass**
   (today it iterates components only) that parses
   `metadata.extensions.parrot_data_sources`, checks `target` pointers against
   bindings, `locked ⊆ params`, `join.with`/`union.sources` naming sibling
   sources, `transform.ref` ∈ manifest, and the origin gate
   `DATA_SOURCES_NOT_ALLOWED_FOR_LLM` (mirrors D10b and FEAT-473).
2. **Deterministic builder + agent tool.** `build_surface` gains
   `surface_metadata`; `build_linked_surface(components, sources, frames, …)`
   validates `x`/`y`/`columns` props against the fetched frames' columns and
   dtypes and emits `CreateSurface(origin=TOOL)`. The agent-facing tool is
   **`qs_build_linked_surface` on FEAT-558 `QuerysourceToolkit`**: tenant
   gate first (`SlugCatalog.get_allowed(slug, tenant=)`, made tenant-aware
   over QuerySource's `DefinitionRepository`), extended `describe_slug`
   (`PlaceholderInfo` + `required`/`accepts_keywords` via
   `querysource.queries.describe.build_variables`) → `params`,
   `build_conditions(..., forced=forced_conditions)` → `conditions` with
   forced keys → `locked` and `@`-values rejected, **one mandatory
   execution** through the Python executor, then the pure builder.
3. **Python executor + ui_surfaces integration.** `linked/executor.py`
   fetches each source through `QuerySlugSource(slug, tenant=)` →
   `QS(..., tenant=)` (or `MultiQS` when `is_multiquery`), applies the DSL over
   a `pandas.DataFrame` (`linked/dsl.py`), writes `dataModel[target]`, stamps
   `snapshot_at`. Wired into `UISurfacesHandler._refresh` next to
   `RecipeRunner` and into the save path (`_pin_save`, `publish_surface`) to
   produce the snapshot when a linked envelope arrives without one; `GET`
   lanes never execute; `refreshable = recipe_name is not None or
   has_data_sources`. Trust model (revised for QuerySource 5.1.1 / FEAT-150):
   credentials stay trusted-service, but every owner-context lane passes
   `principal=to_qs_principal(owner_pctx)` so QuerySource evaluates the same
   slug PBAC as its HTTP API **in-process**; ai-parrot's
   `AuthorizingDataSource` guard remains mandatory (defense in depth —
   QuerySource's PBAC is a no-op when its bootstrap is absent).
   `QueryAccessDenied` (with a principal, "missing" and "denied" collapse)
   maps to 404 like `TenantError.error_code` (404/503) before the generic
   502.
4. **Published contract + bundled UI lane + `ref` transforms.** JSON Schema
   and golden fixtures under `tests/outputs/a2ui/golden/linked/`; a static,
   anonymous `/static/a2ui/transforms/<name>@<version>.js` route with an
   HMAC-signed `manifest.json` (`name@version` → SRI integrity, `deprecated`
   flag) served from `STATIC_DIR`; the bundled `ai-parrot-server/ui`
   implements **its own** executor lane (QuerySource client with bearer, DSL,
   refresh scheduler with 30 s clamp and `visibilitychange` pause, `ref`
   loader with SRI check, share-denied degradation) and a `FilterBar` branch
   honouring `parrot_param`.

Decisions carried verbatim from the brainstorm and applied here:
descriptor lives in `metadata.extensions.parrot_data_sources` (G4 of FEAT-470:
`parrot_*` keys, `a2ui_` reserved); refresh policy `on_mount` default,
`manual`/`interval` optional, `interval_seconds >= 30`, paused while hidden;
`locked` is a UX hint only; snapshot optional in chat, mandatory once
persisted (save path executes once, owner context); share-token viewers denied
by QuerySource keep the last snapshot with a "data as of `snapshot_at`" notice
and a server-side refresh button; UDF keywords (`TODAY`, `YESTERDAY`, `FDOM`,
`LDOM`, `CURRENT_YEAR`, `CURRENT_MONTH`, `LAST_YEAR`) as condition values;
never raw SQL on the wire; QuerySource floor `>=5.1.1` (revised 2026-09-25:
5.1.1 shipped the FEAT-151 tenant-MultiQuery dispatch and FEAT-150
`principal=`, so the 5.0.0 floor + runtime `>=5.1.0` gate design is dropped).

### Component Diagram

```
 LLM (agent turn)
   │ qs_list_slugs / qs_describe_slug / qs_execute_slug        (FEAT-558, existing)
   │ qs_build_linked_surface(slug, tenant?, request, component, snapshot)   [M7]
   ▼
 QuerysourceToolkit.build_linked_surface ──► SlugCatalog.get_allowed(slug, tenant)  [M7, tenant-aware via DefinitionRepository]
   │   describe_slug(+required/accepts_keywords) ─► params
   │   build_conditions(forced=…) ─► conditions, locked ; reject '@' values
   ▼
 linked.executor.execute_sources ──► QuerySlugSource(slug, tenant=, principal=) ─► QS / MultiQS (tenant=, principal=)   [M5, M6]
   │                                    └─► linked.dsl.apply_transform(frame, ops|ref)          [M2]
   ▼  frames (+ optional ≤500-row snapshot)
 builders.build_linked_surface ──► validate axes vs frames ─► CreateSurface(origin=TOOL,
   │                                metadata.extensions.parrot_data_sources=…)   [M4]
   ▼
 catalog.validate_envelope  ── per-component pass (existing) + SURFACE pass [M3]
   │                            (targets, locked⊆params, join/union refs, ref∈manifest [M9], origin gate)
   ▼
 a2ui_envelope ──► chat renderer (bundled UI lane [M11] / navigator-frontend-next)
   │                 fetch POST /api/v3/queries/{slug} | /api/v1/{tenant}/queries/{slug} (viewer JWT)
   │                 dsl.ts · scheduler (30s clamp) · ref loader (SRI) · FilterBar parrot_param [M10]
   └──► ui_surfaces (FEAT-492) [M8]: save → snapshot if missing (owner ctx) ; POST …/refresh → executor ; GET never executes
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/outputs/a2ui/builders.py` `build_surface` (L69) | extends | `surface_metadata: SurfaceMetadata \| None` parameter; new `build_linked_surface` |
| `parrot/outputs/a2ui/catalog/__init__.py` `validate_envelope` (L499) | extends | surface-level pass after the component loop; new error codes in `catalog/base.py` |
| `parrot/outputs/a2ui/models.py` `CreateSurface.metadata` (L470) | uses | already exists; no model change |
| `parrot/outputs/a2ui/baking.py` `bake_envelope` (L356) | none | a snapshot makes every binding resolvable; callers guarantee snapshot before `GET`/HTML |
| `parrot/outputs/a2ui/catalog/parrot/filterbar.py` `FilterBarComponent` (L104) | extends | filters may carry `metadata.extensions.parrot_param = {source, name}`; lowering passes it through |
| `parrot/tools/dataset_manager/sources/query_slug.py` `QuerySlugSource` (L36), `MultiQuerySlugSource` (L165) | extends | `tenant=` / `is_multiquery=` / `principal=` (+ optional `definition=` preload) pass-through to `QS`/`MultiQS`; `to_qs_principal(pctx)` mapper |
| `parrot_tools/querysource/toolkit.py` `QuerysourceToolkit` (L59) | extends | `build_linked_surface` tool; `tenant` on `describe_slug`/`execute_slug`/`list_slugs` |
| `parrot_tools/querysource/catalog.py` `SlugCatalog` (L131), `TenantGuard` (L97) | modifies | lookups over `DefinitionRepository` + `QueryIdentity`; guard unchanged (runtime `program_slug` == schema) |
| `parrot_tools/querysource/models.py` `PlaceholderInfo` (L24) | extends | `required: bool`, `accepts_keywords: bool` |
| `parrot_tools/querysource/dialect.py` (`build_conditions` L165, `check_version_compatibility` L195) | uses / extends | `@`-value rejection helper (no version gate — floor `>=5.1.1` covers tenant MultiQuery) |
| `packages/ai-parrot-tools/pyproject.toml` L77 | modifies | `querysource>=5.1.1` |
| `handlers/models/ui_surfaces.py` `UISurfaceRecord.refreshable` (L84) | modifies | `recipe_name is not None or has_data_sources(envelope)` |
| `handlers/ui_surfaces.py` `_refresh` (L577), `_pin_save` (L491), `post` (L385) | extends | descriptor refresh path; save-time snapshot; `TenantError` mapping; `GET` untouched |
| `parrot_tools/ui_surfaces.py` `PublishSurfaceTool` (L149) | modifies | `refreshable` from the record |
| `bots/mixins/infographic_authoring.py` `publish_surface` (L440) | extends | produce snapshot when missing |
| `handlers/infographic_render.py` `STATIC_DIR` precedent (L633-663) | reuses | `/static/a2ui/transforms/` served by the existing `add_static("/static/", …)` route |
| `ui/…/a2ui/a2ui-types.ts` `CreateSurface` (L63), `A2UISurface.svelte`, `A2UINode.svelte` (L35), `lib/api/auth-headers.ts` | extends / new | bundled UI executor lane |
| `tests/outputs/a2ui/conformance/test_all_emitters.py` `_assert_conformant` (L115) | extends | register `build_linked_surface` |
| QuerySource 5.1.1 (FEAT-147 tenants, FEAT-148 describe, FEAT-151 tenant MultiQuery dispatch + `definition=`, FEAT-150 `principal=`) | depends on | released; the floor — no runtime version gate |

### Data Models

```python
# parrot/outputs/a2ui/linked/models.py  (new) — Pydantic v2, extra="forbid" everywhere
class ParamSpec(BaseModel):
    type: str | None = None              # canonical QuerySource type (date, integer, string, …)
    default: Any = None
    required: bool = False
    editable: bool = True
    accepts_keywords: bool = False

class SourceRequest(BaseModel):          # the CANONICAL condition representation (S5); editable by a FilterBar
    placeholders: dict[str, Any] = {}
    filter: dict[str, Any] = {}
    fields: list[str] = []
    ordering: list[str] = []
    grouping: list[str] = []
    limit: int | None = None
    offset: int | None = None             # `refresh`/`querylimit` are never stored: lane-time additions

class RefreshPolicy(BaseModel):
    policy: Literal["on_mount", "manual", "interval"] = "on_mount"
    interval_seconds: int | None = None   # validator: >= 30 when policy == "interval"

class TransformRef(BaseModel):
    name: str                             # opaque manifest id "<name>@<semver>" — NEVER a URL (S6); the renderer resolves
    integrity: str                        # the URL from ITS OWN transforms base + manifest; "sha384-…" SRI pin

# ten ops: Select, Rename, Filter, GroupBy(sum|avg|count|min|max), Sort, Limit, Derive(arith only),
#          Pivot, Join(inner|left, equality keys, null never matches, prefix on collision, `with`: sibling key),
#          Union(sources: [sibling keys], by matching columns)
TransformOp = Annotated[Select | Rename | Filter | GroupBy | Sort | Limit | Derive | Pivot | Join | Union,
                        Field(discriminator="op")]

class TransformSpec(BaseModel):          # exactly one of ops / ref
    ops: list[TransformOp] | None = None
    ref: TransformRef | None = None

class LinkedDataSource(BaseModel):
    kind: Literal["query_slug"] = "query_slug"
    slug: str
    tenant: str | None = None             # QuerySource store schema; None = public/legacy
    is_multiquery: bool = False
    multi_output: str | None = None       # MultiQuery only: frame name to bind; None = "result" / the single frame (S4)
    conditions: dict[str, Any]            # DERIVED cache of `request` (+ locked values): what the renderer POSTs; must equal
                                          # derive_conditions(request, locked=…) — checked by validation (S5)
    request: SourceRequest
    params: dict[str, ParamSpec] = {}
    locked: list[str] = []                # ⊆ params; UX hint only
    transform: TransformSpec | None = None
    target: str                           # absolute JSON pointer, e.g. "/activity/rows"
    snapshot_at: datetime | None = None
    snapshot_truncated: bool = False
    refresh: RefreshPolicy = RefreshPolicy()

LinkedSources = RootModel[dict[str, LinkedDataSource]]   # the value of extensions["parrot_data_sources"]
```

```python
# parrot/outputs/a2ui/linked/conditions.py (new) — pure, fixture-pinned (S5)
def derive_conditions(request: SourceRequest, *, locked: Mapping[str, Any]) -> dict[str, Any]:
    """placeholders ∪ locked (locked wins) + filter entries + fields/ordering/grouping/limit/offset in the QuerySource
    dialect; deterministic key order; never adds querylimit/refresh. Every executor re-implements this from
    contract/fixtures/conditions/*.json."""

# parrot/outputs/a2ui/linked/executor.py (new)
class SourceOutcome(BaseModel):
    key: str; rows: list[dict[str, Any]] | None; snapshot_at: datetime | None
    truncated: bool = False; error: str | None = None; ignored_params: list[str] = []

class ExecutionOutcome(BaseModel):
    outcomes: dict[str, SourceOutcome]
    def data_model_patch(self) -> dict[str, Any]: ...   # {root_key: {"rows": [...]}} for successful sources only
```

### New Public Interfaces

```python
from parrot.outputs.a2ui.linked import (LinkedDataSource, LinkedSources, TransformSpec, export_json_schema,
                                        apply_transform, derive_conditions, execute_sources, has_data_sources,
                                        LinkedSurfaceService)
from parrot.outputs.a2ui.builders import build_linked_surface          # + build_surface(surface_metadata=…)
from parrot_tools.querysource import QuerysourceToolkit                # gains build_linked_surface (qs_build_linked_surface)
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Descriptor & DSL models + JSON Schema + `derive_conditions` | yes | field list above; `extra="forbid"`; discriminated union on `op`; `interval_seconds >= 30`; `export_json_schema()` writes `linked/contract/schema.json`; `derive_conditions` rules fixed in §7 | — |
| M2: DSL executor (pandas) | yes | `apply_transform(frame, spec, *, frames)`; pure; `TransformError(source_key, op_index, message)`; semantics fixed in §7 | — |
| M3: Surface-level validation + origin gate | yes | pass appended to `validate_envelope` after the component loop; codes `DATA_SOURCES_NOT_ALLOWED_FOR_LLM`, `DATA_SOURCE_INVALID`, `TRANSFORM_REF_UNKNOWN`; issues collected, raised together as today | — |
| M4: Builders | yes | `build_surface(..., surface_metadata=None)`; `build_linked_surface(...)` signature fixed below; axis validation rules in §7 | — |
| M5: Python executor + `LinkedSurfaceService` | yes | `execute_sources(...)` and service contracts below; `querylimit = max_fetch_rows`; `to_thread` for pandas; fail-closed guard rule; `TenantError` mapping table in §7 | — |
| M6: `QuerySlugSource` tenant pass-through | yes | keyword-only `tenant`, `is_multiquery`; `MultiQS` via `_get_multiqs()` mirror of `_get_qs()` | — |
| M7: FEAT-558 toolkit changes | yes (resolved 2026-09-25) | `SlugCatalog` obtains the repository via the `QuerySource()` singleton accessor `get_definition_repository()` (`interfaces/connections.py:439-454`) — connection ownership stays inside querysource; `TenantQueryHandler._prepare` (`handlers/tenant.py:198-212`) is the reference read-once pattern, and the loaded definition MAY be forwarded as `QS/MultiQS(definition=)` to skip the second lookup | — |
| M8: ui_surfaces integration | yes | all four call sites delegate to `LinkedSurfaceService`; recipe-first dispatch; `refreshable` rule; `update_envelope(expected_updated_at=)` → 409 | — |
| M9: `ref` transforms static route + signed manifest | yes | opaque `name@version` ids; file layout, manifest JSON shape and HMAC rule fixed in §7 | — |
| M10: FilterBar `parrot_param` | yes | schema extension + lowering pass-through only | — |
| M11: Bundled UI executor lane | **no** | Svelte state design for a stateful `A2UISurface` and the scheduler's lifecycle need the thinking model; the DSL port itself (dsl.ts) is eligible once fixtures exist | — |
| M12: Contract package data (schema + fixtures) + conformance + tests | yes | `linked/contract/` layout fixed below; mandatory fixture cases listed in §4 | — |
| M13: Docs | yes | sections listed in §7 | — |

### Module 1: Descriptor & DSL models + JSON Schema + `derive_conditions`
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/linked/__init__.py`, `linked/models.py`, `linked/schema.py`, `linked/conditions.py` (new)
- **Responsibility**: the wire contract of `parrot_data_sources` and the transform DSL; the canonical `request → conditions` derivation (S5); JSON Schema export used by the conformance suite and published for renderers.
- **Depends on**: `parrot.outputs.a2ui.models` (`SurfaceMetadata`, `Extensions`)
- **Interface Skeleton**:
  ```python
  # parrot/outputs/a2ui/linked/models.py  (new)
  class LinkedDataSource(BaseModel):
      """One data source of a linked surface (spec §2 Data Models). extra='forbid'."""
      # fields as in §2; validators: target is an absolute pointer; locked ⊆ params; TransformRef.name matches
      # ^[a-z0-9_-]+@\d+\.\d+\.\d+$ (never a URL). request → conditions equality is checked by M3 (surface pass).

  class LinkedSources(RootModel[dict[str, LinkedDataSource]]):
      """Value of createSurface.metadata.extensions['parrot_data_sources']; keys are dataModel root keys."""

  class RefreshPolicy(BaseModel):
      """policy on_mount|manual|interval; interval_seconds >= 30 when interval."""

  class TransformSpec(BaseModel):
      """Exactly one of `ops` (inline) or `ref` (catalogued module)."""

  # parrot/outputs/a2ui/linked/conditions.py  (new)
  def derive_conditions(request: SourceRequest, *, locked: Mapping[str, Any]) -> dict[str, Any]:
      """Canonical, deterministic request → QuerySource payload (rules in §7). Pinned by
      contract/fixtures/conditions/*.json; the toolkit asserts build_conditions(...) minus its lane-time keys
      (querylimit, refresh) equals this output (S5)."""

  # parrot/outputs/a2ui/linked/schema.py  (new)
  def export_json_schema() -> dict[str, Any]:
      """JSON Schema (draft 2020-12) of LinkedSources, deterministic key order; written to
      parrot/outputs/a2ui/linked/contract/schema.json (package data, S7) and asserted byte-equal by a test."""

  # parrot/outputs/a2ui/linked/__init__.py  (new)
  def has_data_sources(envelope: "CreateSurface | dict[str, Any]") -> bool:
      """True when metadata.extensions.parrot_data_sources is a non-empty mapping."""
  ```

### Module 2: DSL executor (pandas)
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/linked/dsl.py` (new)
- **Responsibility**: apply a `TransformSpec.ops` list to a DataFrame; `join`/`union` pull sibling frames. Pure; no I/O; `ref` transforms are never executed in Python (they are TypeScript; the executor **skips** a `ref` transform and reports it).
- **Depends on**: M1
- **Interface Skeleton**:
  ```python
  # parrot/outputs/a2ui/linked/dsl.py  (new)
  class TransformError(Exception):
      """Raised for a missing column, type mismatch in derive, absent join key; carries source_key and op_index."""

  def apply_transform(frame: "pd.DataFrame", spec: TransformSpec | None, *,
                      frames: Mapping[str, "pd.DataFrame"]) -> "pd.DataFrame":
      """Apply spec.ops in order. `frames` maps sibling source keys to their ALREADY-executed frames
      (join.with / union.sources). Returns a new frame; never mutates inputs. A spec with `ref` returns
      `frame` unchanged (ref is renderer-side) and the caller records `transform_skipped: ref`."""
  ```

### Module 3: Surface-level validation + origin gate
- **Path**: modifies `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py:499` (`validate_envelope`), `catalog/base.py:82-86` (error codes)
- **Responsibility**: the first surface-level rule loop in `validate_envelope`; the LLM-origin gate mirroring D10b (`catalog/__init__.py:617-632`) and the inline-data gate (L646-661).
- **Depends on**: M1, M9 (manifest lookup for `transform.ref`)
- **Interface Skeleton**:
  ```python
  # parrot/outputs/a2ui/catalog/base.py  (modifies catalog/base.py:82-86 — append after TOOL_ONLY_NOT_ALLOWED_FOR_LLM)
  DATA_SOURCES_NOT_ALLOWED_FOR_LLM = "DATA_SOURCES_NOT_ALLOWED_FOR_LLM"   # origin is LLM and parrot_data_sources present
  DATA_SOURCE_INVALID = "DATA_SOURCE_INVALID"                             # model parse error, target unbound, locked ⊄ params, bad sibling ref
  TRANSFORM_REF_UNKNOWN = "TRANSFORM_REF_UNKNOWN"                         # ref not in manifest (or manifest unavailable)

  # parrot/outputs/a2ui/catalog/__init__.py  (modifies validate_envelope, catalog/__init__.py:499)
  def _validate_linked_sources(envelope: CreateSurface, *, origin: ProducerOrigin,
                               issues: list[ValidationIssue]) -> None:   # ValidationIssue verified: catalog/base.py
      """Surface-level pass: parse extensions['parrot_data_sources'] with LinkedSources; every target's root key
      must exist in dataModel OR be referenced by ≥1 binding; locked ⊆ params; join.with/union.sources name other
      keys of the same surface; kind == 'query_slug'; conditions == derive_conditions(request, locked=locked values)
      (S5); ref.name ∈ manifest (S6); origin LLM ⇒ DATA_SOURCES_NOT_ALLOWED_FOR_LLM. Appends issues; never raises."""
  ```

### Module 4: Builders
- **Path**: modifies `packages/ai-parrot/src/parrot/outputs/a2ui/builders.py:69` (`build_surface`); adds `build_linked_surface`
- **Responsibility**: pure envelope construction from components + sources + fetched frames; TOOL origin; axis validation.
- **Depends on**: M1, M3
- **Interface Skeleton**:
  ```python
  # parrot/outputs/a2ui/builders.py  (modifies builders.py:69-112)
  def build_surface(component: str, properties: dict[str, Any], *, surface_id: str, component_id: str = "root",
                    data_model: dict[str, Any] | None = None, origin: ProducerOrigin = ProducerOrigin.LLM,
                    metadata: ComponentMetadata | None = None,
                    surface_metadata: SurfaceMetadata | None = None) -> CreateSurface:   # verified: builders.py:69-76
      """Unchanged behaviour; when surface_metadata is given it is set on CreateSurface.metadata (today only the
      root component's metadata is set, builders.py:101-107)."""

  def build_linked_surface(components: Sequence[dict[str, Any]], sources: Mapping[str, LinkedDataSource],
                           frames: Mapping[str, "pd.DataFrame"], *, surface_id: str, snapshot: bool = True,
                           max_snapshot_rows: int = 500, catalog_id: str = DEFAULT_CATALOG_ID) -> CreateSurface:
      """Build a TOOL-origin CreateSurface whose metadata.extensions['parrot_data_sources'] = sources. For every
      component prop among x / y / columns / value bound to /<key>/rows, the named columns must exist in
      frames[key] (dtype rules §7). When snapshot: dataModel[key] = {'rows': frames[key].head(max_snapshot_rows)
      records}, snapshot_at stamped, snapshot_truncated set; else dataModel[key] = {'rows': []} and snapshot_at=None,
      so EVERY binding still resolves (bake_envelope never raises) and renderers show a loading state (S9).
      Raises ValueError with the offending prop/column. Calls validate_envelope(origin=TOOL) (builders.py:112)."""
  ```

### Module 5: Python executor + `LinkedSurfaceService`
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/linked/executor.py`, `linked/service.py` (new)
- **Responsibility**: fetch + transform every source of a surface; tenant-aware; per-source failure isolation; `TenantError` mapping; **one** service (S1) that every persistence/refresh call site delegates to, enforcing provenance and the fail-closed guard (S2).
- **Depends on**: M1, M2, M6
- **Interface Skeleton**:
  ```python
  # parrot/outputs/a2ui/linked/executor.py  (new)
  async def execute_sources(sources: Mapping[str, LinkedDataSource], *, param_overrides: Mapping[str, Mapping[str, Any]] | None = None,
                            pctx: "PermissionContext | None" = None, guard: "Any | None" = None,
                            max_snapshot_rows: int | None = None, max_fetch_rows: int = 5000) -> ExecutionOutcome:
      """For each source (join/union dependencies first): conditions = derive_conditions(request, locked) merged with
      overrides (locked keys ignored → ignored_params) + {'querylimit': max_fetch_rows} (S8: QuerySource caps the fetch
      itself); principal = to_qs_principal(pctx) when pctx is not None (mapped ONCE, channel='ui_surfaces'); fetch via
      QuerySlugSource(slug, tenant=source.tenant, is_multiquery=source.is_multiquery,
      multi_output=source.multi_output, principal=principal) wrapped in AuthorizingDataSource when guard is given
      (sources/authorizing.py:41); apply_transform runs in asyncio.to_thread (S8); records. A failing source yields
      SourceOutcome(error=…) and does not fail the others. Never raises for data errors; raises only for programming
      errors."""

  def map_query_error(exc: BaseException) -> tuple[int, str]:
      """querysource QueryAccessDenied → (404, 'query_not_found') (FEAT-150: with a principal, missing and denied
      collapse; exceptions.py:63 carries code 404, generic message — never surface 'denied');
      TenantError.error_code → (404, 'tenant_not_available'|'query_not_found') | (503, 'tenant_store_unavailable');
      anything else → (502, 'data_stage')."""

  # parrot/outputs/a2ui/linked/service.py  (new) — the ONE entry point for save / publish / refresh (S1)
  class LinkedGuardRequired(Exception):
      """Raised (→ HTTP 403) when a linked envelope reaches persistence and no data-plane guard is configured."""

  class LinkedSurfaceService:
      def __init__(self, *, guard: "Any | None", max_fetch_rows: int = 5000, max_snapshot_rows: int = 500) -> None: ...
      async def validate_for_persistence(self, envelope: CreateSurface, *, owner_pctx: "PermissionContext") -> None:
          """validate_envelope(envelope, origin=ProducerOrigin.TOOL) structurally (catalog/__init__.py:499); when
          has_data_sources: REQUIRE self.guard (else LinkedGuardRequired — fail CLOSED, unlike RecipeRunner's fail-open
          runner.py:262-264) and assert the owner's `slug:execute` on every (tenant, slug) through the guard (S2)."""
      async def ensure_snapshot(self, envelope: dict[str, Any], *, owner_pctx: "PermissionContext") -> dict[str, Any]:
          """When has_data_sources and any target lacks rows or snapshot_at: execute_sources once (owner ctx), patch
          dataModel + snapshot_at; a failed run raises SnapshotError(status, code) via map_query_error — nothing persists."""
      async def refresh(self, envelope: dict[str, Any], *, params: Mapping[str, Any], owner_pctx: "PermissionContext") -> "RefreshOutcome":
          """execute_sources with per-source param overrides; returns the patched envelope, warnings and the new
          snapshot_at; the caller persists with update_envelope(expected_updated_at=…) (S11)."""
  ```

### Module 6: `QuerySlugSource` tenant + principal pass-through
- **Path**: modifies `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/query_slug.py:36-162` and `:165-260`
- **Responsibility**: carry `tenant` and `principal` to `QS(..., tenant=, principal=)`; dispatch `MultiQS` for `is_multiquery`; map `PermissionContext` → `QSPrincipal` (FEAT-150's prescribed ai-parrot follow-up).
- **Depends on**: —
- **Interface Skeleton**:
  ```python
  # parrot/tools/dataset_manager/sources/query_slug.py  (modifies query_slug.py:51-56, :110, :151, :175)
  class QuerySlugSource(DataSource):   # verified: query_slug.py:36
      def __init__(self, slug: str, prefetch_schema_enabled: bool = True,
                   permanent_filter: Optional[Dict[str, Any]] = None, *,
                   tenant: str | None = None, is_multiquery: bool = False, multi_output: str | None = None,
                   principal: "QSPrincipal | None" = None, definition: "LoadedDefinition | None" = None) -> None:
          """tenant/principal/definition → QS/MultiQS keyword-only kwargs (querysource 5.1.1 qs.py:56-68,
          multi/__init__.py:106-121; `residual=` exists on QS but is never passed).
          With a principal, QuerySource enforces slug PBAC in-process BEFORE store resolution and raises
          QueryAccessDenied (qs.py:215-250); MultiQS pre-checks every stored child. definition= (optional,
          FEAT-151) skips the second DefinitionRepository lookup when the caller already holds the
          LoadedDefinition (tenants.py:54). is_multiquery selects MultiQS, whose DataFrame | dict[str, DataFrame]
          output is normalised to ONE frame: the one named multi_output, else 'result', else the single frame
          (results.py:77-79 precedent) (S4). cache_key gains ':t=<tenant>' when tenant is set (query_slug.py:67-80);
          the principal is NEVER part of the cache_key (identical rows either way — PBAC gates execution, not
          content). fetch() closes the QS/MultiQS instance in a `finally` (toolkit.py:231 precedent; today it never
          closes, query_slug.py:151-162) (S8)."""

  def to_qs_principal(pctx: "PermissionContext", *, channel: str = "ui_surfaces") -> "QSPrincipal":
      """Map parrot.auth.permission.PermissionContext → querysource.auth.principal.QSPrincipal
      (principal.py:21: user_id, username, groups, roles, programs, superuser, tenant_id, channel).
      tenant_id is informational only (logs — it never selects a store; the descriptor's `tenant` does, AC4).
      Lazy import mirroring _get_qs(); field mapping verified against permission.py:81 at task time."""

  def _get_multiqs():
      """Lazy import of querysource.queries.multi.MultiQS, mirroring _get_qs() (query_slug.py:23)."""
  ```

### Module 7: FEAT-558 toolkit changes
- **Path**: modifies `packages/ai-parrot-tools/src/parrot_tools/querysource/{toolkit,catalog,models,dialect,errors,__init__}.py`, `packages/ai-parrot-tools/pyproject.toml:77`
- **Responsibility**: tenant-aware catalog; extended describe; the agent tool; `@`-rejection; floor bump to `>=5.1.1` (no runtime version gate).
- **Depends on**: M1, M4, M5, M6
- **Interface Skeleton**:
  ```python
  # parrot_tools/querysource/models.py  (modifies models.py:24-29)
  class PlaceholderInfo(BaseModel):
      name: str; type: str | None = None; default: Any = None
      required: bool = False          # NEW — from querysource.queries.describe.build_variables (describe.py:154)
      accepts_keywords: bool = False  # NEW — type ∈ KEYWORD_TYPES or raw_type is None (describe.py:163)

  # parrot_tools/querysource/catalog.py  (modifies catalog.py:131-187)
  class SlugCatalog:   # verified: catalog.py:131
      async def get(self, slug: str, *, tenant: str | None = None) -> SlugRecord:
          """Resolve through querysource's DefinitionRepository: store = registry.resolve(tenant)
          (tenants.py:402-425), rec = await repo.get(QueryIdentity(store, slug)) (definitions.py:161).
          SlugRecord.program_slug = the runtime program_slug (== schema for tenant stores, definitions.py:111-119).
          TenantError(query_not_found|tenant_not_available) → SlugNotFoundError."""
      async def get_allowed(self, slug: str, *, tenant: str | None = None) -> SlugRecord:   # verified: catalog.py:161
          """get() then guard.assert_allowed() — unchanged rule, now tenant-aware."""
      async def list(self, *, search: str | None, program: str | None, limit: int,
                     tenant: str | None = None) -> list[SlugRecord]:   # verified: catalog.py:167
          """tenant=None: existing QueryModel path over public.queries; tenant set: repo.list(store, params) (definitions.py:175)."""

  # parrot_tools/querysource/dialect.py  (modifies dialect.py — add after check_version_compatibility L195)
  def reject_variable_values(conditions: Mapping[str, Any]) -> None:
      """Raise InvalidConditionsError when any scalar value starts with '@' (FEAT-558 deployment variables are not
      portable on the linked-surface wire)."""
  # NOTE (2026-09-25): no supports_tenant_multiquery() and no TenantMultiQueryUnsupportedError — the pyproject
  # floor `querysource>=5.1.1` guarantees the tenant {slug} route dispatches MultiQS (handlers/tenant.py:194-212);
  # check_version_compatibility (L195, existing) enforces the floor as before.

  # parrot_tools/querysource/toolkit.py  (modifies toolkit.py:3, :152-200; adds one tool)
  class QuerysourceToolkit(AbstractToolkit):   # verified: toolkit.py:59
      async def list_slugs(self, search: str | None = None, program: str | None = None, limit: int = 50,
                           tenant: str | None = None) -> list[SlugSummary]: ...          # verified: toolkit.py:152
      async def describe_slug(self, slug: str, dry_run: bool = False, tenant: str | None = None) -> SlugDetail:
          """placeholders_detail now carries required/accepts_keywords via build_variables(rec.query_raw, rec.conditions,
          rec.cond_definition) (querysource/queries/describe.py:108-111)."""                # verified: toolkit.py:160
      async def execute_slug(self, slug: str, placeholders=None, filter=None, fields=None, ordering=None, grouping=None,
                             limit=None, offset=None, refresh=False, tenant: str | None = None) -> ExecutionResult:
          """QS(slug=slug, conditions=conditions, tenant=tenant); MultiQS when rec.is_multiquery."""   # verified: toolkit.py:190
      async def build_linked_surface(self, slug: str, component: dict[str, Any], request: dict[str, Any] | None = None,
                                     tenant: str | None = None, snapshot: bool = True, surface_id: str | None = None,
                                     target_key: str | None = None, refresh: dict[str, Any] | None = None,
                                     transform: dict[str, Any] | None = None) -> dict[str, Any]:
          """Emit a linked A2UI surface for a query-slug (tool name qs_build_linked_surface). Order: get_allowed(slug, tenant=)
          → describe_slug → params → validate_placeholders + build_conditions(
          forced=self.forced_conditions) → conditions; forced keys → locked; reject_variable_values → execute_sources
          (one mandatory run, uncapped) → build_linked_surface(snapshot=snapshot). Returns the FEAT-473 dual-emission
          shape: {'a2ui_envelope': …, 'artifacts': [...]}. `component` = {'component': 'Chart'|'DataTable'|'KPICard', …props}."""
  ```

### Module 8: ui_surfaces integration (server)
- **Path**: modifies `packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py:84,648`, `handlers/ui_surfaces.py:385-645`, `packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py:149,185`, `packages/ai-parrot/src/parrot/bots/mixins/infographic_authoring.py:440,501`
- **Responsibility**: every persistence/refresh call site delegates to `LinkedSurfaceService` (S1); provenance + fail-closed guard at the boundary (S2); optimistic concurrency on refresh (S11); `refreshable` widening; `GET` never executes. Every lane hands `owner_pctx` to `execute_sources`, which maps it to `QSPrincipal` (M5/M6) — QuerySource then re-evaluates the owner's slug PBAC in-process on save, publish, refresh and scheduled runs. NOTE: FEAT-150 §8 suggested passing `record.tenant` as `tenant=`; superseded by this spec's descriptor-tenant rule (AC4) — each source's `tenant` comes from `parrot_data_sources`, never from `UISurfaceRecord.tenant`.
- **Depends on**: M1, M5
- **Interface Skeleton**:
  ```python
  # handlers/models/ui_surfaces.py  (modifies ui_surfaces.py:84-86 and :648)
  @property
  def refreshable(self) -> bool:
      """recipe_name is not None or has_data_sources(self.envelope)."""   # has_data_sources verified: M1

  async def update_envelope(self, surface_id: str, envelope: dict[str, Any], recipe_params: dict[str, Any], *,
                            expected_updated_at: datetime | None = None) -> bool:   # verified: models/ui_surfaces.py:648
      """Unchanged when expected_updated_at is None. Otherwise `UPDATE … WHERE surface_id = $1 AND updated_at = $expected`;
      returns False when no row matched (a newer snapshot won the race) (S11)."""

  # handlers/ui_surfaces.py  (modifies ui_surfaces.py:546-572 save path and :577-645)
  #   _pin_save: after CreateSurface.model_validate (L546) → await service.validate_for_persistence(envelope, owner_pctx=…)
  #              → envelope_dict = await service.ensure_snapshot(…) → store.save (L572). LinkedGuardRequired → 403;
  #              SnapshotError → its status; validation issues → 422 (existing shape).
  async def _refresh(self) -> web.Response:   # verified: ui_surfaces.py:577
      """Precedence: recipe path when record.recipe_name (unchanged); else outcome = await service.refresh(record.envelope,
      params=req.params, owner_pctx=owner_pctx) (each source's tenant from the descriptor); `warnings` for partial
      failures; status from map_query_error when every source failed; ok = await store.update_envelope(...,
      expected_updated_at=record.updated_at); not ok → 409 {"error": "stale refresh", "snapshot_at": <newer>} (S11)."""

  # parrot_tools/ui_surfaces.py  (modifies ui_surfaces.py:146-150 and :185)
  #   after CreateSurface.model_validate (L185): await service.validate_for_persistence(...); ensure_snapshot(...)
  #   "refreshable": record.refreshable   (was: recipe_name is not None)

  # bots/mixins/infographic_authoring.py  (modifies infographic_authoring.py:440, :501)
  async def publish_surface(self, *, kind, title, envelope, ..., surface_store=None, user_id=None, session_id=None) -> str:
      """Unchanged signature; after model_validate (L501) delegates to LinkedSurfaceService.validate_for_persistence +
      ensure_snapshot with the caller's PermissionContext before saving."""
  ```

### Module 9: `ref` transforms static route + signed manifest
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/linked/manifest.py` (new, core: loader/verifier); `packages/ai-parrot-server/src/parrot/handlers/a2ui_transforms.py` (new: publish helper), files under `STATIC_DIR/a2ui/transforms/`
- **Responsibility**: catalogued TypeScript modules served anonymously with immutable cache headers, pinned by SRI, governed by an HMAC-signed manifest; builder-side lookup.
- **Depends on**: M1
- **Interface Skeleton**:
  ```python
  # parrot/outputs/a2ui/linked/manifest.py  (new)
  class TransformManifest(BaseModel):
      """{version: 1, entries: {"<name>@<semver>": {"file": "<name>@<semver>.js", "integrity": "sha384-…", "deprecated": bool}},
      signature: str}. No absolute URLs anywhere: a renderer joins `file` onto ITS configured transforms base (S6)."""
  def load_manifest(path: Path | None = None) -> TransformManifest | None:
      """Read STATIC_DIR/a2ui/transforms/manifest.json (parrot.conf.STATIC_DIR, infographic_render.py:649 precedent);
      verify HMAC-SHA256(canonical JSON of entries, key=os.environ['PARROT_A2UI_MANIFEST_KEY']); None when absent or
      invalid (validation then reports TRANSFORM_REF_UNKNOWN)."""
  def resolve_ref(name: str, manifest: TransformManifest) -> TransformRef:
      """Return TransformRef(name, integrity) for an opaque "<name>@<semver>" id; raises KeyError when missing; logs a
      warning when deprecated. The descriptor never carries a URL (S6)."""

  # parrot/handlers/a2ui_transforms.py  (new, server)
  def publish_transforms(source_dir: Path, *, key: str) -> TransformManifest:
      """Copy <name>@<version>.js into STATIC_DIR/a2ui/transforms/, compute SRI, write + sign manifest.json;
      never deletes existing versions (retirement = deprecated: true)."""
  ```

### Module 10: FilterBar `parrot_param`
- **Path**: modifies `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/filterbar.py:29-61` (`FILTERBAR_SCHEMA`), `:104-129` (`FilterBarComponent.lower`)
- **Responsibility**: a filter may declare `metadata.extensions.parrot_param = {"source": "<key>", "name": "<param>"}`; lowering keeps it on the `ChoicePicker` (next to `parrot_filter_column`).
- **Depends on**: —
- **Interface Skeleton**:
  ```python
  # parrot/outputs/a2ui/catalog/parrot/filterbar.py  (modifies filterbar.py:29-61 and :110)
  # FILTERBAR_SCHEMA.filters[*] gains optional "param": {"source": str, "name": str}
  class FilterBarComponent:   # verified: filterbar.py:104
      def lower(self, ...):   # verified: filterbar.py:110
          """Unchanged Row(parrot_variant='filter-bar') of ChoicePicker; when a filter has `param`, the ChoicePicker's
          metadata.extensions gains parrot_param = {source, name} in addition to parrot_filter_column."""
  ```

### Module 11: Bundled UI executor lane
- **Path**: `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/{types.ts,dsl.ts,fetch.ts,scheduler.ts,ref.ts,index.ts}` (new), `lib/api/querysource.ts` (new), modifies `a2ui-types.ts:63-68`, `A2UISurface.svelte`, `A2UINode.svelte:35`
- **Responsibility**: the bundled renderer's own executor (one renderer among others, not a reference).
- **Depends on**: M1 (schema), M12 (fixtures)
- **Interface Skeleton**:
  ```typescript
  // a2ui-types.ts  (modifies a2ui-types.ts:63-68)
  export interface CreateSurface { surfaceId: string; catalogId?: string; components: WireComponent[];
    dataModel?: Record<string, unknown>; metadata?: { extensions?: Record<string, unknown> }; }   // metadata NEW

  // linked/types.ts (new) — mirrors the JSON Schema of LinkedSources (generated by `pnpm generate` from schemas/)
  // linked/fetch.ts (new)
  export async function fetchSource(src: LinkedDataSource, conditions: Record<string, unknown>,
                                    opts: { baseUrl: string; headers: HeadersInit }): Promise<Row[]>;
  // POST `${baseUrl}/api/v3/queries/${slug}` or `${baseUrl}/api/v1/${tenant}/queries/${slug}` when src.tenant;
  // 404 ⇒ SourceUnavailable (never "denied"); `refresh` sent as boolean true only.
  // linked/dsl.ts (new)
  export function applyTransform(rows: Row[], spec: TransformSpec | undefined, frames: Record<string, Row[]>): Row[];
  // linked/scheduler.ts (new)
  export class RefreshScheduler { constructor(policy: RefreshPolicy, run: () => Promise<void>); start(): void; stop(): void; }
  // clamps interval to >= 30 s; pauses on document.hidden; immediate run on resume.
  // linked/ref.ts (new)
  export async function loadRef(ref: TransformRef, opts: { transformsBase: string }): Promise<((rows: Row[]) => Row[]) | null>;
  // URL = `${transformsBase}/${manifest.entries[ref.name].file}` — the descriptor's `name` is opaque, never a URL (S6);
  // dynamic import with SRI check (`integrity` on a <script type="module"> or fetch+hash); null on mismatch/unknown.
  // CSP for module execution is the host page's responsibility and is documented in §13 docs.
  // A2UISurface.svelte — becomes stateful over dataModel; mounts the lane when extensions.parrot_data_sources exists
  // A2UINode.svelte — FilterBar branch: a filter with parrot_param re-fetches that source; others filter locally (§7.4)
  ```

### Module 12: Contract package data (schema + fixtures) + conformance + tests
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/` (new **package data**, S7: `schema.json`, `fixtures/dsl/<op>_<case>.json` `{input, frames?, ops, expected}`, `fixtures/conditions/<case>.json` `{request, locked, expected}`, `fixtures/envelopes/linked_chart.json`, `linked_dashboard_join.json`, `linked_no_snapshot.json`, `linked_multiquery_public.json`); `packages/ai-parrot/tests/outputs/a2ui/linked/` (new tests); modifies `tests/outputs/a2ui/conformance/test_all_emitters.py:115`
- **Responsibility**: the shared, *installable* contract every executor must pass: Python tests parametrise over the package directory; the bundled UI's vitest reads the same files by monorepo-relative path; `pip install ai-parrot` ships them to third-party renderer teams. Mandatory cases: nulls, timezone-aware datetimes, dtype preservation, ordering stability, join collision prefixing, empty results, `multi_output` selection, gated tenant MultiQuery.
- **Depends on**: M1, M2, M4
- **Interface Skeleton**: fixtures only (no code) — see §4. Task note: verify the build backend includes `contract/**` as package data (`packages/ai-parrot/pyproject.toml`).

### Module 13: Docs
- **Path**: modifies `docs/outputs/a2ui-v1.md:150-156` (extension table), `docs/frontend/agentdashboard-a2ui-reference.md` (§6.5 new, §7.4 amended), `docs/tools/querysource-toolkit.md:33` (Tools); new `docs/outputs/a2ui-linked-surfaces.md` (wire doc incl. the `locked`-is-not-security and trust-model statements)
- **Depends on**: all
- **Interface Skeleton**: n/a (prose).

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_linked_models_roundtrip` | M1 | every field survives `model_dump(mode="json")` → `model_validate`; `extra="forbid"` rejects unknown keys |
| `test_refresh_interval_min_30` | M1 | `interval_seconds=29` fails; 30 passes; `manual` ignores it |
| `test_transform_spec_ops_xor_ref` | M1 | both or neither → ValidationError |
| `test_json_schema_export_deterministic` | M1 | two exports byte-equal; file under `docs/outputs/schemas/` matches |
| `test_dsl_golden[<fixture>]` | M2 | parametrised over `linked/contract/fixtures/dsl/*.json`: `apply_transform(input) == expected` |
| `test_derive_conditions_golden[<fixture>]` / `test_toolkit_build_conditions_matches_derive` | M1/M7 | `contract/fixtures/conditions/*.json`; `build_conditions(...)` minus `querylimit`/`refresh` equals `derive_conditions` (S5) |
| `test_validate_linked_conditions_mismatch` | M3 | `conditions ≠ derive_conditions(request)` → `DATA_SOURCE_INVALID` (S5) |
| `test_build_linked_surface_no_snapshot_bakes` | M4 | `snapshot=False` → `dataModel[key] == {"rows": []}`, `bake_envelope` succeeds, `snapshot_at is None` (S9) |
| `test_execute_sources_querylimit_bound` / `test_query_slug_source_closes_qs` / `test_apply_transform_off_loop` | M5/M6 | `querylimit == max_fetch_rows` in conditions; fake `QS.close` awaited in `finally`; `to_thread` used (S8) |
| `test_multiquery_output_selection` / `test_multiquery_single_frame` / `test_multiquery_empty_frame` | M6 | `multi_output` picks the frame; `'result'`/single fallback; empty → `rows: []` (S4) |
| `test_persist_validates_envelope` / `test_persist_requires_guard_fail_closed` / `test_persist_owner_slug_execute_denied` | M5/M8 | `validate_for_persistence` runs `validate_envelope(origin=TOOL)`; no guard → `LinkedGuardRequired` (403); owner denied on one `(tenant, slug)` → 403, nothing persisted (S2) |
| `test_refresh_conflict_409` / `test_update_envelope_expected_updated_at` | M8 | stale `expected_updated_at` → `False` → 409 with newer `snapshot_at` (S11) |
| `test_ref_name_is_opaque` / `loadRef.test.ts` | M1/M9/M11 | `TransformRef.name` rejects URLs; the UI joins `file` onto its configured base (S6) |
| `test_dsl_join_null_never_matches` / `test_dsl_join_prefix_on_collision` / `test_dsl_union_by_matching_columns` / `test_dsl_derive_rejects_non_arith` | M2 | semantics fixed in §7 |
| `test_dsl_ref_is_skipped_in_python` | M2 | `ref` spec returns frame unchanged |
| `test_validate_linked_llm_origin_rejected` | M3 | `origin=LLM` + descriptor → `DATA_SOURCES_NOT_ALLOWED_FOR_LLM` |
| `test_validate_linked_target_unbound` / `_locked_not_in_params` / `_join_with_unknown_key` / `_ref_not_in_manifest` | M3 | each → `DATA_SOURCE_INVALID` / `TRANSFORM_REF_UNKNOWN`, all issues reported together |
| `test_build_surface_surface_metadata` | M4 | `surface_metadata` lands on `CreateSurface.metadata`, root component metadata unchanged |
| `test_build_linked_surface_axis_validation` | M4 | unknown `x`, non-numeric `y` → ValueError naming prop/column |
| `test_build_linked_surface_snapshot_cap` | M4 | 501 rows → 500 embedded, `snapshot_truncated=True`; `snapshot=False` → empty roots |
| `test_build_linked_surface_golden` | M4/M12 | byte-equal to `golden/linked/envelope_linked_chart.json` (`test_components_filterbar.py:15-42` convention) |
| `test_execute_sources_tenant_passthrough` | M5/M6 | fake `QS` records `tenant=`; `is_multiquery` → fake `MultiQS` |
| `test_execute_sources_locked_override_ignored` | M5 | override of a locked key → `ignored_params` |
| `test_execute_sources_partial_failure` | M5 | one failing source does not fail siblings; `error` set |
| `test_map_query_error_tenant_codes` | M5 | `QueryAccessDenied`→404 `query_not_found` (never "denied"), `tenant_not_available`→404, `query_not_found`→404, `tenant_store_unavailable`→503, other→502 |
| `test_execute_sources_passes_principal` | M5/M6 | with `pctx`, every `QS`/`MultiQS` receives `principal=` (fake_qs asserts kwarg); `pctx=None` → no principal (trusted-service unchanged) |
| `test_to_qs_principal_mapping` | M6 | `PermissionContext` → `QSPrincipal` field-for-field; `channel='ui_surfaces'`; `tenant_id` never routes the store |
| `test_query_slug_source_cache_key_tenant` | M6 | `cache_key` differs per tenant; identical with/without principal |
| `test_placeholder_info_required_accepts_keywords` | M7 | `firstdate` never required (IMPLICIT_DEFAULTS), untyped → `accepts_keywords=True` |
| `test_catalog_get_tenant_uses_definition_repository` | M7 | fake repo asserts `QueryIdentity(store, slug)`; `program_slug == schema` |
| `test_reject_variable_values` | M7 | `{"firstdate": "@today"}` → `InvalidConditionsError` |
| `test_tenant_multiquery_builds` | M7 | `tenant="acme"`, `is_multiquery=True` → builds; `MultiQS` (not `QS`) dispatched with `tenant=` |
| `test_build_linked_surface_tool_order` | M7 | get_allowed before describe; one execution; envelope `origin=TOOL`; forced keys → `locked` |
| `test_refreshable_with_data_sources` | M8 | record without recipe but with sources → `refreshable=True` |
| `test_refresh_descriptor_path` / `test_refresh_recipe_precedence` | M8 | executor called with descriptor tenant; recipe wins when both |
| `test_save_without_snapshot_executes_once` / `test_save_failure_persists_nothing` | M8 | `_pin_save` runs executor once; 502/404 → no record |
| `test_get_never_executes` | M8 | `GET` JSON/HTML with a linked envelope never calls the executor |
| `test_publish_surface_tool_refreshable_from_record` | M8 | `PublishSurfaceTool` result mirrors `record.refreshable` |
| `test_manifest_signature_verified` / `test_manifest_deprecated_warns` / `test_resolve_ref_unknown` | M9 | HMAC mismatch → `None`; deprecated → warning + still resolves |
| `test_filterbar_param_passthrough` | M10 | lowered `ChoicePicker` carries `parrot_param`; golden updated |
| `dsl.test.ts` / `conditions.test.ts` / `scheduler.test.ts` / `fetch.test.ts` / `A2UISurface.test.ts` | M11 | TS DSL and conditions pass the same `linked/contract/fixtures/**`; 30 s clamp; 404 → snapshot kept + "unavailable"; tenant URL when `tenant` set; loading state while `snapshot_at` is null |

### Integration Tests
| Test | Description |
|---|---|
| `test_all_emitters.py::test_build_linked_surface_conformant` | `_assert_conformant(envelope, origin=TOOL)` over the linked chart, table and dashboard (two sources + join) |
| `test_linked_surface_end_to_end` | tool (fake QS) → envelope → `validate_envelope` → `bake_envelope` (snapshot makes bindings resolvable) → `_refresh` (fake executor) → updated `snapshot_at` |
| `test_linked_surface_no_snapshot_persist_roundtrip` | publish without snapshot → save executes → `GET ?format=html` renders without executing |

### Test Data / Fixtures
```python
# tests/outputs/a2ui/linked/conftest.py
@pytest.fixture
def activity_frame() -> pd.DataFrame:      # day (date), visits (int), program (str) — 12 rows
@pytest.fixture
def linked_source() -> LinkedDataSource:   # slug epson_field_activity, tenant None, request placeholders firstdate=YESTERDAY lastdate=TODAY
@pytest.fixture
def fake_qs(monkeypatch):                  # patches parrot.tools.dataset_manager.sources.query_slug._get_qs / _get_multiqs, records kwargs
@pytest.fixture
def manifest_file(tmp_path, monkeypatch):  # signed manifest with group_by_day@1.0.0 (+ a deprecated 0.9.0), PARROT_A2UI_MANIFEST_KEY set
# golden/linked/dsl/<op>_<case>.json: {"input": [...rows], "frames": {"other": [...]}?, "ops": [...], "expected": [...rows]}
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] AC1 `pytest packages/ai-parrot/tests/outputs/a2ui -v` and `pytest packages/ai-parrot-tools/tests -v` and `pytest packages/ai-parrot-server/tests -v` pass; `pnpm test` in `packages/ai-parrot-server/ui` passes.
- [ ] AC2 A `CreateSurface` with `metadata.extensions.parrot_data_sources` validates under `origin=TOOL` and fails with `DATA_SOURCES_NOT_ALLOWED_FOR_LLM` under `origin=LLM`; unbound `target`, `locked ⊄ params`, unknown `join.with`/`union.sources`, unknown `transform.ref` each produce `DATA_SOURCE_INVALID`/`TRANSFORM_REF_UNKNOWN`, reported together.
- [ ] AC3 `qs_build_linked_surface` always executes the slug once, validates axes against the fetched columns/dtypes, embeds ≤500 rows only when `snapshot=True` (`snapshot_truncated` when cut), derives `conditions` from `request`, maps `forced_conditions` keys to `locked`, rejects any `@`-prefixed value, and emits `origin=TOOL`.
- [ ] AC4 Every source carries `tenant: str | null`; the renderer lane and the Python executor both route `tenant` (URL `/api/v1/{tenant}/queries/{slug}` / `QS(..., tenant=)`); a `null` tenant runs against `public`; `tenant` is never inferred from session, JWT or `UISurfaceRecord.tenant`.
- [ ] AC5 `tenant != null ∧ is_multiquery` builds and executes through `MultiQS(tenant=)` — no runtime version gate exists anywhere (`supports_tenant_multiquery` / `TENANT_MULTIQUERY_UNSUPPORTED` are never introduced); the `querysource>=5.1.1` floor (AC12) is the only guarantee.
- [ ] AC6 `describe_slug` reports `required` and `accepts_keywords` exactly as QuerySource's `build_variables` does (static `required`, `IMPLICIT_DEFAULTS`, `or raw_type is None`); `SlugCatalog` resolves tenant slugs through `DefinitionRepository` and the `programs` allowlist applies unchanged.
- [ ] AC7 The ten DSL operations behave per §7; `derive_conditions` is deterministic; the Python executor and the bundled UI's `dsl.ts`/`conditions.ts` both pass every fixture under `parrot/outputs/a2ui/linked/contract/fixtures/` (shipped as package data, incl. the mandatory null/timezone/dtype/ordering/join-collision/empty/`multi_output` cases); `contract/schema.json` is committed and deterministic.
- [ ] AC8 `UISurfaceRecord.refreshable` is true for a surface with sources and no recipe; `POST …/refresh` runs the executor with the descriptor's tenant (recipe path wins when both exist); saving a linked envelope without a snapshot executes once with the owner's context and persists the snapshot, or answers 404/503/502 (per `map_query_error`) and persists nothing; `GET` (JSON and HTML) never executes.
- [ ] AC9 `transform.ref` resolves only against a manifest whose HMAC verifies; deprecated entries still resolve with a warning; unknown refs fail validation; the bundled UI refuses to execute a module whose SRI does not match and falls back to the snapshot.
- [ ] AC10 Bundled UI: `on_mount` fetch with the viewer's bearer, `interval` clamped to ≥30 s and paused while hidden, `manual` never auto-fetches; a 404 keeps the snapshot with an "unavailable" notice (never "denied"); `refresh` is sent as boolean `true`; a `FilterBar` filter with `parrot_param` re-fetches its source, others filter locally.
- [ ] AC11 Baked surfaces, `bake_envelope`, `lower()`, all existing golden files and the six satellite renderers are byte-for-byte unaffected (existing tests unchanged and green).
- [ ] AC12 `packages/ai-parrot-tools/pyproject.toml` declares `querysource>=5.1.1`; no new Python runtime dependency; `ruff check` (TID251) and `black --check` clean.
- [ ] AC13 Docs updated: `docs/outputs/a2ui-v1.md` extension table (`parrot_data_sources`, `parrot_param`), `docs/frontend/agentdashboard-a2ui-reference.md` §6.5 + §7.4 (Filter vs Refresh vs Reload), `docs/tools/querysource-toolkit.md` (new tool, `tenant`), new `docs/outputs/a2ui-linked-surfaces.md` stating that `locked` is not security, that server lanes run as a trusted service behind a mandatory guard, and that `ref` module CSP is the host page's responsibility.
- [ ] AC14 **Persistence boundary (S2)**: every save path (`_pin_save`, `PublishSurfaceTool`, `publish_surface`) runs `LinkedSurfaceService.validate_for_persistence` — `validate_envelope(origin=TOOL)` plus, for linked envelopes, a **configured** data-plane guard asserting the owner's `slug:execute` on every `(tenant, slug)`; no guard ⇒ 403 `LinkedGuardRequired` (fail closed); a denied source ⇒ 403 and nothing persisted.
- [ ] AC15 **Concurrency (S11)**: `store.update_envelope(..., expected_updated_at=)` is conditional; a refresh that lost the race answers 409 with the newer `snapshot_at`; no stale snapshot ever overwrites a newer one.
- [ ] AC16 **No-snapshot contract (S9)**: a `snapshot=False` envelope always carries `dataModel[key] = {"rows": []}`; `bake_envelope` succeeds; JSON/HTML/chat renderers show a loading state while `snapshot_at` is null; persisted surfaces never lack a snapshot (AC8).
- [ ] AC17 **Bounded fetch (S8)**: every executor lane sends `querylimit = max_fetch_rows` (default 5000); `QuerySlugSource.fetch` closes its `QS`/`MultiQS` in `finally`; `apply_transform` runs off the event loop; `TransformRef.name` is an opaque `name@version` id (S6) and `multi_output` selects the MultiQuery frame (S4).
- [ ] AC18 **In-process PBAC (FEAT-150)**: every owner-context lane (`_pin_save` snapshot, `PublishSurfaceTool`, `publish_surface`, `_refresh`, scheduled delivery) passes `principal=to_qs_principal(owner_pctx)` to `QS`/`MultiQS`; `QueryAccessDenied` maps to 404 `query_not_found` (renderer notice stays "unavailable", never "denied"); `pctx=None` (agent-tool lane) keeps today's trusted-service path; the `AuthorizingDataSource` guard (AC14) remains mandatory regardless — principal is additive, not a replacement.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified against `bc296148e` (dev, 2026-09-24; `origin/dev` `ccf5a2b6b` touches none of the files below).
> QuerySource references are against `../querysource` tag `5.1.1` (`989193d`), re-verified 2026-09-25
> (originally drafted against `5.0.0` `aebc55c`; 5.1.1 ships FEAT-151 tenant-MultiQuery dispatch +
> `definition=`, FEAT-150 `principal=`, FEAT-152 qsurl — the latter unused here).

### Verified Imports
```python
from parrot.outputs.a2ui.builders import build_surface, build_chart, build_kpicard, build_datatable   # builders.py:69,116,137,179
from parrot.outputs.a2ui.catalog import ProducerOrigin, validate_envelope, register_component        # catalog/__init__.py
from parrot.outputs.a2ui.catalog.base import ACTION_NOT_ALLOWED_FOR_LLM, INLINE_DATA_NOT_ALLOWED_FOR_LLM, TOOL_ONLY_NOT_ALLOWED_FOR_LLM  # catalog/base.py:78,82,86
from parrot.outputs.a2ui.models import CreateSurface, Component, ComponentMetadata, SurfaceMetadata, Extensions   # models.py:446,338-378
from parrot.outputs.a2ui.baking import bake_envelope, persist_envelope, BakeError                    # baking.py:356,46
from parrot.tools.dataset_manager.sources.query_slug import QuerySlugSource, MultiQuerySlugSource    # query_slug.py:36,165
from parrot.tools.dataset_manager.sources.authorizing import AuthorizingDataSource                   # authorizing.py:41
from parrot.tools.toolkit import AbstractToolkit                                                     # toolkit.py:206 (tool_prefix L254, exclude_tools L240)
from parrot.auth.permission import PermissionContext, build_principal_context                        # permission.py:81,166
from parrot_tools.querysource import QuerysourceToolkit, SlugDetail, ExecutionResult                 # parrot_tools/querysource/__init__.py:23
from parrot_tools.querysource.models import PlaceholderInfo                                          # models.py:24
from parrot_tools.querysource.catalog import SlugCatalog, SlugRecord, TenantGuard                    # catalog.py:131,39,97
from parrot_tools.querysource.dialect import build_conditions, validate_placeholders, load_variables, check_version_compatibility  # dialect.py:165,207,195
from parrot_tools.querysource._qs import get_qs, get_multiqs, installed_version, default_dsn        # _qs.py:33,67
from parrot_tools.querysource.errors import QuerysourceToolkitError, SlugNotFoundError, TenantDeniedError, InvalidConditionsError  # errors.py:8
from parrot_tools.ui_surfaces import PublishSurfaceTool                                              # parrot_tools/ui_surfaces.py:60
from parrot.handlers.models.ui_surfaces import UISurfaceRecord, UISurfaceKind                        # ai-parrot-server
from parrot.conf import STATIC_DIR                                                                   # infographic_render.py:649 (local import precedent)
# ../querysource >= 5.1.1
from querysource.queries.qs import QS                                                                # qs.py:50; __init__(slug, conditions, request, loop, *, tenant=None, definition=None, principal=None, residual=None) L56-68
from querysource.queries.multi import MultiQS                                                        # multi/__init__.py:100; __init__(…, *, tenant=None, definition=None, principal=None) L106-121
from querysource.queries.describe import build_variables, KEYWORD_TYPES, IMPLICIT_DEFAULTS, DescribeVariable   # queries/describe.py:108,29,31,41 (unchanged in 5.1.1)
from querysource.tenants import QueryIdentity, LoadedDefinition, TenantError                         # tenants.py:46,54; TenantError re-exported from tenant_errors.py:15 (tenants.py:14)
from querysource.repositories.definitions import DefinitionRepository                                # definitions.py:56 (get L161, list L175 — unchanged in 5.1.1)
from querysource.auth.principal import QSPrincipal                                                   # principal.py:21 (frozen dataclass; for_authz L67 NOT needed here)
from querysource.exceptions import QueryAccessDenied                                                 # exceptions.py:63 (code 404, generic "Query not available.")
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/builders.py
def build_surface(component: str, properties: dict[str, Any], *, surface_id: str, component_id: str = "root",
                  data_model: dict[str, Any] | None = None, origin: ProducerOrigin = ProducerOrigin.LLM,
                  metadata: ComponentMetadata | None = None) -> CreateSurface:   # L69-76; metadata → ROOT component only L101-107;
                                                                                   # validate_envelope(envelope, origin=origin) L112
def build_html_document(...)   # L264 — hardcodes origin=ProducerOrigin.TOOL at L311 (TOOL-origin precedent)
def build_graph(..., origin: ProducerOrigin = ProducerOrigin.TOOL)   # L316

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py
def validate_envelope(envelope: CreateSurface | UpdateComponents, *, origin: ProducerOrigin = ProducerOrigin.TOOL,
                      surface_catalog_id: str | None = None) -> None:   # L499; per-component loop only; D10b gate L617-632;
                                                                           # tool_only gate L634-644; inline-data gate L646-661
_STRUCTURED_INLINE_DATA_COMPONENTS = {"Chart", "DataTable", "Map"}; _STRUCTURED_INLINE_DATA_FIELDS = ("data", "datasets")   # L105-109
# catalog/base.py: ProducerOrigin(str, Enum) TOOL/LLM L89-98; ACTION_NOT_ALLOWED_FOR_LLM L78, INLINE_DATA_NOT_ALLOWED_FOR_LLM L82,
#   TOOL_ONLY_NOT_ALLOWED_FOR_LLM L86

# packages/ai-parrot/src/parrot/outputs/a2ui/models.py
class CreateSurface(A2UIMessageBase):   # L446, extra="forbid" L463; surface_id L465, catalog_id L466, send_data_model L467,
    components: list[Component]; data_model: dict[str, Any]   # L468-469
    metadata: SurfaceMetadata | None = None                    # L470
class Extensions(RootModel[dict[str, Any]])   # L341; keys isidentifier(), "a2ui_" reserved (_RESERVED_EXTENSION_PREFIX L338) L351-361
class ComponentMetadata(BaseModel): extensions: Extensions | None   # L364-373;  SurfaceMetadata = ComponentMetadata  L378

# packages/ai-parrot/src/parrot/outputs/a2ui/baking.py
class BakeError(Exception)   # L46
def bake_envelope(envelope: CreateSurface) -> list[dict[str, Any]]   # L356; parrot_optional read L187-191

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/filterbar.py
FILTERBAR_SCHEMA   # L29-61: {title, filters: [{column, label, options: [{label, value}], multiple?}]}
class FilterBarComponent   # L104; lower() L110 → Row(parrot_variant="filter-bar") of ChoicePicker(parrot_filter_column)

# packages/ai-parrot/src/parrot/tools/dataset_manager/sources/query_slug.py
class QuerySlugSource(DataSource):   # L36
    def __init__(self, slug: str, prefetch_schema_enabled: bool = True, permanent_filter: Optional[Dict[str, Any]] = None)   # L51-56
    cache_key -> str   # L67-80
    async def fetch(self, **params) -> pd.DataFrame   # L122; merged = {**params, **permanent_filter} L143; qs_cls(slug=self.slug, conditions=merged) L151
class MultiQuerySlugSource(DataSource):   # L165; __init__(self, slugs: List[str]) L175; N independent QS calls L205-260
def _get_qs()   # L23 (lazy import slot; tests monkeypatch it)
# sources/authorizing.py: class AuthorizingDataSource(DataSource) L41; __init__(inner, guard, pctx_provider) L58-63; fetch L74

# packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py  (FEAT-558)
class QuerysourceToolkit(AbstractToolkit):   # L59; tool_prefix "qs" L67; exclude_tools ("open","close") L68; confirming_tools {"save_multiquery"} L69
    def __init__(self, programs=None, allow_write=False, allow_raw_sql=False, allow_external_sources=True, include_sql=True,
                 max_rows=200, forced_conditions=None, dsn=None, multiquery_timeout=600.0, **kwargs)   # L73-84; guard = TenantGuard(programs) L95
    async def _open(self) -> None   # L111: SlugCatalog(self._dsn or _qs.default_dsn(), self.guard) + open()
    async def list_slugs(self, search=None, program=None, limit=50) -> list[SlugSummary]   # L152
    async def describe_slug(self, slug: str, dry_run: bool = False) -> SlugDetail   # L160; PlaceholderInfo(name, type=cond_definition.get(n), default=conditions.get(n)) L166-169
    async def execute_slug(self, slug, placeholders=None, filter=None, fields=None, ordering=None, grouping=None,
                           limit=None, offset=None, refresh=False) -> ExecutionResult   # L190-200; get_allowed L208; validate_placeholders L209;
                           # validate_filter L210; build_conditions(..., max_rows, forced) L211-222; QS(slug=slug, conditions=conditions).query("pandas") L226-228
# models.py: PlaceholderInfo(name, type: str|None, default: Any) L24-29 — NO required/accepts_keywords; SlugDetail L32-45; ExecutionResult L47-59 — NO dtypes
# catalog.py: SlugRecord(slug, program_slug, description, provider, is_cached, cache_timeout, conditions, cond_definition, filtering, fields,
#   ordering, grouping, query_raw, pipeline) L39-55; TenantGuard L97 (assert_allowed L108-110, resolve_write_program L112); SlugCatalog L131
#   (__init__(dsn, guard) L134; open L139; get_allowed(slug) L161-165; list(*, search, program, limit) L167-187 via QueryModel.filter(program_slug=…))
# dialect.py: build_conditions(...) L165; check_version_compatibility(...) L195; load_variables() -> {'@name': doc} L207
# _qs.py: get_qs L~25, get_multiqs L33, get_query_model, get_component_registry, get_exceptions, default_dsn, installed_version L67

# packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py
class UISurfaceRecord(BaseModel): surface_id, kind, title, envelope: dict, catalog_id, agent_id, user_id, session_id, recipe_name,
    recipe_owner, recipe_params, tenant: str | None (L77, FEAT-535 auth scope — NOT a QuerySource schema), visibility, allowed_groups   # L62-79
    @property def refreshable(self) -> bool: return self.recipe_name is not None   # L84-86

# packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py
class PublishSurfaceRequest(BaseModel)   # L64-89 (deliberately NO tenant field L85-87)
class RefreshSurfaceRequest(BaseModel): params: dict[str, Any]   # L91-95
async def post(self)   # L385;  async def _pin_save(self)   # L491; tenant=scope.tenant server-set L566; surface_id = await self.store.save(record) L572
async def _refresh(self) -> web.Response   # L577; 409 when not refreshable L590-597; merged_params L604;
    # owner_pctx = build_principal_context(record.user_id, channel="ui_surfaces") L620 (tenant_id defaults to principal — permission.py:188-202)
    # runner.run(..., include_envelope=True) L622-629; store.update_envelope L638-645
# parrot_tools/ui_surfaces.py: PublishSurfaceTool L60; returns {"surface_id","kind","refreshable": recipe_name is not None} L146-150
# bots/mixins/infographic_authoring.py: async def publish_surface(self, *, kind, title, envelope, recipe_name=None, recipe_owner=None,
#   recipe_params=None, overwrite=False, surface_store=None, user_id=None, session_id=None) -> str   # L440
# handlers/infographic_render.py: STATIC_DIR helper L633-663 (from parrot.conf import STATIC_DIR L649; served by add_static("/static/", …) L646-647)
```

```typescript
// packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-types.ts
interface Binding { path: string }   // L14-16
interface WireComponent { id; component; catalogId?; child?; children?; metadata?: { extensions?: Record<string, unknown> }; [prop: string]: unknown }  // L27-40
export interface CreateSurface { surfaceId; catalogId?; components: WireComponent[]; dataModel?: Record<string, unknown> }   // L63-68 — NO metadata
// a2ui-binding.ts: isBinding L13, resolvePointer(path, dataModel) L33, resolveBinding L57, resolveProps L68
// a2ui-chart-adapter.ts: toChartBlockData(properties, dataModel): ChartBlockData L46-49
// A2UISurface.svelte: props { envelope } L12; dataModel L18; stateless L26-30 (dataModel at L18, L28, L30)
// A2UINode.svelte: resolved = $derived(resolveProps(properties, dataModel)) L35; no FilterBar branch
// lib/api/auth-headers.ts exists (bearer helper); lib/api/ has agents.ts, http.ts, infographic.ts, stream.ts — NO querysource client
```

```python
# ../querysource (tag 5.1.1, 989193d) — re-verified 2026-09-25
# services.py: POST/GET /api/v3/queries/{slug}{meta} → handlers.multi.QueryHandler (single + MultiQuery via MultiQS);
#   POST /api/v1/{tenant}/queries/{slug} → TenantQueryHandler; describe routes + tenant variants; v2 legacy
# handlers/tenant.py: TenantQueryHandler L147; FEAT-151 kind-aware dispatch: _prepare L198-212 loads the definition ONCE
#   (repo.get(QueryIdentity)) → _is_multi L194 (runtime.provider == 'multi') → QueryService (single) | QueryHandler (multi),
#   forwarding the pre-loaded definition — the reference pattern for M6/M7
# queries/qs.py: QS L50; __init__(slug='', conditions=None, request=None, loop=None, *, tenant=None, definition=None,
#   principal=None, residual=None, **kw) L56-68; FEAT-150: principal ⇒ enforce_principal(SLUG, slug, 'slug:execute')
#   BEFORE store/definition/provider/cache L225-231; _COLLAPSED_OWNER_ERRORS = {query_not_found, tenant_not_available}
#   → QueryAccessDenied L45-47, 249-250; request=None ∧ principal=None ⇒ service creds, no PBAC (unchanged);
#   PBAC not bootstrapped ⇒ no-op with one warning per process (FEAT-150)
# queries/multi/__init__.py: MultiQS L100; __init__(…, *, tenant=None, definition=None, principal=None) L106-121;
#   with principal, every stored child (and the stored slug itself) is pre-checked before any child runs
# auth/principal.py: QSPrincipal L21 (frozen: user_id, username, groups, roles, programs, superuser, tenant_id, channel,
#   authz_backend; tenant_id/channel = logs only, never store routing); enforce_principal (auth/enforcement.py:134)
# exceptions.py: QueryAccessDenied L63 — QueryException, code 404, generic message (never names the policy)
# tenants.py: QueryIdentity L46; LoadedDefinition L54 (identity, runtime, revision); TenantRegistry.resolve(None) →
#   public.queries, literal "public" ok, unknown → TenantError(tenant_not_available) L402+; TenantError moved to
#   tenant_errors.py:15 (still importable from querysource.tenants)
# interfaces/connections.py: get_definition_repository() singleton accessor L439-454 — SlugCatalog's construction path (M7)
# repositories/definitions.py: DefinitionRepository L56; get(identity) L161; list(store, params) -> DefinitionPage L175 (unchanged)
# handlers/abstract.py: PBAC on bare slug name; every denial → HTTPNotFound (no 403) (unchanged)
# queries/describe.py: KEYWORD_TYPES L29; IMPLICIT_DEFAULTS L31-33; DescribeVariable L41-51; build_variables L108-111 (pure; DescribeVariable objects;
#   required L154; accepts_keywords L163; variables_supported=False for JSON dialect L116-118) — semantics unchanged in 5.1.1
# cache_identity.py: key qs:r2:sha256(namespace, schema, table, slug, revision, provider_checksum)
# providers/abstract.py: refresh = bool(conditions.pop('refresh')); _udf_resolved_conditions
# types/validators.pyx + utils/vocabulary.py: UDF vocabulary still exactly 7 keywords, case-insensitive (unchanged)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_validate_linked_sources` (M3) | `validate_envelope` | call after the component loop | `catalog/__init__.py:499-682` |
| `build_linked_surface` (M4) | `validate_envelope(origin=TOOL)` | same call as `build_surface` | `builders.py:112` |
| `execute_sources` (M5) | `QuerySlugSource.fetch` / `AuthorizingDataSource.fetch` | await | `query_slug.py:122`, `authorizing.py:74` |
| `QuerySlugSource(tenant=, principal=)` (M6) | `QS(slug=, conditions=, tenant=, principal=, definition=)` / `MultiQS(...)` | constructor kwargs | `query_slug.py:151`; `../querysource/queries/qs.py:56-68`, `multi/__init__.py:106-121` |
| `SlugCatalog.get(tenant=)` (M7) | `DefinitionRepository.get(QueryIdentity(store, slug))` | await | `../querysource/repositories/definitions.py:161`; `tenants.py:402` |
| `describe_slug` (M7) | `querysource.queries.describe.build_variables` | call with `rec.query_raw, rec.conditions, rec.cond_definition` | `../querysource/queries/describe.py:108-111` |
| `build_linked_surface` tool (M7) | `AbstractToolkit` tool generation (`tool_prefix="qs"`) | method on the toolkit | `toolkit.py:67`, `parrot/tools/toolkit.py:254` |
| `_refresh` descriptor path (M8) | `execute_sources`, `store.update_envelope` | await | `handlers/ui_surfaces.py:577-645` |
| `_ensure_snapshot` (M8) | `_pin_save` before `store.save(record)` | call | `handlers/ui_surfaces.py:491-572` |
| `load_manifest` (M9) | `parrot.conf.STATIC_DIR` | path join | `handlers/infographic_render.py:649-658` |
| `dsl.ts` (M11) | `tests/outputs/a2ui/golden/linked/dsl/*.json` | vitest fixture import | `tests/outputs/a2ui/golden/` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.outputs.a2ui.linked` (any of `LinkedDataSource`, `LinkedSources`, `TransformSpec`, `apply_transform`, `execute_sources`, `has_data_sources`, `TransformManifest`)~~ — net-new (M1/M2/M5/M9).
- ~~`build_linked_surface`, `build_surface(surface_metadata=…)`, `CreateSurface.metadata` set by any builder~~ — net-new; today only root-component metadata is set (`builders.py:101-107`).
- ~~A surface-level rule loop in `validate_envelope`, `DATA_SOURCES_NOT_ALLOWED_FOR_LLM`, `DATA_SOURCE_INVALID`, `TRANSFORM_REF_UNKNOWN`~~ — net-new (M3).
- ~~`QuerySlugSource(tenant=…)`, `MultiQuerySlugSource(tenant=…)`, `_get_multiqs`~~ — no tenant parameter today (`query_slug.py:51-56, 175`); `QS` built without `tenant` (L151).
- ~~`SlugCatalog` seeing tenant stores, `SlugCatalog.get(tenant=)`, `describe_slug(tenant=)`, `execute_slug(tenant=)`, `list_slugs(tenant=)`~~ — it reads `public.queries` via `QueryModel` only (`catalog.py:132-187`); FEAT-558's `TenantGuard` is a `program_slug` allowlist.
- ~~`PlaceholderInfo.required`, `PlaceholderInfo.accepts_keywords`, `ExecutionResult.dtypes`~~ — absent (`models.py:24-59`).
- ~~`qs_build_linked_surface`, `reject_variable_values`~~ — net-new (M7). (`supports_tenant_multiquery` / `TenantMultiQueryUnsupportedError` from rev 0.1 are NEVER built — dropped 2026-09-25 with the `>=5.1.1` floor.)
- ~~`to_qs_principal`, any `principal=`/`definition=` kwarg on `QuerySlugSource`~~ — net-new (M6).
- ~~`QSourceTool`, `parrot_tools/qsource.py`, `ToolResult.metadata["dtypes"]`, `qs_describe`, `qs_columns`, `qs_vocabulary`, `qs_run`, "FEAT-567"~~ — hard-cut / never existed; the toolkit is FEAT-558.
- ~~`LinkedSurfaceToolkit`, `parrot_tools/linked_surfaces.py`~~ — NOT built (superseded 2026-09-24).
- ~~`LinkedSurfaceService`, `LinkedGuardRequired`, `derive_conditions`, `linked/contract/`, `has_data_sources` in `refreshable`~~ — net-new (M1/M5/M8/M12); `refreshable` is `recipe_name is not None` (`models/ui_surfaces.py:84-86`).
- ~~`update_envelope(expected_updated_at=…)`~~ — today `update_envelope(surface_id, envelope, recipe_params) -> None` is an unconditional update by id (`models/ui_surfaces.py:648-654`).
- ~~`validate_envelope` called on any save path~~ — `_pin_save` (L546), `PublishSurfaceTool` (L185) and `publish_surface` (L501) only run `CreateSurface.model_validate`.
- ~~`QS.close()` in `QuerySlugSource.fetch`~~ — never closed today (`query_slug.py:151-162`); the toolkit does (`toolkit.py:231`).
- ~~`TransformRef.url`~~ — the descriptor carries an opaque `name@version`, never a URL.
- ~~`/static/a2ui/transforms/`, `manifest.json`, `PARROT_A2UI_MANIFEST_KEY`, `handlers/a2ui_transforms.py`~~ — net-new (M9); only the generic `add_static("/static/", …)` route exists.
- ~~`ui/src/lib/api/querysource.ts`, `a2ui/linked/`, `CreateSurface.metadata` in `a2ui-types.ts`, a `FilterBar` branch in `A2UINode.svelte`~~ — absent.
- ~~Shared JSON fixtures between Python goldens and `ui/src/**/*.test.ts`, `golden/linked/`~~ — none today.
- ~~`/api/v3/{tenant}/queries/{slug}`, tenant discovery endpoint, tenant in JWT/session, tenant-membership check on execution, 403 from QuerySource~~ — still none in QuerySource 5.1.1 (`QueryAccessDenied` carries code **404**; FEAT-150 adds no membership check).
- ~~Per-user datasource credentials via `principal=`~~ — FEAT-150 authorizes only; credentials stay trusted-service (rejected in its brainstorm, FEAT-091).
- ~~`LAST_WEEK` / offset keywords, invocable date helpers, `{today}` placeholder grammar~~ — vocabulary closed at 7 keywords.
- ~~`QS.get_definition()`~~ — only `BaseProvider.get_definition()` in QuerySource.

### Edit Sites (Blueprint Anchors)

Verified against: `bc296148e` (2026-09-24). `/sdd-task` MUST re-run the `grep -c` for every row it uses.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/__init__.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/models.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/schema.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/dsl.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/executor.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/manifest.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/conditions.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/service.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/**` (`schema.json`, `fixtures/{dsl,conditions,envelopes}/*.json`) | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/outputs/a2ui/builders.py` | MODIFY | `def build_surface(` | `builders.py:69` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/builders.py` | MODIFY | `    validate_envelope(envelope, origin=origin)` | `builders.py:112` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py` | MODIFY | `def validate_envelope(` | `catalog/__init__.py:499` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py` | MODIFY | `    INLINE_DATA_NOT_ALLOWED_FOR_LLM,` (import block; context: preceded by `    ACTION_NOT_ALLOWED_FOR_LLM,` at L38, inside `from parrot.outputs.a2ui.catalog.base import (`) | `catalog/__init__.py:43` | 3 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py` | MODIFY | `TOOL_ONLY_NOT_ALLOWED_FOR_LLM` | `catalog/base.py:86` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/filterbar.py` | MODIFY | `FILTERBAR_SCHEMA` (definition; context: `FILTERBAR_SCHEMA = {` at L29 vs the reference at L107) | `filterbar.py:29` | 2 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/filterbar.py` | MODIFY | `class FilterBarComponent` | `filterbar.py:104` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/__init__.py` | MODIFY | `__all__ = [` (append `linked` re-exports; one-way import rule L9 still holds — `linked/` imports models only) | `a2ui/__init__.py:46` | 1 |
| `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/query_slug.py` | MODIFY | `        permanent_filter: Optional[Dict[str, Any]] = None,` | `query_slug.py:55` | 1 |
| `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/query_slug.py` | MODIFY | `qs_cls(slug=self.slug` (two sites: prefetch L110 and fetch L151 — both gain `tenant=`) | `query_slug.py:110,151` | 2 |
| `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/query_slug.py` | MODIFY | `class MultiQuerySlugSource(DataSource):` | `query_slug.py:165` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/querysource/models.py` | MODIFY | `class PlaceholderInfo(BaseModel):` | `models.py:24` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/querysource/catalog.py` | MODIFY | `class SlugCatalog:` | `catalog.py:131` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/querysource/catalog.py` | MODIFY | `    async def get_allowed(` | `catalog.py:161` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/querysource/catalog.py` | MODIFY | `    async def list(self, *, search: str \| None, program: str \| None, limit: int) -> list[SlugRecord]:` | `catalog.py:167` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/querysource/dialect.py` | MODIFY | `def check_version_compatibility(` | `dialect.py:195` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py` | MODIFY | `Generated tool names (tool_prefix 'qs')` (module docstring) | `toolkit.py:3` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py` | MODIFY | `    async def list_slugs(` | `toolkit.py:152` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py` | MODIFY | `    async def describe_slug(self, slug: str, dry_run: bool = False) -> SlugDetail:` | `toolkit.py:160` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py` | MODIFY | `    async def execute_slug(` | `toolkit.py:190` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py` | MODIFY | `        rec = await self._catalog.get_allowed(slug)` (three sites L165 describe, L208 execute, L361 multiquery — all gain `tenant=`) | `toolkit.py:165,208,361` | 3 |
| `packages/ai-parrot-tools/src/parrot_tools/querysource/__init__.py` | MODIFY | `__all__ = [` | `__init__.py:23` | 1 |
| `packages/ai-parrot-tools/pyproject.toml` | MODIFY | `db = ["querysource>=4.5.11", "psycopg-binary>=3.2"]` | `pyproject.toml:77` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py` | MODIFY | `"refreshable": recipe_name is not None` | `ui_surfaces.py:149` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py` | MODIFY | `        envelope_model = CreateSurface.model_validate(envelope)` | `ui_surfaces.py:185` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py` | MODIFY | `    def refreshable(self) -> bool:` | `models/ui_surfaces.py:84` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py` | MODIFY | `    async def update_envelope(self, surface_id: str, envelope: dict[str, Any], recipe_params: dict[str, Any]) -> None:` | `models/ui_surfaces.py:648` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py` | MODIFY | `            envelope = CreateSurface.model_validate(envelope_dict)` (save path, `_pin_save`) | `handlers/ui_surfaces.py:546` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py` | MODIFY | `    async def _refresh(self) -> web.Response:` | `handlers/ui_surfaces.py:577` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py` | MODIFY | `            tenant=scope.tenant,  # server-set, NEVER from the body (spec §2/§6)` (save path; `_ensure_snapshot` runs before `store.save` L572) | `handlers/ui_surfaces.py:566` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py` | MODIFY | `owner_pctx = build_principal_context(` | `handlers/ui_surfaces.py:620` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/a2ui_transforms.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/bots/mixins/infographic_authoring.py` | MODIFY | `    async def publish_surface(` | `infographic_authoring.py:440` | 1 |
| `packages/ai-parrot/src/parrot/bots/mixins/infographic_authoring.py` | MODIFY | `        envelope_model = envelope if isinstance(envelope, CreateSurface) else CreateSurface.model_validate(envelope)` | `infographic_authoring.py:501` | 1 |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-types.ts` | MODIFY | `export interface CreateSurface {` | `a2ui-types.ts:63` | 1 |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UISurface.svelte` | MODIFY | `dataModel` (L18 declaration is the anchor; L28/L30 are uses) | `A2UISurface.svelte:18` | 3 |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UINode.svelte` | MODIFY | `resolveProps(properties, dataModel)` | `A2UINode.svelte:35` | 1 |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/{types,dsl,fetch,scheduler,ref,index}.ts` | CREATE | — | — | — |
| `packages/ai-parrot-server/ui/src/lib/api/querysource.ts` | CREATE | — | — | — |
| `packages/ai-parrot/tests/outputs/a2ui/conformance/test_all_emitters.py` | MODIFY | `def _assert_conformant(` | `test_all_emitters.py:115` | 1 |
| `packages/ai-parrot/tests/outputs/a2ui/linked/**` | CREATE | — | — | — |
| `docs/outputs/a2ui-v1.md` | MODIFY | `parrot_series_data` (extension table row; L156 is the table, L349 prose) | `a2ui-v1.md:156` | 2 |
| `docs/frontend/agentdashboard-a2ui-reference.md` | MODIFY | `7.4` (§7.4 heading at L805; L493/L547 are cross-references) | `agentdashboard-a2ui-reference.md:805` | 3 |
| `docs/tools/querysource-toolkit.md` | MODIFY | `## Tools` | `querysource-toolkit.md:33` | 1 |
| `docs/outputs/a2ui-linked-surfaces.md` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- TOOL-origin precedent: `build_html_document` (`builders.py:311`) and `build_graph(origin=TOOL)` (`builders.py:316`); origin gates: D10b (`catalog/__init__.py:617-632`) and FEAT-473 inline data (L646-661).
- Golden convention: `json.dumps(tree.model_dump(mode="json", exclude_none=True), sort_keys=True, indent=2)` byte-equal to the file (`tests/outputs/a2ui/test_components_filterbar.py:15-42`); conformance registration via `_assert_conformant` (`test_all_emitters.py:115`).
- Toolkit conventions: `_post_execute` Pydantic→dict (`toolkit.py:127-133`), tenant check before any `QS` construction (`toolkit.py:208`), lazy `_qs` accessors (`_qs.py`), errors in `errors.py`.
- Lazy import slots for tests: `_get_qs()` / `_get_multiqs()` (`query_slug.py:23`).
- Owner context: `build_principal_context(record.user_id, channel="ui_surfaces")` (`handlers/ui_surfaces.py:620`) — **pass the descriptor's tenant to the executor; never read `pctx.tenant_id` for store selection.**
- Static assets: `parrot.conf.STATIC_DIR` local import (`infographic_render.py:649`), served by navigator's `add_static("/static/", …)`.
- UI: Svelte 5 runes only; `$lib` alias; `src/lib/types/generated/` from `pnpm generate` (put the linked JSON Schema under `ui/schemas/`); vitest next to code.

### DSL v1 semantics (binding for every executor; fixtures are the contract)
- `select {columns}` keep+order; `rename {mapping}`; `filter {column, op ∈ eq|ne|gt|ge|lt|le|in|contains, value}` (null never matches); `group_by {by, aggregate: {col: sum|avg|count|min|max}}`; `sort {by: [{column, direction}]}` (stable; nulls last); `limit {n}`; `derive {name, expr}` where `expr` is a binary tree of `+ - * /` over column names and numeric constants only (`/` by zero → null); `pivot {index, columns, values, aggregate}`; `join {with: <sibling key>, how ∈ inner|left, on: [{left, right}]}` — equality only, `null` never matches, colliding column names take `<with>_` prefix, one join per step; `union {sources: [<sibling keys>]}` — concatenation on the intersection of column names, in order.
- Row records are `orient="records"`; dates serialize ISO-8601; numeric dtypes preserved; a Python `TransformError` ↔ a TS thrown `TransformError` with the same `(source_key, op_index)`.

### `derive_conditions` rules (M1; binding for every executor; fixtures are the contract)
- Output keys in this order: placeholders (request order) with `locked` values overriding same-named keys; then `filter` entries verbatim (dialect grammar, `dialect.py:165` `build_conditions` semantics); then `fields`, `ordering`, `grouping` only when non-empty; then `limit` and `offset` mapped to the same dialect keys `build_conditions` uses for them. `querylimit` (the lane-time fetch cap) and `refresh` are never emitted by `derive_conditions`. The toolkit's test pins `build_conditions(...) − {querylimit, refresh} == derive_conditions(...)`; the exact key names are fixed by the first conditions fixture, not by prose.

### Axis validation (M4)
- `Chart.x` must name a column; each `Chart.y[*]` a numeric column (int/float/bool → numeric; datetime allowed for `x` only); `DataTable.columns[*].key` must name a column; `KPICard.value` bound to `/<key>/rows/0/<col>` must name a column. Violations raise `ValueError("<prop> '<column>' not in source '<key>' columns [...]")`.

### Known Risks / Gotchas
- **Tenant is routing, not security** (FEAT-147: no membership check, PBAC on the bare slug name). A user with `slug:execute` can run `x` under any registered tenant by editing the URL. Document next to `locked`.
- **In-process PBAC is opt-in and can silently no-op** (FEAT-150): without `principal=`, in-process QuerySource still runs zero PBAC on trusted-service credentials; with it, PBAC runs — but when QuerySource's PBAC bootstrap is absent it degrades to a no-op with one warning per process. That is why ai-parrot's guard (`AuthorizingDataSource` / `LinkedSurfaceService`) stays MANDATORY and fail-closed (AC14) — the principal is defense in depth, never the only gate. Share-token viewers still see owner snapshots (FEAT-492). State all of this in `docs/outputs/a2ui-linked-surfaces.md`.
- **Hand-crafted descriptor + trusted-service execution = exfiltration (S2)**: today every save path only runs `CreateSurface.model_validate`; a user could persist a descriptor for any `(tenant, slug)` and have the server fetch it at save time. `LinkedSurfaceService.validate_for_persistence` is therefore mandatory on all four call sites and **fails closed** without a guard (`LinkedGuardRequired` → 403) — deliberately unlike `RecipeRunner`'s fail-open on falsy `pctx` (`runner.py:262-264`).
- **Concurrent refresh writers (S11)**: renderer interval + manual + server refresh can race; `update_envelope` is unconditional today. Refresh persists with `expected_updated_at`; losers get 409.
- **Unbounded fetch before pandas (S8)**: the 500-row cap is a *snapshot* cap; the fetch itself is bounded by `querylimit = max_fetch_rows` (5000) on every lane, transforms run in `asyncio.to_thread`, and every `QS`/`MultiQS` is closed in `finally`.
- **`ref` modules execute JavaScript in the host page (S6)**: SRI authenticates bytes, not behaviour. Mitigations: opaque `name@version` ids (no URLs on the wire), operator-published per-release catalogue, `deprecated` never `deleted`, and the host page's CSP (documented, not enforced by ai-parrot).
- **`resolve(None)` silently falls back to `public.queries`** — a same-named public slug runs instead of the tenant's. Every lane must pass `tenant` explicitly; tests assert the kwarg.
- **Tenant MultiQuery needs querysource >= 5.1.1** — guaranteed by the pyproject floor (AC12), not by a runtime gate; an environment pinned below the floor fails `check_version_compatibility` at toolkit init, not per-call.
- **`build_variables` returns `DescribeVariable` objects**, `.model_dump()` them; `required` is static and `firstdate/lastdate/filterdate` are never required (`IMPLICIT_DEFAULTS`); `accepts_keywords` is also true for untyped variables (`raw_type is None`); JSON-dialect slugs → `variables_supported=False` (empty `params`).
- **Every QuerySource denial is 404** (no 403): renderer notices must say "unavailable"; server maps `QueryAccessDenied` (code 404 — with a principal, "missing" and "denied" are indistinguishable by design) and `TenantError.error_code` before 502.
- **FEAT-150 §8 vs AC4**: FEAT-150's follow-up note suggests `_refresh` pass `record.tenant` as `tenant=`; this spec's descriptor-tenant rule wins — `tenant` comes from each `parrot_data_sources` entry, never from `UISurfaceRecord.tenant` (AC4). Only the `PermissionContext → QSPrincipal` half of that note is adopted (M6).
- **`refresh` is `bool(raw)`** on the QuerySource side (`providers/abstract.py:83-85`) — send boolean `true` or omit.
- **Vocabulary is closed** (7 keywords, case-insensitive values) — no offsets; `@variables` rejected.
- **Save-time execution is a write with a data-plane side effect** — bounded to `POST /api/v1/ui/surfaces` (no snapshot) and `POST …/refresh`; `GET` never executes (AC8).
- **DSL parity drift** between Python and every renderer — mitigated by the shared fixtures and the closed op set; any DSL change must add fixtures first.
- **`ref` modules are anonymous static files** — never `deleted`, only `deprecated`; SRI mismatch ⇒ never executed; manifest HMAC key `PARROT_A2UI_MANIFEST_KEY` from the environment only.
- **Multiple `get_allowed` call sites** (`toolkit.py:165,208,361`) — all must gain `tenant=` or MultiQuery pipelines silently resolve against `public`.
- **`cache_key` of `QuerySlugSource`** must include the tenant or DatasetManager caches collide across tenants.
- **`a2ui/__init__.py` one-way import rule (spec G8, L9)** — `linked/` may import `models`; nothing in `linked/` may import from `catalog/` at module import time (validation imports `linked.models`, not the reverse).

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `pydantic` | v2 (existing) | descriptor + DSL models, JSON Schema export |
| `pandas` | existing | Python DSL executor |
| `querysource` | `>=5.1.1` (floor bump; no runtime gate) | `QS`/`MultiQS(tenant=, principal=, definition=)`, kind-aware tenant MultiQuery dispatch, `QSPrincipal`, `QueryAccessDenied`, `DefinitionRepository`, `queries.describe.build_variables` |
| `jsonschema` | existing | validate `parrot_data_sources` in the conformance suite |
| `aiohttp` | existing | static route (no new code path — navigator `add_static`) |
| Svelte 5 + TypeScript + vitest | existing | bundled UI lane |

No new Python runtime dependency.

---

## 8. Open Questions

> Questions that must be resolved before or during implementation.

None open. Every question was resolved in the brainstorm and is carried forward here (audit trail):

**Resolved 2026-09-15 (brainstorm discovery)**
- [x] Flow type / base — *Resolved in brainstorm*: `feature`, base `dev`.
- [x] Where the descriptor lives — *Resolved in brainstorm*: surface-level `metadata.extensions.parrot_data_sources`; components bind by `path`; any surface. → §2 Overview, AC2.
- [x] Fetch path — *Resolved in brainstorm*: renderer → QuerySource directly with the viewer's JWT; no proxy (endpoint revised 09-24). → G3.
- [x] Transform DSL scope — *Resolved in brainstorm*: ten ops incl. `join`/`union`; no LLM code; library shapes are the renderer's. → §7 DSL semantics.
- [x] `transform.ref` in v1 — *Resolved in brainstorm*: URL to a TS module served by ai-parrot-server, SRI-pinned; inline `ops` is the rule. → M9.
- [x] Who may emit — *Resolved in brainstorm*: TOOL-origin only; `DATA_SOURCES_NOT_ALLOWED_FOR_LLM`. → M3, AC2.
- [x] Refresh policy — *Resolved in brainstorm*: `on_mount` default; `manual`/`interval`; `refreshable = recipe_name or data_sources`. → M1, M8.
- [x] `locked` — *Resolved in brainstorm*: UX hint only; security is PBAC + slug design. → §7 risks, AC13.
- [x] Snapshot — *Resolved in brainstorm*: optional in chat, mandatory once persisted (save path executes once); `GET` never executes. → M8, AC8.
- [x] Relative dates — *Resolved in brainstorm*: UDF keyword vocabulary as values; no placeholder grammar. → §7.
- [x] No TypeScript shipped for third parties — *Resolved in brainstorm*: schema + fixtures are the contract; bundled UI implements its own lane. → G1, M11, M12.
- [x] FilterBar ↔ params — *Resolved in brainstorm*: extend `FilterBar` with `parrot_param`; no `ParamBar`. → M10.
- [x] `interval` policy — *Resolved in brainstorm*: 30 s minimum, paused while hidden, immediate fetch on resume. → M1, M11, AC10.
- [x] Snapshot row cap — *Resolved in brainstorm*: 500 rows per source, `snapshot_truncated`. → M4, AC3.
- [x] Share-token viewers denied — *Resolved in brainstorm*: keep snapshot + "data as of" notice + server-side refresh button; no automatic server refresh. → M11.
- [x] ~~Multi-tenant slugs: tenant-agnostic descriptor~~ — *superseded 2026-09-24*: see below.
- [x] `ref` governance — *Resolved in brainstorm*: per-release static directory + signed manifest; builder accepts manifest refs only; retirement = `deprecated`. → M9, AC9.
- [x] `MultiQuerySlugSource` — *Resolved in brainstorm*: N descriptors + `union`. → §7 DSL.
- [x] HTML lane without snapshot — *Resolved in brainstorm*: never for persisted surfaces (save produces it). → M8.
- [x] ~~FEAT-567 sequencing~~ — *superseded*: FEAT-558 shipped 2026-09-17.

**Resolved 2026-09-24 (FEAT-558 re-verification rounds)**
- [x] Params source — *Resolved in brainstorm*: extend `qs_describe_slug` (`PlaceholderInfo` + `required`/`accepts_keywords` via `build_variables` in-process). → M7, AC6.
- [x] Date grammar — *Resolved in brainstorm*: UDF keywords only; `@variables` rejected. → M7, §7.
- [x] Builder tool location — *Resolved in brainstorm*: new tool on `QuerysourceToolkit`; no `LinkedSurfaceToolkit`. → M7.
- [x] Snapshot/execution path — *Resolved in brainstorm*: Python executor via `QuerySlugSource`; builder always executes once. → M4, M5, AC3.
- [x] Column types — *Resolved in brainstorm*: from the mandatory execution's dtypes. → §7 axis validation.
- [x] Fetch endpoint — *Resolved in brainstorm*: `POST /api/v3/queries/{slug}` / `/api/v1/{tenant}/queries/{slug}`; v2 legacy. → G3.
- [x] `conditions` shape — *Resolved in brainstorm*: raw + structured `request`. → M1, AC3.
- [x] Sequencing — *Resolved in brainstorm*: QuerySource 5.0.0 in production; floor bump is a task here. → AC12.

**Resolved 2026-09-24 (FEAT-147 / FEAT-148 cross-check)**
- [x] Tenant in the descriptor — *Resolved in brainstorm*: `tenant: str | null` per source; independent of `UISurfaceRecord.tenant`; routing, not security. → M1, AC4.
- [x] Catalog for tenant slugs — *Resolved in brainstorm*: tenant-aware `SlugCatalog` over `DefinitionRepository`; `programs` allowlist unchanged. → M7, AC6.
- [x] Server-lane tenant plumbing — *Resolved in brainstorm*: `QuerySlugSource(tenant=)`, `QS`/`MultiQS` dispatch, `TenantError` mapping, trusted-service model. → M5, M6, M8.
- [x] Tenant MultiQuery — *Resolved in brainstorm*: rejected while QuerySource `< 5.1.0`. → M7, AC5.
- [x] Relative offsets — *Resolved in brainstorm*: "last week" claim withdrawn; vocabulary closed. → §7.
- [x] `accepts_keywords` / `required` / `build_variables` — *Resolved in brainstorm*: adopted as implemented. → M7, AC6.
- [x] Error semantics — *Resolved in brainstorm*: 404 = "unavailable"; server maps `TenantError.error_code`. → M5, M11, AC8/AC10.
- [x] `refresh` — *Resolved in brainstorm*: boolean `true` only. → AC10.
- [x] Floor — *Resolved in brainstorm*: `querysource>=5.0.0`; `5.1.7` tag spurious. → AC12. *(Superseded 2026-09-25, see below.)*

**Resolved 2026-09-25 (QuerySource 5.1.1 released — re-verification against `989193d`)**
- [x] Tenant MultiQuery gate — *Resolved (Jesus Lara)*: 5.1.1 ships FEAT-151's kind-aware dispatch (`handlers/tenant.py:194-212`); floor bumped to `>=5.1.1` and the runtime gate (`supports_tenant_multiquery`, `TenantMultiQueryUnsupportedError`) is dropped entirely. Supersedes the two brainstorm rows above. → M7, AC5, AC12.
- [x] In-process PBAC — *Resolved (Jesus Lara)*: adopt FEAT-150 `principal=` now on every owner-context lane (`to_qs_principal(owner_pctx)` in M6, threaded by M5/M8); the agent-tool lane stays trusted-service (allowlist + `forced_conditions`) as an explicit non-goal; `AuthorizingDataSource` guard remains mandatory. → M5, M6, M8, AC18.
- [x] `DefinitionRepository` connection ownership (M7 delegation blocker) — *Resolved*: use the `QuerySource()` singleton accessor `get_definition_repository()` (`interfaces/connections.py:439-454`); `TenantQueryHandler._prepare` is the read-once reference; the `LoadedDefinition` MAY be forwarded as `definition=` to skip the execution-time re-read. M7 is now fully delegation-eligible. → M6, M7.

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `gpt-5.6-luna` (codex-cli 0.156.1, reasoning high) · Status: completed
> · Transcript: `sdd/state/FEAT-598/design_research/` (brief, suggestions.json, run.json, triage.md)
> Every row is a suggestion the reviewer made; the disposition is the spec author's
> call (CONFIRM = folded into the spec, REJECT = reason recorded, ESCALATE = §8 question).
> All 41 `affected_paths` verified (containment + existence); S2, S8 and S11 spot-checked in code before disposition.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Centralize linked execution for publish, refresh, and HTML (architecture) | CONFIRM | four call sites (`_pin_save`, `publish_surface`, `PublishSurfaceTool`, `_refresh`) → one core `LinkedSurfaceService` with atomic failure semantics | §3 M5 (`linked/service.py`), M8 |
| S2 | Make TOOL provenance enforceable at persistence boundaries (risk) | CONFIRM | verified: save paths only `model_validate`; with trusted-service execution this allowed exfiltration via a hand-written descriptor; persistence now runs `validate_envelope(origin=TOOL)` **and** a mandatory, fail-closed owner `slug:execute` guard | §3 M5/M8, §5 AC14, §7 risks |
| S3 | Tenant-aware `(tenant, slug)` identity before building descriptors (architecture) | CONFIRM | already the outcome of the FEAT-147 cross-check; independent corroboration | §3 M6, M7 |
| S4 | One normalized result shape for MultiQuery sources (api) | CONFIRM | `multi_output` selects the `MultiQS` frame (`"result"`/single fallback, `results.py:77-79`); fixtures for public/gated/empty | §2 Data Models, §3 M6, §4 |
| S5 | Make `request` the canonical condition representation (api) | CONFIRM | `derive_conditions` (core, pure, fixture-pinned); `conditions` is a derived cache; M3 rejects mismatches; toolkit test pins parity with `build_conditions` | §2, §3 M1/M3, §7 |
| S6 | Defer arbitrary `ref` transforms or reduce them to opaque allowlisted IDs (risk) | CONFIRM (opaque ids) / REJECT (deferral) | `TransformRef.name` is an opaque `name@version`, never a URL; renderer resolves against its own base + manifest. Deferral rejected: keeping `ref` in v1 is an explicit author decision in the accepted brainstorm; CSP is the host page's, documented | §2, §3 M9/M11, §7 risks |
| S7 | Publish fixtures as a shared consumable contract (testing) | CONFIRM | contract (schema + fixtures) ships as package data at `linked/contract/`; Python tests and vitest read the same files; mandatory edge cases enumerated | §3 M12, §5 AC7, §6 Edit Sites |
| S8 | Bound fetch volume before pandas transforms and close QS resources (risk) | CONFIRM | verified: `QuerySlugSource.fetch` never closes; `querylimit = max_fetch_rows` on every lane, `to_thread`, `finally: close()` | §3 M5/M6, §5 AC17, §7 risks |
| S9 | Specify behavior when a linked surface has no snapshot (architecture) | CONFIRM | builder always writes `{"rows": []}` so `bake_envelope` never raises; loading state while `snapshot_at` is null; JSON/HTML/chat tests | §3 M4, §5 AC16, §4 |
| S10 | Carry `parrot_param` through FilterBar lowering (api) | CONFIRM | already M10; runtime consumes **lowered** nodes — now stated | §3 M10/M11 |
| S11 | Prevent stale concurrent refreshes from overwriting newer snapshots (risk) | CONFIRM | verified: `update_envelope` unconditional; `expected_updated_at` predicate → 409 on conflict | §3 M8, §5 AC15, §6 Edit Sites |

Summary: **11** confirmed (S6 partially — its deferral half rejected) · **0** rejected outright · **0** escalated.

---

## Worktree Strategy

- **Isolation**: ONE feature worktree `feat-FEAT-598-a2ui-linked-surfaces` (from `origin/dev`); the `sdd-coder` engine gives each task its own sub-worktree inside it.
- **Module dependency graph** (edges = imports/uses, evidence in §3):
  - M2 → M1 (`TransformSpec`), M3 → M1 (`LinkedSources`) and → M9 (`load_manifest` for `ref`), M4 → M1, M3 (`validate_envelope` call), M5 → M1, M2, M6 (`QuerySlugSource(tenant=)`), M7 → M1, M4, M5, M6, M8 → M1 (`has_data_sources`), M5, M9 → M1, M11 → M1 (schema), M12 (fixtures), M12 → M1, M2, M4, M13 → all.
  - No edge between: M6 ‖ M1/M2/M3/M9/M10; M10 ‖ everything except M13; M9 ‖ M2/M4/M6; M11's `dsl.ts` can start as soon as M12's DSL fixtures exist. These run concurrently.
- **Shared files** (tasks serialized): `catalog/__init__.py` (M3 only), `builders.py` (M4 only), `parrot_tools/querysource/toolkit.py` + `catalog.py` (M7 — split into two tasks that touch different files: catalog swap vs tool method), `handlers/ui_surfaces.py` (M8 refresh + save in ONE task), `a2ui/__init__.py` (M1 export + nothing else), golden files for `filterbar_lowered.json` (M10) vs `golden/linked/` (M12) — disjoint.
- **Exclusive resources** (`parallel: false`): `packages/ai-parrot-tools/pyproject.toml` floor bump (M7; may touch `uv.lock`); `ui/src/lib/types/generated/` regeneration via `pnpm generate` (M11).
- **Cross-feature dependencies**: none to merge first. FEAT-558 (merged), FEAT-492 (merged), FEAT-535 (merged). External: QuerySource 5.1.1 released (`989193d`) — the floor; no task blocks on anything unreleased.

---

## Errata (task-time verification, 2026-09-26)

Eight prose errors were found while decomposing this spec into TASK-3769..3796 and are corrected
**in the task files, which are authoritative where they disagree with the prose above**:

1. `Filter`'s comparison field is `operator` — `op` is the node-type discriminator, not the comparator.
2. `derive_conditions` never emits `limit`; every lane sends `querylimit = min(request.limit or cap, cap)`.
3. `ExecutionOutcome.frames` carries the executed DataFrames so the toolkit never rebuilds dtypes from rows.
4. `DataTable` columns use `name`, not `key`.
5. `ValidationIssue` does not exist — `validate_envelope` raises `CatalogValidationError(issues=[…])`.
6. `check_version_compatibility` only WARNS; §7's "fails at toolkit init" is false.
7. `get_definition_repository()` lives on `Connection`, not on `QuerySource()`.
8. `contract/schema.json` ships at `linked/contract/` (package data), not `docs/outputs/schemas/`.

Owner decisions recorded the same day (details in the task files):
- **Owner-check resource naming (TASK-3781)** — CONFIRMED: `authorize_source` with
  `PhysicalResources(source_type="query_slug", source_id="<tenant|public>:<slug>")`, i.e. PBAC
  `source:read` on `query_slug:<tenant|public>:<slug>`. No new `slug:execute` action.
- **AC14 vs AC11 (TASK-3781)** — CONFIRMED: every save path calls `validate_for_persistence`, but
  TOOL-origin validation + guard run only when `has_data_sources(envelope)`; baked envelopes keep
  today's behaviour.
- **Guard wiring** — new TASK-3805 ships default wiring (`setup_dataplane_guard()` →
  `app["dataplane_guard"]` + `bot._dataplane_guard` when PBAC initializes); un-wired/bare installs
  keep answering 403 for linked saves (fail closed).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-24 | Jesus Lara / Claude | Initial draft from the accepted brainstorm (three revisions, incl. FEAT-147/FEAT-148 cross-check) |
| 0.2 | 2026-09-25 | Jesus Lara / Claude | Re-verified against QuerySource 5.1.1 (`989193d`): floor `>=5.1.1`, runtime tenant-MultiQuery gate dropped (AC5/AC12/M7); FEAT-150 `QSPrincipal` adopted on owner-context lanes (`to_qs_principal`, M5/M6/M8, new AC18, `QueryAccessDenied`→404); M7 `DefinitionRepository` open question resolved (singleton accessor + optional `definition=` preload); contract anchors refreshed |
| 0.3 | 2026-09-26 | Jesus Lara / Claude | Errata section (eight task-time prose corrections; tasks authoritative); owner confirmed `query_slug:<tenant\|public>:<slug>` resource naming and the AC14/AC11 resolution; TASK-3805 (default data-plane guard wiring) added |
