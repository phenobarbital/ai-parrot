---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
# projects: parts of the codebase this doc concerns. Use `packages/*` dir names
#   (ai-parrot, ai-parrot-server, parrot-formdesigner, …) or an area
#   (sdd-tooling, dev-loop, admin-ui, docs, ci). Unknown values warn, not fail.
projects: [ai-parrot-semantic, ai-parrot-server, ai-parrot]
# tags: free-form kebab-case keywords for organizing specs (e.g. memory, mcp).
tags: [semantic-layer, sidemantic, sqlglot, rls, pbac, mcp]
---

# Brainstorm: Semantic Layer — governed metric queries for agents (`ai-parrot-semantic`)

**Date**: 2026-10-19
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: B
**Source proposal**: `sdd/proposals/semantic-layer.proposal.md` (research of 2026-10-14; still untracked in git at the time of writing)

---

## Problem Statement

Agents that answer KPI questions today either write free SQL against `DatabaseQueryToolkit` /
`SQLToolkit` or call pre-registered QuerySource slugs. Free text-to-SQL produces *plausible but
wrong* numbers (the dbt Labs 2026 benchmark cited in the proposal: 84–90 % accuracy vs 98–100 %
with a semantic layer, and — more important for governance — a semantic layer fails **loudly**
on out-of-scope questions instead of inventing a figure). Slugs are exact but rigid: every new
breakdown is a new slug.

There is no place in ai-parrot where **metrics, dimensions, joins and time grains are declared
once** and compiled on demand, and there is no governance plane for such queries: row-level
security (RLS) in the repo exists only as a *post-hoc wrapper* (`inject_rls_sql` wraps the whole
statement in `SELECT * FROM (...) WHERE pred`), which is **wrong for aggregates** — a tenant filter
applied after `SUM()`/`COUNT()` either filters nothing (the column is gone) or leaks totals. There
is no per-role metric/dimension allowlist, no column masking, no positive SQL allowlist, and no
audit record that stores the compiled SQL next to the security context.

Affected: **end users** (wrong KPI answers, data leakage across tenants/programs), **developers**
(every dashboard agent re-invents metric definitions), **ops/security** (no auditable trail of
what SQL ran under which identity).

The proposal's research established three facts this brainstorm builds on:

1. **No semantic-layer library is async.** The only viable integration is *compile-only*
   (CPU-bound, `asyncio.to_thread`) and execute through our own async drivers.
2. **No RLS format is portable** (Apache Ossie defines none; sidemantic / metrics_layer / semql
   each differ), so governance is ai-parrot code regardless of engine.
3. **Ibis was already rejected in this repo**: TASK-1437 (FEAT-219) resolved **NO-GO** for Ibis;
   `dataset_manager/spatial/compiler.py:19` documents that two hand-written dialect templates are
   used instead. That removes BSL-over-Ibis as the natural primary path.

Decisions taken during discovery (Rounds 0–2):

| Decision | Answer |
|---|---|
| Flow | `feature` → `dev` |
| Engine | **sidemantic** (AGPL accepted, used directly, no engine-abstraction layer) for the main features; **own sqlglot compiler** where full control is needed |
| Own-code responsibilities | free-SQL positive guard · RLS enforcement (not sidemantic `SecurityPolicy`) · column masking · a **fallback native metric compiler** |
| Placement | new satellite distribution **`ai-parrot-semantic`** (PEP 420 namespace `parrot.semantic`) |
| Model definitions / execution | YAML directory per agent (sidemantic-native + Ossie import); compile-only; execution via existing `DatabaseQueryToolkit` sources |
| v1 scope | RLS via PBAC context · role allowlist · positive sqlglot guard + audit · saved/verified queries + Ossie import |
| Surfaces | `SemanticLayerToolkit` · `parrot mcp-local` server · aiohttp handlers · DatasetManager hand-off |

## Constraints & Requirements

- **Async-first, compile-only.** sidemantic (and any fallback) runs as a pure function in
  `asyncio.to_thread`; the event loop never touches a sync DB adapter. Execution goes through
  `AbstractDatabaseSource.query()` (asyncpg / BigQuery / DuckDB) — never sidemantic's own adapters.
- **AGPL containment.** sidemantic is AGPL-3.0; core `ai-parrot` is MIT (`packages/ai-parrot/pyproject.toml:17`).
  Only `ai-parrot-semantic` may import sidemantic. Nothing under `packages/ai-parrot/`,
  `ai-parrot-tools/` or `ai-parrot-server/` may import it at module level; the server handler
  imports lazily and registers only when the satellite is installed.
- **Governance is deny-by-default.** A model marked governed compiled without a
  `PermissionContext` raises — this is *stricter* than `DataPlanePolicyGuard`'s fail-open when
  `ctx is None` and must be an explicit design statement.
- **RLS before aggregation.** Predicates are injected at the base-table scan (fan-out safe), never
  by wrapping the final statement. Values are rendered as typed literals/parameters, never string-formatted.
- **Positive allowlists only.** sqlglot is a transpiler, not a validator: the guard walks the AST
  and requires every table / column / function to be known. One `Select`, no `Command`/DDL/DML,
  forced `LIMIT`.
- **Caches never cross security contexts.** Compiled-SQL cache keys include the role-set and
  tenant digest. No result cache in v1.
- **Dialects:** Postgres, BigQuery, DuckDB in v1 (all three have `AbstractDatabaseSource`
  implementations and entries in `SQLGLOT_DIALECT_MAP`).
- **Pins:** `sidemantic==0.12.0` (exact — field moves and CLI renames shipped unlabeled; `main`
  already adds a Rust wheel `sidemantic-rs`), `sqlglot>=30.1,<31` (sidemantic floor), Apache Ossie
  spec `0.1.1` pinned in the loader.
- **No new tool surface in core.** Only base machinery lives in `parrot/tools/`; the concrete
  toolkit ships in the satellite (the AGPL boundary is the reason it is not in `ai-parrot-tools`).
- Codebase conventions apply (`.claude/rules/codebase-conventions.md`): aiohttp only, Pydantic v2,
  `self.logger`, `uv`, 120 cols, tests under `packages/ai-parrot-semantic/tests/`.

---

## Options Explored

### Option A: Boring Semantic Layer over Ibis (the proposal's recommendation)

Adopt `boring-semantic-layer` (MIT) as the metric compiler: `SemanticTable` over unbound
`ibis.table(schema, name)`, `.sql(dialect=)` for Postgres/BigQuery/DuckDB without any backend
extra. Governance (RLS as `.filter()` injection, role-filtered `json_definition`, sqlglot guard,
audit) written in ai-parrot. Ibis-direct as fallback.

