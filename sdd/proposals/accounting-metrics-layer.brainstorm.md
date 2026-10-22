---
# SDD flow type and base branch.
type: feature
base_branch: dev
---

# Brainstorm: Accounting Metrics Layer — chart-of-accounts rollups compiled to deterministic queries

**Date**: 2026-10-20
**Author**: Jesus Lara (drafted with Claude)
**Status**: accepted (2026-10-21; Open Questions resolved the same day)
**Recommended Option**: B
**Related**: `claude/semantic-layer.research.md` (generic semantic layer candidates, 2026-10-14); `claude/schema-plane.brainstorm.md` (SQL metadata plane)
**Inspiration**: dbt MetricFlow (derived metrics, filtered measures), Cube (`filters:` on measures), ledger-style compile-time validation

---

## Problem Statement

Finance questions that agents receive — "revenue for Pokémon at TROC last quarter", "EBITDA by cost center", "operating expenses YTD" — are not analytical questions over a schema; they are **rollups over a chart of accounts**. Which GL accounts sum into *revenue*, which ones are netted (returns, discounts), what sign convention applies to each account, and which accounts moved between buckets at the last fiscal year change is **internal, closed knowledge** that no LLM has and no `information_schema` exposes.

Today the only places that knowledge could live are:

1. **A skill / system prompt in prose.** Lossy by construction: a list of 40 account codes in a markdown skill will eventually be paraphrased, truncated or partially recalled, and one omitted account silently changes the number. There is no way to *validate* a prose skill against the chart of accounts.
2. **Free-form SQL from the DB Query Toolkit.** The agent writes the aggregation itself. Even with the sqlglot positive allowlist guard planned in the semantic-layer research, the guard validates *tables and columns*, not *which accounts belong in the `IN (...)` list*. The query is syntactically safe and semantically wrong.
3. **A view maintained by DBAs.** Deterministic, but opaque to the agent (no lineage, no explanation), not portable to in-memory DataFrames in `DatasetManager`, and the "why is revenue this number" question cannot be answered.

The generic semantic layer (BSL/Ibis per the research, sidemantic pending legal) solves metric *naming* and *governance*, but its primitives (measures, dimensions, joins) do not express the accounting-specific invariants: completeness of the chart of accounts over the declared buckets, debit/credit sign normalisation, effective-dated account membership, and reconciliation assertions (`revenue − expenses == net_income`).

Who is affected: any agent using `DatabaseToolkit` / `SQLToolkit` or `DatasetManager` over a general ledger; finance users of the client deployments (TROC is the first concrete case); the AuditLedger (a financial figure must be traceable to the exact query and the exact model version that produced it). Why now: the semantic-layer spec is in progress and this layer must be designed as its *specialisation*, not bolted on after; and the first client request for GL-level answers is on the table.

## Constraints & Requirements

- **The LLM never writes the aggregation.** It selects `metric + grain + filters + period`; the compiler produces the query. This is the "probabilistic proposes, deterministic decides" invariant applied to finance. (Owner constraint.)
- **One compiler, two execution targets.** The same compiled SQL text runs against the source database through `DatabaseToolkit` and against in-memory DataFrames through `DatasetManager`. (Owner decision, 2026-10-20.)
- **DuckDB is the in-process engine; Arrow is the bridge.** polars/pandas DataFrames are registered into DuckDB via Arrow (zero-copy), never serialised. No pickle across trust boundaries (security invariant). (Owner decision, 2026-10-20.)
- **A basic, closed parser.** The metric expression grammar covers exactly what the accounting layer needs — sums over account sets, `+ − × ÷`, parentheses, references to other metrics — and nothing more. No conditionals, no free functions, no inline SQL. Growth pressure on the grammar is a signal that an account set is missing, not that the grammar is. (Owner decision, 2026-10-20.)
- **Home and packaging (resolved 2026-10-21).** `parrot.semantic.accounting`, a standalone package inside the `ai-parrot-semantic` satellite — **not** an engine of FEAT-704 (semantic layer), which is approved but paused until its AGPL-3.0 dependency (sidemantic) is migrated away. FEAT-704's satellite does not exist yet, so this feature creates its skeleton (PEP 420, **no sidemantic**) and FEAT-704 builds on it when it resumes.
- **No new heavy dependency.** `sqlglot` (already used by `SQLToolkit`), `duckdb`, `pyarrow`, Pydantic v2. No AGPL code in the tree; the YAML *shape* may borrow from Cube/MetricFlow conventions, adapter code may not.
- **Determinism is a contract.** Same model version + same request ⇒ byte-identical SQL. `IN (...)` lists sorted, CTE/column names derived from the model, no timestamps or random aliases in the output. The SQL hash and the model hash are recorded with every result.
- **Compile-time validation, never runtime surprises.** Chart-of-accounts completeness, metric cycles, empty sets, dangling references and declared reconciliation assertions are checked when the model loads. A model that fails validation does not load.
- **Explainability for finance people.** Every result carries lineage: which account sets contributed, which concrete accounts each set resolved to, and the formula. A controller must be able to accept the number without reading SQL.
- **Multi-tenant, per-model security.** Models are tenant-scoped; metric visibility is filtered by the PBAC context like any other catalog entry in `DatasetManager`. Results caches are never shared across security contexts (research rule).
- **Pydantic at the I/O boundary; `parrot.interfaces.*` contract pattern** with lazy loading of the DuckDB/Arrow implementation behind an optional extra.
- **Language split:** identifiers, YAML keys, module paths and docs in English.
- **Validation-first:** spikes prove Arrow registration, cross-dialect compilation of the `CASE`-column pattern, and completeness checking on a real chart of accounts before `/sdd-spec`.

