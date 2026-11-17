---
id: FEAT-880
title: DatasetManager semantic source — add_semantic() backed by the governed Semantic Layer
slug: datasetmanager-semantic-source
type: feature
mode: enrichment
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-11-11
  summary_oneline: "DatasetManager add_semantic(): a dataset sourced from a Semantic Layer YAML model instead of raw SQL or a Query slug"
overall_confidence: medium
base_branch: dev
projects: [ai-parrot, ai-parrot-semantic]
tags: [dataset-manager, semantic-layer, data-source, governance, duckdb]
research_state: sdd/state/FEAT-880/
created: "2026-11-11"
updated: "2026-11-11"
---

# FEAT-880 — DatasetManager semantic source: `add_semantic()` backed by the governed Semantic Layer

> **Mode**: enrichment
> **Confidence**: medium
> **Source**: `inline`
> **Audit**: [`sdd/state/FEAT-880/`](../state/FEAT-880/)

---

## 0. Origin

The original request, preserved verbatim (translated from Spanish). The full source is at
`sdd/state/FEAT-880/source.md`.

> Could the DatasetManager toolkit support our semantic layer? An `add_semantic(yaml file, driver)`
> so the data does not come from a raw SQL query (or a Query slug) but from a semantic-layer YAML.
> I imagine this dataset is compiled, generating the SQL that is then executed by DatasetManager
> itself with its internal execution capabilities. Could it be built in one spec with what we have?
> Possibly, at operation time, the data extracted through the semantic layer would live in a DuckDB
> instead of in-memory DataFrames.

**Initial signals** (extracted, not interpreted):
- Verbs: "support", "add", "compile", "execute" → feature-shaped.
- Named entities: `DatasetManager`, `add_semantic`, Semantic Layer YAML, Query slug, DuckDB.
- Components / labels: none (inline source).
- Acceptance criteria provided: no.

---

## 1. Synthesis Summary

The request is feasible with what exists, in one spec, but not in the literal form "compile the
YAML and let DatasetManager execute the SQL". The semantic compiler (`compile`) emits
*pre-governance* SQL: row-level security, masks, member grants, limits and audit are applied only
by `SemanticLayerToolkit._run_governed`, and DatasetManager's own authorization
(`AuthorizingDataSource.fetch`) has no masking or member rights and fails open without a
permission context. DatasetManager also keeps rows in a subject-less cache
(`DatasetEntry.materialize`, `DatasetManager._cache_df`), while the existing hand-off
(`_validate_sink`) deliberately keeps governed rows out of a raw DatasetManager. The proposed shape,
fixed by the owner decisions in §5, is a new `DataSource` shipped from `ai-parrot-semantic` and
registered through `DatasetManager.add_source` (with an `add_semantic` convenience): every fetch
takes a semantic query, runs the full governed path under the caller's identity through the
semantic executor, and returns a DataFrame that is never cached across subjects. The DuckDB-backed
store is out of this feature and moves into a revision of FEAT-713.

---

## 2. Codebase Findings

> All entries in this section are grounded in the research findings persisted at
> `sdd/state/FEAT-880/findings/`. Each cites the finding ID(s) that justify its inclusion.

### 2.1 Localization

