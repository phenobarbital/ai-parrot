---
id: F014
query_id: Q004
type: wiki_query
intent: "Find any prior DuckDB-backed dataset store design or decision (Q004 + Q005)."
executed_at: 2026-11-11T22:20:00Z
duration_ms: 0
parent_id: null
depth: 1
lane_id: FW-002
---

# F014 — No spec designs a DuckDB-backed DatasetManager store or a semantic source; the only prior art is FEAT-713 (draft, undecomposed), which runs DuckDB beside DatasetManager without modifying it

## Summary

Nothing in specs, proposals, decisions or saved wiki memories designs (a) a DuckDB store replacing
DatasetManager's in-memory DataFrames or (b) a semantic-layer `DataSource` / `add_semantic`. Wiki
queries for both return only the in-memory surface (`DatasetManager.evict_*`, `PythonPandasTool` sync)
and the unrelated `databasequery/sources/duckdb.py` (DuckDB as a *queried* database). The closest prior
art is FEAT-713 `accounting-metrics-layer`: an owner decision dated 2026-10-20 fixes "one compiler, two
execution targets" with DuckDB as the in-process engine and Arrow as the zero-copy bridge for
pandas/polars frames. But its spec is **draft**, has no task index, `parrot/semantic/accounting/` does
not exist, and it lists "Modifying `DatasetManager`" as a non-goal — frames reach a `DuckDBRunner`
through an injected `frame_provider`. It also defers "lowering into the generic semantic layer".

## Citations

- wiki: `file:sdd/state/FEAT-713/design_research/constraints_and_goals.txt` (Q004 score=0.02)

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
- wiki: `file:sdd/specs/accounting-metrics-layer.spec.md` (score=0.13 on "accounting metrics layer DatasetManager")

- path: `sdd/specs/accounting-metrics-layer.spec.md`
  lines: 13
  symbol: `Status`
  excerpt: |
    **Status**: draft

- path: `sdd/specs/accounting-metrics-layer.spec.md`
  lines: 49-52
  symbol: `Goals`
  excerpt: |
    - **One canonical IR, two execution targets.** The same compiled AST is rendered per dialect and runs against the
    - **DuckDB in-process, Arrow as the bridge.** pandas/polars frames are registered into DuckDB via Arrow, never

- path: `sdd/specs/accounting-metrics-layer.spec.md`
  lines: 79-81
  symbol: `Non-Goals`
  excerpt: |
    - Materialisation via Flowtask (brainstorm Option D) and lowering into the generic semantic layer (Option A) —
    - Modifying `SQLToolkit`, `DatasetManager`, `AuditLedgerEntry` or `parrot/clients/base.py` — the layer is purely

- path: `sdd/specs/accounting-metrics-layer.spec.md`
  lines: 119
  symbol: `DuckDBRunner`
  excerpt: |
    `DuckDBRunner` registers Arrow tables on a root `duckdb` connection and executes on a per-thread cursor

- path: `sdd/specs/accounting-metrics-layer.spec.md`
  lines: 172
  symbol: `Integration Points`
  excerpt: |
    | `DatasetManager` | **not modified** | frames reach the DuckDB runner through an injected `frame_provider` callable; the server wires it to a `DatasetManager` instance. |

- path: `sdd/specs/accounting-metrics-layer.spec.md`
  lines: 413
  symbol: `pyproject extras`
  excerpt: |
    duckdb = ["duckdb>=1.0"]
- wiki: `sym:packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py#DatasetManager.evict_table_sources` (Q004 score=0.38), `#DatasetManager.evict_all` (0.08), `#DatasetManager.evict_unactive` (0.03) — eviction is "release materialized DataFrames from memory"
- wiki: `file:packages/ai-parrot/src/parrot/tools/databasequery/sources/duckdb.py` (Q004 score=0.01) — "DuckDB database source for DatabaseToolkit"

## Notes

- Absence is explicit: no file under `sdd/specs/` or `sdd/proposals/` has `duckdb` in its name;
  `sdd/tasks/index/` has no `accounting-metrics-layer.json`; `wikitoolkit memories` holds one semantic
  entry only (`mem-40bea21d8186`, "No cross-connection check in the semantic layer").
- FEAT-713 was written while FEAT-704 was paused on sidemantic; FEAT-704 has since merged with a native
  compiler, so FEAT-713's "satellite skeleton" module and its FEAT-704-is-paused premise are stale. A
  DuckDB store for DatasetManager overlaps FEAT-713's `DuckDBRunner` (Arrow registration, per-thread
  cursor, optional `duckdb` extra) — reconcile rather than design twice.
- "Results caches are never shared across security contexts" applies directly to a semantic source
  (see the FW-001 cache note).
- [cross-lane: type=grep, intent=confirm whether duckdb / pyarrow are declared in packages/ai-parrot and packages/ai-parrot-semantic pyproject extras today]
