---
id: FW-003
query_id: Q006
type: wiki_page
intent: "Semantic construction / hand-off contracts already researched in FEAT-769, and decisions on the governed hand-off (Q006 + Q007)."
executed_at: 2026-11-11T22:20:00Z
duration_ms: 0
parent_id: null
depth: 1
---

# FW-003 — The semantic→DatasetManager hand-off (M9H) deliberately rejects a bare DatasetManager: governed rows may only land in a host `GovernedDatasetSink` that re-authorizes every read

## Summary

The existing direction (semantic result → dataset) is `save_result_as_dataset`, exposed only when the
host passes `dataset_manager_factory`, an async callable `(SemanticRequestIdentity) -> GovernedDatasetSink`.
The sink is a `runtime_checkable` Protocol (`scope_id`, immutable 4-tuple `owner`, `guarded_reads=True`,
async `publish(name, handle, authorize_read)`). `_validate_sink` rejects anything whose MRO contains
`DatasetManager`, `AbstractToolkit` or `DataFrame`; there is no default session-manager adapter. The
documented rationale (TASK-4709, M9H): a retained snapshot of governed rows must stay governed — every
list/metadata/sample/cache/query/export/derived read re-invokes `authorize_read` with the *current*
caller identity, and "automatic semantic authorization in `DatasetManager.add_dataframe()`" is listed
under Does-NOT-Exist. The sanctioned ungoverned surfaces are a policy with `governed: false` and
`sl_compile_query`, which returns compiled SQL without executing it.

## Citations

- wiki: `file:sdd/state/FEAT-769/findings/F008-construction-and-surface-contracts.md` (Q007 score=0.42), `file:sdd/tasks/completed/TASK-4709-semantic-guarded-dataset-sink.md` (score=0.10), `file:wiki/tools/semantic-layer.md` (score=0.11), `sym:packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py#SemanticLayerToolkit._dataset_manager_for` (score=1.00), `sym:packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py#SemanticLayerToolkit.save_result_as_dataset` (score=0.33)
- path: `wiki/tools/semantic-layer.md`
  lines: 100-112
  symbol: `Guarded dataset hand-off`
  excerpt: |
    ## Guarded dataset hand-off
    A bare `DatasetManager`, dataframe, or plain manager factory is rejected. The
    host adapter must declare guarded reads, immutable owner scope, async publish,
    and pass the sink conformance tests; without it the hand-off tool is not
- path: `wiki/tools/semantic-layer.md`
  lines: 46
  symbol: `Authorization and identity`
  excerpt: |
    request. Only a policy with `governed: false` opts out explicitly.
- path: `wiki/tools/semantic-layer.md`
  lines: 81-88
  symbol: `Tools and audit`
  excerpt: |
    | `sl_compile_query` | `compile_query(query: SemanticQuery)` |
    `allow_raw_sql: true` enables it; it still uses model-manifest authorization,
- path: `wiki/tools/semantic-layer.md`
  lines: 184
  symbol: `Example agents`
  excerpt: |
    `models_ungoverned/`, which serves as the compiler surface for ad-hoc analysis.
- path: `sdd/tasks/completed/TASK-4709-semantic-guarded-dataset-sink.md`
  lines: 18-21
  symbol: `Scope`
  excerpt: |
    - Implement GovernedDatasetSink protocol: scope_id, immutable owner tuple, guarded_reads=True and async publish(name, handle, authorize_read). Reject raw/shared DatasetManager targets; no default session-manager adapter.
    - Capability flags alone are not proof. [...] No unguarded manager, source, dataframe reference or alternate endpoint may escape. Callback uses current caller identity, never captured original context.
- path: `sdd/tasks/completed/TASK-4709-semantic-guarded-dataset-sink.md`
  lines: 87
  symbol: `Does NOT Exist`
  excerpt: |
    - Automatic semantic authorization in `DatasetManager.add_dataframe()` — retained snapshots require the guarded host-sink contract.
- path: `packages/ai-parrot-semantic/src/parrot/semantic/handoff.py`
  lines: 24-45
  symbol: `GovernedDatasetSink`
  excerpt: |
    _RAW_TYPE_NAMES = frozenset({"DatasetManager", "AbstractToolkit", "DataFrame"})
    class GovernedDatasetSink(Protocol): async def publish(self, name, handle, authorize_read) -> dict[str, Any]
- path: `packages/ai-parrot-semantic/src/parrot/semantic/handoff.py`
  lines: 54-118
  symbol: `_validate_sink`
  excerpt: |
    `_validate_sink` and `GovernedSinkRegistry.register` reject a bare `AbstractToolkit`/`DatasetManager` with `SemanticResultError("sink_rejected", ...)`

## Notes

- The two `handoff.py` entries are quoted from FEAT-769 F008 (2026-10-29), **not re-read in this lane**.
  [cross-lane: type=read, intent=re-verify handoff.py line ranges for GovernedDatasetSink, _RAW_TYPE_NAMES, _validate_sink and build_read_authorizer on current dev]
- Design tension for FEAT-880: an `add_semantic` on a plain DatasetManager that materializes governed
  rows into `_df` and the shared Redis cache is precisely the "retained snapshot in a raw manager" that
  M9H forbids. A compliant design must (a) restrict the semantic source to `governed: false` models,
  or (b) compile + govern per fetch under the caller's identity and never cache across subjects, or
  (c) reuse the sink / `authorize_read` contract on the DatasetManager side.
- No wiki `decision` page records the M9H rationale; it lives in the FEAT-704 spec and TASK-4709 only.
- An example already wraps a private DatasetManager behind a guarded facade
  (`sym:examples/agents/semantic/agent_semantic_example.py#GuardedDatasetFacade`, score=0.08).