`DM` = `packages/ai-parrot/src/parrot/tools/dataset_manager`,
`SL` = `packages/ai-parrot-semantic/src/parrot/semantic`.

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `DM/sources/base.py` | `DataSource` | 23-132 | source contract: `fetch(**params) -> DataFrame`, `describe()`, `cache_key`, optional `prefetch_schema` / `has_builtin_cache` | F001, F013 |
| 2 | `DM/tool.py` | `DatasetManager.add_source` | 1433-1481 | generic registration of any pre-built `DataSource` — the plug-in point | F001 |
| 3 | `DM/tool.py` | `DatasetManager.add_query` | 1483-1534 | the shape every `add_*` follows (lazy import, build, `_make_source`, `DatasetEntry`) | F001 |
| 4 | `DM/tool.py` | `DatasetManager._make_source` | 682-714 | wraps every non-memory source in `AuthorizingDataSource` when a guard is configured | F006 |
| 5 | `DM/tool.py` | `DatasetEntry.materialize` | 337-365 | first fetch fills the in-memory DataFrame `entry._df` | F002 |
| 6 | `DM/tool.py` | `DatasetManager.materialize` | 4270-4335 | manager-level materialize with the Redis Parquet cache | F002 |
| 7 | `DM/tool.py` | `DatasetManager._cache_df` | 4244-4263 | writes the cache entry keyed only by `source.cache_key` | F002 |
| 8 | `DM/sources/sql.py` | `SQLQuerySource.fetch` | 181-231 | DatasetManager's own SQL execution (AsyncDB → pandas, `str.format` placeholders) | F001 |
| 9 | `DM/sources/authorizing.py` | `AuthorizingDataSource.fetch` | 103-150 | DatasetManager-side PBAC + RLS wrapper | F006, F015 |
| 10 | `DM/sources/resolver.py` | `resolve_physical_resources` | 120-188 | maps a source class to physical resources; unknown classes go to the opaque resolver | F006 |
| 11 | `DM/sources/dialects.py` | `_DRIVER_DIALECT_MAP` | 23-38 | driver → sqlglot dialect map (asyncdb names such as `pg`) | F002 |
| 12 | `DM/sources/composite.py` | `CompositeDataSource` | 1-30 | precedent: definition-driven source with `has_builtin_cache = True` | F007 |
| 13 | `SL/engines/__init__.py` | `compile` | 14-46 | compile-only entry point, pre-governance SQL | F003 |
| 14 | `SL/engines/native.py` | `NativeCompiler.compile` | 72-90 | needs a full `SemanticQuery`; always appends the policy `LIMIT` | F003 |
| 15 | `SL/toolkit.py` | `SemanticLayerToolkit._run_governed` | 289-328 | the only path from a query to rows: PBAC, rights, compile, govern, execute, audit | F004 |
| 16 | `SL/governance/pipeline.py` | `GovernancePipeline.govern` | 152-188 | compiled SQL → governed SQL (usage lineage, RLS push-down, masking, limit cap) | F004 |
| 17 | `SL/governance/pbac.py` | `PbacGate.authorize` | 63-100 | returns early for `governed: false` | F004 |
| 18 | `SL/handoff.py` | `_validate_sink` | 25-71 | rejects a sink whose class lineage contains `DatasetManager` | F005 |
| 19 | `SL/toolkit.py` | `SemanticLayerToolkit.save_result_as_dataset` | 546-592 | existing push direction into a per-owner `GovernedDatasetSink` | F005 |
| 20 | `packages/ai-parrot-semantic/pyproject.toml` | `dependencies` | 6-30 | `ai-parrot-semantic` depends on `ai-parrot`, never the reverse | F004 |
| 21 | `sdd/specs/accounting-metrics-layer.spec.md` | `DuckDBRunner` | 119 | only prior art for an in-process DuckDB engine (FEAT-713, draft, no code) | F014 |

### 2.2 Constraints Discovered

- **Dependency direction.** `ai-parrot-semantic` depends on `ai-parrot`; nothing in core or
  `ai-parrot-tools` imports `parrot.semantic`.
  *Implication*: the source class ships from `ai-parrot-semantic`; `DatasetManager` may only reach
  it through `add_source()` or a lazy import inside `add_semantic`.
  *Evidence*: F004

- **Compiled SQL is pre-governance.** `compile` needs no identity, but its output carries no RLS or
  masks; `_run_governed` is the single path to rows and the toolkit never hands governed SQL to a
  caller.
  *Implication*: storing compiled SQL in a plain `SQLQuerySource` is a governance bypass.
  *Evidence*: F003, F004

- **`governed: false` is not "no governance".** It skips PBAC and the connection requirement only;
  usage rights, RLS, masking and the limit guard still run.
  *Implication*: there is no cheap "ungoverned" shortcut through the pipeline.
  *Evidence*: F004

- **The hand-off forbids a raw DatasetManager.** Governed results are owned by one
  `(agent, user, tenant, session)`, expire, and are re-authorized on every read.
  *Implication*: a pull-direction source must not materialize governed rows once and serve them to
  other subjects.
  *Evidence*: F005, F010

- **Subject-less cache.** Rows live in `entry._df` and in a Redis Parquet entry keyed only by
  `source.cache_key`, shared across agents.
  *Implication*: the semantic source sets `has_builtin_cache = True`; its rows must not be reused
  across subjects or across different queries.
  *Evidence*: F002, F013

