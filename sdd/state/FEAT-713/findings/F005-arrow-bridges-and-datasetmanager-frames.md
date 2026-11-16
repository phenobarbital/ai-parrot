---
id: F005
query_id: Q032, Q040, Q044, Q045
type: grep
intent: "Existing Arrow bridges in core, how DatasetManager stores frames, and whether any DuckDB/Arrow-backed dataset store exists (FEAT-880 U4)."
executed_at: 2026-11-11T22:45:00Z
duration_ms: 0
parent_id: null
depth: 1
lane_ids: [FC-008, FW-003]
---

# F005 — Arrow is used only as a pandas serialisation bridge (REPL worker transport, task-memory blobs); DatasetManager holds pandas frames in `entry._df` and has no DuckDB/Arrow store

## Summary

*(FC-008)* `pyarrow` in core appears in four places: `repl_worker/transport.py` and `repl_worker/protocol.py`
(`pa.Table.from_pandas` to ship DataFrames to the REPL worker), `working_memory/task_memory/blob.py`
(Arrow blobs), `dataset_manager/sources/iceberg.py` (lazy, table creation) and a type guard in
`tools/toolkit.py`. There is no `.to_arrow()` (polars) call, no `fetch_arrow_table()` and no DuckDB
registration of an Arrow table anywhere in `packages/ai-parrot/src/parrot`. DatasetManager keeps each
dataset as a pandas `DataFrame` on `DatasetEntry._df` (set at `tool.py:278`, filled by
`materialize` at :350-356, exposed by the `df` property at :421/:426) and reads it directly from ~15 sites
in `tool.py` (schema/metadata, computed columns, filtering, the pandas hand-over at :4153, the Redis
Parquet path at :4308-4321). FEAT-880's research (its F014) reached the same conclusion: no spec, decision
or code designs a DuckDB-backed dataset store; FEAT-713's draft is the only prior art and it lists
"Modifying DatasetManager" as a non-goal, feeding frames to a `DuckDBRunner` through an injected
`frame_provider`.

*(FW-003)* The query returns, in order: FEAT-880's F014 ("no spec designs a DuckDB-backed DatasetManager store or a semantic source; the only prior art is FEAT-713"), FEAT-880's F002 ("data is held as in-memory pandas DataFrames, cached in Redis as Parquet; no DuckDB store"), FEAT-746's Arrow-footprint finding, and two DatasetManager sources whose `fetch` returns a DataFrame (`DeltaTableSource.fetch`, `IcebergSource.fetch`). No source symbol about registering frames in DuckDB surfaces. FEAT-713's own design research fixed "one compiler, two execution targets" and "DuckDB in-process, Arrow as the bridge" as an owner decision of 2026-10-20, with "Modifying DatasetManager" as a non-goal (frames via an injected `frame_provider`). FEAT-880 U4 now assigns the DuckDB-backed store to this revision, which contradicts that non-goal.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/repl_worker/transport.py`
  lines: 36-36
  symbol: `import`
  excerpt: |
    import pyarrow as pa

- path: `packages/ai-parrot/src/parrot/tools/repl_worker/transport.py`
  lines: 120-120
  symbol: `pa.Table.from_pandas`
  excerpt: |
    table = pa.Table.from_pandas(df, preserve_index=True)

- path: `packages/ai-parrot/src/parrot/tools/repl_worker/transport.py`
  lines: 191-191
  symbol: `pa.Table.from_pandas`
  excerpt: |
    table = pa.Table.from_pandas(df, preserve_index=True)

- path: `packages/ai-parrot/src/parrot/tools/repl_worker/protocol.py`
  lines: 417-426
  symbol: `pa.Table.from_pandas`
  excerpt: |
    import pyarrow as pa
    ...
    table = pa.Table.from_pandas(frame)

- path: `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/blob.py`
  lines: 244-257
  symbol: `pa.Table.from_pandas`
  excerpt: |
    import pyarrow as pa
    ...
    table = pa.Table.from_pandas(df, preserve_index=True)

- path: `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/blob.py`
  lines: 331-355
  symbol: `pa.Table.from_batches`
  excerpt: |
    table = pa.Table.from_batches(collected, schema=schema) if collected else schema.empty_table()

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/iceberg.py`
  lines: 38-38
  symbol: `import`
  excerpt: |
    import pyarrow as pa  # lazy — only needed for create_table_from_df