✅ **Pros:**
- Clean licenses (MIT on Apache-2.0); fan-out-safe joins (`join_one` promoted to `join_many`
  semantics) and a catalog (`json_definition`, `index()`) already exist.
- Fallback to Ibis-direct is architecturally trivial (BSL *is* Ibis expressions).

❌ **Cons:**
- **Contradicts a recorded repo decision**: TASK-1437 resolved NO-GO for Ibis (connection
  mapping vs navconfig) and FEAT-219 ships hand-written dialect templates instead.
- Pin `ibis-framework<12` while Ibis 12.0.0 is out since 2026-02-07; two-maintainer project.
- No RLS, no metric types beyond measures (no ratio/cumulative/time-comparison), no format
  importers (Ossie reader is ours to write).
- Unbound tables need column types from the host → schema drift fails at the DB, not at compile.
- Generated SQL is nested 3–4 subselects deep — harder for the AST guard and for RLS push-down.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `boring-semantic-layer==0.3.18` | metric compiler | MIT, 2026-08-24, deps `attrs`, `ibis-framework<12,>=11`, `returns`, `toolz`, `pyyaml` (PyPI JSON, 2026-10-19) |
| `ibis-framework>=11,<12` | expression → SQL | Apache-2.0; 12.0.0 (2026-02-07) unsupported by BSL |
| `sqlglot` | AST guard | already in core (`>=20.0`) |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/tools/dataset_manager/spatial/_ibis_probe.py` — the FEAT-219 Ibis spike (throwaway; documents why Ibis was rejected).
- `packages/ai-parrot/src/parrot/tools/databasequery/base.py` — `AbstractDatabaseSource` execution.

---

### Option B: sidemantic core + ai-parrot governance compiler on sqlglot, in `ai-parrot-semantic` ⭐

sidemantic (`==0.12.0`, AGPL accepted) owns **what the proposal calls "the hard semantic part"**:
model/dimension/metric pydantic core (12 aggregations + ratio/derived/cumulative/time_comparison/
conversion/retention/cohort), relationships with five cardinalities and **symmetric aggregates**
(no double counting on one-to-many joins), `load_from_directory` auto-detecting 15 formats
(**Apache Ossie included**, plus dbt MetricFlow, LookML, Cube…), `compile(metrics, dimensions,
filters, order_by, limit, dialect)` → SQL with no warehouse connection, catalog/explain helpers.

ai-parrot owns, on **sqlglot** (own code, full control):

1. **`SemanticQuery`** pydantic contract (superset of Cube / dbt / Ossie query shapes: metrics,
   dimensions, time dimensions with grain, typed filter tree with `and`/`or`, order, limit,
   offset, timezone, `saved_query` XOR `metrics`). Compiles to sidemantic's `filters=[...]`
   strings *or* to the native compiler's AST.
2. **Governance compiler** — a post-compile AST pass over whatever SQL the engine produced:
   - **RLS push-down**: every `exp.Table` matching an `RlsRule (driver, schema.table)` is
     rewritten to a filtered scan (predicate rendered from `RlsRegistry.render(rule, ctx)` → typed
     `exp.Literal`s) **below** any aggregation. Deny-by-default when the model is governed and no
     `PermissionContext` is available.
   - **Column masking**: projection rewrite per role (`null` / `hash` / `partial`) and catalog hiding.
   - **Positive guard**: `qualify` with the model-derived schema, allowlist of tables/columns/
     functions, single `Select`, forced/capped `LIMIT`. Applied to compiled SQL (sanity) and to the
     optional free-SQL `run_sql` tool (exploration path).
3. **Role allowlist** over the catalog (`<model>.policy.yaml` side-file: `roles → metrics/dimensions`,
   `mask`, `rls` bindings, `saved_queries` with `verified_by/verified_at`). The LLM only ever sees
   the filtered catalog, which also shrinks the prompt.
4. **Native fallback compiler** (`engine: native` per model, default `sidemantic`): metrics with
   simple aggregations, dimensions, `DATE_TRUNC` grains, declared one-to-many joins (fan-out
   rejected in v1), filter tree, order/limit — built as a sqlglot AST, so sidemantic can be
   bypassed for a model or dropped later. Parity tests on DuckDB fixtures keep both engines honest.
5. **Audit**: a signed `SemanticAuditEntry {structured_query, subject digest (user, tenant,
   roles), model, engine, compiled_sql, dialect, row_count, duration_ms, outcome}` persisted
   through the same `AbstractKMSSigner` + async `storage` callable contract `AuditLedger` uses.
6. **Execution bridge** to `DatabaseQueryToolkit.get_source(driver).query(credentials, sql)`;
   credentials come from the model's named `connection` (env/navconfig), never from the LLM.
7. **Surfaces**: `SemanticLayerToolkit(AbstractToolkit, tool_prefix="sl")`; `parrot mcp-local
   semantic-layer` through a `.parrot/mcp-toolkits.yaml` section (no new server code — `mcp-local`
   already serves any `AbstractToolkit` class path); `SemanticLayerHandler(BaseView)` under
   `/api/v1/agents/semantic/{agent_id}` registered in `manager.py` like `DatasetManagerHandler`;
   `sl_save_result_as_dataset` → `DatasetManager.add_dataframe()` for pandas/viz follow-ups.

✅ **Pros:**
- Richest semantic core available in Python today, compile-only, three dialects, Ossie + dbt +
  LookML import for free; its `docs/security.md` and `mcp_server.py` are the reference designs
  for our own RLS and tool contract.
- Everything security-relevant is **ours and engine-independent** (RLS, masking, guard, audit,
  allowlist), so the AGPL dependency never becomes the authority on who sees what.
- Native fallback gives an exit path without an abstraction layer: one internal
  `compile(query, model, dialect)` that dispatches on `model.engine`.
- AGPL blast radius confined to one opt-in distribution; `ai-parrot-tools` stays MIT-clean.
- Reuses PBAC primitives that already exist (`PermissionContext`, `RlsRegistry`/`RlsRule`,
  `DataPlanePolicyGuard`, `_pctx_var`) and the proven ContextVar pattern from `DatasetManager`.

❌ **Cons:**
- **AGPL-3.0** on a component linked in-process behind a network API: the network clause applies
  (accepted by the user; the satellite's own `license` field still needs legal confirmation).
- Single maintainer (130★, 0 open issues, "young, rough patches"); unlabeled breaking changes →
  exact pin and an upgrade checklist are mandatory.
- Pulls `duckdb`, `antlr4-python3-runtime`, `click`, `typer`, `jinja2` (duckdb and jinja2 already
  in the venv; typer/click are new transitive deps for the satellite only).
- Two compilers to keep in parity (native subset vs sidemantic) — extra test surface.
- `SemanticLayer.compile` thread-safety is undocumented → one layer per toolkit plus a lock until verified.
- Deviates from "concrete toolkits live in `ai-parrot-tools`" — justified by the license boundary; must be written down.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `sidemantic==0.12.0` | semantic model, 15-format import (Ossie), metric compile | **AGPL-3.0**, 2026-09-13, `python>=3.11`; deps: `antlr4-python3-runtime>=4.13.2`, `click>=8`, `duckdb>=1.0`, `jinja2>=3.1`, `pydantic>=2`, `pyyaml>=6`, `sqlglot>=30.1`, `typer>=0.18` (PyPI JSON 2026-10-19). The 0.12.0 wheel does **not** require `sidemantic-rs`; `main` does. |
| `sqlglot>=30.1,<31` | AST guard, RLS push-down, masking, native compiler, transpile | MIT; venv has 30.23.0 (2026-10-14); core floor is `>=20.0` (`packages/ai-parrot/pyproject.toml:182`) |
| `duckdb` | sidemantic hard dep + DuckDB dialect fixtures for parity tests | venv has 1.5.6; `DuckDBSource` exists |
| `asyncpg`, `google-cloud-bigquery` | execution via existing sources | already installed (0.32.0 / 3.46.2) |
| `jsonschema` | Ossie 0.1.1 document validation before handing to sidemantic | Ossie's own `validate.py` uses `jsonschema` + `pyyaml` + `sqlglot>=30.12` |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/tools/databasequery/base.py` — `AbstractDatabaseSource.query()` / `validate_query()` / `add_row_limit()`; `QueryResult`, `ValidationResult`.
- `packages/ai-parrot/src/parrot/tools/databasequery/toolkit.py` — `DatabaseQueryToolkit.get_source(driver)` (cached source instances; the execution bridge).
- `packages/ai-parrot/src/parrot/auth/rls_registry.py` — `RlsRule`, `RlsPredicate`, `RlsRegistry.lookup()/render()` (predicate templates with `:subject.<attr>` placeholders).
- `packages/ai-parrot/src/parrot/auth/dataplane_guard.py` — `DataPlanePolicyGuard.filter_tables()` / `rls_predicates()` for table-level PBAC decisions.
- `packages/ai-parrot/src/parrot/auth/permission.py` — `UserSession`, `PermissionContext`, `to_eval_context()`.
- `packages/ai-parrot/src/parrot/auth/context.py` — `_pctx_var` ContextVar (how `DatabaseQueryTool` reads the per-call context).
- `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` — the `_pre_execute` → ContextVar → `_get_current_pctx()` pattern and `add_dataframe()` for the hand-off.
- `packages/ai-parrot/src/parrot/security/query_validator.py` — `QueryValidator.validate_sql_ast()` (DDL/DML rejection, single statement) as the negative base the positive guard extends.
- `packages/ai-parrot/src/parrot/security/audit_ledger.py` — `AbstractKMSSigner`, `LocalHMACSigner`, `AzureKeyVaultSigner`, the async `storage` callable contract.
- `packages/ai-parrot/src/parrot/knowledge/common/sql_dialects.py` — `SQLGLOT_DIALECT_MAP` (driver → sqlglot dialect).
- `packages/ai-parrot/src/parrot/mcp/local_cli.py` + `toolkit_config.py` — `parrot mcp-local <name>` serving any `class:` path from `.parrot/mcp-toolkits.yaml`.
- `packages/ai-parrot-server/src/parrot/handlers/datasets.py` + `manager/manager.py:2571` — `BaseView` handler + `router.add_view` registration precedent.
- `packages/ai-parrot-embeddings/pyproject.toml` — satellite packaging template (PEP 420, `dependencies = ["ai-parrot"]`, extras).

