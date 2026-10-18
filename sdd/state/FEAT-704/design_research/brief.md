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

### Constraints and goals
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
- **PBAC gates every request.** Resolve physical resources and enforce `driver:connect` and
  `table:read` before returning compiled SQL or executing it, including cache hits, saved queries,
  dimension-value queries and raw SQL. Governed requests fail closed if the evaluator is unavailable.
- **Caches contain no governed SQL.** Cache only pre-governance compiler output. Apply current
  member permissions, PBAC, RLS and masking on every request; never cache authorization decisions.
  No reusable query-result cache in v1; dataset hand-off uses bounded, expiring, subject-owned handles.
- **Sensitive-column use is explicit.** A projection mask grants no right to filter, group, order,
  join or compute on the underlying value. Enforce role-specific usage rights through AST lineage.
- **Dataset isolation survives hand-off.** Results and attached DatasetManager instances must be
  scoped to the authenticated subject and session. A shared manager is not an eligible destination.
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

### Recommended option / probable scope
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
     Resolve column lineage through aliases, CTEs, subqueries and expressions before rewriting;
     reject unauthorized sensitive-column use anywhere in the query. `ModelPolicy` declares
     separate projection and usage rights; absent usage rights deny filters, joins, grouping,
     ordering, windows and derived expressions over masked/hidden columns. Trusted model metric
     definitions may explicitly grant an aggregate use without granting arbitrary raw-SQL use;
     caller-supplied filters and expressions remain subject to the same restrictions. Only
     compiler-injected RLS predicates and mask expressions have trusted provenance; callers cannot
     label SQL as trusted. Unresolved lineage fails closed.
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
   first resolve all physical resources and call `DataPlanePolicyGuard.authorize_source()`.
   The satellite must require an available evaluator for governed models, because the existing
   guard can fail open when the auth dependency is missing. RLS lookup is not authorization.
   Credentials come from the model's named `connection` (env/navconfig), never from the LLM.
7. **Surfaces**: `SemanticLayerToolkit(AbstractToolkit, tool_prefix="sl")`; `parrot mcp-local
   semantic-layer` through a `.parrot/mcp-toolkits.yaml` section (no new server code — `mcp-local`
   already serves any `AbstractToolkit` class path); `SemanticLayerHandler(BaseView)` under
   `/api/v1/agents/semantic/{agent_id}` registered in `manager.py` like `DatasetManagerHandler`;
   `sl_save_result_as_dataset` → a subject/session-scoped `DatasetManager.add_dataframe()` for
   pandas/viz follow-ups; hosts unable to enforce this isolation do not expose the hand-off tool.

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

### Verified code anchors (paths only — open them yourself)
.parrot/mcp-toolkits.yaml
packages/ai-parrot-embeddings/pyproject.toml
packages/ai-parrot-server/src/parrot/handlers/datasets.py
packages/ai-parrot-server/src/parrot/manager/manager.py
packages/ai-parrot-server/src/parrot/models/datasets.py
packages/ai-parrot/src/parrot/auth/context.py
packages/ai-parrot/src/parrot/auth/dataplane_guard.py
packages/ai-parrot/src/parrot/auth/permission.py
packages/ai-parrot/src/parrot/auth/rls_registry.py
packages/ai-parrot/src/parrot/knowledge/common/sql_dialects.py
packages/ai-parrot/src/parrot/mcp/local_cli.py
packages/ai-parrot/src/parrot/mcp/toolkit_config.py
packages/ai-parrot/src/parrot/models/datasets.py
packages/ai-parrot/src/parrot/security/audit_ledger.py
packages/ai-parrot/src/parrot/security/query_validator.py
packages/ai-parrot/src/parrot/tools/abstract.py
packages/ai-parrot/src/parrot/tools/databasequery/base.py
packages/ai-parrot/src/parrot/tools/databasequery/toolkit.py
packages/ai-parrot/src/parrot/tools/dataset_manager/sources/dialects.py
packages/ai-parrot/src/parrot/tools/dataset_manager/sources/resolver.py
packages/ai-parrot/src/parrot/tools/dataset_manager/sources/rls.py
packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py
packages/ai-parrot/src/parrot/tools/toolkit.py
scripts/release.py
sdd/proposals/semantic-layer.proposal.md
sdd/tasks/completed/TASK-1437-ibis-connection-spike.md

### Questions still open in the exploration document
- [ ] sidemantic `SemanticLayer.compile` reentrancy: spike needed (parallel compile under a thread pool) to decide lock vs lock-free; also confirm `load_from_directory` accepts Ossie 0.1.1 fixtures from `github.com/apache/ossie` unchanged. — *Owner: implementing lane (a)*

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
