---
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-tools, ai-parrot-server, admin-ui, docs]
tags: [a2ui, linked-surfaces, querysource, recipes, transformers, ui-surfaces]
---

# Feature Specification: Linked A2UI surfaces — server-executed Python recipe transformers

**Feature ID**: FEAT-636
**Date**: 2026-10-06
**Author**: Jesus Lara (+ Claude)
**Status**: approved
**Target version**: next minor
**Exploration**: `sdd/proposals/linked-a2ui-recipes-transforms.proposal.md` (accepted; all open questions resolved)

---

## 1. Motivation & Business Requirements

### Problem Statement

Static/recipe A2UI surfaces aggregate data with Python transformers through
`RecipeRunner`, but linked surfaces (FEAT-598) fetch rows client-side straight
from QuerySource and their `TransformSpec` only admits the inline DSL v1 or
renderer-side `transform.ref` JS modules — no Python path exists. Linked
surfaces therefore cannot reuse the registered `@infographic_transformer`
functions that static and recipe definitions already use for aggregation.

### Goals

- A linked data-source descriptor can declare a **registered Python
  transformer** (`transform.python`) that the server applies after executing
  the query slug.
- A new **per-source server data endpoint** lets the renderer fetch
  transformed rows dynamically (viewer identity for authenticated sessions,
  owner identity for share-token viewers — included from day one).
- The Python bake/persist/server-refresh lane applies the **same transformer
  through the same code path**, so Python-lane parity is intrinsic.
- G1 invariant preserved: transformers referenced **by registered name only**
  — never stored or dynamically imported code.
- Existing linked surfaces (no `python` member) behave **byte-identically**.

### Non-Goals (explicitly out of scope)

- Recipe references (`name@owner` via the recipe store) in descriptors —
  explicitly phase 2 (proposal §5 U2).
- Chaining inline DSL ops after the Python transformer, or letting
  derived/join/union siblings reference a python-transformed source — the
  transformer is **terminal in v1** (proposal §5 U3).
- Non-tabular (verbatim JSON / KPI-object) transformer output at `target` —
  rejected for v1 (proposal §5 OQ-C).
- Changes to the DSL v1 op set, `transform.ref`, RecipeRunner, QuerySource,
  or snapshot persistence semantics (AC16 of FEAT-598).
- A dynamic-fetch lane for **non-persisted** surfaces (no `surface_id` ⇒
  snapshot-only; see §2 and S4/S12 in §9).

---

## 2. Architectural Design

### Overview

`TransformSpec` grows a third XOR member, `python: PythonTransform`
(`transformer` registered name, `params`, optional `input_alias` defaulting
to `"source"`, optional `output` key). Because a Python transformer cannot
run in the TS renderer (the mirror image of `transform.ref`, which cannot run
in the Python executor), any source carrying one fetches its rows through the
server: `POST /api/v1/ui/surfaces/{surface_id}/sources/{key}/data` on
`UISurfacesHandler`.

Execution is owned by the core, not the handler (S1): a new
`LinkedSurfaceService.fetch_source()` re-authorizes the `(tenant, slug)`
under the data-plane guard, reconstructs QuerySource conditions **from the
persisted descriptor** (the request body carries parameter overrides only,
never raw conditions — S2), executes the slug via the existing
`execute_sources` machinery, applies the registered transformer via a shared
`apply_python_transform` helper, and returns JSON-safe rows. The same helper
runs inside `_run_source` for bake/persist/server-refresh, so every Python
lane produces identical frames by construction.