---

## Options Explored

### Option A: Express the accounting model as a profile on top of the generic semantic layer engine (BSL / Ibis)

Map `account_sets` to *filtered measures* (`sum(amount) where account_id in (...)`) and `metrics` to *derived metrics* in whatever engine the semantic-layer spec selects (Boring Semantic Layer over Ibis per the research; sidemantic if legal clears AGPL). The accounting YAML becomes a front-end that lowers into the engine's model objects; compilation and dialect rendering are the engine's.

✅ **Pros:**
- One engine, one catalog, one MCP surface for all metrics (financial or not).
- Dialect coverage for free (Ibis: 20+ backends).
- Lowering is conceptually simple: set → filtered measure, metric expression → derived metric.

❌ **Cons:**
- The accounting invariants are **not expressible** in the engine: completeness of the chart of accounts, effective-dated membership, reconciliation assertions, sign normalisation by account nature. They would have to be enforced by a pre-pass that then *trusts* the engine to render what was validated — two sources of truth for the same semantics.
- Lineage comes from the lowering layer, not from the engine; the engine's SQL (CTE per measure, joins) is not the single-scan `CASE` form finance can read, and its shape is not under our control across engine versions — determinism as a byte-level contract becomes fragile.
- The engine choice is still open (legal on AGPL; BSL's `ibis-framework<12` pin). Coupling the finance layer to it blocks this feature on that decision.
- Ibis is sync-only by design; compilation must be wrapped in `asyncio.to_thread` (acceptable, but another moving part for a small grammar).

📊 **Effort:** Medium (plus the open engine decision)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `boring-semantic-layer` + `ibis-framework` | engine | per research; MIT / Apache-2.0; pin issue |
| `sqlglot` | post-validation of rendered SQL | already in tree |

🔗 **Existing Code to Reuse:**
- `bots/database/toolkits/sql.py::SQLToolkit` — execution path and `_SQLGLOT_DIALECT_MAP`.
- Semantic-layer spec's `SemanticQuery` and catalog (in progress).

---

### Option B: Dedicated accounting compiler — YAML → Pydantic IR → sqlglot AST → single-scan SQL; DuckDB over Arrow for DataFrames — *recommended*

A small package (`parrot.semantic.accounting` → `packages/ai-parrot-semantic/src/parrot/semantic/accounting/`; this feature creates the satellite skeleton — see Open Questions) with four parts:

1. **Model** (`model.py`) — Pydantic v2, frozen, hashable:
   - `ChartOfAccounts`: source (`table` or `dataframe`), `account_key`, **`amount_sign: by_nature | signed`** (required, no default — resolved 2026-10-21), `nature` column or per-account map (`debit | credit`, required only with `by_nature`), optional `parent_key` for hierarchy, `amount`, `posting_date`, `entity`/`dimension` columns.
   - `AccountSet`: explicit `accounts: [...]`, or selector (`prefix`, `range`, `tag`, `parent`) plus `except`; optional `valid_from` / `valid_to`. Selectors are **resolved at compile time** against the loaded chart of accounts and materialised to an explicit sorted list; the SQL always carries a literal `IN (...)`. The model hash therefore changes when the chart of accounts changes, which is the desired behaviour.
   - `Metric`: `expr` string over sets and other metrics, `description`, `dimensions` allowed, optional `unit`.
   - `Assertion`: `expr == expr` pairs evaluated as validation queries (e.g. `revenue - total_expenses == net_income`).
   - `Model`: `name`, `version`, `tenant`, `chart_of_accounts`, `sets`, `metrics`, `assertions`, `excluded` (accounts deliberately outside every set, with a `reason`).

2. **Parser** (`grammar.py`) — a Pratt parser (~100 lines) for the metric expression language:
   ```
   expr   := term (("+" | "-") term)*
   term   := factor (("*" | "/") factor)*
   factor := "sum" "(" SET ")" | METRIC | NUMBER | "(" expr ")" | "-" factor
   ```
   Produces a typed AST (`Sum(set)`, `Ref(metric)`, `Num`, `BinOp`). No other node kinds exist.

3. **Compiler** (`compiler.py`) — three passes:
   - *Resolve*: selectors → explicit account lists (with `valid_from/valid_to` filtered by the requested period); detect empty sets, dangling refs, metric cycles (topological sort), **completeness** (every account in the chart is in ≥ 1 set or in `excluded`).
   - *Inline*: each requested metric is expanded to a tree over `Sum(set)` leaves; shared sets are deduplicated.
   - *Emit*: one `SELECT` over the journal table with one column per distinct set — `SUM(CASE WHEN account_id IN (...) THEN amount * sign END) AS set_<name>` — grouped by the requested grain, wrapped in an outer `SELECT` that computes the metric arithmetic over the set columns. Built with `sqlglot.exp` nodes, rendered with `sql(dialect=...)`. A composite metric is **N `CASE` columns and one expression**, never N subqueries; this is fast in DuckDB and readable by finance.
   - Output: `CompiledMetricQuery(sql: str, dialect: str, sql_hash: str, model_hash: str, lineage: Lineage, assertions: list[CompiledMetricQuery])`.

4. **Execution** (`runtime.py`, behind the optional extra):
   - `DatabaseToolkit` path: `compile(..., dialect=toolkit.dialect)` → existing execution (`asyncpg` etc.), result + `CompiledMetricQuery` metadata to the accounting audit ledger (`AccountingAuditEntry`).
   - `DatasetManager` path: `DuckDBRunner` registers the DataFrame via `con.register(name, arrow_table)` (polars `to_arrow()`, pandas via `pyarrow.Table.from_pandas`) and executes the same `sql` compiled with `dialect="duckdb"`. One `DuckDBPyConnection` per worker thread (`root.cursor()`), `asyncio.to_thread` for execution — the connection is not thread-safe (research note).

Tool surface (separate named tools, per the "multi-purpose tools fail" principle): `finance_list_metrics`, `finance_explain_metric` (formula + resolved accounts + assertions touching it), `finance_query_metric(metric, grain, filters, period)` returning rows **and** lineage, `finance_validate_model` (CLI/MCP, runs completeness + assertions against live data).

✅ **Pros:**
- All accounting invariants live in one place and are enforced at load time; the SQL shape is fully under our control, so byte-level determinism is a real contract.
- Independent of the generic engine decision; can later be *lowered* into BSL/sidemantic (Option A becomes an export, not a dependency).
- Single scan + `CASE` columns: trivial to read, trivial to explain, fast in DuckDB and Postgres alike.
- Lineage is a by-product of the resolve pass — no extra work to answer "which accounts made this number".
- Tiny grammar ⇒ tiny attack surface; no SQL from the model author either (sets are data, not expressions).

❌ **Cons:**
- A second compiler next to the generic one; both emit SQL through sqlglot but the models are different objects. Mitigated by keeping this one deliberately small and by the planned lowering.
- No joins in v1: the journal must already carry the dimensions (entity, product line, cost center) or a pre-joined view must be pointed at. Acceptable for GL fact tables; a `dimension_source` join is a v2 item.
- Natural calendar only in v1. Cumulative YTD/QTD/MTD over that calendar **is** in v1 (client requirement, 2026-10-21); fiscal calendars, consolidation and multi-currency are non-goals.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `sqlglot` | AST construction + dialect rendering | core declares `sqlglot>=20.0`; the satellite pins `>=30.1,<31` (FEAT-704's pin) and the per-dialect golden tests guard rendering changes — they would break the byte-level contract |
| `duckdb` | in-process engine for DataFrames | MIT; not a dependency anywhere today (verified 2026-10-21); optional extra `duckdb` (`duckdb>=1.0`) of `ai-parrot-semantic`, the same extra FEAT-704 declares |
| `pyarrow` | zero-copy registration | already a core dependency (`pyarrow>=25.0`, `packages/ai-parrot/pyproject.toml`) |
| `pydantic` v2 | model + IR | in stack |

🔗 **Existing Code to Reuse:**
- `bots/database/toolkits/sql.py::SQLToolkit` — `_SQLGLOT_DIALECT_MAP`, `validate_query`, execution; the compiled SQL goes through the same positive allowlist guard as free SQL (defence in depth).
- `bots/database/models.py::TableMetadata` — to validate that `account_key`, `amount`, `posting_date` columns exist before compiling (schema plane later).
- `parrot.security.audit_ledger` — reuse the signers (`AbstractKMSSigner`, `LocalHMACSigner`) and the async `storage(json_str)` contract for a new signed `AccountingAuditEntry`. `AuditLedgerEntry` itself is credential-shaped (`user_id`, `channel`, `tool`, `provider`, `key_fingerprint`) and is **not** extended (same decision FEAT-704 took for its own ledger).
- `DatasetManager` catalog + PBAC filtering (`parrot/tools/dataset_manager/`; catalog shape ⚠️ VERIFY in spec) — metrics registered as catalog entries with `kind="accounting_metric"`.
- `parrot.interfaces.*` lazy-loading pattern (`faiss _try_create_faiss_store`) for the DuckDB runner.

---

### Option C: Keep the knowledge in a skill / prompt (status quo)

The chart-of-accounts rollups are written as a skill (`SKILL.md` + tables), the agent composes SQL itself through the DB Query Toolkit.

✅ **Pros:**
- Zero code; finance can edit markdown.

❌ **Cons:**
- This is the problem statement. No validation, no completeness, no determinism, no lineage. Every answer is a fresh chance to omit an account.
- The sqlglot allowlist guard cannot catch a semantically incomplete `IN (...)`.

📊 **Effort:** None — and not acceptable for financial figures.

---

### Option D: Pre-materialised metric tables via Flowtask (ETL), agents only read

Compile the model once per period into physical tables (`fin_metrics_monthly(entity, product_line, period, metric, value)`) with a Flowtask job; agents query the materialised table through the normal toolkit.

✅ **Pros:**
- Fastest at query time; trivially cacheable; survives source outages.
- Natural fit for closed periods and reporting packs.

❌ **Cons:**
- Freshness lag; no ad-hoc dimension the job did not pre-aggregate; the rollup logic still has to be *compiled* from somewhere — which is Option B's compiler.
- Loses lineage at query time unless the materialisation also stores it.
- Duplicates logic if hand-written SQL in the Flowtask job drifts from the model.

📊 **Effort:** Low on top of B; High if done without B.

*(Worth keeping as an **output mode** of Option B: `compile(...).to_flowtask_job()` materialises closed periods; open periods go live. Not v1.)*

---

## Recommendation

**Option B.** The accounting layer is small enough to own and specific enough that no generic engine will enforce its invariants. Owning the compiler gives three things the alternatives cannot:

1. **Completeness as a load-time error.** The one failure mode finance cares about — an account silently missing from a bucket — becomes impossible to ship: the model does not load.
2. **Determinism as a contract, not a hope.** We control the AST and pin sqlglot; the SQL hash is reproducible across machines and months, which is what the AuditLedger needs.
3. **Independence from the engine decision.** Legal's answer on AGPL and BSL's Ibis pin stop being blockers (FEAT-704 is in fact paused on the AGPL migration as of 2026-10-21); when the generic layer lands, this model lowers into it as filtered + derived metrics, so finance metrics appear in the same catalog without rewriting them.

What we trade: a second (tiny) compiler and no joins in v1. Option D stays available as a materialisation mode; Option A becomes the lowering path.

---

## Feature Description

### User-Facing Behavior

- A finance owner (or the dev on their behalf) writes `models/<tenant>/<model>.yaml`:

  ```yaml
  model: troc_pnl
  version: 2026.10
  chart_of_accounts:
    source: { table: gl.journal }       # or { dataframe: "<catalog name>" }
    account_key: account_id
    amount: amount
    posting_date: posted_at
    amount_sign: by_nature              # required: by_nature | signed (no default)
    nature: { from_column: nature }     # debit | credit → sign normalisation (only with by_nature)
    dimensions: [entity, product_line, cost_center]

  sets:
    product_sales: { accounts: ["4000", "4010", "4015"] }
    returns:       { accounts: ["4900"] }
    cogs:          { select: { prefix: "5" }, except: ["5900"] }
    opex:          { select: { range: ["6000", "6799"] } }
    d_and_a:       { accounts: ["6810", "6820"], valid_from: "2025-01-01" }

  excluded:
    - { accounts: ["9999"], reason: "suspense, cleared monthly" }

  metrics:
    revenue:          { expr: "sum(product_sales) - sum(returns)" }
    gross_margin:     { expr: "revenue - sum(cogs)" }
    operating_income: { expr: "gross_margin - sum(opex)" }
    ebitda:           { expr: "operating_income + sum(d_and_a)" }

  assertions:
    - "revenue - sum(cogs) - sum(opex) == operating_income"
  ```

- `parrot finance validate models/troc/troc_pnl.yaml [--live]` reports: unassigned accounts (error), empty sets after resolution (error), metric cycles (error), and with `--live` runs the assertions against the source for the last closed period.
- Agents see three tools. `finance_list_metrics` (catalog, PBAC-filtered). `finance_explain_metric("ebitda")` returns the formula tree, each set with its resolved accounts and the assertions that cover it — in plain text suitable for the chat. `finance_query_metric(metric="revenue", grain={"period": "month"}, filters={"entity": "TROC", "product_line": "Pokémon"}, period={"from": "2026-07-01", "to": "2026-09-30"})` returns rows plus `lineage` and `sql_hash`; the agent's answer can show the breakdown by set.
- `period` also accepts `cumulative: "ytd" | "qtd" | "mtd"` over the natural calendar: each output row carries the running total from the start of its year/quarter/month (e.g. `grain=month, cumulative=ytd` for July–September returns the YTD figure at each month end).
- The same `finance_query_metric` works when the journal is a DataFrame loaded in `DatasetManager` (e.g. an exported trial balance): the request is compiled with `dialect="duckdb"` and executed in-process.
- Every result is appended to the accounting audit ledger as a signed `AccountingAuditEntry` with `model`, `version`, `model_hash`, `sql_hash`, the canonical request and a `lineage_ref`. Lineage is **not** stored inline: it is a deterministic function of `model_hash` + canonical request, so `finance_explain_metric` can rebuild it from the versioned model in git.
- Live validation runs on demand (`parrot finance validate --live`) **and** as a scheduled task that checks the last closed period's assertions and new unassigned accounts; findings set `chart_drift` / `assertion_failed` on subsequent results until resolved.

### Internal Behavior

1. `load_model(path | dict, chart: ChartOfAccountsSnapshot) -> Model` — Pydantic validation; selector resolution against the chart snapshot (list of `(account_id, nature, parent_id, tags)` fetched once per load from the source or the DataFrame); completeness, cycles, empties, dangling refs → `ModelValidationError` with the full list of problems (never the first one only).
2. `parse_expr(str) -> Expr` — Pratt parser; raises `GrammarError` with position.
3. `compile(model, request: MetricRequest, dialect: str) -> CompiledMetricQuery` — inline → dedupe sets → build `sqlglot.exp.Select` (inner: `SUM(CASE …)` per set, `WHERE posting_date BETWEEN … AND dimension filters`, `GROUP BY grain`; outer: metric arithmetic, `ORDER BY grain`) → `sql(dialect)`; for `cumulative` requests the scan's lower bound is widened to the start of the earliest window, each **set column** is turned into a running sum (`SUM(set_x) OVER (PARTITION BY <window key>, <dimensions> ORDER BY <grain>)`), the metric arithmetic is applied *after* the window (so a YTD ratio is the ratio of YTD sums, never a sum of ratios), and an outer filter drops rows before the requested `from`; `sql_hash = sha256(dialect + sql)`; `model_hash = sha256(canonical JSON of the resolved model)`.
4. `DuckDBRunner.execute(compiled, frames: dict[str, pa.Table])` — register, execute in a worker thread with a per-thread cursor, return `pa.Table` (callers convert to polars/pandas as they already do).
5. `DatabaseRunner.execute(compiled, toolkit)` — hands the SQL to the existing toolkit execution path after the positive allowlist guard.
6. Catalog registration — on model load, each metric becomes a `DatasetManager` catalog entry (`kind="accounting_metric"`, `model`, `version`, allowed dimensions); PBAC filtering is the catalog's, not this package's.
7. Caching — compile results cached by `(model_hash, canonical request, dialect)`; result caching, if any, keyed additionally by the security context and never shared across contexts.
8. Scheduled validation — a scheduler task per loaded model runs completeness against a fresh chart snapshot and the assertions over the last closed period; it records a signed audit entry and flags drift on the model's catalog entry.

### Edge Cases & Error Handling

- **Account present in two sets** → allowed only when both sets are in `allow_overlap: true` pairs (e.g. a memo bucket); otherwise a validation error. Double counting is the second most common finance bug after omission.
- **Selector resolves differently over the requested period** (`valid_from/valid_to`) → **refused in v1** (resolved 2026-10-21) with an error that names the cut-over date and suggests splitting the request; a cumulative window (e.g. YTD) that reaches back across a membership change is refused the same way. Slice + `UNION ALL` is a v2 option.
- **Chart snapshot drifted since load** (new accounts posted) → `--live` validation and a periodic check flag new unassigned accounts; queries keep running on the loaded model but the result carries `chart_drift: true`.
- **Metric referencing a set with `valid_from` after the period** → compile error, not an empty number.
- **`amount_sign` missing, or `by_nature` with accounts lacking a nature** → validation error listing every such account; `signed` with a `nature` mapping present → validation error (ambiguous intent).
- **Unknown dimension / filter column** → rejected at request validation (Pydantic), before compilation.
- **Division by zero in ratios** → `NULLIF` emitted in the AST; v1 grammar has `/` so this is mandatory.
- **sqlglot upgrade changes rendering** → CI golden tests (`tests/golden/*.sql`) per dialect; the pin is explicit and the golden diff is the review artifact.
- **DuckDB connection used across threads** → never; `DuckDBRunner` owns one root connection and hands cursors per thread.
- **Pandas with non-Arrow dtypes (object columns)** → conversion errors surfaced as a typed `DataFrameConversionError`; no silent casting of amounts.

---

## Capabilities

### New Capabilities
- `accounting-model`: Pydantic model + YAML loader + selector resolution + completeness/cycle/assertion validation.
- `accounting-grammar`: closed Pratt grammar for metric expressions.
- `accounting-compiler`: sqlglot AST emitter (single-scan `CASE` form), hashing, lineage.
- `accounting-runtime-duckdb`: Arrow registration of polars/pandas frames, threaded execution (optional extra).
- `accounting-tools`: `finance_list_metrics`, `finance_explain_metric`, `finance_query_metric`, `finance_validate_model` (MCP + toolkit), CLI `parrot finance validate`.
- `accounting-golden-tests`: per-dialect golden SQL fixtures guarding determinism.
- `semantic-satellite-skeleton`: `packages/ai-parrot-semantic` PEP 420 distribution (no sidemantic), `duckdb` extra, `scripts/release.py` `PACKAGES` entry, CI test step.
- `accounting-audit`: signed `AccountingAuditEntry` + ledger using the core signers and storage contract.
- `accounting-scheduled-validation`: scheduler task running completeness + live assertions per model.

### Modified Capabilities
- `dataset-manager-catalog`: new entry kind `accounting_metric`; PBAC filtering applies. ⚠️ VERIFY against the semantic-layer spec's catalog shape.
- `sql-toolkit-execution`: accept a `CompiledMetricQuery` (SQL + metadata) in addition to raw SQL so the ledger record carries hashes. ⚠️ VERIFY current execution entry point signature.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `packages/ai-parrot-semantic/` (new satellite skeleton) | new | `pyproject.toml`, `src/parrot/semantic/__init__.py` (no `src/parrot/__init__.py`), tests; no sidemantic |
| `parrot/semantic/accounting/` (new) | new | `model.py`, `grammar.py`, `compiler.py`, `runtime.py`, `tools.py`, `cli.py`, `audit.py`, `schedule.py` |
| `bots/database/toolkits/sql.py` | extends | execute `CompiledMetricQuery`; reuse `_SQLGLOT_DIALECT_MAP` |
| `parrot/tools/dataset_manager/` (`DatasetManager`) | extends | catalog entries; Arrow handoff to `DuckDBRunner` |
| `parrot/security/audit_ledger.py` | uses | signers + `storage(json_str)` contract; `AuditLedgerEntry` unchanged |
| `parrot/interfaces/` | new contract | `AccountingModel`, `CompiledMetricQuery`, `MetricRequest`, `Lineage` — always importable |
| `packages/ai-parrot-semantic/pyproject.toml`, `scripts/release.py` | new / modifies | extra `duckdb = [duckdb>=1.0]`; `sqlglot>=30.1,<31`; `PACKAGES` entry (a package missing there strands at its initial version) |
| `packages/ai-parrot-semantic/tests/golden/accounting/` | new | per-dialect golden SQL |
| FEAT-704 semantic layer (approved, **paused** pending AGPL migration) | coordinates | the skeleton must leave room for its modules; `parrot.semantic.models.CompiledQuery` is reserved by FEAT-704, hence `CompiledMetricQuery` here; lowering deferred |

No breaking API changes. New config keys: `FINANCE_MODELS_DIR`, `FINANCE_DUCKDB_THREADS`.

---

## Code Context

### User-Provided Code
_None — decisions were given in prose on 2026-10-20: DuckDB as the single in-process engine, Arrow for polars/pandas DataFrames, a basic parser restricted to what the accounting layer needs; implement in-house rather than depend on sidemantic (AGPL-3.0, under legal review) or another external semantic layer._

### Verified Codebase References
_⚠️ This brainstorm was drafted without a live checkout. The references below were verified in `claude/schema-plane.brainstorm.md` (2026-09) and `claude/semantic-layer.research.md` (2026-10-14) and MUST be re-verified by `/sdd-brainstorm` against `dev` before `/sdd-proposal`._

#### Classes & Signatures
```python
# bots/database/toolkits/sql.py                                   ⚠️ VERIFY line anchors
_SQLGLOT_DIALECT_MAP = {"postgresql","postgres","bigquery","mysql","mariadb","sqlite","mssql","sqlserver","oracle","clickhouse","duckdb","redshift","snowflake"}  # → sqlglot names
class SQLToolkit(DatabaseToolkit): _metadata_source = "information_schema"
    async def describe_table(self, schema, table) -> Optional[TableMetadata]
    async def validate_query(self, sql) -> Dict      # "Table '<s>.<t>' not found in cache."

# bots/database/models.py
class Completeness(IntEnum): NAME_ONLY=1; WITH_COLUMNS=2; FULL=3
@dataclass class TableMetadata: schema, tablename, table_type, full_name, comment, columns, primary_keys, foreign_keys, ...
```

#### Verified Imports
```python
from parrot.bots.database.toolkits.sql import SQLToolkit          # ⚠️ VERIFY path
from parrot.bots.database.models import TableMetadata, Completeness
import sqlglot
from sqlglot import exp
```

#### Key Attributes & Constants
- sqlglot is the transpiler already used for dialect mapping and query validation in `SQLToolkit`; research notes it "is a transpiler, not a validator" — the positive allowlist guard stays in front of execution.
- DuckDB `DuckDBPyConnection` is not thread-safe; per-thread `cursor()` from a root connection (research note, DuckDB Python docs).
- Research rule: never share result caches across security contexts; compile cache is safe to share (it depends only on model + request + dialect).

### Does NOT Exist (Anti-Hallucination) — ⚠️ VERIFY each before /sdd-proposal
- ~~any chart-of-accounts, GL, ledger-rollup or "finance" module under `parrot/`~~ — not referenced in any brainstorm, research doc or memory; assume absent.
- ~~`parrot.semantic` package~~ — verified absent 2026-10-21; FEAT-704 would create it but is paused, so this feature creates the satellite skeleton.
- ~~`duckdb` as a dependency or extra in any `pyproject.toml`~~ — verified absent 2026-10-21.
- ~~Arrow registration of DataFrames anywhere in `DatasetManager`~~ — the "Pickle across sandbox = RCE; use Arrow IPC" principle exists, an Arrow→DuckDB handoff does not.
- ~~a `SemanticQuery` / `CompiledQuery` Pydantic model in the tree~~ — specified by FEAT-704 (`parrot.semantic.models`), not implemented; this feature names its own model `CompiledMetricQuery` to avoid the collision.
- ~~golden SQL tests~~ — none known.
- ~~AuditLedger fields for query hashes~~ — verified 2026-10-21: `AuditLedgerEntry` carries credential fields only; hashes go in the new `AccountingAuditEntry`.

---

## Parallelism Assessment

- **Internal parallelism**: yes, after a foundation lane. **Lane 0**: satellite skeleton + `parrot.interfaces` contracts (`AccountingModel`, `MetricRequest`, `CompiledMetricQuery`, `Lineage`) + grammar + model validation — pure Python, no I/O, unblocks everything. **Lane 1**: compiler + golden tests (depends on Lane 0). **Lane 2**: DuckDB runner + Arrow registration (depends on Lane 0 only; can be built against a hand-written SQL fixture before Lane 1 lands). **Lane 3**: tools/MCP/CLI + catalog + accounting audit + scheduled validation (depends on Lanes 1–2 interfaces).
- **Cross-feature independence**: coordinates with the semantic-layer FEAT on (a) the catalog entry shape in `DatasetManager`, (b) reuse of the `SemanticQuery` filter tree for `MetricRequest.filters`, (c) the package home. Does not touch the wiki planes, GraphIndex, memory, or the SDD tooling. Touches `SQLToolkit` only additively.
- **Recommended isolation**: `mixed` — one worktree for Lane 0, then per-lane worktrees; Lane 3 last.
- **Rationale**: Lane 0 is a handful of frozen Pydantic models everything imports; the rest are additive modules in one new package plus small extensions, which merge cleanly.

---

## Spikes (gates before `/sdd-spec`)

- **S1 — Arrow → DuckDB handoff.** Register a 5M-row polars frame and the equivalent pandas frame; measure registration cost (expect ~0 copy for polars `to_arrow()`, one copy for pandas object columns) and a `SUM(CASE …)` with 500-element `IN` lists grouped by month. Confirm the per-thread cursor pattern under `asyncio.to_thread` with 8 concurrent requests. Pass: no copy for polars numeric columns; p95 < 300 ms at 5M rows on a laptop.
- **S2 — Cross-dialect determinism of the `CASE`-column form.** Build the AST once, render for `duckdb`, `postgres`, `bigquery`; execute on DuckDB and Postgres (BigQuery compile-only). Pin sqlglot and verify that re-rendering is byte-identical across 50 runs and that sorted `IN` lists survive transpilation. Pass: identical hashes; results equal across engines on a 10k-row fixture with mixed debit/credit natures.
- **S3 — Completeness on a real chart of accounts.** Run the resolve + completeness pass on TROC's (or an anonymised) chart with the draft `troc_pnl.yaml`. Measure how many accounts fall unassigned on the first draft and how many selectors (`prefix`, `range`) are needed versus explicit lists. Pass: a finance owner can reach zero unassigned accounts in one session; the error report is actionable without reading code. This spike also decides whether `parent`-based selectors (hierarchy rollup) are needed in v1.
- **S4 — Effective-dated membership.** With a set whose `valid_from` falls inside the requested period, compare the `UNION ALL`-per-slice strategy against refusing the request. Decision taken (2026-10-21): refuse in v1. Pass: the refusal error names the cut-over date and is actionable for the interannual example that motivated `valid_from`, including a YTD request that crosses it.
- **S5 — Lowering sketch (non-blocking).** Hand-lower the draft model into BSL filtered/derived metrics to confirm Option A remains a viable v2 export. Not a gate; informs the semantic-layer spec.

---

## Open Questions

All resolved on 2026-10-21 (owner: Jesus).

- [x] **Package home** → `parrot.semantic.accounting` in the `ai-parrot-semantic` satellite, as a **standalone package, not an engine** of FEAT-704. FEAT-704 is paused until sidemantic (AGPL-3.0) is migrated away; this feature creates the satellite skeleton without sidemantic.
- [x] **Where models live per tenant** → git, `<models_dir>/<tenant>/<model>.yaml`, reviewed in PRs; `model_hash` is tied to a commit. Admin UI is v2.
- [x] **Effective-dated membership strategy** → refuse requests (including cumulative windows) that span a membership change in v1, with an actionable error. Slice + `UNION ALL` is v2. S4 validates the error.
- [x] **Sign convention** → explicit required key `amount_sign: by_nature | signed`, no default. `nature` is required only with `by_nature`.
- [x] **Hierarchy selectors** (`parent:`) → v2 by default; S3 promotes them to v1 only if explicit lists/prefix/range cannot reach zero unassigned accounts in one session.
- [x] **Period semantics** → natural calendar by `posting_date`, **plus cumulative YTD/QTD/MTD in v1** (client requirement). Fiscal calendars and closed-period flags stay non-goals.
- [x] **Assertions at load vs. on schedule** → both: on demand (`parrot finance validate --live`) and a scheduled task over the last closed period + chart drift.
- [x] **AuditLedger payload** → own signed `AccountingAuditEntry` (core signers, `storage(json_str)` contract) with hashes, canonical request and a `lineage_ref`; lineage is rebuilt deterministically from `model_hash` + request, never stored inline. `AuditLedgerEntry` is not extended.
- [x] **Lowering into the generic layer** → deferred until FEAT-704 resumes; not committed in either spec now.

---

## Non-Goals (v1)

- Joins to dimension tables (journal must carry dimensions or point at a pre-joined view).
- Fiscal calendars and period close flags (cumulative YTD/QTD/MTD over the natural calendar **is** in v1).
- Requests spanning an account-membership change (refused with an actionable error).
- Hierarchy (`parent:`) selectors, unless S3 promotes them.
- Multi-entity consolidation and intercompany eliminations.
- Multi-currency and FX translation.
- Any grammar beyond `sum(set)`, `+ − × ÷`, parentheses, metric references.
- Materialisation (Option D) and lowering into the generic semantic layer (Option A) — both designed as later output modes.
