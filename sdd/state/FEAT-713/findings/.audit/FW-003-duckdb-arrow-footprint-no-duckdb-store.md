---
id: FW-003
query_id: Q003
type: wiki_query
intent: "Orient: where in-process DuckDB and Arrow are already used for datasets / dataframes."
executed_at: 2026-11-11T22:41:00Z
duration_ms: 0
parent_id: null
depth: 1
---

# FW-003 — The graph knows no DuckDB-backed dataset store and no DuckDB-over-registered-frames engine; datasets are in-memory pandas frames (Redis Parquet cache), and the only design for "DuckDB + Arrow over frames" is the FEAT-713 draft itself

## Summary

The query returns, in order: FEAT-880's F014 ("no spec designs a DuckDB-backed DatasetManager store or a semantic source; the only prior art is FEAT-713"), FEAT-880's F002 ("data is held as in-memory pandas DataFrames, cached in Redis as Parquet; no DuckDB store"), FEAT-746's Arrow-footprint finding, and two DatasetManager sources whose `fetch` returns a DataFrame (`DeltaTableSource.fetch`, `IcebergSource.fetch`). No source symbol about registering frames in DuckDB surfaces. FEAT-713's own design research fixed "one compiler, two execution targets" and "DuckDB in-process, Arrow as the bridge" as an owner decision of 2026-10-20, with "Modifying DatasetManager" as a non-goal (frames via an injected `frame_provider`). FEAT-880 U4 now assigns the DuckDB-backed store to this revision, which contradicts that non-goal.

## Citations

- wiki: `file:sdd/state/FEAT-880/findings/F014-duckdb-store-and-semantic-source-prior-art.md` (Q003 score=1.00)
- wiki: `file:sdd/state/FEAT-880/findings/F002-dataset-entry-lifecycle-and-runtime-storage.md` (Q003 score=0.61)
- wiki: `sym:packages/ai-parrot/src/parrot/tools/dataset_manager/sources/deltatable.py#DeltaTableSource.fetch` (Q003 score=0.31)
- wiki: `sym:packages/ai-parrot/src/parrot/tools/dataset_manager/sources/iceberg.py#IcebergSource.fetch` (Q003 score=0.11)
- wiki: `file:sdd/state/FEAT-713/design_research/recommended_option_or_scope.txt` (Q003 score=0.24)

- path: `sdd/state/FEAT-713/design_research/constraints_and_goals.txt`
  lines: 4-5
  symbol: `Constraints & Requirements`
  excerpt: |
    - **One compiler, two execution targets.** The same compiled SQL text runs against the source database through `DatabaseToolkit` and against in-memory DataFrames through `DatasetManager`. (Owner decision, 2026-10-20.)
    - **DuckDB is the in-process engine; Arrow is the bridge.** polars/pandas DataFrames are registered into DuckDB via Arrow (zero-copy), never serialised. No pickle across trust boundaries (security invariant).

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

- FEAT-880 F014's cited lines of `constraints_and_goals.txt` and of the old spec are second-hand (from that finding, dated 2026-11-11); the FEAT-880 proposal lines were read in this session.
- Tension for the synthesis: FEAT-880 says "the DuckDB store moves to FEAT-713", but FEAT-713 as designed only *reads* frames into DuckDB for accounting queries; a store that replaces `entry._df` (nine direct accessors per FEAT-880 C12) is a different, cross-cutting change in core `ai-parrot`, not in the satellite.
- [cross-lane: type=grep, intent=confirm whether deltatable.py / iceberg.py use duckdb in-process (import duckdb, .register, .arrow()) — the wiki summaries do not say]