---

### Option C: Own compiler on sqlglot only (no sidemantic)

Everything in Option B minus sidemantic: our pydantic model (`Dataset`, `Field`, `Metric`,
`Relationship`), our Ossie reader, our compiler building sqlglot ASTs for the three dialects.

✅ **Pros:**
- Zero new runtime deps (sqlglot already in core), no AGPL, no single-maintainer risk, one
  compiler instead of two, SQL shape fully under our control (RLS/guard trivially integrated).

❌ **Cons:**
- Reimplements the hard parts: symmetric aggregates for one-to-many joins, ratio/cumulative/
  time-comparison/cohort metrics, 15 format importers (we would ship Ossie only).
- Slower time-to-value; the user explicitly wants sidemantic for the main features.

📊 **Effort:** High (larger than B for the same feature set)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `sqlglot>=30.1,<31` | everything | MIT |
| `jsonschema` | Ossie validation | — |

🔗 **Existing Code to Reuse:** same as Option B minus sidemantic-specific items; `spatial/compiler.py`
shows the repo's existing "hand-written dialect templates" precedent.

---

### Option D (unconventional): Push governance into the database — governed views + native RLS

Compile each semantic model + policy into **database objects**: per-model SQL views (one per
role allowlist) and native row security (`CREATE POLICY` on Postgres, authorized views / row
access policies on BigQuery). The agent then queries views only; `SET LOCAL ROLE` / session
variables carry the subject. ai-parrot compiles the *DDL* once and the queries stay trivial.

✅ **Pros:**
- Enforcement by the database engine, independent of any Python path (free SQL included).
- Metric SQL becomes `SELECT ... FROM view` — the guard is almost tautological.

❌ **Cons:**
- Needs DDL privileges and schema management on customer warehouses; DuckDB has no RLS;
  BigQuery row access policies are account-level objects.
- Role explosion (views × roles), migrations on every policy change, no dynamic attributes
  (`programs`, `groups`) without session variables plumbing in asyncpg.
- Does not fit "credentials are a per-call tool argument" and read-only replicas.

📊 **Effort:** High, and operationally heavy.

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `sqlglot` | DDL generation | — |

🔗 **Existing Code to Reuse:** `AbstractDatabaseSource` for DDL execution (currently DDL is unconditionally rejected by `DatabaseQueryToolkit` — would need a privileged path).

---

## Recommendation

**Option B** — *sidemantic core + ai-parrot governance compiler on sqlglot, shipped as the opt-in
`ai-parrot-semantic` satellite* — because:

- It matches the discovery decisions (sidemantic for the semantic core, own sqlglot code where
  control matters, satellite placement, full v1 governance scope) and the repo's prior **NO-GO on
  Ibis** (TASK-1437), which rules out Option A as the primary path.
- Governance is ours in every option; B gets the semantic core (metric types, symmetric aggregates,
  Ossie/dbt/LookML import) for free and confines its only real cost — AGPL + maintainer risk — to
  one opt-in distribution with an exact pin and a native fallback compiler as the exit.
- Option C would spend the budget re-deriving sidemantic's hardest features; Option D moves the
  problem into warehouse administration we do not control.

What we trade off: a two-compiler parity surface, an AGPL package in the workspace, and a
deliberate deviation from "toolkits live in `ai-parrot-tools`" (the license boundary is the
reason, and it must be stated in the spec).

Clarification carried into the spec: "no abstraction layer" (Round 2a) and "fallback native
compiler" (Round 2b) are reconciled as **one internal `compile()` dispatch on `model.engine`
(`sidemantic` | `native`)** — not a plugin protocol, not a third-party engine registry.

---

## Feature Description

### User-Facing Behavior

- An agent configured with `SemanticLayerToolkit(models_dir=..., policy_dir=..., dialect=...,
  connection=...)` gains tools (prefix `sl`):
  `sl_list_models`, `sl_list_metrics`, `sl_get_dimensions(metrics)`,
  `sl_get_dimension_values(dimension, metrics?, limit)`, `sl_search_data_model(text)`,
  `sl_list_saved_queries`, `sl_compile_query(query)` → SQL + explanation,
  `sl_query_metrics(query)` → rows + compiled SQL + audit id,
  `sl_run_sql(sql)` (only when `allow_raw_sql=True`; positive-guarded exploration),
  `sl_save_result_as_dataset(result_id, name)` (only when a `DatasetManager` is attached).
  Each tool has a single effect and a truthful side-effect annotation.
- The catalog the LLM sees is already filtered by the caller's roles; asking for an unlisted
  metric returns an error naming the nearest allowed members — never a number.
- Out-of-scope or malformed queries fail with a structured error (unknown member, mixed
  measure/dimension filter group, missing grain on a time dimension, fan-out join in native mode).
- Saved queries (`verified_by`, `verified_at`) are listable and runnable by name; `saved_query`
  and `metrics` are mutually exclusive in `SemanticQuery`.
- Operators drop sidemantic YAML or Apache Ossie 0.1.x documents in the models directory; a
  `<model>.policy.yaml` side-file holds roles, masks, RLS bindings and saved queries so the model
  file stays portable. Models declaring sidemantic's own `security:` block are rejected at load
  (one RLS semantics only).
- Same tools over `parrot mcp-local semantic-layer` (Claude Code / Codex) and over HTTP
  (`GET …/semantic/{agent_id}` catalog, `POST …/compile`, `POST …/query`) with navigator-auth
  session → `PermissionContext`.

### Internal Behavior

1. **Load** (`SemanticModelLoader`): read models dir → sidemantic `SemanticLayer` via
   `load_from_directory` (format auto-detect; Ossie documents first validated against the pinned
   0.1.1 JSON Schema) → parse `*.policy.yaml` into `ModelPolicy` → build the **physical schema
   map** (datasets → `schema.table`, fields → columns/types) used by `qualify`, the guard and RLS.
   Reject models with `security:`; warn on policy entries referencing unknown members.
2. **Request** → `SemanticQuery` (pydantic, validators: WHERE/HAVING separation, grain required
   for time dims, `saved_query` XOR `metrics`, limit ≤ cap).
3. **Authorize**: `PermissionContext` from `_permission_context` (`_pre_execute` → ContextVar,
   the `DatasetManager` pattern). Governed model + no context → `SemanticAccessError`.
   Role allowlist check on every requested member (unlisted → error with suggestions).
4. **Compile** in `asyncio.to_thread`: `engine == "sidemantic"` → `layer.compile(...)`;
   `engine == "native"` → sqlglot AST builder. Both return a `CompiledQuery {sql, dialect,
   engine, members, tables}`.
5. **Govern** (own sqlglot pass, same for both engines and for `run_sql`):
   `parse_one(sql, read=dialect)` → `qualify(schema)` → **RLS push-down** (rules via
   `RlsRegistry.lookup(driver, tables)`, rendered with `render(rule, ctx)`, injected as filtered
   scans below aggregation; literals typed) → **masking** rewrite of projected sensitive columns →
   **positive guard** (single `Select`, allowlisted tables/columns/functions, no
   `Command`/DDL/DML, forced `LIMIT ≤ cap`) → `sql(dialect=)`.
6. **Cache** compiled governed SQL by `(model digest, canonical query JSON, dialect, roles+tenant
   digest)` — in-memory LRU per toolkit; never shared across contexts.
7. **Execute** via `DatabaseQueryToolkit.get_source(driver).query(credentials, sql)`; credentials
   resolved from the model's named connection (env/navconfig), never from tool arguments.
8. **Audit**: append `SemanticAuditEntry` (signed; `storage` async callable) with the structured
   query, subject digest, engine, compiled SQL, dialect, `row_count`, `duration_ms`, outcome.
   The audit id is returned to the agent.
9. **Hand-off**: `sl_save_result_as_dataset` turns the cached result into a DataFrame and calls
   `DatasetManager.add_dataframe(name, df, description, metadata={audit_id, compiled_sql})`.

### Edge Cases & Error Handling

- **No `PermissionContext`** (direct call, mcp-local): governed models deny; ungoverned models
  (no RLS binding, no role allowlist) compile. For `mcp-local`, an explicit `static_subject`
  kwarg (user, tenant, roles) can supply an operator identity — logged on every call.
- **Role sees no metrics**: catalog returns an empty list with an explicit message, not an error.
- **Schema drift** (model says column exists, DB disagrees): compile succeeds, execution fails →
  `SemanticExecutionError` with the audit id; compiled SQL is in the audit, not in the LLM message.
- **Mixed measure and dimension filters in one logical group** → validation error (WHERE vs HAVING).
- **Fan-out join** requested from a native-engine model → compile error (symmetric aggregates are
  sidemantic-only in v1).
- **RLS rule references an attribute missing from `UserSession.metadata`** → `RlsRegistry.render`
  already yields `1=0`; the compiled query returns zero rows and the audit records `rls=deny-empty`.
- **LIMIT**: absent → injected default (1000); above cap → clamped; `offset` without `order_by` → error.
- **sidemantic exceptions** (`SecurityError`, parse errors) are wrapped; sidemantic's security
  layer is never active because `security:` blocks are rejected at load.