Identity rule (proposal §5 U1/U4): an authenticated viewer executes under
their own `PermissionContext` (`build_principal_context(viewer_id,
channel="ui_surfaces")` → QuerySource PBAC scopes rows per viewer); a
share-token viewer has no JWT, so the endpoint executes under the **owner's**
pctx — exactly the existing share-refresh semantics ("Share-bearer refresh
runs with the OWNER's PermissionContext", `ui_surfaces.py:645-647`).

Renderer behavior: a python-transformed source never calls QuerySource
directly and never runs `applyTransform` client-side. Dynamic fetch requires
a persisted surface (`persistedSurfaceId`); a non-persisted envelope renders
that source from its snapshot with refresh disabled — never a silent
fallback to direct QuerySource, which would drop the transform (S4).

Transformer output contract (proposal §5 OQ-C + S6): the returned dict is
reduced by the shared `select_output_frame` rule — `python.output` override →
`"result"` key → sole key → deterministic error. The selected value must be a
`pd.DataFrame` or a list of row mappings; anything else is a transform-stage
error. The resulting frame is capped at `max_fetch_rows` post-transform (S9)
and then behaves exactly like a fetched frame (≤500-row snapshot, bindings).

### Component Diagram

```
                      ┌────────────────────────────────────────────────┐
 renderer (TS lane)   │ parrot-server                                  │
 LinkedLane           │  UISurfacesHandler                             │
  ├─ DSL/ref source ──┼──────────► QuerySource (viewer JWT, direct)    │
  └─ python source ───┼─► POST /sources/{key}/data                     │
        (params only) │      │ resolve_surface_access (+share token)   │
                      │      ▼                                         │
                      │  LinkedSurfaceService.fetch_source(pctx)       │
                      │      │ guard + _assert_sources_allowed         │
                      │      ▼                                         │
 bake / persist /     │  execute_sources ──► QuerySlugSource ──► QS    │
 server refresh ──────┼─►    │ (one source, conditions from descriptor)│
 (owner pctx)         │      ▼                                         │
                      │  apply_python_transform                        │
                      │      │ transformer_registry.get(name)          │
                      │      │ {input_alias: frame} → dict             │
                      │      ▼ select_output_frame → cap → records     │
                      └────────────────────────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `TransformSpec` (`linked/models.py:178`) | extends | third XOR member `python` |
| `transformer_registry` / `@infographic_transformer` (`recipes/transformers.py`) | uses | name lookup + `TransformerManifest` gate; registry code untouched |
| `execute_sources` / `_run_source` (`linked/executor.py:231`) | extends | python branch next to the `ref`-skip branch (`executor.py:284`) |
| `LinkedSurfaceService` (`linked/service.py:67`) | extends | persist-time gate + new `fetch_source()` |
| `UISurfacesHandler` (`handlers/ui_surfaces.py:313`) | extends | `/data` suffix dispatch in `post()` (`ui_surfaces.py:402`) |
| route table (`manager/manager.py:2420-2425`) | extends | one `add_view` for the sources route |
| `qs_build_linked_surface` (`parrot_tools/querysource/toolkit.py`) | extends | accepts + gates the `python` member at build time |
| `LinkedLane` (`ui/.../linked/index.ts:265`) | extends | endpoint branch; no client transform for python sources |
| schema chain (`linked/schema.py` → `contract/schema.json`; `ui/schemas/LinkedSources.json` → `pnpm generate`) | regenerates | S10 — generated artifacts, never hand-edited |

### Data Models

```python
# packages/ai-parrot/src/parrot/outputs/a2ui/linked/models.py  (M1)
class PythonTransform(BaseModel):
    """Server-side registered transformer applied to the fetched frame (G1: name, never code)."""
    model_config = _CFG
    transformer: str                    # registered name in transformer_registry
    params: dict[str, Any] = Field(default_factory=dict)
    input_alias: str = "source"         # alias the frame is handed under (OQ-B)
    output: str | None = None           # output-dict key override (OQ-C; like multi_output)

class TransformSpec(BaseModel):
    """Exactly one of: inline DSL ops, catalogued renderer module, or server-side Python transformer."""
    ops: list[TransformOp] | None = None
    ref: TransformRef | None = None
    python: PythonTransform | None = None   # NEW — XOR of three
```

```python
# endpoint request/response (M5; params only — S2)
class SourceDataRequest(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict)   # placeholder overrides; locked names ignored

# response body (JSON)
# {"status": "success", "key": "<key>", "rows": [...], "truncated": bool,
#  "snapshot_at": "<ISO|null>", "warnings": [...]}
```

### New Public Interfaces

```python
# packages/ai-parrot/src/parrot/outputs/a2ui/linked/pytransform.py  (M2 — new module)
def validate_python_transform(spec: PythonTransform) -> list[str]:
    """Build/persist-time gate (S5/S8): registry membership + alias-vs-manifest check.

    Returns human-readable problems (empty = pass). Never executes the transformer.
    """

def select_output_frame(result: Mapping[str, Any], output: str | None) -> "pd.DataFrame":
    """Reduce a transformer's returned dict to ONE frame (OQ-C/S6).

    `output` override → "result" key → sole key → TransformStageError("transform_invalid_output").
    Accepts pd.DataFrame or list-of-mapping values; rejects scalars/nested dicts.
    """

async def apply_python_transform(frame: "pd.DataFrame", spec: PythonTransform,
                                 *, max_rows: int) -> "pd.DataFrame":
    """Run the registered transformer off-thread and cap the result (S9).

    Raises TransformStageError with a stable code: transformer_not_registered |
    transform_failed | transform_invalid_output (all → 422, S7).
    """

class TransformStageError(Exception):
    """Transform-stage failure; `.code` is a stable key of executor.ERROR_STATUS."""
```

```python
# packages/ai-parrot/src/parrot/outputs/a2ui/linked/service.py  (M4)
class LinkedSurfaceService:
    async def fetch_source(self, envelope: dict[str, Any], key: str, *,
                           params: Mapping[str, Any], pctx: "PermissionContext") -> SourceFetchOutcome:
        """One-source guarded fetch+transform for the /sources/{key}/data endpoint (S1).

        Reconstructs conditions from the persisted descriptor (never from the caller — S2),
        executes under `pctx` (viewer or owner per the identity rule), applies the python
        transformer when declared, returns JSON-safe records. Never persists.
        """
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: wire model + schema regen | yes | field names/defaults fixed above; XOR + terminal validators specified; regen via `linked/schema.py::write_json_schema` | — |
| M2: pytransform core | yes | signatures + error codes fixed above; selection rule mirrors `fetch.ts::selectFrame` | — |
| M3: executor integration | yes | branch point `executor.py:284-288`; ERROR_STATUS additions enumerated | — |
| M4: service gate + fetch_source | yes | `fetch_source` contract above; gate wired into `validate_for_persistence` (`service.py:115`) | — |
| M5: HTTP endpoint | yes | route, dispatch suffix, identity rule, request model and response shape fixed | — |
| M6: toolkit gate | yes | gate call + `InvalidConditionsError` mapping; param surface unchanged otherwise | — |
| M7: TS lane | yes | generated types + branch points `fetch.ts:61` / `index.ts:265-268`; behavior table in §2 | — |
| M8: docs | yes | sections enumerated | — |

### Module 1: Wire model + schema regeneration
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/linked/models.py`,
  `.../linked/contract/schema.json` (regenerated), `packages/ai-parrot-server/ui/schemas/LinkedSources.json` (regenerated)
- **Responsibility**: `PythonTransform` model; `TransformSpec` XOR of three;
  `DerivedDataSource` also rejects `python`; `LinkedSources` cross-source
  terminal rule (no `derived.from`, `Join.with`, `Union.sources` referencing a
  python-transformed sibling — proposal U3); schema regeneration (S10).
- **Depends on**: — (first module)
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot/src/parrot/outputs/a2ui/linked/models.py:178
  class PythonTransform(BaseModel):   # new, above TransformSpec
      """Server-side registered transformer (G1: referenced by name, never code)."""
      transformer: str
      params: dict[str, Any] = Field(default_factory=dict)
      input_alias: str = "source"
      output: str | None = None

  class TransformSpec(BaseModel):     # verified: linked/models.py:178
      """Exactly one of 'ops', 'ref' or 'python'."""
      ops: list[TransformOp] | None = None
      ref: TransformRef | None = None
      python: PythonTransform | None = None
      @model_validator(mode="after")
      def _xor(self) -> TransformSpec: ...   # exactly-one-of-three (was two-way at models.py:186-189)

  class DerivedDataSource(BaseModel):  # verified: linked/models.py:226
      @model_validator(mode="after")
      def _ops_only(self) -> DerivedDataSource: ...  # extend models.py:257-261: reject python too

  class LinkedSources(RootModel[...]): # verified: linked/models.py:267
      @model_validator(mode="after")
      def _python_terminal(self) -> LinkedSources:
          """Reject derived/join/union references to a python-transformed sibling (U3)."""
  ```

### Module 2: pytransform core (new module)
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/linked/pytransform.py` (CREATE)
- **Responsibility**: `validate_python_transform` (S5/S8 gate: registry
  membership; when the manifest declares `requires_columns` aliases, the
  declared `input_alias` must be one of them — and the manifest must declare
  at most one input alias: multi-input transformers are build-time rejects in
  v1), `select_output_frame` (S6), `apply_python_transform` (off-thread run +
  post-transform `max_rows` cap, S9), `TransformStageError` with stable codes
  (S7). Imports `transformer_registry` lazily (function-local, matching the
  `linked/` one-way-import discipline, `service.py:117`).
- **Depends on**: M1 (`PythonTransform`)
- **Interface Skeleton**: see §2 New Public Interfaces (verbatim contract).

### Module 3: Executor integration
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/linked/executor.py`
- **Responsibility**: python branch in `_run_source` (next to the ref-skip
  branch, `executor.py:284-288`); ERROR_STATUS gains
  `transformer_not_registered: 422`, `transform_failed: 422`,
  `transform_invalid_output: 422` (`executor.py:27-32`); `TransformStageError`
  caught and mapped distinctly from data-stage errors (S7); post-transform cap
  applied via `apply_python_transform(max_rows=max_fetch_rows)`.
  `dependencies_of` (`executor.py:100-112`) needs no change: a python spec has
  `ops=None`, so it contributes no edges — assert this in tests.
- **Depends on**: M2
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot/src/parrot/outputs/a2ui/linked/executor.py:284
  # inside _run_source (verified: executor.py:231):
  #   if src.transform is not None and src.transform.python is not None:
  #       frame = await apply_python_transform(frame, src.transform.python, max_rows=max_fetch_rows)
  #   elif src.transform.ref is not None: ...  (existing skip-warning branch)
  ```

### Module 4: Service gate + fetch_source
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/linked/service.py`
- **Responsibility**: `validate_for_persistence` (`service.py:115`) runs
  `validate_python_transform` for every python source and raises the existing
  validation error path (→ 422 at callers) when the gate fails — an
  unregistered transformer is a persist-time reject, not a runtime surprise;
  new `fetch_source(envelope, key, *, params, pctx)` (S1/S2): locates the
  descriptor, `_require_guard` + `_assert_sources_allowed` under `pctx`,
  derives per-source conditions exactly as `refresh` does (broadcast rules
  N/A — single source), runs `execute_sources` for that one source, returns a
  `SourceFetchOutcome` (records via `frame_to_records`, verified
  `linked/dsl.py:97`; `truncated`; `snapshot_at`; `warnings`;
  `error_status/error_code`). Never persists.
- **Depends on**: M2, M3
- **Interface Skeleton**: see §2 New Public Interfaces.

### Module 5: HTTP endpoint
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py`,
  `packages/ai-parrot-server/src/parrot/manager/manager.py`,
  `packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py`
- **Responsibility**: route
  `POST /api/v1/ui/surfaces/{surface_id}/sources/{key}/data` (register next to
  `manager.py:2422`); dispatch via `path.endswith("/data")` in `post()`
  (`ui_surfaces.py:402-409`); access via `_resolve_surface_for_access`
  (`ui_surfaces.py:430`, `?share=` token honored — S3); **identity rule**:
  authenticated viewer → `build_principal_context(viewer_user_id,
  channel="ui_surfaces")` (import verified `ui_surfaces.py:31`); share-token
  access (no session user) → owner pctx (`record.user_id`), mirroring
  `_refresh`'s owner rule (`ui_surfaces.py:645-647`); body validated as
  `SourceDataRequest` (params only — S2); error mapping like
  `_refresh_linked` (`ui_surfaces.py:688-710`): `LinkedGuardRequired` → 403,
  `AuthorizationRequired` → 403, executor codes via their ERROR_STATUS (404
  "unavailable" semantics preserved), unknown `key` → 404, transform-stage
  codes → 422.
- **Depends on**: M4
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py:402 (post() dispatch)
  async def _source_data(self) -> web.Response:
      """POST /api/v1/ui/surfaces/{surface_id}/sources/{key}/data — guarded one-source fetch.

      Returns {"status","key","rows","truncated","snapshot_at","warnings"}; never persists.
      """
  ```

### Module 6: Toolkit build gate
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py`
- **Responsibility**: the `transform` dict params (single-widget
  `toolkit.py:361`, dashboard sources `toolkit.py:617-637`) already pass
  through `TransformSpec.model_validate` — M1 makes `python` parse; this
  module adds the build-time gate: after validation, run
  `validate_python_transform` and raise `InvalidConditionsError` with the
  gate's problems (S8), so an agent gets a correcting tool error instead of a
  broken surface. Docstrings updated to document the `python` member.
- **Depends on**: M1, M2
- **Interface Skeleton**: no new public names — gate call inside the existing
  validation blocks (`toolkit.py:487-499` widget lane, `toolkit.py:628-637`
  dashboard lane).

### Module 7: TS renderer lane
- **Path**: `packages/ai-parrot-server/ui/src/lib/types/generated/LinkedSources*` (via
  `pnpm generate` — never hand-edited), `ui/.../a2ui/linked/types.ts`,
  `ui/.../a2ui/linked/fetch.ts`, `ui/.../a2ui/linked/index.ts`,
  `ui/.../a2ui/A2UISurface.svelte`
- **Responsibility**: regenerate types from the updated
  `ui/schemas/LinkedSources.json` (S10; drift guarded by
  `packages/ai-parrot-server/tests/test_ts_codegen.py`); `types.ts` re-exports
  `PythonTransform`; new `fetchSourceData(surfaceId, key, params, opts)` in
  `fetch.ts` posting to the endpoint (share token propagated as `?share=` —
  S3); `index.ts` lane branch (`index.ts:265-268`): python source → endpoint
  fetch, **no** `applyTransform`; without `persistedSurfaceId` the source is
  snapshot-only with per-source refresh disabled and a visible "saved data"
  state (S4) — never a direct-QuerySource fallback; `refreshSource` dependency
  logic unchanged (python sources are terminal).
- **Depends on**: M1 (schema), M5 (endpoint contract)
- **Interface Skeleton**:
  ```typescript
  // adds to ui/.../a2ui/linked/fetch.ts (fetchSource verified: fetch.ts:61)
  export async function fetchSourceData(
    src: LinkedDataSource, params: Record<string, unknown>,
    opts: { surfaceBaseUrl: string; surfaceId: string; shareToken?: string; headers: HeadersInit },
  ): Promise<Row[]>;  // POST .../sources/{key}/data; 404 → SourceUnavailable (never "denied")
  ```

### Module 8: Documentation
- **Path**: `docs/outputs/a2ui-linked-surfaces.md` (§5 Transforms, §3 fetch
  path, §6 trust model), toolkit docstrings already in M6; a short §
  "Python transformers" with the identity rule and the persisted-only dynamic
  fetch behavior.
- **Depends on**: M1–M7

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_transform_spec_xor_three` | M1 | exactly-one-of `ops`/`ref`/`python`; all invalid combos raise |
| `test_derived_rejects_python` | M1 | `DerivedDataSource` with `python` raises |
| `test_python_source_is_terminal` | M1 | derived `from`/`join.with`/`union.sources` naming a python source raises (U3) |
| `test_schema_regenerated` | M1 | `contract/schema.json` == `dumps_schema()` output (existing contract test pattern) |
| `test_validate_python_transform_gate` | M2 | unregistered name; alias not in manifest; multi-input manifest → problems (S5/S8) |
| `test_select_output_frame_rule` | M2 | `output` override → `result` → sole key → `transform_invalid_output`; DataFrame + records accepted; scalars rejected (S6) |
| `test_apply_python_transform_cap` | M2 | row-expanding transformer capped at `max_rows` (S9) |
| `test_executor_python_branch` | M3 | `_run_source` applies the transformer; `ref` skip branch untouched |
| `test_transform_stage_codes` | M3 | `TransformStageError` → 422 codes, distinct from `data_stage` 502 (S7) |
| `test_dependencies_of_python_none` | M3 | python spec contributes no dependency edges |
| `test_persist_gate_unregistered` | M4 | `validate_for_persistence` rejects unregistered transformer |
| `test_fetch_source_conditions_server_side` | M4 | body params only; locked respected; conditions from descriptor (S2) |
| `test_toolkit_python_gate` | M6 | `qs_build_linked_surface` with bad python spec → `InvalidConditionsError` |

### Integration Tests

| Test | Description |
|---|---|
| `test_source_data_endpoint_auth_matrix` | owner / authenticated viewer (allowed + PBAC-denied) / share token (owner pctx) / no guard 403 / unknown key 404 / wrong surface 404 (S3/S11) |
| `test_source_data_transform_errors` | unregistered → 422; failing transformer → 422; slug error → existing 404/502 codes |
| `test_python_lane_parity` | endpoint rows == `ensure_snapshot`/`refresh` rows for the same descriptor+params (S11) |
| `test_linked_golden_unchanged` | existing golden/parity suites pass byte-identical for descriptors without `python` |
| `fetch.test.ts` / `index.test.ts` additions | endpoint branch, share-token propagation, no client `applyTransform`, snapshot-only when not persisted (S4) |
| `test_ts_codegen.py` | regenerated `LinkedSources` types drift-free (S10) |

### Test Data / Fixtures

```python
@pytest.fixture
def py_transformer():
    """Register a scoped test transformer (monkeypatched registry) returning {'result': [...]}."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] AC1 — `TransformSpec` enforces exactly-one-of `ops`/`ref`/`python`; `DerivedDataSource` rejects `python`.
- [ ] AC2 — A python-transformed source is terminal: validation rejects any derived/join/union sibling referencing it (U3).
- [ ] AC3 — `contract/schema.json` and `ui/schemas/LinkedSources.json` are regenerated from the models and `test_ts_codegen.py` passes; `src/lib/types/generated/` is produced by `pnpm generate`, never hand-edited (S10).
- [ ] AC4 — One shared code path (`apply_python_transform` + `select_output_frame`) serves bake, persist, server refresh and the endpoint; parity test proves identical rows (S1/S6).
- [ ] AC5 — Transform-stage failures map to stable 422 codes (`transformer_not_registered`, `transform_failed`, `transform_invalid_output`), distinct from data-stage 502/404 (S7).
- [ ] AC6 — The transformed frame is capped at `max_fetch_rows` post-transform; snapshot stays ≤ 500 rows; `GET` never executes (S9).
- [ ] AC7 — The endpoint accepts parameter overrides only; conditions are reconstructed server-side from the persisted descriptor; `locked` names are ignored (S2).
- [ ] AC8 — Identity rule enforced and tested: authenticated viewer → viewer pctx; share token → owner pctx; no guard → 403; PBAC denial → 403; unknown key/surface → 404 (U1/U4/S3).
- [ ] AC9 — Persist-time gate: an envelope naming an unregistered transformer (or an alias outside the manifest) is rejected at `validate_for_persistence` and at `qs_build_linked_surface` (S5/S8).
- [ ] AC10 — TS lane: python sources fetch via the endpoint (share token propagated), never direct QuerySource, no client `applyTransform`; non-persisted surfaces render snapshot-only with per-source refresh disabled (S4).
- [ ] AC11 — Descriptors without `python` behave byte-identically: existing linked golden/parity/vitest suites pass unchanged.
- [ ] AC12 — Docs updated: `docs/outputs/a2ui-linked-surfaces.md` (§3/§5/§6) + toolkit docstrings document the member, identity rule and persisted-only dynamic fetch.
- [ ] AC13 — No new external dependencies; `ruff check` clean on touched files.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor** — verified against `36ba87b58` (dev, 2026-10-06).

### Verified Imports

```python
from parrot.outputs.a2ui.linked.models import LinkedDataSource, LinkedSources, TransformSpec  # verified: linked/__init__.py:31,103
from parrot.outputs.a2ui.linked import has_data_sources                       # verified: linked/__init__.py:62,105
from parrot.outputs.a2ui.linked.service import LinkedGuardRequired, LinkedSurfaceService, SnapshotError  # verified: ui_surfaces.py:47
from parrot.outputs.a2ui.linked.executor import ERROR_STATUS, execute_sources # verified: service.py:127,162
from parrot.outputs.a2ui.linked.dsl import apply_transform, frame_to_records  # verified: executor.py:250; dsl.py:97
from parrot.outputs.a2ui.recipes.transformers import transformer_registry, infographic_transformer, validate_inputs  # verified: recipes/transformers.py (module)
from parrot.auth.permission import build_principal_context                    # verified: ui_surfaces.py:31
from parrot.auth.exceptions import AuthorizationRequired                      # verified: service.py:19
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/outputs/a2ui/linked/models.py
class TransformSpec(BaseModel):                      # line 178; XOR validator at 185-189
    ops: list[TransformOp] | None = None             # line 182
    ref: TransformRef | None = None                  # line 183
class LinkedDataSource(BaseModel):                   # line 192; kind: Literal["query_slug"]
    transform: TransformSpec | None = None           # line 205
class DerivedDataSource(BaseModel):                  # line 226; _ops_only validator at 257-261 (rejects ref)
class LinkedSources(RootModel[dict[str, LinkedSource]]):  # line 267; _default_kind 270-287; _check_keys 289-295

# packages/ai-parrot/src/parrot/outputs/a2ui/linked/executor.py
ERROR_STATUS: dict[str, int]                         # line 27: query_not_found 404, tenant_not_available 404,
                                                     #          tenant_store_unavailable 503, data_stage 502
def dependencies_of(src: LinkedSource) -> list[str]  # line 100 (reads transform.ops only)
async def _run_source(key, src, overrides, frames, *, sources, principal, pctx, guard,
                      max_fetch_rows, probed=()) -> pd.DataFrame   # line 231; ref-skip at 284-285
async def execute_sources(sources, *, param_overrides=None, pctx, guard,
                          max_snapshot_rows, max_fetch_rows) -> ExecutionOutcome  # line 298

# packages/ai-parrot/src/parrot/outputs/a2ui/linked/service.py
class LinkedSurfaceService:                          # line 67
    def __init__(self, *, guard, max_fetch_rows=5000, max_snapshot_rows=500)  # line 76
    async def _assert_sources_allowed(self, sources, owner_pctx) -> None      # line 87
    async def validate_for_persistence(self, envelope, *, owner_pctx) -> None # line 115
    async def ensure_snapshot(self, envelope, *, owner_pctx) -> dict          # line 125
    async def refresh(self, envelope, *, params, owner_pctx) -> RefreshOutcome  # line 158

# packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py
async def resolve_surface_access(store, surface_id, user_id, token, scope=None)  # line 167 (module-level, shared)
class UISurfacesHandler(BaseView):                   # line 313 (@is_authenticated/@user_session at 313-314)
    def _linked_service(self) -> LinkedSurfaceService    # line 346
    def _recipe_runner(self) -> RecipeRunner | None      # line 358
    async def post(self) -> web.Response                 # line 402: dispatch by path suffix
    async def _resolve_surface_for_access(...)           # line 430
    async def _refresh(self) -> web.Response             # line 617; owner pctx at 645-647
    async def _refresh_linked(...)                       # line 688; 403/404 mapping 699-710

# packages/ai-parrot/src/parrot/outputs/a2ui/recipes/transformers.py
TransformerFunc = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
class TransformerRegistry:
    def register(self, name, func, *, requires_columns=None, description="", params_schema=None)
    def get(self, name) -> RegisteredTransformer     # KeyError lists available names
    def manifest(self, name) -> TransformerManifest
transformer_registry = TransformerRegistry()          # process-wide, import side effect

# packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py
#   qs_build_linked_surface(..., transform: dict[str, Any] | None = None, ...)  # line 355-362
#   widget-lane TransformSpec.model_validate at 487-499; dashboard lane at 628-637
```

```typescript
// packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/
// types.ts:8-19 — re-exports GENERATED types from $lib/types/generated/LinkedSources
// fetch.ts:61  — fetchSource(src, conditions, {baseUrl, headers, maxFetchRows}) → direct QuerySource
// fetch.ts:13  — DEFAULT_MAX_FETCH_ROWS = 5000
// index.ts:265 — rawRows = await fetchSource(...); index.ts:268 — applyTransform(rawRows, src.transform, frames)
// $lib/api/querysource.ts:29-37 — queryUrl: tenant → /api/v1/{t}/queries; multiquery → /api/v3; else /api/v2/services/queries
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `PythonTransform` | `TransformSpec` XOR validator | new member | `linked/models.py:185-189` |
| `apply_python_transform` | `transformer_registry.get()` | function-local import | `recipes/transformers.py` (module) |
| executor python branch | `_run_source` transform block | `elif src.transform.python` | `linked/executor.py:284-288` |
| `fetch_source` | `execute_sources` | one-source call | `linked/service.py:184-191` (refresh's call shape) |
| `_source_data` | `post()` suffix dispatch | `path.endswith("/data")` | `ui_surfaces.py:402-409` |
| route | `router.add_view` | new line | `manager/manager.py:2422` |
| `fetchSourceData` | `LinkedLane` fetch branch | python-source check | `linked/index.ts:265-268` |
| schema regen | `write_json_schema()` | CLI/`python -m` | `linked/schema.py:31-37` |

### Does NOT Exist (Anti-Hallucination)

- ~~`TransformSpec.python`~~ — does not exist yet (M1 adds it); today's XOR is two-way (`models.py:186-189`).
- ~~a per-source HTTP data endpoint~~ — only `/api/v1/ui/surfaces[/{id}[/refresh|/share[/{token}]]]` exist (`manager.py:2420-2425`).
- ~~`LinkedSurfaceService.fetch_source`~~ — does not exist (M4 adds it); today's entry points are `validate_for_persistence` / `ensure_snapshot` / `refresh` only.
- ~~`parrot.outputs.a2ui.linked.pytransform`~~ — module does not exist (M2 creates it).
- ~~`validate_inputs` accepting a linked descriptor~~ — it takes a recipe `TransformStep` (`recipes/transformers.py`); the linked gate is new (S8).
- ~~`RecipeRunner` involvement in linked surfaces~~ — recipes lane (`recipe_name` set) is disjoint from the linked lane (`ui_surfaces.py:648-649`); this feature never calls `RecipeRunner`.
- ~~viewer-identity execution in today's server lanes~~ — every existing server execution uses the OWNER's pctx (`ui_surfaces.py:645-647`); viewer-pctx execution is new (M5).
- ~~`transform.ref` running in Python~~ — skipped with a warning (`executor.py:284-285`); mirror precedent for `python` never running in TS.

### Edit Sites (Blueprint Anchors)

Verified against: `36ba87b58`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/models.py` | MODIFY | `class TransformSpec(BaseModel):` | `models.py:178` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/models.py` | MODIFY | `class DerivedDataSource(BaseModel):` | `models.py:226` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/models.py` | MODIFY | `class LinkedSources(RootModel[dict[str, LinkedSource]]):` | `models.py:267` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/pytransform.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/executor.py` | MODIFY | `ERROR_STATUS: dict[str, int] = {` | `executor.py:27` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/executor.py` | MODIFY | `if src.transform is not None and src.transform.ref is not None:` | `executor.py:284` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/service.py` | MODIFY | `async def validate_for_persistence(self, envelope: CreateSurface, *, owner_pctx: "PermissionContext") -> None:` | `service.py:115` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/service.py` | MODIFY | `async def refresh(` | `service.py:158` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/schema.json` | MODIFY (regenerated) | — (run `python -m parrot.outputs.a2ui.linked.schema`) | `schema.py:31-37` | — |
| `packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py` | MODIFY | `if path.endswith("/refresh"):` | `ui_surfaces.py:405` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py` | MODIFY | (add `SourceDataRequest` beside `RefreshSurfaceRequest`) | `(unverified — check before use)` | — |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | `router.add_view("/api/v1/ui/surfaces/{surface_id}/refresh", UISurfacesHandler)` | `manager.py:2422` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py` | MODIFY | `transform = TransformSpec.model_validate(widget.transform)` | `toolkit.py:489` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py` | MODIFY | `transform=TransformSpec.model_validate(transform) if transform else None,` | `toolkit.py:637` | 1 |
| `packages/ai-parrot-server/ui/schemas/LinkedSources.json` | MODIFY (regenerated) | — | — | — |
| `packages/ai-parrot-server/ui/src/lib/types/generated/LinkedSources.d.ts` | MODIFY (via `pnpm generate`) | — | — | — |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/types.ts` | MODIFY | `  TransformSpec,` (import block from generated) | `types.ts:17` | 2 — import at 9-19 AND re-export at 20-30; anchor within the `import type {` block |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/fetch.ts` | MODIFY | `export async function fetchSource(` | `fetch.ts:61` | 1 |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/index.ts` | MODIFY | `const rawRows = await fetchSource(src, conditions, { baseUrl: opts.baseUrl, headers: opts.headers() });` | `index.ts:265` | 1 |
| `docs/outputs/a2ui-linked-surfaces.md` | MODIFY | `## 5. Transforms — DSL v1 and \`transform.ref\`` | §5 heading | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Lane asymmetry à la `transform.ref`**: explicit validator rejections and a
  documented "runs only in X lane" rule — never silent divergence
  (`models.py:257-261`, `executor.py:284-285`).
- **Fail-closed trust model**: guard mandatory (`LinkedGuardRequired` → 403);
  denials surface as 404 "unavailable", never "denied" (FEAT-598 §7 risks).
- **Function-local imports in `linked/`**: `linked/` never imports `catalog/`
  (or heavyweight deps) at module import time (`service.py:117`); the
  `transformer_registry` import in M2 follows the same discipline.
- **Error responses built directly** via `json_response`, never
  `BaseView.error()` (status whitelist landmine — `ui_surfaces.py:377-389`).
- **Deep-copy conditions** before handing them to a data source (querysource
  parsers mutate nested dicts — `executor.py:281-283`).
- **Generated artifacts are regenerated, never hand-edited**: `contract/schema.json`
  via `write_json_schema()`, UI types via `pnpm generate` (S10).

### Known Risks / Gotchas

- **Transformer availability is an import side effect** — a server that never
  imported the module (boot wiring / `load_transformer_module`) will 422 on
  `transformer_not_registered` even for a validly-persisted surface (the
  owner's process had it registered; the serving process may not). Mitigation:
  AC9's persist gate + documented operator wiring in M8; the 422 payload lists
  available names (registry `get()` already does).
- **Identity duality doubles the auth paths** (viewer pctx vs owner pctx for
  shares): the auth matrix in §4 is mandatory, not optional (S3/S11).
- **Non-persisted surfaces have no server record** — the renderer must treat
  python sources as snapshot-only until persisted; a silent direct-QuerySource
  fallback would drop the transform and leak untransformed rows (S4).
- **Row expansion**: a transformer can synthesize rows; without the
  post-transform cap the endpoint response is unbounded (S9).
- **`validate_inputs` empty-frame check**: the recipes gate rejects empty
  input frames; for linked sources an empty slug result is legitimate
  (FEAT-598 ledger issue 819e882f4064 context) — the linked gate (M2) must
  NOT reject empty frames at runtime; emptiness handling belongs to the
  transformer.
- **Vitest/golden fixtures are parity-pinned** (`contract/fixtures/`,
  `parity.test.ts`): M1's schema change regenerates fixtures only where the
  schema file itself is asserted; row-level golden tests must stay untouched
  (AC11).

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| — | — | no new dependencies; pandas/pydantic/aiohttp already in place |

---

## 8. Open Questions

> All design-level questions were resolved in the proposal's Q&A
> (`sdd/proposals/linked-a2ui-recipes-transforms.proposal.md` §5).

- [x] Identity for the per-source endpoint — *Resolved in proposal (U1/U4)*:
  viewer pctx for authenticated sessions; owner pctx for share-token viewers;
  share viewers included from day one.
- [x] Transformer name vs recipe reference — *Resolved in proposal (U2)*:
  registered transformer name + params in v1; recipe (`name@owner`) reference
  is phase 2, out of scope.
- [x] Chaining after the transformer — *Resolved in proposal (U3)*: terminal
  in v1 — no DSL ops after it, no derived/join/union sibling references.
- [x] Wire shape + endpoint path — *Resolved in proposal (OQ-A)*: third
  `TransformSpec` member + `POST /api/v1/ui/surfaces/{surface_id}/sources/{key}/data`.
- [x] Input adaptation — *Resolved in proposal (OQ-B)*: optional
  `input_alias`, default `"source"`; manifest-checked at build time.
- [x] Output adaptation — *Resolved in proposal (OQ-C)*: multi-frame
  selection rule (`output` override → `result` → sole key → error).

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted proposal**
> (never over this spec). Model: `gpt-5.6-luna` · Status: completed
> · Transcript: `sdd/state/FEAT-636/design_research/`

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Put one-source execution behind LinkedSurfaceService (architecture) | CONFIRM | guard/auth/error mapping must stay in the service; handler resolves access + serializes only | §2 Overview, §3 M4/M5 |
| S2 | Accept parameter overrides, not client-supplied conditions (api) | CONFIRM | raw conditions would let a client bypass `locked`/caps; server reconstructs from the descriptor | §2, §3 M5, AC7 |
| S3 | Resolve viewer-vs-owner identity + share-token propagation explicitly (risk) | CONFIRM | matches proposal U1/U4; spec pins the pctx rule and share propagation through the TS lane | §2, §3 M5/M7, AC8 |
| S4 | Specify non-persisted-surface behavior (architecture) | CONFIRM | snapshot-only + refresh disabled; never a silent direct-QuerySource fallback | §2, §3 M7, AC10, §7 risks |
| S5 | Align input_alias with the registry manifest contract (api) | CONFIRM | gate checks alias against `requires_columns` and rejects multi-input manifests in v1 | §3 M2, AC9 |
| S6 | Define the result-to-rows contract (api) | CONFIRM | shared `select_output_frame`: DataFrame or records; scalars/ambiguity rejected deterministically | §2, §3 M2, AC4 |
| S7 | Separate transform-stage from data-stage failures (risk) | CONFIRM | three stable 422 codes added to ERROR_STATUS, distinct from data_stage 502 | §3 M3, AC5 |
| S8 | Shared linked-transform validation gate (architecture) | CONFIRM | one `validate_python_transform` used by toolkit, persistence and runtime | §3 M2/M4/M6, AC9 |
| S9 | Enforce row/serialization limits post-transform (risk) | CONFIRM | `max_fetch_rows` cap inside `apply_python_transform`; `frame_to_records` serialization | §3 M2, AC6 |
| S10 | Update the Python schema source and regenerate UI types (api) | CONFIRM | both schema artifacts + `pnpm generate` + `test_ts_codegen.py` are in M1/M7 | §3 M1/M7, AC3 |
| S11 | End-to-end matrix for auth, parity and lane routing (testing) | CONFIRM | adopted as §4's integration matrix | §4 |
| S12 | Persisted/server-refresh-only first phase (alternative) | REJECT | dynamic renderer fetch for persisted surfaces IS the feature (user-decided scope, proposal U1/U4); S4's persisted-only rule already bounds the new surface — non-persisted envelopes get no endpoint at all | — |

Summary: **11** confirmed · **1** rejected · **0** escalated.

---

## Worktree Strategy

- **Isolation**: ONE feature worktree for FEAT-636
  (`.claude/worktrees/feat-FEAT-636-linked-a2ui-recipes-transforms`); the
  `sdd-coder` engine gives each task its own sub-worktree inside it.
- **Module dependency graph**:
  - M2 → M1 (imports `PythonTransform` from `models.py`)
  - M3 → M2 (imports `apply_python_transform`, `TransformStageError`)
  - M4 → M2, M3 (gate + error codes)
  - M5 → M4 (calls `fetch_source`)
  - M6 → M1, M2 (model parse + gate)
  - M7 → M1 (regenerated schema), M5 (endpoint contract)
  - M8 → M1–M7 (documents the final behavior)
  - No edge between M5 and M6, or M6 and M7 — expected to run concurrently.
- **Shared files**: `models.py` (M1 only), `executor.py` (M3 only),
  `service.py` (M4 only), `ui_surfaces.py` (M5 only), `toolkit.py` (M6 only)
  — no file is modified by two modules.
- **Exclusive resources**: `pnpm generate` (M7) rewrites
  `ui/src/lib/types/generated/` — M7's regen task is `parallel: false`
  against other UI tasks.
- **Cross-feature dependencies**: none — FEAT-598/FEAT-611 are merged on
  `dev`; this feature builds on their landed state (`36ba87b58`).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-06 | Jesus Lara + Claude | Initial draft from accepted proposal + codex design research (11C/1R/0E) |