- **DatasetManager authorization dispatches by class.** An unknown source class gets the opaque
  resolver and no RLS; a missing permission context fails open; a sensitive driver rejects every
  non-`QuerySlugSource`. Both stacks share the `(driver, table)` RLS registry.
  *Implication*: the new class needs a defined behavior in the wrapper — self-governed, so RLS is
  not injected twice.
  *Evidence*: F006, F015

- **A model is a directory, not a file.** A `LoadedModel` exists only after the loader reads a
  models directory with one policy side-file per model.
  *Implication*: `add_semantic` takes a models directory and a model name.
  *Evidence*: F003

- **Row cap.** The compiler always appends `LIMIT min(query.limit or limits.default, limits.max)`;
  policy defaults are 1000 / 10000.
  *Implication*: a semantic dataset is a capped query result; truncation must be visible.
  *Evidence*: F003

- **Different driver names and executors.** DatasetManager uses asyncdb names (`pg`) and AsyncDB →
  DataFrame; the semantic layer uses the toolkit `dialect` string, `PARROT_SEMANTIC_CONN_*`
  overlays and `DatabaseQueryToolkit` → row dicts with a `limit + 1` probe row.
  *Implication*: with the semantic executor (U2), the source only converts trimmed rows to a
  DataFrame; driver names matter only if the DatasetManager wrapper also authorizes the source.
  *Evidence*: F004, F001

- **No DuckDB-backed store exists.** Nine accessors and the pandas REPL hand-over read `entry._df`
  directly; FEAT-713 (draft) already chose DuckDB + Arrow and lists modifying DatasetManager as a
  non-goal.
  *Implication*: the DuckDB store is a cross-cutting change, independent of this source.
  *Evidence*: F002, F014

### 2.3 Recent History (Relevant)