- **Thread-safety**: one `SemanticLayer` per toolkit, compile under an `asyncio.Lock` until
  `compile()` is verified reentrant; cache hits bypass the lock.
- **Cache key leakage**: tests assert that two contexts with different roles never share a key.
- **Dialect without a source** (e.g. `snowflake`): compile allowed (`sl_compile_query`), execution refused.

---

## Capabilities

### New Capabilities
- `semantic-query-model`: `SemanticQuery`, typed filter tree, `CompiledQuery`, error taxonomy.
- `semantic-model-loader`: sidemantic directory loading, Ossie 0.1.1 validation + import, `ModelPolicy` side-files, physical schema map.
- `semantic-governance-compiler`: sqlglot pass — RLS push-down from `RlsRegistry`, column masking, positive allowlist guard, LIMIT policy.
- `semantic-native-compiler`: fallback metrics/dimensions/joins → sqlglot AST compiler with parity tests.
- `semantic-role-catalog`: role-filtered catalog, saved/verified queries registry.
- `semantic-audit`: signed `SemanticAuditEntry` ledger reusing `AbstractKMSSigner` and the storage callable.
- `semantic-layer-toolkit`: `SemanticLayerToolkit` (`sl_*` tools), execution bridge, compiled-SQL cache, DatasetManager hand-off.
- `semantic-layer-http`: `SemanticLayerHandler` + route registration in `manager.py` (lazy import).
- `semantic-layer-mcp`: `.parrot/mcp-toolkits.yaml` section + `static_subject` operator identity for `parrot mcp-local semantic-layer`.
- `ai-parrot-semantic-distribution`: new workspace member (pyproject, PEP 420 layout, extras, `release.py` `PACKAGES` entry, CI matrix).

### Modified Capabilities
- `databasetoolkit` (`sdd/specs/databasetoolkit.spec.md`): none required — `get_source()` is consumed as is. (If a named-connection credential resolver is wanted, it would be an *extension*, see Open Questions.)
- `policy-based-access-control`: no code change; `RlsRegistry`/`RlsRule` reused. Documentation gains the "governed models deny-by-default" statement.
- `mcp-local-server-wikitoolkit`: config-only (new YAML section); no server code.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `packages/ai-parrot-semantic/` (new) | adds | PEP 420 `src/parrot/semantic/` (only this subpackage has `__init__.py`); `dependencies = ["ai-parrot", "sidemantic==0.12.0", "sqlglot>=30.1,<31", "jsonschema"]`; extras `bigquery`, `duckdb` |
| root `pyproject.toml` `[tool.uv.sources]` | modifies | add `ai-parrot-semantic = { workspace = true }` (`members = ["packages/*"]` already picks the dir up) |
| `scripts/release.py` `PACKAGES` | modifies | new `Package("ai-parrot-semantic", …)` entry — a missing entry strands the package at its initial version (see memory note on `parrot-codec`) |
| `packages/ai-parrot/src/parrot/tools/databasequery/toolkit.py` | depends on | `get_source(driver)` + `AbstractDatabaseSource.query()`; no change |
| `packages/ai-parrot/src/parrot/auth/rls_registry.py`, `dataplane_guard.py`, `permission.py`, `context.py` | depends on | RLS rules, PBAC context, ContextVar; no change |
| `packages/ai-parrot/src/parrot/security/audit_ledger.py` | depends on | signer + storage contract reused by `SemanticAuditEntry`; no change (see OQ on extending `AuditLedgerEntry`) |
| `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` | depends on | `add_dataframe()` for the hand-off |
| `packages/ai-parrot-server/src/parrot/handlers/semantic.py` (new) + `manager/manager.py` | extends | `BaseView` handler registered next to `DatasetManagerHandler` (`manager.py:2571`); lazy import, registered only when `parrot.semantic` is importable |
| `.parrot/mcp-toolkits.yaml`, `.mcp.json` | config | `semantic-layer:` section with `class: parrot.semantic.toolkit.SemanticLayerToolkit` |
| `parrot/tools/__init__.py` meta-path finder | none | finder redirects `parrot.tools.<x>` → `parrot_tools.<x>`; `parrot.semantic` is a plain namespace subpackage, no finder change |
| CI | modifies | add `packages/ai-parrot-semantic/tests` to the test matrix; TID251 import-ban check must flag `sidemantic` imports outside the satellite |
| Licensing | adds | first AGPL-3.0 dependency in the workspace; satellite license field pending legal (OQ) |

No breaking changes to existing APIs. New runtime deps are confined to the satellite.

---

## Code Context

### User-Provided Code

No code was pasted during discovery. The input artifact is the research proposal
`sdd/proposals/semantic-layer.proposal.md` (Spanish; 2026-10-14 PyPI/wheel inspection).

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/tools/databasequery/base.py
class ValidationResult(BaseModel): ...          # line 86
class ColumnMeta(BaseModel): ...                # line 100
class TableMeta(BaseModel): ...                 # line 118
class MetadataResult(BaseModel): ...            # line 134
class QueryResult(BaseModel): ...               # line 148
class RowResult(BaseModel): ...                 # line 166
def add_row_limit(...)                          # line 213 — dialect-specific LIMIT injection into a SQL string
class AbstractDatabaseSource(ABC):              # line 323
    driver: str                                 # line 336
    sqlglot_dialect: str | None = None          # line 337
    async def resolve_credentials(self, credentials: dict[str, Any] | None) -> dict[str, Any]   # line 339
    async def validate_query(self, query: str) -> ValidationResult                              # line 362
    async def test_connection(...)                                                              # line 408
    async def get_metadata(...)                                                                 # line 429
    async def query(self, credentials: dict[str, Any], sql: str, params: dict[str, Any] | None = None, ...)  # line 446
    async def query_row(...)                                                                    # line 464
    async def close(self) -> None                                                               # line 515

# From packages/ai-parrot/src/parrot/tools/databasequery/toolkit.py
class DatabaseQueryToolkit(AbstractToolkit):    # line 115 — tool_prefix "dq"
    def __init__(self, **kwargs: Any) -> None   # line 154 — accepts ONLY output_dir / static_dir (+ AbstractToolkit kwargs)
    async def _post_execute(self, tool_name: str, result: Any, /, **kwargs: Any) -> Any  # line 180
    def get_source(self, driver: str) -> AbstractDatabaseSource   # line 202 — cached; in exclude_tools
    async def cleanup(self) -> None             # line 220