- path: `packages/ai-parrot/src/parrot/tools/toolkit.py`
  lines: 88-90
  symbol: `_UNSUPPORTED_SCHEMA_TYPES`
  excerpt: |
    import pyarrow as pa
    cls._UNSUPPORTED_SCHEMA_TYPES.add(pa.Table)

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py`
  lines: 278-278
  symbol: `DatasetEntry._df`
  excerpt: |
    self._df: Optional[pd.DataFrame] = df  # pre-load when df provided directly

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py`
  lines: 350-356
  symbol: `DatasetEntry.materialize`
  excerpt: |
    if self._df is None or force:
        self._df = await self.source.fetch(**params)
        ...
    return self._df

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py`
  lines: 421-426
  symbol: `DatasetEntry.df`
  excerpt: |
    return self._df
    ...
    self._df = value

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py`
  lines: 1232-1232
  symbol: `entry._df = df`
  excerpt: |
    entry._df = df

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py`
  lines: 4153-4153
  symbol: `active_loaded`
  excerpt: |
    active_loaded = {n: e._df for n, e in active_entries.items() if e.loaded and e._df is not None}

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py`
  lines: 4308-4321
  symbol: `DatasetManager.materialize`
  excerpt: |
    return entry._df
    ...
    entry._df = cached

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/memory.py`
  lines: 23-43
  symbol: `InMemorySource`
  excerpt: |
    self._df = df
    ...
    return self._df

- path: `sdd/state/FEAT-880/findings/F014-duckdb-store-and-semantic-source-prior-art.md`
  lines: 13-27
  symbol: `F014`
  excerpt: |
    # F014 — No spec designs a DuckDB-backed DatasetManager store or a semantic source; the only prior
    art is FEAT-713 (draft, undecomposed), which runs DuckDB beside DatasetManager without modifying it

- path: `sdd/state/FEAT-713/design_research/constraints_and_goals.txt`
  lines: 4-5
  symbol: `Constraints & Requirements`
  excerpt: |
    - **One compiler, two execution targets.** ... (Owner decision, 2026-10-20.)
    - **DuckDB is the in-process engine; Arrow is the bridge.** polars/pandas DataFrames are registered
      into DuckDB via Arrow (zero-copy), never serialised. No pickle across trust boundaries.

- wiki: `file:sdd/state/FEAT-880/findings/F014-duckdb-store-and-semantic-source-prior-art.md` (Q003 score=1.00)

- wiki: `file:sdd/state/FEAT-880/findings/F002-dataset-entry-lifecycle-and-runtime-storage.md` (Q003 score=0.61)

- wiki: `sym:packages/ai-parrot/src/parrot/tools/dataset_manager/sources/deltatable.py#DeltaTableSource.fetch` (Q003 score=0.31)

- wiki: `sym:packages/ai-parrot/src/parrot/tools/dataset_manager/sources/iceberg.py#IcebergSource.fetch` (Q003 score=0.11)

- wiki: `file:sdd/state/FEAT-713/design_research/recommended_option_or_scope.txt` (Q003 score=0.24)

- path: `sdd/state/FEAT-713/design_research/constraints_and_goals.txt`
  lines: 12
  symbol: `Multi-tenant, per-model security`
  excerpt: |
    Results caches are never shared across security contexts (research rule).

- path: `sdd/specs/accounting-metrics-layer.spec.md`
  lines: 172
  symbol: `Integration Points`
  excerpt: |
    | `DatasetManager` | **not modified** | frames reach the DuckDB runner through an injected `frame_provider` callable; the server wires it to a `DatasetManager` instance. |

- path: `sdd/proposals/datasetmanager-semantic-source.proposal.md`
  lines: 294-297
  symbol: `U4`
  excerpt: |
    - [x] **U4 — Is the DuckDB-backed store part of this feature?** —
      *Resolved*: No — it is folded into a revision of FEAT-713 (`accounting-metrics-layer`), whose
      "FEAT-704 is paused" premise is now stale.

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/deltatable.py`
  lines: null
  symbol: `DeltaTableSource.fetch`
  excerpt: |
    (wiki symbol summary) "Query the Delta table and return a DataFrame."

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/iceberg.py`
  lines: null
  symbol: `IcebergSource.fetch`
  excerpt: |
    (wiki symbol summary) "Execute a query against the Iceberg table and return a DataFrame."

## Notes

*(FC-008)*
- The REPL transport's own docstring (`transport.py:23`) notes that `to_pandas()` / `from_pandas()` still
  copy — "zero-copy" for pandas → Arrow is not guaranteed; only Arrow → DuckDB registration is.
- Scope tension for the revision: FEAT-880's U4 says the DuckDB-backed **dataset store** "is folded into a
  revision of FEAT-713", while the old FEAT-713 design only *reads* frames through a `frame_provider` and
  never changes how DatasetManager stores them. Replacing `entry._df` touches ~50 accessor lines in
  `tool.py` plus `filtering/values.py:31` and the pandas REPL hand-over; a `frame_provider`-fed DuckDB
  runner touches none of them. These are different features.
- `DatasetManager._pre_execute` at `tool.py:2762` (old-spec anchor) and `add_dataframe` were not re-verified.
- [cross-lane: type=git_log, intent=FEAT-750 / PR #1817 / PR #1836 commits that introduced repl_worker/transport.py Arrow transport]
*(FW-003)*
- FEAT-880 F014's cited lines of `constraints_and_goals.txt` and of the old spec are second-hand (from that finding, dated 2026-11-11); the FEAT-880 proposal lines were read in this session.
- Tension for the synthesis: FEAT-880 says "the DuckDB store moves to FEAT-713", but FEAT-713 as designed only *reads* frames into DuckDB for accounting queries; a store that replaces `entry._df` (nine direct accessors per FEAT-880 C12) is a different, cross-cutting change in core `ai-parrot`, not in the satellite.
- [cross-lane: type=grep, intent=confirm whether deltatable.py / iceberg.py use duckdb in-process (import duckdb, .register, .arrow()) — the wiki summaries do not say]