| Commit | When | Message | Touched area |
|--------|------|---------|--------------|
| `b396eccb4d` | 2026-11-11 (PR #2094) | terminal fetch-error classification | `DM/tool.py` |
| `55619c5ceb` | last 45 days | request-scoped RLS injection | `DM/sources/` |
| `a44cf79608` | last 45 days | fail-closed slug authorization | `DM/sources/` |
| `9986ac7c49` | 2026-10-26 | TASK-4709 guarded dataset sink and read-time authorization | `SL/handoff.py` |
| `1952913136` | earlier | `CompositeDataSource` added in one task (TASK-431) | `DM/sources/composite.py` |
| `bc0e0499e3` | earlier | Iceberg / Mongo / DeltaTable sources, one file each | `DM/sources/` |

DatasetManager had only these three hardening commits in 45 days; the semantic package has had no
source change since 2026-10-30. No branch combines both areas (branch search matched names
containing `semantic` or `dataset` only). *Evidence*: F008, F009, F010, F011, F012

---

## 3. Probable Scope

### What's New

- **`SemanticDataSource`** (in `ai-parrot-semantic`) — a `DataSource` bound to a models directory,
  a model name and a dialect. `fetch(**params)` builds a `SemanticQuery` from the call parameters
  (metrics, dimensions, time dimensions, filters, order, limit), runs the full governed path under
  the caller's permission context, executes through the semantic executor and returns a DataFrame.
  `has_builtin_cache = True`.
- **Registration entry point** — `DatasetManager.add_semantic(name, models_dir, model, driver, ...)`
  with a lazy import and a clear error when `ai-parrot-semantic` is not installed; it ends in the
  same path as `add_source()`.
- **Reusable governed-run core** — the govern-and-execute steps of `_run_governed` exposed to a
  trusted in-process source, without the LLM-facing tool surface.
- **Schema / description for the LLM** — `prefetch_schema()` and `describe()` list the model's
  members so the agent knows which metrics and dimensions it may request.
- **Tests** in `packages/ai-parrot-semantic/tests/` (source contract, per-subject isolation, no
  shared cache, fail-closed without context, truncation reporting) plus a DatasetManager
  registration test.

### What Changes

- **`DM/tool.py`::`DatasetManager.add_source`** — sibling `add_semantic` method following the
  `add_query` shape.  *Evidence*: F001
- **`DM/sources/resolver.py`::`resolve_physical_resources`** and
  **`DM/sources/authorizing.py`::`AuthorizingDataSource.fetch`** — a defined behavior for the new
  class: self-governed, no second RLS injection, explicit sensitive-driver rule.  *Evidence*: F006
- **`SL/toolkit.py`::`SemanticLayerToolkit._run_governed`** — factor the core so the source reuses
  it; no behavior change for the toolkit.  *Evidence*: F004

### What's Untouched (Non-Goals)

- A DuckDB-backed dataset store — moves to a revision of FEAT-713 (U4).
- DatasetManager executing the SQL itself; compiled or governed SQL never leaves the semantic
  layer (U2).
- An ungoverned mode for semantic datasets (U1).
- The LLM-facing semantic tools, the push hand-off (`save_result_as_dataset`,
  `GovernedDatasetSink`), the model format, the compiler grammar and the policy schema.
- Cross-connection joins; the FEAT-742 Rust compiler.

### Patterns to Follow

- One `DataSource` subclass per source kind plus one `add_*` method.  *Evidence*: F001, F011
- `CompositeDataSource`: definition-driven, `has_builtin_cache = True`.  *Evidence*: F007
- `QuerySlugSource` keeps a per-request principal out of the cache key.  *Evidence*: F001
- Depend on `compile` (the engine entry point), not on `NativeCompiler`, so FEAT-742 can replace
  the compiler.  *Evidence*: F012
- Reuse the sink conformance suite to assert governed data never crosses subjects.  *Evidence*: F010

### Integration Risks

- **Cross-subject or cross-query reuse of `entry._df`**: with a dynamic query, a materialized
  DataFrame is only valid for the subject and query that produced it. Mitigation: the source never
  uses the Redis layer, and the entry is re-fetched (or keyed) per subject and query; how
  DatasetManager instances are scoped in hosts must be verified in the spec.  *Evidence*: F002, F005
- **Overlap with the `sl_*` tools**: a fully dynamic fetch gives the agent a second way to run
  semantic queries. Mitigation: the spec states the difference — the dataset lands as a DataFrame
  in the pandas workspace.  *Evidence*: F004
- **Member visibility in `describe()`**: listing members must respect the caller's role, as the
  semantic catalog does.  *Evidence*: F004
- **Double RLS injection** from the shared `(driver, table)` registry. Mitigation: mark the source
  self-governed.  *Evidence*: F006, F015
- **Silent truncation** at the policy row cap. Mitigation: surface `truncated` in the dataset
  metadata.  *Evidence*: F003
- **Fail-open wrapper vs fail-closed pipeline**: without a permission context the semantic path
  refuses; the dataset fetch must report that as a terminal error, not retry.  *Evidence*: F006, F008

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | A new source kind needs no change to the registration machinery: `add_source()` registers any `DataSource` | F001 | high | read directly |
| C2 | Datasets are in-memory DataFrames with a subject-less Redis Parquet cache; there is no DuckDB store | F002, F013 | high | `materialize` / `_cache_df` read; `duckdb` grep shows only the dialect map and Delta / Iceberg engines |
| C3 | The semantic layer compiles without identity or connection, but that SQL is pre-governance | F003 | high | read directly |
| C4 | `governed: false` only skips PBAC and the connection requirement | F004 | high | read directly |
| C5 | Running compiled SQL through a plain `SQLQuerySource` would bypass masks, usage grants, model RLS, limits and audit | F003, F004, F006 | high | follows from C3 and the absence of masking / member rights in the wrapper |
| C6 | The existing hand-off is push-only and forbids a raw DatasetManager as holder of governed rows | F005, F010 | high | `_validate_sink` read; TASK-4709 history |
| C7 | The source class must live in `ai-parrot-semantic` or be lazily imported | F004 | high | `pyproject` dependencies; no `parrot.semantic` import in core or tools |
| C8 | A semantic dataset needs a full `SemanticQuery` and is row-capped by the policy limits | F003 | high | read directly |
| C9 | A governed-per-fetch source registered through `add_source` fits one spec of roughly TASK-431 size plus authorization integration | F001, F004, F006, F007, F011 | medium | every piece exists, but the governed-run core is private to the toolkit and sizing is by precedent |
| C10 | DatasetManager could execute governed SQL itself if driver names were aligned and the probe row trimmed | F001, F004 | medium | not exercised end to end; moot after U2 |
| C11 | Whether one DatasetManager instance is shared across users or sessions decides whether `entry._df` itself can leak across subjects | F002, F005 | low | instance scoping in hosts was not researched |
| C12 | A DuckDB-backed store is a separate, cross-cutting feature that overlaps FEAT-713 | F002, F014 | medium | nine direct `_df` accessors; FEAT-713 is draft and its premise is stale |
| C13 | Collision risk is low: no in-flight work combines the two areas | F008, F009, F012 | medium | branch search matched names only |

Distribution: **8** high, **4** medium, **1** low.

> C11 is the one low claim that matters to the design; it is answerable by research and is carried
> into the spec as an unresolved item, which keeps the overall confidence at medium.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **U1 — Which governance posture should `add_semantic` have for the rows it materializes?** —
  *Resolved*: Governed per fetch — every fetch compiles and goes through the semantic pipeline
  under the caller's identity; the result is never cached across users.
  *Resolves claims*: C5, C9

- [x] **U2 — Who executes the SQL: DatasetManager's own engine or the semantic executor?** —
  *Resolved*: The semantic executor; the source converts the rows to a DataFrame. This replaces
  the original idea of DatasetManager executing the compiled SQL.
  *Resolves claims*: C10

- [x] **U3 — Is the `SemanticQuery` pinned at registration or supplied per fetch?** —
  *Resolved*: Dynamic per fetch — the agent supplies metrics, dimensions and filters on each fetch.
  *Resolves claims*: C8

- [x] **U4 — Is the DuckDB-backed store part of this feature?** —
  *Resolved*: No — it is folded into a revision of FEAT-713 (`accounting-metrics-layer`), whose
  "FEAT-704 is paused" premise is now stale.
  *Resolves claims*: C12

### Unresolved (defer to spec / implementation)

- [ ] **How are DatasetManager instances scoped in hosts (per session vs shared), and how is a
  dynamic-query entry keyed so a DataFrame is never reused for another subject or query?** —
  *Owner*: tbd (research in `/sdd-spec`)
  *Blocks claims*: C11
  *Plausible answers*: a) per-session managers, entry re-fetched on every call · b) entry keyed by
  subject digest + canonical query