# imports at toolkit.py:29,38,39:
#   from parrot.security import QueryLanguage, QueryValidator
#   from parrot.tools.databasequery.sources import get_source_class, normalize_driver
#   from parrot.tools.toolkit import AbstractToolkit

# From packages/ai-parrot/src/parrot/tools/toolkit.py
class ToolkitTool(AbstractTool):                # line 37 — re-injects `_permission_context` into _pre_execute (lines 174-178)
class AbstractToolkit(ServerManagedToolkit, ABC):   # line 225
    exclude_tools: tuple[str, ...] = ()         # line 262
    tool_prefix: str | None = None              # line 276
    def __init__(self, **kwargs)                # line 357
    async def _pre_execute(self, tool_name: str, /, **kwargs) -> None                      # line 491 — receives _permission_context
    async def _post_execute(self, tool_name: str, result: Any, /, **kwargs) -> Any        # line 506 — does NOT receive _permission_context
    def get_tools(...)                          # line 522

# From packages/ai-parrot/src/parrot/tools/abstract.py
class AbstractTool:
    async def execute(self, *args, **kwargs) -> ToolResult   # line 916 — pops "_permission_context" (line 939) and "_resolver"

# From packages/ai-parrot/src/parrot/auth/permission.py
@dataclass(frozen=True) class UserSession:      # ~line 40
    user_id: str; tenant_id: str; roles: frozenset[str]; metadata: dict[str, Any]   # lines 46-49
class PermissionContext:                        # line 81
    session: UserSession; request_id: Optional[str]; channel: Optional[str]; trace_context; extra: dict   # lines 122-126
def to_eval_context(context: "PermissionContext") -> "EvalContext"   # line 209 — userinfo keys: username, user_id, tenant_id, groups, roles, programs

# From packages/ai-parrot/src/parrot/auth/context.py
_pctx_var: contextvars.ContextVar["PermissionContext | None"]   # line 33 — read by DatabaseQueryTool (tool.py:598-600)

# From packages/ai-parrot/src/parrot/auth/rls_registry.py
class RlsRule(BaseModel):                       # line 49
    driver: str; table: str; predicate_template: str; subject_attribute: str; description: str = ""   # lines 63-67
    # predicate_template uses ":subject.<attr>" placeholders, table is "schema.table"
class RlsPredicate(BaseModel):                  # line 70
    table: str; sql_predicate: str; bound_params: dict[str, list[str]]   # lines 82-84
class RlsRegistry:                              # line 87
    def register(self, rule: RlsRule) -> None   # line 112
    def lookup(self, driver: str, tables: set[str]) -> list[RlsRule]   # line 125
    def render(self, rule: RlsRule, ctx: PermissionContext) -> RlsPredicate   # line 150 — missing attribute → sql_predicate "1=0"

# From packages/ai-parrot/src/parrot/auth/dataplane_guard.py
class DataPlanePolicyGuard:                     # line 45 — ctx None → FAIL-OPEN; evaluator error → fail-closed
    def __init__(self, evaluator, rls_registry, sensitive_drivers=..., logger=None)   # line 71
    async def can_connect_driver(...)           # line 113
    async def filter_tables(self, ctx: PermissionContext, driver: str, tables: list[str]) -> set[str]   # line 150
    async def authorize_source(...)             # line 193
    async def rls_predicates(self, ctx: PermissionContext, resources: "PhysicalResources") -> "list[RlsPredicate]"   # line 316
# Built in parrot/auth/pbac.py:355 — DataPlanePolicyGuard(evaluator=evaluator, rls_registry=RlsRegistry())

# From packages/ai-parrot/src/parrot/tools/dataset_manager/sources/rls.py
def inject_rls_sql(sql: str, dialect: str, predicates: "list[RlsPredicate]") -> tuple[str, dict[str, list[str]]]   # line 72
    # WRAPPING strategy: SELECT * FROM (<original>) AS _rls WHERE (...) — values inlined via _escape_sql_value (line 56)
def inject_rls_table_source(...)  # line 132 · inject_rls_query_slug(...) line 172 · inject_rls_mongo(...) line 212 · inject_rls_postfetch(...) line 243

# From packages/ai-parrot/src/parrot/tools/dataset_manager/sources/resolver.py
class PhysicalResources(BaseModel)              # line 47
def resolve_physical_resources(...)             # line 120
# From packages/ai-parrot/src/parrot/tools/dataset_manager/sources/dialects.py
def driver_to_dialect(driver: str) -> Optional[str]   # line 41

# From packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py
class DatasetManager(...):
    def add_dataframe(self, name: str, df: pd.DataFrame, description: Optional[str] = None,
                      metadata: Optional[Dict[str, Any]] = None, is_active: bool = True,
                      computed_columns: Optional[List[Any]] = None,
                      usage_guidance: Optional[Dict[str, List[str]]] = None) -> str   # line 1091
    def _get_current_pctx(self) -> Optional["PermissionContext"]   # line 2663 — reads module-level _pctx_var set by _pre_execute

# From packages/ai-parrot/src/parrot/security/query_validator.py
class QueryLanguage(str, Enum)                  # line 19 — SQL, FLUX, MQL, CYPHER, JSON, AQL
class QueryValidator:                           # line 29
    @classmethod def validate_sql_ast(cls, query: str, dialect: Optional[str] = None, read_only: bool = True,
                                      require_pk_in_where: bool = False, primary_keys: Optional[List[str]] = None) -> Dict[str, Any]   # line 165
    # rejects unparseable / multi-statement / DDL always; read_only allows Select/Union/Intersect/Except/With/Describe/Pragma

# From packages/ai-parrot/src/parrot/security/audit_ledger.py
class AuditLedgerEntry(BaseModel):              # line 80 — fields: entry_id, user_id, channel, tool, provider, key_fingerprint, signature, created_at (lines 99-107)
    def canonical_bytes(self) -> bytes          # line 109
class AbstractKMSSigner(ABC):                   # line 135 — sign(data) -> str (143), verify(data, signature) -> bool (154)
class LocalHMACSigner(AbstractKMSSigner)        # line 166
class AzureKeyVaultSigner(AbstractKMSSigner)    # line 199
class AuditLedger:                              # line 296
    def __init__(self, signer: Optional[AbstractKMSSigner] = None, storage: Optional[Any] = None)   # line 327 — storage is an async callable(json_str)
    async def append(self, *, user_id: str, channel: str, tool: str, provider: str, credential_material: Any) -> AuditLedgerEntry   # line 338

