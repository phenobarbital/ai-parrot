---
id: F001
query_id: Q001
type: read
intent: Pin down the FEAT-598 linked-surface contract (goals, descriptor model, non-goals) from the spec
executed_at: 2026-09-28T18:20:21Z
parent_id: null
depth: 0
---
# F001 — FEAT-598 contract: descriptors in metadata.extensions.parrot_data_sources
## Summary
FEAT-598 (spec approved 2026-09-24, all 28 tasks closed) makes an A2UI surface carry, instead of only baked rows, a
surface-level map `createSurface.metadata.extensions.parrot_data_sources` keyed by the `dataModel` root key each
source fills; components keep ordinary `{"path": "/<key>/rows"}` bindings (no new component prop). The renderer is
expected to fetch QuerySource DIRECTLY with the viewer's JWT (ai-parrot-server never proxies); the server-side Python
executor is the alternative lane (refresh / save-time snapshot). Only TOOL-origin builders may emit descriptors
(`DATA_SOURCES_NOT_ALLOWED_FOR_LLM`). No TypeScript executor is shipped for third parties — every renderer must
implement its own executor against the published JSON Schema + golden fixtures.
## Citations
- path: `sdd/specs/a2ui-linked-surfaces.spec.md`
  lines: 58-73
  symbol: `-`
  excerpt: |
    - G1 **One descriptor, one Python reference executor, N renderer executors,
      one set of golden fixtures.** ...
    - G2 **Any surface, not only widgets**: a dashboard may declare several
      sources under `createSurface.metadata.extensions.parrot_data_sources`,
      keyed by the `dataModel` root key each source fills; ...
    - G3 **The renderer fetches QuerySource directly with the viewer's JWT** on
      `POST /api/v3/queries/{slug}` (or `POST /api/v1/{tenant}/queries/{slug}`
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/linked/models.py`
  lines: 19-226
  symbol: `LinkedDataSource`, `SourceRequest`, `ParamSpec`, `RefreshPolicy`, `TransformSpec`, `LinkedSources`
  excerpt: |
    class ParamSpec(BaseModel):          # L19
    class SourceRequest(BaseModel):      # L30  placeholders/filter/fields/ordering/grouping/limit/offset
    class RefreshPolicy(BaseModel):      # L43  on_mount|manual|interval, interval_seconds >= 30
    class LinkedDataSource(BaseModel):   # L192
    class LinkedSources(RootModel[dict[str, LinkedDataSource]]):  # L226
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py`
  lines: 89
  symbol: `DATA_SOURCES_NOT_ALLOWED_FOR_LLM`
  excerpt: |
    DATA_SOURCES_NOT_ALLOWED_FOR_LLM = "DATA_SOURCES_NOT_ALLOWED_FOR_LLM"
## Implications
- The FEAT-610 dashboard must be produced by a TOOL-origin path (toolkit or `builders.build_linked_surface`), never an LLM-authored envelope.
- A standalone HTML5 (echarts + grid.js) renderer is exactly the "N renderer executors" case: it must re-implement `derive_conditions` + the DSL (or avoid transforms) against the contract fixtures.
- Non-goals to respect: no per-user principal on the agent-tool lane, no `@variables`, no raw SQL on the wire.