- [ ] **How does a dynamic fetch differ, for the agent, from the existing `sl_query` tool, and
  should `add_semantic` require a default query for `prefetch_schema()`?** — *Owner*: tbd
  *Blocks claims*: C9

- [ ] **Row cap: is the policy limit (1000 / 10000) acceptable for datasets, or does the spec need
  a documented way to raise `limits.max` per model?** — *Owner*: tbd
  *Blocks claims*: C8

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-880`** — *Rationale*: localization is high-confidence, every building block
exists, and the architectural fork (governance posture, executor, query pinning) is closed by
U1–U3; the three unresolved items are spec-level design details, the first one answerable by
reading the hosts.

### Alternatives

- **`/sdd-brainstorm FEAT-880`** — if the dynamic-per-fetch choice should be weighed against the
  overlap with the `sl_*` tools before committing to a design.
- **Revise FEAT-713** — the follow-up for the DuckDB-backed store (U4); not part of this feature.
- **Manual review** — not needed; research was not truncated.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-880/state.json` |
| Source (raw) | `sdd/state/FEAT-880/source.md` |
| Research plan | `sdd/state/FEAT-880/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-880/findings/F001-*.md` … `F015-*.md` |
| Lane originals | `sdd/state/FEAT-880/findings/.audit/` |
| Synthesis (JSON) | `sdd/state/FEAT-880/synthesis.json` |

**Budget consumed**:
- Files read: 18 / 40
- Grep calls: 17 / 25
- Git calls: 10 / 10
- Wall time: 222s / 300s (longest lane)
- Truncated: **no**

**Execution notes**:
- Research ran in three parallel lanes (codebase, git, wiki); 17 lane findings merged into 15.
- The research-plan gate was not presented for approval; the plan ran as generated.
- The citation check ran inline rather than through the probe agent: 87 citations, none stale or
  missing. Partial reads: `rls.py` and `table.py` by definition inventory, `composite.py` lines
  1-60, test files located but not opened.

**Mode determination**: `auto` → resolved to `enrichment` (additive verbs: "add", "support").

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Claude Code (Fable 5.2) |