# From packages/ai-parrot/src/parrot/knowledge/common/sql_dialects.py
SQLGLOT_DIALECT_MAP: Dict[str, str]             # line 6 — postgres/postgresql→postgres, bigquery, mysql/mariadb→mysql, sqlite, mssql/sqlserver→tsql, oracle, clickhouse, duckdb, redshift, snowflake

# From packages/ai-parrot/src/parrot/mcp/local_cli.py
@click.command("mcp-local") def mcp_local(name: str | None, config_path: Path | None, include: tuple[str, ...], exclude: tuple[str, ...], list_toolkits: bool) -> None   # line 136-170
# From packages/ai-parrot/src/parrot/mcp/toolkit_config.py
class ToolkitSection(BaseModel): class_path: str = Field(..., alias="class")   # lines 20, 50 (kwargs/env sections per .parrot/mcp-toolkits.yaml:121-129 precedent)
class MCPToolkitsConfig(BaseModel)              # line 80
def load_toolkits_config(root: Path, config_path: Path | None = None) -> MCPToolkitsConfig   # line 90

# From packages/ai-parrot-server/src/parrot/handlers/datasets.py
class DatasetManagerHandler(BaseView):          # line 141 — get 179 / patch 259 / put 311 / post 383 / delete 563
# imports (lines 19-21): from navigator.views import BaseView; from navigator_auth.decorators import is_authenticated, user_session; from navigator_session import get_session
# From packages/ai-parrot-server/src/parrot/manager/manager.py
router.add_view("/api/v1/agents/datasets/{agent_id}", DatasetManagerHandler)                # line 2571
router.add_view("/api/v1/agents/datasets/{agent_id}/{dataset_id}", DatasetManagerHandler)   # line 2572
```

#### Verified Imports
```python
from parrot.tools.databasequery.base import AbstractDatabaseSource, QueryResult, ValidationResult, add_row_limit  # databasequery/base.py:86-323
from parrot.tools.databasequery.toolkit import DatabaseQueryToolkit          # databasequery/toolkit.py:115
from parrot.tools.databasequery.sources import get_source_class, normalize_driver   # toolkit.py:38
from parrot.tools.toolkit import AbstractToolkit                             # tools/toolkit.py:225
from parrot.auth import PermissionContext, UserSession, RlsRegistry, RlsRule, DataPlanePolicyGuard  # auth/__init__.py:33-47 (lazy map)
from parrot.auth.rls_registry import RlsPredicate                            # auth/__init__.py:48
from parrot.auth.context import _pctx_var                                    # auth/context.py:33
from parrot.security import QueryLanguage, QueryValidator                    # security/__init__.py:14
from parrot.security.audit_ledger import AbstractKMSSigner, LocalHMACSigner, AuditLedger, AuditLedgerEntry  # security/__init__.py:50
from parrot.knowledge.common.sql_dialects import SQLGLOT_DIALECT_MAP         # knowledge/common/sql_dialects.py:6
from parrot.tools.dataset_manager.sources.dialects import driver_to_dialect  # dialects.py:41
from parrot.tools.dataset_manager import DatasetManager                      # used by handlers/datasets.py:32
from navigator.views import BaseView                                         # handlers/datasets.py:19
from navigator_auth.decorators import is_authenticated, user_session         # handlers/datasets.py:20
```

#### Key Attributes & Constants
- `AbstractDatabaseSource.driver` → `str`; `.sqlglot_dialect` → `str | None` (base.py:336-337). Concrete sources exist for `postgres.py`, `bigquery.py`, `duckdb.py` (+ mysql, mssql, oracle, clickhouse, sqlite, mongodb, elastic, influx, atlas, documentdb) under `databasequery/sources/`.
- `AbstractToolkit.tool_prefix` / `prefix_separator` / `exclude_tools` (toolkit.py:262-276) — tool name = `f"{tool_prefix}{sep}{method}"`.
- `UserSession.metadata` keys used by PBAC: `groups`, `programs` (permission.py:230-236); `RlsRule.subject_attribute` names one of them.
- `DataPlanePolicyGuard` failure semantics: `ctx is None` → fail-open (dataplane_guard.py:52) — the semantic layer deliberately inverts this for governed models.
- `.parrot/mcp-toolkits.yaml` section shape: `name: {class: <dotted path>, kwargs: {...}, env: {}}` (lines 121-129 for `database-query`); `.mcp.json` runs `parrot mcp-local <name> --config <yaml>`.
- Satellite template: `packages/ai-parrot-embeddings/pyproject.toml` (setuptools, `dynamic = ["version"]`, `dependencies = ["ai-parrot"]`, `license = "MIT"`, `requires-python = ">=3.11,<3.14"`); version file at `src/parrot/embeddings/version.py`; `scripts/release.py` `PACKAGES` list (line 116).
- Root workspace: `pyproject.toml:57-58` `[tool.uv.workspace] members = ["packages/*"]`; `[tool.uv.sources]` at line 229 lists each satellite as `{ workspace = true }`.
- Installed (venv, 2026-10-19): `sqlglot 30.23.0`, `duckdb 1.5.6`, `asyncpg 0.32.0`, `google-cloud-bigquery 3.46.2`. Core pins `sqlglot>=20.0` (ai-parrot/pyproject.toml:182).
- Prior decision: **TASK-1437 → NO-GO for Ibis** (`sdd/tasks/completed/TASK-1437-ibis-connection-spike.md`; `dataset_manager/spatial/compiler.py:19`).

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.semantic`~~ / ~~`packages/ai-parrot-semantic/`~~ — does not exist yet (this feature creates it). ~~`parrot_tools.semantic`~~ — does not exist and must not be created (AGPL boundary).
- ~~`sidemantic`~~, ~~`boring_semantic_layer`~~, ~~`ibis`~~ — **not installed** in the venv; no `import ibis` in `packages/*/src` except the throwaway `_ibis_probe.py`. `ai-parrot-semantic` is where `sidemantic` gets added.
- ~~`SemanticQuery`~~, ~~`CompiledQuery`~~, ~~`SemanticLayerToolkit`~~, ~~`sl_*` tools~~, ~~`SemanticAuditEntry`~~, ~~`ModelPolicy`~~ — none exist; names proposed here.
- ~~`AuditLedgerEntry.payload` / `.compiled_sql` / `.structured_query`~~ — `AuditLedgerEntry` has only `entry_id, user_id, channel, tool, provider, key_fingerprint, signature, created_at`; `AuditLedger.append()` requires `credential_material`. A semantic audit record needs its own entry type (see OQ).
- ~~RLS push-down below aggregation~~ — `inject_rls_sql` exists but only **wraps** the statement; there is no sqlglot-AST RLS rewrite anywhere in the repo.
- ~~Positive table/column allowlist~~ — `QueryValidator.validate_sql_ast` is a *negative* guard (DDL/DML/multi-statement); `SQLToolkit._check_query_safety` (bots/database/toolkits/sql.py:578) is also negative.
- ~~Named-connection credential registry in `DatabaseQueryToolkit`~~ — `__init__` accepts only `output_dir`/`static_dir`; credentials are a per-call argument to `AbstractDatabaseSource.query(credentials, sql)`. The satellite must resolve its model's `connection` into a credentials dict itself.
- ~~`DatabaseQueryToolkit` passing `_permission_context` to `_post_execute`~~ — `_post_execute` receives tool params only (toolkit.py:195-198).
- ~~`packages/ai-parrot-server/src/parrot/models/datasets.py`~~ — the request models live in **core** `packages/ai-parrot/src/parrot/models/datasets.py` (handler imports `..models.datasets` through the merged namespace).
- ~~`UserInfoService.get_attributes()`~~ — `UserInfoService` (auth/userinfo.py:80) exposes `get_profile(user_id)` / `get_profile_by_email(email)` only.
- ~~An async API in sidemantic / BSL / MetricFlow~~ — none; compile in `asyncio.to_thread`.
- ~~`sidemantic-rs` as a requirement of `sidemantic==0.12.0`~~ — the published 0.12.0 wheel does not require it (PyPI JSON 2026-10-19); only `main` does. Pin exact to keep it that way.
- ~~Apache Ossie Python SDK on PyPI~~ — `ossie`/`apache-ossie`/`osi-spec` do not exist; validation is JSON Schema + sidemantic's `ossie` importer.
- ~~A `parrot mcp-local` code change~~ — not needed; a YAML section with a `class:` path is sufficient.
- ~~`ai-parrot-semantic` in `KNOWN_PROJECTS`~~ — the vocabulary (`parrot.knowledge.wiki.ledger.sdd_meta.KNOWN_PROJECTS`) does not list it; the frontmatter value warns, it does not fail. Add it when the package lands.

---

## Parallelism Assessment

- **Internal parallelism**: high after a short sequential head. Task 1 (distribution skeleton:
  pyproject, PEP 420 layout, `release.py`, workspace source, CI) and Task 2 (`SemanticQuery` +
  `CompiledQuery` + error taxonomy + `ModelPolicy` schema) must land first. Then four independent
  lanes: (a) loader + Ossie validation + sidemantic engine, (b) governance compiler (RLS push-down,
  masking, positive guard) with pure sqlglot tests, (c) native compiler + parity fixtures,
  (d) audit ledger + saved queries. The toolkit/execution bridge, then the HTTP handler and the
  MCP config, follow once (a)+(b) are merged.
- **Cross-feature independence**: no in-flight per-spec index with pending tasks touches
  `databasequery/`, `dataset_manager/`, `auth/rls_registry.py`, `auth/dataplane_guard.py`,
  `mcp/` or `handlers/` (checked 2026-10-19 over `sdd/tasks/index/*.json`). The only shared
  files are `packages/ai-parrot-server/src/parrot/manager/manager.py` (two `add_view` lines),
  root `pyproject.toml` (`[tool.uv.sources]`), `scripts/release.py` and `.parrot/mcp-toolkits.yaml`
  — all touched by single, late tasks.
- **Recommended isolation**: `mixed`.
- **Rationale**: the satellite is a brand-new directory, so lanes (a)–(d) write disjoint
  modules under `src/parrot/semantic/` and `tests/`; only the skeleton/contract tasks and the
  final wiring tasks are sequential. Note the shared-venv caveat for worktrees: a new distribution
  is not editable-installed in the main venv, so tests must run with
  `PYTHONPATH=packages/ai-parrot-semantic/src:packages/ai-parrot/src` and `sidemantic` must be
  installed by the main-checkout operator (never `uv sync` inside a worktree).

---

## Open Questions

- [ ] Legal: confirm AGPL-3.0 acceptance in writing and decide the `license` field of `ai-parrot-semantic` itself (MIT with an AGPL dependency vs AGPL-3.0 for the satellite). The user accepted AGPL for the embedded dependency during discovery; the distribution's own license text is still a legal call. — *Owner: Jesus Lara*
- [ ] Reconciliation of "no abstraction" with the native fallback: confirm the single internal `compile()` dispatch on `model.engine ∈ {sidemantic, native}` (no plugin protocol) is the intended reading. — *Owner: Jesus Lara*
- [ ] Audit storage: separate `SemanticAuditEntry` ledger reusing `AbstractKMSSigner` + the async `storage` callable (recommended, zero core change) vs extending `AuditLedgerEntry` with an optional `payload` field in core (`parrot/security/audit_ledger.py`). Where is the storage callable wired in production (Postgres table like `security_events.sql`, or the existing credential ledger sink)? — *Owner: Jesus Lara*
- [ ] Deny-by-default scope: governed models deny when `PermissionContext` is `None`. Should *every* model be governed by default (deny unless the policy file opts out), or only models with RLS/allowlist entries (as drafted)? — *Owner: Jesus Lara*
- [ ] `mcp-local` identity: is a `static_subject` kwarg (user/tenant/roles from `.parrot/mcp-toolkits.yaml`) acceptable for local operators, or must mcp-local calls stay ungoverned-only? — *Owner: Jesus Lara*
- [ ] Credentials for execution: resolve the model's `connection` name via navconfig env lookups inside the satellite (drafted) vs adding a named-connection resolver to `DatabaseQueryToolkit` in core (a modified capability of `databasetoolkit`). — *Owner: Jesus Lara*
- [ ] Free SQL (`sl_run_sql`): ship in v1 behind `allow_raw_sql=False`, or defer the exploration path to a follow-up spec and keep v1 metrics-only? — *Owner: Jesus Lara*
- [ ] sidemantic `SemanticLayer.compile` reentrancy: spike needed (parallel compile under a thread pool) to decide lock vs lock-free; also confirm `load_from_directory` accepts Ossie 0.1.1 fixtures from `github.com/apache/ossie` unchanged. — *Owner: implementing lane (a)*
- [ ] Native compiler v1 subset: confirm "simple aggregations + declared one-to-many joins, no symmetric aggregates, no cumulative/time-comparison metrics" is enough for the fallback's purpose. — *Owner: Jesus Lara*
- [ ] Should the proposal `sdd/proposals/semantic-layer.proposal.md` be committed to `dev` alongside this brainstorm (it is currently untracked)? — *Owner: Jesus Lara*
