---
type: feature
base_branch: dev
projects: [ai-parrot-semantic, ai-parrot, ai-parrot-server]
tags: [accounting, semantic-layer, duckdb, arrow, sqlglot, audit]
docs:
  policy: required
  pages:
    - wiki/tools/accounting-metrics-layer.md
    - wiki/tools/semantic-layer.md
  api_modules:
    - parrot.semantic.accounting
    - parrot.interfaces.duckdb_engine
---

# Feature Specification: Accounting Metrics Layer — chart-of-accounts rollups compiled to deterministic queries

**Feature ID**: FEAT-713
**Date**: 2026-11-12
**Author**: Jesus Lara
**Status**: approved
**Target version**: next minor after 2.1.3
**Source**: `sdd/proposals/accounting-metrics-layer.proposal.md` (revision of 2026-11-11, U1–U4 resolved) over
`sdd/proposals/accounting-metrics-layer.brainstorm.md` (accepted 2026-10-21, Option B)

> **Revision 0.3** incorporates the five review resolutions below and replaces the draft of 2026-10-21. That draft assumed FEAT-704 was paused and created the
> `ai-parrot-semantic` satellite itself. FEAT-704 has shipped the satellite (PR #1821), so this revision builds
> `parrot.semantic.accounting` inside it, reuses its audit ledger and executor, and adds a reusable in-process
> DuckDB engine in core. Revision 0.3 retains the grammar but moves final metric arithmetic to a shared exact evaluator over SQL set
> aggregates. Its contracts supersede revision 0.2.

---

## 1. Motivation & Business Requirements

### Problem Statement

Finance questions that agents receive — "revenue for Pokémon at TROC last quarter", "EBITDA by cost center",
"operating expenses YTD" — are not analytical questions over a schema; they are **rollups over a chart of
accounts**. Which GL accounts sum into *revenue*, which ones are netted (returns, discounts), what sign convention
applies to each account, and which accounts moved between buckets at the last fiscal year change is **internal,
closed knowledge** that no LLM has and no `information_schema` exposes.

Today that knowledge can only live in (1) a prose skill — lossy by construction, impossible to validate against the
chart of accounts; (2) free-form SQL from the DB toolkit — the sqlglot guard validates tables and columns, not which
accounts belong in the `IN (...)` list, so the query is syntactically safe and semantically wrong; or (3) a DBA view —
deterministic but opaque (no lineage), not portable to in-memory DataFrames, and unable to answer "why is revenue
this number".

The generic semantic layer (FEAT-704, shipped in `ai-parrot-semantic`) solves metric *naming* and *governance*, but
its `NativeCompiler` works on measures, dimensions and joins. It has no account sets, no debit/credit sign
normalisation, no effective-dated membership, no cumulative window totals and no reconciliation assertions
(`revenue − expenses == net_income`), and its compile entry point has no engine dispatch. The accounting layer is
therefore a second compiler in the same package, sharing the package's audit ledger, executor and compile cache.

The repository also has no in-process engine over DataFrames: DuckDB is used only as a queried database, one
short-lived connection per query. FEAT-880 (`datasetmanager-semantic-source`) deferred a DuckDB-backed dataset
store to this revision; this feature delivers the reusable engine that store will build on, not the store.

Who is affected: any agent answering finance questions over a general ledger; finance users of client deployments
(TROC first); the audit trail (a financial figure must be traceable to the exact query and model version that
produced it); and the future DuckDB-backed dataset store.

### Goals

- **The LLM never writes the aggregation.** It selects `metric + grain + filters + period`; the compiler produces the
  query ("probabilistic proposes, deterministic decides").
- **One canonical IR, two execution targets.** One serialisable plan is rendered per dialect and runs against the
  source database through the semantic `Executor` and against in-memory DataFrames through DuckDB. Each rendering
  has its own `sql_hash`; the `model_hash` is shared.
- **A reusable DuckDB engine in core.** `parrot.interfaces.duckdb_engine.DuckDBEngine`: one root connection,
  Arrow-registered frames, per-thread cursors, behind a new core `duckdb` extra. It carries no accounting concept.
- **Arrow as the bridge.** pandas (and polars, when installed) frames reach DuckDB through Arrow; no pickle across
  trust boundaries.
- **A closed grammar.** `sum(set)`, `+ − × ÷`, parentheses, metric references. Nothing else.
- **Determinism as a contract.** Same `model_hash` + same canonical request + same dialect ⇒ byte-identical SQL.
  Sorted `IN` lists, model-derived aliases, no timestamps. Guarded by per-dialect golden tests and the satellite's
  sqlglot pin.
- **Compile-time validation, never runtime surprises.** Completeness (per effective-dated interval), overlaps,
  cycles, dangling references, empty sets, sign-convention consistency and numeric types are checked when the model
  loads; a model that fails validation does not load.
- **Explainability.** Every result carries lineage: contributing sets, the concrete accounts each resolved to, the
  formula, and the assertions that cover the metric.
- **Multi-tenant, PBAC-filtered, audited.** Models are tenant-scoped under `<models_dir>/<tenant>/`; metric
  visibility is filtered through `DatasetPolicyGuard`; every executed query appends a signed accounting entry to the
  shared semantic audit ledger.
- **Natural calendar with cumulative periods.** `posting_date` buckets by day/week/month/quarter/year plus
  YTD/QTD/MTD running totals over the natural calendar (client requirement). Weekly cumulative requests are
  rejected in v1; non-cumulative weekly queries remain supported.
- **Compile path importable on its own.** Model, grammar, validation and compiler import without loading the
  governed stack.
- **Portable to the Rust compiler.** The plan is plain data, so FEAT-742 can port the accounting compiler.

### Non-Goals (explicitly out of scope)

- The DuckDB-backed dataset store and any change to how `DatasetManager` stores frames — a separate feature built on
  the engine delivered here (proposal U3).
- Packaging, release entry, CI step and nightly matrix for the satellite — already delivered by FEAT-704.
- Changes to `NativeCompiler`, `engines.compile`, `GovernancePipeline` or the `sl_*` tools; lowering accounting
  metrics into the generic layer (brainstorm Option A) stays deferred.
- Row-level security and column masking for finance metrics — the finance path does not go through
  `GovernancePipeline`; visibility is per metric (proposal U2).
- Joins to dimension tables — the journal must already carry the dimensions, or a pre-joined view is pointed at.
- Fiscal calendars and period-close flags (cumulative periods over the **natural** calendar are in scope).
- Requests whose period (or cumulative window) spans an account-membership change — refused with an actionable
  error; slice + `UNION ALL` is a v2 option.
- Hierarchy (`parent:`) selectors — v2.
- Multi-entity consolidation, intercompany eliminations, multi-currency / FX.
- Result caching of any kind (compile cache only).
- Materialisation via Flowtask (brainstorm Option D).
- Modifying `SQLToolkit`, `DatabaseQueryToolkit`, `DuckDBSource`, `AuditLedgerEntry` or `parrot/clients/base.py`.
- Implementing any Rust code — FEAT-742 owns it; this spec only keeps the plan portable.
- A finance admin UI for editing models (models live in git).
- Any grammar node beyond `Sum`, `Ref`, `Num`, `Neg`, `BinOp`.

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:7ee631cb368c97479e2195d418b2e07d10bb28916376d7748fbd22161390ebe3 evaluation_digest=sha256:7f8e45f688bcbbf4eee6b68871988b267685a6fb53888374f616fd5eb6cbb992 rules_version=1 status=pass -->

No eligible decisions govern subsystems: auth, bots, clients, config, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, server, skills, tools

## 2. Architectural Design

### Overview

`parrot.semantic.accounting` is a sub-package of the shipped `ai-parrot-semantic` satellite. It owns the accounting
model, grammar, validation and compiler, and **reuses** the satellite's `SemanticAuditLedger`, `Executor` /
`ConnectionResolver` and `CompileCache` (proposal U1). A new core module, `parrot.interfaces.duckdb_engine`,
provides the in-process DuckDB engine; it lives in core because `ai-parrot-semantic` depends on `ai-parrot` and a
future `DatasetManager` store must be able to import it.

Pipeline:

1. **Load** — `load_model(path | dict, snapshot)` validates the YAML with Pydantic, resolves selectors
   (`accounts`, `prefix`, `range`, `tag`, `except`) against an immutable, hashed `ChartSnapshot` (the account
   master), partitions time by every `valid_from`/`valid_to` boundary and checks **completeness, overlap and
   exclusions per interval**, then checks cycles, dangling references, empty sets, sign-convention consistency and
   numeric column types. Errors are collected and raised together as `ModelValidationError`.
   Preserve resolved account natures in the model; compilation never fetches the original snapshot.
   `model_hash = sha256(canonical JSON of the resolved model + snapshot_hash)`.
2. **Parse** — `parse_expr()` is a small Pratt parser producing a closed AST.
3. **Plan** — `plan_metric(model, request)` validates the request, inlines metric references, deduplicates sets and
   produces a `MetricPlan`: frozen, JSON-serialisable data with no sqlglot objects (the portable IR for FEAT-742).
4. **Render** — `render_plan(plan, dialect)` builds one `sqlglot.exp.Select`: inner scan with one
   `COALESCE(SUM(CASE WHEN account_id IN (...) THEN <normalised amount> END), 0) AS set_<name>` per distinct set,
   `WHERE posting_date >= <from> AND posting_date < <to_exclusive>` plus dimension filters, `GROUP BY <grain
   buckets>`; the outer `SELECT` returns exact set aggregates and `ORDER BY` the grain. Formulas stay in
   `MetricPlan.columns` for shared runtime evaluation; SQL never divides metric operands.
   For `cumulative` requests the scan lower bound is widened to the start of the earliest window, every set column
   becomes `SUM(set_x) OVER (PARTITION BY <window key>, <dimensions> ORDER BY <grain>)`; the evaluator applies
   formulas **after** the window (a YTD ratio is the ratio of YTD sums). Filter output buckets using
   `bucket >= DATE_TRUNC(grain, output_from)` to retain a partial first bucket; the last bucket includes postings
   only through `to`. Reject cumulative with `week` or no grain before rendering. A **self-check pass**
   re-parses the rendered SQL and asserts it references only the declared journal
   table and declared columns. `compile_metric()` is `plan_metric` + `render_plan` and returns
   `CompiledMetricQuery(sql, dialect, sql_hash, model_hash, plan_hash, plan, request, lineage, assertions)`.
5. **Execute** — two targets, one compiled query:
   - **database**: `DatabaseRuntime` wraps `compiled.sql` in a `GovernedQuery` and calls
     `Executor.run_with_columns(governed, connection=...)`. The SQL is sent unchanged (so the executed text matches
     `sql_hash`); a `truncated` result raises `AccountingExecutionError` instead of returning partial groups.
   - **duckdb**: `DuckDBRuntime` obtains frames from an injected `frame_provider`, converts them with `to_arrow`,
     and runs the query on a `DuckDBEngine` with the frames registered for that call only.
   Both feed exact aggregates to `evaluate_rows(compiled.plan, rows)` and return final `Decimal` metric columns
   in `RuntimeResult(columns, rows)`, under the numeric contract below.
6. **Audit** — every executed query appends a signed `AccountingAuditEntry` to the shared `SemanticAuditLedger`
   (generalised to accept any signable entry). `FINANCE_AUDIT_MODE=required` (default) calls
   `append(entry, required=True)` and fails closed: if the durable append fails, the result is not returned.
7. **Expose** — `AccountingToolkit` (`tool_prefix = "finance"`): `finance_list_metrics`, `finance_explain_metric`,
   `finance_query_metric`, `finance_validate_model`; served over MCP through `parrot mcp-local`; `parrot finance`
   CLI; a scheduled live validation the host registers on its scheduler.

Decisions reflected in this design:

| Decision | Source | Where it lands |
|---|---|---|
| Home `parrot.semantic.accounting`, extending the shipped satellite | brainstorm, revised by semantic-layer spec U6 | §2, M2 |
| Reuse audit ledger, executor, compile cache | proposal U1 | M6, M7, M8 |
| `DatasetPolicyGuard`, resources `accounting:<tenant>:<model>:<metric>`, no guard ⇒ allow | proposal U2 | M8 |
| Reusable DuckDB engine here; dataset store is a separate feature | proposal U3 | M1, Non-Goals |
| Engine lives in core behind a core `duckdb` extra | owner, 2026-11-11 | M1, AC16 |
| Models in git: `<models_dir>/<tenant>/<model>.yaml` | brainstorm, proposal U4 | M4, M8 |
| polars accepted when installed, never a dependency | owner, 2026-11-11 | M1 `to_arrow` |
| Compile path independently importable | owner, 2026-11-11 | M2, AC1 |
| Accounting compiler is in FEAT-742's scope | owner, 2026-11-11 | M5 `MetricPlan` |
| Refuse requests spanning a membership change (incl. cumulative windows) | brainstorm | M4, M5 |
| Explicit required `amount_convention`, no default | brainstorm + codex S4 | §2 Data Models, M4 |
| Natural calendar + YTD/QTD/MTD in v1 | brainstorm | M5 |
| Live assertions on demand **and** scheduled | brainstorm | M8 CLI, M9 |
| `lineage_ref`, lineage rebuilt and never stored inline | brainstorm | M7 |

### Component Diagram

```
<models_dir>/<tenant>/<model>.yaml ──┐
                                     ▼
            ChartSnapshot ──► loader.load_model() ──► AccountingModel (frozen, model_hash)
     (Executor query, Arrow    │                              │
      table or manifest)       │        grammar.parse_expr()  │
                               │                              ▼
   MetricRequest ──────────────┴─► compiler.plan_metric() ──► MetricPlan (portable IR)
                                                                   │ render_plan(dialect)
                                                                   ▼
                                                        CompiledMetricQuery (sql, sql_hash, lineage)
                                   ┌───────────────────────────────┴───────────────────────────────┐
                                   ▼                                                               ▼
                    runtime.DatabaseRuntime                                          runtime.DuckDBRuntime
        parrot.semantic.execution.Executor (shipped)                     frame_provider ─► to_arrow ─► DuckDBEngine (core, new)
                                   └───────────────────────────────┬───────────────────────────────┘
                                                                   ▼
                                    parrot.semantic.audit.SemanticAuditLedger (shipped, generalised)
                                                                   ▼
            AccountingToolkit (finance_*) ──► MCP (parrot mcp-local) · CLI (parrot finance) · host scheduler job
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.semantic.execution.Executor.run_with_columns` (`execution.py:60`) | uses | database target; a `GovernedQuery` is built around the compiled SQL. No change to `Executor`. |
| `parrot.semantic.execution.ConnectionResolver` (`execution.py:18`) | uses | named connections through `PARROT_SEMANTIC_CONN_<NAME>_<KEY>`. |
| `AbstractDatabaseSource.get_metadata` (`databasequery/base.py:429`) | uses | pre-load check that the journal columns exist and amounts are exact numeric. |
| `AbstractDatabaseSource.sqlglot_dialect` (`databasequery/base.py:337`) | uses | dialect for rendering against a database. |
| `parrot.semantic.audit.SemanticAuditLedger` (`audit.py:70`) | modifies | annotations widened to a `SignableAuditEntry` protocol; behaviour unchanged. |
| `parrot.semantic.cache.CompileCache` (`cache.py:32`) | modifies | annotations widened to a `CacheableCompiled` protocol; behaviour unchanged. |
| `parrot/semantic/__init__.py` (`:3-7`) | modifies | exports resolved lazily so `parrot.semantic.accounting` does not load the toolkit. |
| `DatasetPolicyGuard.filter_datasets` / `can_read_dataset` (`auth/dataset_guard.py:128,278`) + `_pctx_var` (`auth/context.py:33`) | uses | metric visibility; resource names `accounting:<tenant>:<model>:<metric>`. |
| `DatasetManager.materialize` (`dataset_manager/tool.py:4270`) | **not modified** | the natural `frame_provider` target a host wires in. |
| `AbstractKMSSigner` / `LocalHMACSigner` (`security/audit_ledger.py:135,166`) | uses | through the shared ledger. |
| `parrot._imports.require_extra` (`_imports.py:248`) | uses | `require_extra("duckdb", "duckdb")` in the engine; its message names `ai-parrot[duckdb]`, which is the new core extra. |
| `parrot.cli` lazy registry (`cli/__init__.py:170-231`) | extends | `"finance": "parrot.semantic.accounting.cli"` + extras hint. |
| `parrot mcp-local` (`.parrot/mcp-toolkits.yaml`, `mcp/toolkit_config.py:21`) | config only | a `finance` entry under `toolkits:`; documented, not committed. |
| `SchedulerManager.register_object_schedules` (`scheduler/base.py:806`) + `@schedule` (`scheduler/manager.py:50`) | extends (server) | `accounting_jobs.py` adapter; the host calls it on `app["scheduler_manager"]`. |
| `packages/ai-parrot/pyproject.toml` optional dependencies (`:223`) | extends | new core extra `duckdb = ["duckdb>=1.0"]`. |
| FEAT-742 (Rust compiler, reserved) | coordinates | `MetricPlan` is the contract FEAT-742 ports; golden plan files are its parity fixtures. |
| FEAT-880 (`datasetmanager-semantic-source`) | coordinates | independent; the dataset store it deferred builds on `DuckDBEngine`. |

### Data Models

```python
# packages/ai-parrot-semantic/src/parrot/semantic/accounting/models.py  (new) — all frozen Pydantic v2
from typing import Annotated, Literal
from decimal import Decimal
from datetime import date, datetime
from pydantic import BaseModel, Field, model_validator

AmountConvention = Literal["debit_positive", "credit_positive", "debit_credit_columns", "natural_balance"]
Nature = Literal["debit", "credit"]
AccountingGrain = Literal["day", "week", "month", "quarter", "year"]   # subset of parrot.semantic.models.Grain; never named `Grain`
Cumulative = Literal["mtd", "qtd", "ytd"]

class JournalSource(BaseModel, frozen=True):
    table: str | None = None            # "schema.table"  — XOR dataframe
    dataframe: str | None = None        # name resolved by frame_provider
    connection: str | None = None       # ConnectionResolver name; required with `table`
    driver: str | None = None           # DatabaseQueryToolkit driver ("pg", "bigquery", "duckdb", ...); required with `table`

class NatureSpec(BaseModel, frozen=True):
    from_column: str | None = None
    accounts: dict[str, Nature] | None = None      # XOR from_column

class ChartOfAccounts(BaseModel, frozen=True):
    source: JournalSource
    account_key: str
    posting_date: str
    amount_convention: AmountConvention            # REQUIRED, no default
    amount: str | None = None                      # required unless debit_credit_columns
    debit: str | None = None                       # required with debit_credit_columns
    credit: str | None = None
    nature: NatureSpec | None = None               # required unless natural_balance
    dimensions: tuple[str, ...] = ()
    allow_float: bool = False                      # float amounts ⇒ validation error unless true (then CAST DECIMAL(38,6))

class Selector(BaseModel, frozen=True):
    prefix: str | None = None
    range: tuple[str, str] | None = None
    tag: str | None = None

class AccountSet(BaseModel, frozen=True):
    accounts: tuple[str, ...] = ()
    select: Selector | None = None
    except_: tuple[str, ...] = Field(default=(), alias="except")
    valid_from: date | None = None
    valid_to: date | None = None
    allow_overlap: tuple[str, ...] = ()            # names of sets this one may overlap (memo buckets)

class MetricDef(BaseModel, frozen=True):           # NOT `Metric` — parrot.semantic.model already defines one
    expr: str
    description: str = ""
    dimensions: tuple[str, ...] | None = None      # None ⇒ all chart dimensions
    unit: str | None = None

class Assertion(BaseModel, frozen=True):
    expr: str                                      # "<expr> == <expr>"
    tolerance: Decimal = Decimal("0")
    on_failure: Literal["flag", "block"] = "flag"

class Exclusion(BaseModel, frozen=True):
    accounts: tuple[str, ...]
    reason: str

class AccountingModelSpec(BaseModel, frozen=True):          # the YAML as written
    model: str
    version: str
    tenant: str
    chart_of_accounts: ChartOfAccounts
    sets: dict[str, AccountSet]
    metrics: dict[str, MetricDef]
    assertions: tuple[Assertion, ...] = ()
    excluded: tuple[Exclusion, ...] = ()

class ChartAccount(BaseModel, frozen=True):
    account_id: str
    nature: Nature | None
    parent_id: str | None = None
    tags: tuple[str, ...] = ()

class ChartSnapshot(BaseModel, frozen=True):                # immutable account master
    accounts: tuple[ChartAccount, ...]
    taken_at: date
    source: str                                             # "table:gl.accounts" | "dataframe:<name>" | "manifest:<path>"
    @property
    def snapshot_hash(self) -> str: ...                     # sha256 of sorted account tuples

class ResolvedSet(BaseModel, frozen=True):
    name: str
    accounts: tuple[str, ...]                               # sorted, explicit
    valid_from: date | None
    valid_to: date | None

class AccountingModel(BaseModel, frozen=True):              # resolved, validated, hashable
    spec: AccountingModelSpec
    snapshot_hash: str
    natures: tuple[tuple[str, Nature], ...]                  # sorted immutable resolved account/nature pairs
    intervals: tuple[tuple[date | None, date | None], ...]  # membership partition
    sets: dict[str, ResolvedSet]
    model_hash: str

class Period(BaseModel, frozen=True):
    from_: date = Field(alias="from")
    to: date                                                # inclusive
    cumulative: Cumulative | None = None

class MetricRequest(BaseModel, frozen=True):
    kind: Literal["metric"] = "metric"
    metric: str
    grain: AccountingGrain | None = None                    # None ⇒ one row per dimension combination
    dimensions: tuple[str, ...] = ()
    filters: dict[str, str | int | tuple[str | int, ...]] = {}   # equality / IN on declared dimensions only
    period: Period
    @model_validator(mode="after")
    def _cumulative_fits_grain(self): ...                   # explicit allowed combinations in the period contract

class AssertionRequest(BaseModel, frozen=True):
    kind: Literal["assertion"] = "assertion"
    assertion_index: int = Field(ge=0)                       # index into model.spec.assertions, bound by model_hash
    period: Period                                          # no cumulative mode for live assertions

# Decode request JSON through a kind-discriminated union of MetricRequest and AssertionRequest.
AccountingRequest = Annotated[MetricRequest | AssertionRequest, Field(discriminator="kind")]

class Lineage(BaseModel, frozen=True):
    metric: str | None                                      # None for assertion plans
    assertion_index: int | None = None
    formula: str                                            # fully inlined expression
    sets: tuple[ResolvedSet, ...]
    assertions: tuple[str, ...]                             # assertion exprs touching this metric
    warnings: tuple[str, ...] = ()                          # "division_by_zero_possible", "float_cast", "chart_drift"

class PlanSet(BaseModel, frozen=True):                      # one aggregated account set
    alias: str                                              # "set_<name>"
    accounts: tuple[str, ...]                               # sorted
class PlanExpr(BaseModel, frozen=True):                     # serialisable expression tree over set aliases
    op: Literal["set", "num", "neg", "add", "sub", "mul", "div"]
    alias: str | None = None
    value: str | None = None                                # Decimal as string
    args: tuple["PlanExpr", ...] = ()
class MetricPlan(BaseModel, frozen=True):                   # portable IR — plain data, no sqlglot (FEAT-742 contract)
    schema_version: Literal[1] = 1
    table: str                                              # journal table or registered frame name
    account_key: str
    posting_date: str
    amount_convention: AmountConvention
    amount: str | None
    debit: str | None
    credit: str | None
    natures: tuple[tuple[str, Nature], ...]                  # sorted subset of model.natures used by this plan
    result_scale: Literal[6] = 6
    rounding: Literal["half_even"] = "half_even"
    arithmetic_version: Literal[1] = 1                     # exact intermediates; final quantization only
    cast_decimal: bool                                      # True for explicitly permitted float conversion; exact inputs also use fixed scale
    sets: tuple[PlanSet, ...]
    columns: tuple[tuple[str, PlanExpr], ...]               # (output alias "m_<metric>" | assertion side, expression)
    grain: AccountingGrain | None
    dimensions: tuple[str, ...]
    filters: tuple[tuple[str, tuple[str | int, ...]], ...]  # sorted
    scan_from: date                                         # widened for cumulative
    output_from: date
    to_exclusive: date
    cumulative: Cumulative | None
    @property
    def plan_hash(self) -> str: ...                         # sha256 of canonical JSON

class CompiledMetricQuery(BaseModel, frozen=True):          # NOT `CompiledQuery` — that is parrot.semantic.models.CompiledQuery
    sql: str
    dialect: str
    sql_hash: str                                           # sha256(dialect + "\n" + sql)
    model_hash: str
    plan_hash: str
    plan: MetricPlan                                       # formulas evaluated after SQL execution
    request: AccountingRequest
    lineage: Lineage
    assertions: tuple["CompiledMetricQuery", ...] = ()
    @property
    def cache_key(self) -> str: ...                         # JSON list [model_hash, canonical request, dialect] — CompileCache shape

class RuntimeResult(BaseModel, frozen=True):
    columns: tuple[str, ...]
    rows: tuple[dict, ...]                                  # amounts are Decimal
    target: Literal["database", "duckdb"]
    duration_ms: int

class AssertionResult(BaseModel, frozen=True):
    expr: str
    status: Literal["passed", "failed", "skipped"]
    lhs: Decimal | None
    rhs: Decimal | None
    tolerance: Decimal
    period: Period

class MetricResult(BaseModel, frozen=True):
    columns: tuple[str, ...]
    rows: tuple[dict, ...]
    row_count: int
    compiled: CompiledMetricQuery
    assertion_results: tuple[AssertionResult, ...]
    chart_drift: bool
    audit_id: str
    duration_ms: int

# packages/ai-parrot-semantic/src/parrot/semantic/accounting/audit.py  (new)
class AccountingAuditEntry(BaseModel):                      # signed by the shared ledger; satisfies SignableAuditEntry
    schema_version: Literal[1] = 1
    entry_id: str
    created_at: datetime
    user_id: str                                            # keys the shipped Postgres sink reads: entry_id, created_at,
    tenant_id: str                                          #   user_id, tenant_id, model, outcome, signature
    subject_digest: str
    model: str
    version: str
    model_hash: str
    snapshot_hash: str
    sql_hash: str
    plan_hash: str
    dialect: str
    target: Literal["database", "duckdb"]
    tool: str
    request_canonical: str                                  # discriminated canonical JSON of AccountingRequest
    lineage_ref: str                                        # f"{model_hash}:{plan_hash}:{sql_hash}" — never inline lineage
    assertion_status: Literal["passed", "failed", "skipped", "none"]
    outcome: Literal["ok", "denied", "validation_error", "execution_error"]
    row_count: int | None
    duration_ms: int | None
    signature: str = ""
    def canonical_bytes(self) -> bytes: ...                 # sorted-key compact JSON without `signature`
```

Sign normalisation (`amount_convention`), applied inside the `CASE` so every account is **positive in its natural
balance** (revenue positive, expenses positive; metrics subtract):

| convention | source shape | normalised amount |
|---|---|---|
| `debit_positive` | one `amount` column, debits > 0 | `amount` if nature = debit else `-amount` |
| `credit_positive` | one `amount` column, credits > 0 | `amount` if nature = credit else `-amount` |
| `debit_credit_columns` | two columns `debit`, `credit` | `debit - credit` if nature = debit else `credit - debit` |
| `natural_balance` | `amount` already in natural-balance sign | `amount` (nature optional) |

### Numeric and period contracts (revision 0.3)

- Exact source amounts must fit `DECIMAL(38,6)` without rounding: at most 32 integer and six fractional digits.
  Validate declared types at load time and actual frame values at execution; reject incompatible sources rather
  than silently casting away precision. `allow_float` is the sole explicit exception: its lossy conversion is
  warned as `float_cast`; exactness is promised from conversion onward only.
- SQL returns dimensions/buckets and exact per-set sums (or cumulative sums), never metric-expression results.
  Cast exact inputs before aggregation: DuckDB `DECIMAL(38,6)`, Postgres `NUMERIC(38,6)`,
  BigQuery `BIGNUMERIC` (enforce the common precision/scale bounds; ordinary NUMERIC has insufficient integer
  range). Reject aggregate
  overflow. Both runtimes reject floating aggregate values; accepted representations are `Decimal`, integer,
  or a validated finite decimal string that fits the same precision/scale contract. Never repair a floating SQL
  quotient by casting it back to decimal. NULL set aggregates normalize to zero before formula evaluation.
- `evaluation.py` evaluates `PlanExpr` with standard-library `fractions.Fraction`, built from exact `Decimal`
  inputs and literals, so `+`, `-`, `*`, `/` have exact intermediates. Division by zero yields NULL, which
  propagates through the remaining expression; lineage warns `division_by_zero_possible`. Quantize each final
  output once to scale 6 with half-even rounding using integer quotient/remainder operations; do not use the
  ambient Decimal context or finite-precision division as an intermediate. Convert the scaled integer to
  `Decimal` exactly. A rounded result outside `DECIMAL(38,6)` raises `AccountingExecutionError`. Both assertion
  sides use the same output rule; compare tolerance exactly. A NULL side produces `skipped`, never `passed`.
  `result_scale`, `rounding` and `arithmetic_version` are hashed plan fields.
- A compiled artifact contains SQL and its plan. `sql_hash` identifies executed aggregation SQL; `plan_hash`
  identifies formulas and numeric semantics. Different formulas over the same sets may share SQL but not a plan
  hash. Audit records retain both hashes; replay verifies both before rebuilding lineage.
- Allowed cumulative combinations: **mtd: day/month**, **qtd: day/month/quarter**,
  **ytd: day/month/quarter/year**. `week` and `None` with any cumulative mode raise `RequestValidationError`
  before SQL execution or frame access. This v1 restriction prevents weeks straddling natural windows.
  Non-cumulative `week` remains valid. Supported grains retain the bucket containing `period.from_`, even if
  its label precedes that date; cumulative values include earlier window postings. The final bucket is partial
  through inclusive `period.to`. Empty buckets are not synthesized.

### New Public Interfaces

```python
# parrot.semantic.accounting  (public surface; toolkit/runtime names resolved lazily)
from parrot.semantic.accounting import (
    load_model, parse_expr, plan_metric, render_plan, compile_metric,
    AccountingModel, MetricRequest, MetricPlan, CompiledMetricQuery, Lineage, MetricResult,
    DuckDBRuntime, DatabaseRuntime, AccountingAuditEntry, AccountingToolkit,
    AccountingError, ModelValidationError, GrammarError, RequestValidationError,
    PeriodSpansMembershipChange, AccountingExecutionError, AccountingAuditError,
)
# core
from parrot.interfaces.duckdb_engine import DuckDBEngine, to_arrow, FrameConversionError
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Core DuckDB engine | no | signatures fixed below | per-call frame isolation on cursors is unproven in this repository (§8 Q1); the implementer must settle it with a test first |
| M2: Package entry, contracts & errors | yes | Pydantic models of §2; error hierarchy and lazy `__init__` shape fixed below | — |
| M3: Grammar | yes | grammar fixed below; AST node set closed; `GrammarError(position)` | — |
| M4: Snapshot, loader, validation | no | — | interval partition + completeness semantics are the core invariant |
| M5: Compiler (plan + render) + golden tests | no | — | plan shape, cumulative windows and the self-check allowlist define the determinism and FEAT-742 contracts |
| M6: Accounting runtimes and exact evaluator | yes (after M1, M5) | `GovernedQuery`, truncation and exact numeric policy fixed below | — |
| M7: Audit on the shared ledger | yes | protocol and entry fields fixed; `canonical_bytes` = sorted-key JSON without `signature` | — |
| M8: Catalog, toolkit, CLI | yes (after M4–M7) | tool names, PBAC rule, CLI anchors fixed | — |
| M9: Live validation + scheduler adapter | yes | `@schedule` + `register_object_schedules` verified; host wiring documented | — |
| M10: Documentation | yes | pages listed in §10 | — |

### Module 1: Core DuckDB engine over Arrow
- **Path**: `packages/ai-parrot/src/parrot/interfaces/duckdb_engine.py` (new);
  `packages/ai-parrot/tests/interfaces/test_duckdb_engine.py` (new); MODIFY `packages/ai-parrot/pyproject.toml`
  (new `duckdb` extra)
- **Responsibility**: a reusable in-process engine with no accounting concept. One root `duckdb.connect()` per
  engine; every `execute` runs on its own `root.cursor()` inside `asyncio.to_thread`, bounded by a semaphore of
  `threads`. Frames registered with `register()` are long-lived and visible to every call (the future dataset
  store's use). Frames passed to `execute(frames=...)` are registered for that call only and are not visible to
  concurrent calls. Results come back as `pyarrow.Table`. `duckdb` is imported lazily through
  `require_extra("duckdb", "duckdb")`, so core imports without the extra. `to_arrow` converts pandas
  (`pa.Table.from_pandas(frame, preserve_index=False)`), polars (any object exposing `to_arrow()`, never
  `import polars`) and passes Arrow tables through; it rejects object-dtype decimal columns and floats unless
  `allow_float`, in which case the listed columns are cast to `decimal128(38, 6)`.
- **Depends on**: nothing.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/interfaces/duckdb_engine.py  (new)
  class FrameConversionError(ValueError):
      """A frame could not be converted to Arrow under the requested numeric rules."""

  def to_arrow(frame: Any, *, decimal_columns: tuple[str, ...] = (), allow_float: bool = False) -> "pa.Table":
      """pandas | polars-like (has .to_arrow()) | pa.Table → pa.Table. Raises FrameConversionError for an
      unsupported type, an object-dtype decimal column, or a float decimal column when allow_float is False."""

  class DuckDBEngine:
      """In-process DuckDB over Arrow: one root connection, per-thread cursors, never a shared cursor."""
      def __init__(self, *, threads: int = 4, database: str = ":memory:") -> None:
          """require_extra("duckdb", "duckdb")  # verified: _imports.py:248"""
      async def register(self, name: str, table: "pa.Table", *, replace: bool = True) -> None:
          """Register a long-lived Arrow table visible to every later call. Raises ValueError when the name
          exists and replace is False."""
      async def unregister(self, name: str) -> None: ...
      def registered(self) -> tuple[str, ...]:
          """Names of the long-lived tables, sorted."""
      async def execute(self, sql: str, *, frames: Mapping[str, "pa.Table"] | None = None,
                        parameters: Sequence[Any] | None = None) -> "pa.Table":
          """Run *sql* on a fresh cursor in a worker thread. *frames* are registered for this call only and
          removed afterwards; they shadow long-lived tables of the same name and are invisible to other calls."""
      async def close(self) -> None:
          """Close the root connection; later calls raise RuntimeError."""
  ```
  ```toml
  # packages/ai-parrot/pyproject.toml  (modifies — insert before the anchor `# Financial analysis (ta-lib requires libta-lib-dev)`)
  # In-process DuckDB engine (parrot.interfaces.duckdb_engine)
  duckdb = ["duckdb>=1.0"]
  ```

### Module 2: Package entry, contracts & error taxonomy
- **Path**: `packages/ai-parrot-semantic/src/parrot/semantic/accounting/__init__.py`, `models.py`, `errors.py` (new);
  MODIFY `packages/ai-parrot-semantic/src/parrot/semantic/__init__.py`;
  `packages/ai-parrot-semantic/tests/accounting/__init__.py`, `conftest.py`, `test_models.py`,
  `test_import_isolation.py` (new)
- **Responsibility**: the frozen Pydantic models of §2 Data Models (all except `AccountingAuditEntry`) and the
  exception hierarchy. Validators: `JournalSource` table XOR dataframe, and `connection` + `driver` required with
  `table`; `amount_convention` ⇒ required columns (`amount` vs `debit`+`credit`) and `nature` required unless
  `natural_balance`; `nature.from_column` XOR `nature.accounts`; `AccountSet` has `accounts` or `select`;
  `valid_from < valid_to`; cumulative/grain combinations match the period contract; `Period.from_ <= Period.to`.
  `AccountingModel.natures` is sorted, unique and round-trippable with immutable nested tuples. Reject the
  reserved metric name `__validate__`.
  `parrot/semantic/__init__.py` keeps its four public names but resolves `SemanticQuery`, `SemanticQueryResult` and
  `SemanticLayerToolkit` through a module `__getattr__`, so importing a sub-package no longer imports
  `toolkit.py`. `accounting/__init__.py` imports the compile path eagerly and resolves `AccountingToolkit`,
  `DuckDBRuntime`, `DatabaseRuntime` and `AccountingAuditEntry` lazily. `conftest.py` defines every shared
  accounting fixture of §4, so later modules add no fixtures to it.
- **Depends on**: nothing.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-semantic/src/parrot/semantic/__init__.py  (modifies :3-7)
  """Governed semantic queries using the native sqlglot compiler."""
  from .version import __version__
  __all__ = ["__version__", "SemanticQuery", "SemanticQueryResult", "SemanticLayerToolkit"]
  def __getattr__(name: str) -> Any:
      """Resolve SemanticQuery / SemanticQueryResult (.models) and SemanticLayerToolkit (.toolkit) on first use;
      raise AttributeError for any other name."""

  # parrot/semantic/accounting/errors.py  (new)
  class AccountingError(Exception): """Base of every accounting-layer error."""
  class Problem(BaseModel, frozen=True):
      code: Literal["unassigned_account", "empty_set", "overlap", "dangling_ref", "cycle", "nature_missing",
                    "nature_ambiguous", "float_amount", "numeric_type", "column_missing", "interval_gap", "selector_no_match"]
      message: str; interval: tuple[date | None, date | None] | None = None; accounts: tuple[str, ...] = ()
  class ModelValidationError(AccountingError):
      """Model failed load-time validation. `problems: list[Problem]` carries EVERY problem, never only the first."""
  class GrammarError(AccountingError): """Expression syntax error; `position: int`."""
  class RequestValidationError(AccountingError): """Unknown metric/dimension/filter, cumulative/grain mismatch."""
  class PeriodSpansMembershipChange(RequestValidationError):
      """Requested period or cumulative window crosses a membership boundary; `boundary: date`, `suggestion: str`."""
  class AccountingExecutionError(AccountingError): """Runtime failed or the result was truncated; `audit_id` when audited."""
  class AccountingAuditError(AccountingError): """Durable audit append failed under FINANCE_AUDIT_MODE=required."""
  ```

### Module 3: Metric expression grammar
- **Path**: `packages/ai-parrot-semantic/src/parrot/semantic/accounting/grammar.py`; `tests/accounting/test_grammar.py`
- **Responsibility**: tokenizer + Pratt parser for
  `expr := term (("+"|"-") term)* ; term := factor (("*"|"/") factor)* ; factor := "sum" "(" SET ")" | METRIC | NUMBER | "(" expr ")" | "-" factor`.
  Also `==` at the top level for assertions (`parse_assertion`). Produces a closed AST; `references(ast)` returns
  the set and metric names it uses.
- **Depends on**: M2.
- **Interface Skeleton**:
  ```python
  # parrot/semantic/accounting/grammar.py  (new)
  @dataclass(frozen=True) class Sum:  set_name: str
  @dataclass(frozen=True) class Ref:  metric: str
  @dataclass(frozen=True) class Num:  value: Decimal
  @dataclass(frozen=True) class Neg:  operand: "Expr"
  @dataclass(frozen=True) class BinOp: op: Literal["+", "-", "*", "/"]; left: "Expr"; right: "Expr"
  Expr = Sum | Ref | Num | Neg | BinOp
  def parse_expr(text: str) -> Expr:
      """Parse a metric expression; raise GrammarError(position) on any token outside the grammar."""
  def parse_assertion(text: str) -> tuple[Expr, Expr]:
      """Parse `<expr> == <expr>`; raise GrammarError otherwise."""
  def references(expr: Expr) -> tuple[frozenset[str], frozenset[str]]:
      """Return (set_names, metric_names) referenced by *expr*."""
  ```

### Module 4: Chart snapshot, loader and validation
- **Path**: `packages/ai-parrot-semantic/src/parrot/semantic/accounting/snapshot.py`, `loader.py`, `validation.py`;
  `tests/accounting/test_loader_validation.py`
- **Responsibility**: `snapshot.py` builds a `ChartSnapshot` from (a) rows already fetched from an account-master
  table, (b) an Arrow table, or (c) a YAML/CSV manifest. It never opens a connection itself, so the compile path
  stays import-isolated; M6 supplies the fetch. `loader.py` reads the YAML (`yaml.safe_load`), builds
  `AccountingModelSpec`, resolves selectors against the snapshot, builds the **interval partition** from every
  `valid_from`/`valid_to`, materialises `ResolvedSet`s, and runs `validation.validate(...)`, which returns **all**
  problems: per interval — unassigned accounts (not in any valid set nor `excluded`), overlaps outside
  `allow_overlap`, empty sets; globally — dangling refs, cycles, selectors matching nothing, nature missing or
  ambiguous, float amount columns (`allow_float=False`), incompatible exact precision/scale, missing columns.
  Resolve `nature.from_column` from `ChartSnapshot.accounts[*].nature` (the name identifies the account-master
  column, not a journal column); resolve `nature.accounts` from the explicit mapping and reject conflicts with
  snapshot natures. Retain sorted immutable pairs in `AccountingModel.natures` and hash them. Require natures
  for selected accounts unless `natural_balance`; `plan_metric` copies its needed subset without fetching a
  snapshot. `detect_drift(model, fresh_snapshot)`
  returns accounts present in the fresh snapshot but unassigned in the loaded model.
- **Depends on**: M2, M3.
- **Interface Skeleton**:
  ```python
  # parrot/semantic/accounting/snapshot.py  (new)
  def snapshot_from_rows(rows: Sequence[Mapping[str, Any]], *, account_key: str, nature_column: str | None,
                         parent_column: str | None = None, tags_column: str | None = None,
                         source: str, taken_at: date) -> ChartSnapshot:
      """Build the sorted, hashed snapshot from account-master rows (dict rows from the executor)."""
  def snapshot_from_arrow(table: "pa.Table", *, account_key: str, nature_column: str | None,
                          parent_column: str | None = None, tags_column: str | None = None,
                          source: str, taken_at: date) -> ChartSnapshot: ...
  def snapshot_from_manifest(path: Path) -> ChartSnapshot:
      """YAML/CSV manifest: account_id, nature, parent_id, tags."""

  # parrot/semantic/accounting/loader.py  (new)
  def load_spec(source: Path | dict) -> AccountingModelSpec:
      """yaml.safe_load + Pydantic; raise ModelValidationError(problems) on schema errors."""
  def load_model(source: Path | dict, snapshot: ChartSnapshot, *,
                 columns: Mapping[str, str] | None = None) -> AccountingModel:
      """Resolve selectors, partition intervals, validate (ALL problems), hash. *columns* maps journal column
      name → declared type; None skips the column checks. Raises ModelValidationError."""
  def canonical_json(obj: BaseModel) -> str:
      """Sorted keys, no whitespace, Decimals as strings — the hashing representation."""
  def detect_drift(model: AccountingModel, fresh: ChartSnapshot) -> tuple[str, ...]: ...

  # parrot/semantic/accounting/validation.py  (new)
  def partition_intervals(sets: Mapping[str, AccountSet]) -> tuple[tuple[date | None, date | None], ...]: ...
  def validate(spec: AccountingModelSpec, resolved: Mapping[str, ResolvedSet], snapshot: ChartSnapshot,
               columns: Mapping[str, str] | None) -> list[Problem]:
      """Every invariant listed in Module 4; never stops at the first problem."""
  def metric_order(spec: AccountingModelSpec) -> tuple[str, ...]:
      """Topological order of metrics; a cycle is reported as Problem(code='cycle')."""
  ```

### Module 5: Compiler — plan, render, hashing, lineage, self-check — and golden tests
- **Path**: `packages/ai-parrot-semantic/src/parrot/semantic/accounting/compiler.py`;
  `tests/accounting/test_compiler.py`, `test_golden.py`,
  `tests/accounting/golden/{duckdb,postgres,bigquery}/*.sql`, `tests/accounting/golden/plans/*.json`
- **Responsibility**: `plan_metric` validates the request against the model (metric exists, dimensions ⊆ metric
  dimensions, filters on declared dimensions, period inside one membership interval — including the widened
  cumulative window — else `PeriodSpansMembershipChange(boundary, suggestion)`), inlines metric refs via
  `metric_order`, dedupes sets and returns a `MetricPlan`. `render_plan` builds the inner/outer `exp.Select` of §2
  Overview from the plan alone (`exp.DateTrunc` for grain buckets; `COALESCE(SUM(CASE …), 0)` per set;
  window `SUM(...) OVER (PARTITION BY DATE_TRUNC(<window>, bucket), <dims> ORDER BY bucket)` for
  cumulative; literal `IN` lists sorted; aliases `set_<name>` / `m_<metric>`), renders with
  `expression.sql(dialect=dialect, pretty=False)`, and runs the self-check. `compile_metric` composes both and
  fills `sql_hash`, `plan_hash`, `plan`, `lineage`. SQL projects set aliases; `plan.columns` holds metric or
  assertion-side expressions for the shared evaluator. Apply the numeric and period contracts, including
  partial-bucket filtering and rejection of weekly cumulative requests. Assertions use the same aggregation
  shape, with both side expressions in the plan. `AssertionRequest.assertion_index` must resolve within
  `model.spec.assertions`; reject out-of-range indices and cumulative assertion periods. Its lineage carries
  `metric=None` and the assertion index; metric lineage carries its metric name and `assertion_index=None`. Golden
  `.sql` files are the review artifact for any sqlglot bump; golden plan `.json` files are the FEAT-742 parity
  fixtures. The module imports nothing from `parrot.semantic` outside `accounting`.
- **Depends on**: M2, M3, M4.
- **Interface Skeleton**:
  ```python
  # parrot/semantic/accounting/compiler.py  (new)
  def plan_metric(model: AccountingModel, request: MetricRequest) -> MetricPlan:
      """Dialect-independent, JSON-serialisable plan. Raises RequestValidationError / PeriodSpansMembershipChange."""
  def plan_assertion(model: AccountingModel, request: AssertionRequest) -> MetricPlan: ...
  def render_plan(plan: MetricPlan, dialect: str) -> str:
      """Render *plan* to SQL for *dialect*; deterministic; never returns SQL that fails the self-check."""
  def compile_metric(model: AccountingModel, request: MetricRequest, dialect: str) -> CompiledMetricQuery:
      """plan_metric + render_plan. Same (model_hash, canonical request, dialect) ⇒ byte-identical sql."""
  def compile_assertion(model: AccountingModel, request: AssertionRequest, dialect: str) -> CompiledMetricQuery: ...
  def self_check(sql: str, dialect: str, *, table: str, columns: frozenset[str]) -> None:
      """Re-parse and assert referenced tables/columns ⊆ declared; raise AccountingError otherwise."""
  def canonical_request(request: AccountingRequest) -> str: ...
  ```

### Module 6: Accounting runtimes — DuckDB engine and semantic executor
- **Path**: `packages/ai-parrot-semantic/src/parrot/semantic/accounting/runtime/__init__.py`, `runtime/duckdb.py`,
  `runtime/database.py`, `packages/ai-parrot-semantic/src/parrot/semantic/accounting/evaluation.py`; `tests/accounting/test_runtime.py`, `test_evaluation.py`,
  `test_e2e_duckdb.py`
- **Responsibility**: `duckdb.py` — `DuckDBRuntime(engine, frame_provider)`: awaits `frame_provider(name)` for the
  model's `dataframe` source, converts with core `to_arrow(decimal_columns=<amount columns>, allow_float=...)`, and
  calls `engine.execute(compiled.sql, frames={name: table})`; the compiled dialect must be `duckdb`. It converts
  the Arrow result to `RuntimeResult` rows with `Decimal` amounts. `database.py` — `DatabaseRuntime(executor)`:
  builds `GovernedQuery(sql=compiled.sql, dialect=compiled.dialect, driver=<source.driver>, tables=(<journal
  table>,), rls_applied=(), masked_columns=(), limit=<result limit>, subject_digest=<digest>, members=(<metric>,),
  physical_columns=<declared columns>)` and awaits `executor.run_with_columns(governed, connection=<source.connection>)`.
  The SQL carries no `LIMIT`; when `truncated` is true it raises `AccountingExecutionError` (never partial
  groups). Both targets validate exact aggregate types and call shared `evaluate_rows(compiled.plan, rows)`;
  floats are rejected, never repaired using `Decimal(str(value))`. Evaluation and quantization follow the numeric
  contract above. `SemanticExecutionError` is
  re-raised as `AccountingExecutionError`. It also provides the two helpers the loader path needs from a live
  database: `fetch_chart_rows` (account master) and `fetch_columns` (journal column types through
  `get_metadata`).
- **Depends on**: M1, M2, M5.
- **Interface Skeleton**:
  ```python
  # parrot/semantic/accounting/evaluation.py (new, standard library + accounting models only)
  def evaluate_rows(plan: MetricPlan, rows: Sequence[Mapping[str, Any]]) -> tuple[dict, ...]:
      """Validate exact aggregates, evaluate formulas and round final columns once; preserve grain/dimensions.
      Raise AccountingExecutionError for floats, malformed aggregates or precision/scale overflow."""

  # parrot/semantic/accounting/runtime/duckdb.py  (new)
  FrameProvider = Callable[[str], Awaitable[Any]]                    # name → pandas / polars-like / pa.Table
  class DuckDBRuntime:
      def __init__(self, engine: "DuckDBEngine", frame_provider: FrameProvider) -> None: ...   # DuckDBEngine: M1
      async def execute(self, compiled: CompiledMetricQuery, model: AccountingModel) -> RuntimeResult:
          """Fetch the model's frame, convert, run on the engine with a per-call registration. Raises
          AccountingExecutionError when the model has no `dataframe` source or the dialect is not 'duckdb'."""

  # parrot/semantic/accounting/runtime/database.py  (new)
  class DatabaseRuntime:
      def __init__(self, executor: "Executor", *, result_limit: int = 10_000) -> None: ...   # verified: execution.py:52
      def dialect_for(self, model: AccountingModel) -> str:
          """executor.toolkit.get_source(driver).sqlglot_dialect  # verified: toolkit.py:202, base.py:337"""
      async def execute(self, compiled: CompiledMetricQuery, model: AccountingModel, *,
                        subject_digest: str) -> RuntimeResult:
          """Executor.run_with_columns(governed, connection=...)  # verified: execution.py:60. Truncated ⇒
          AccountingExecutionError."""
      async def fetch_chart_rows(self, *, connection: str, driver: str, table: str, columns: Sequence[str]) -> list[dict]:
          """SELECT DISTINCT of the account master through the executor; feeds snapshot_from_rows."""
      async def fetch_columns(self, *, connection: str, driver: str, table: str) -> dict[str, str]:
          """source.get_metadata(credentials, [table]) → {column name: data_type}  # verified: base.py:429, :100"""
  ```

### Module 7: Accounting audit on the shared ledger
- **Path**: `packages/ai-parrot-semantic/src/parrot/semantic/accounting/audit.py` (new); MODIFY
  `packages/ai-parrot-semantic/src/parrot/semantic/audit.py`; `tests/accounting/test_audit.py`
- **Responsibility**: `parrot/semantic/audit.py` gains a `SignableAuditEntry` protocol (`entry_id: str`,
  `signature: str`, `canonical_bytes() -> bytes`, `model_dump_json() -> str`) and the ledger's annotations
  (`entries`, `append`, `verify`) are widened to it; no behaviour changes and `SemanticAuditEntry` is untouched.
  `accounting/audit.py` defines `AccountingAuditEntry` (fields in §2), `subject_digest`, `build_entry` and
  `append_entry`, which maps `FINANCE_AUDIT_MODE` to `ledger.append(entry, required=...)` and re-raises
  `SemanticExecutionError("audit_unavailable")` as `AccountingAuditError`. `rebuild_lineage(entry, model)`
  parses the discriminated `request_canonical`, dispatches to `compile_metric` or `compile_assertion`, and
  returns `Lineage` only after verifying model/plan/SQL hashes and `lineage_ref`. Assertion indices are stable
  within the hashed model; never guess an assertion from a metric name. M9 constructs one `AssertionRequest`
  per assertion index and period, so every assertion entry is independently replayable.
- **Depends on**: M2, M5.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-semantic/src/parrot/semantic/audit.py  (modifies)
  @runtime_checkable
  class SignableAuditEntry(Protocol):
      """What the ledger needs from an entry: an id, a signature slot and a canonical byte form."""
      entry_id: str
      signature: str
      def canonical_bytes(self) -> bytes: ...
      def model_dump_json(self) -> str: ...
  class SemanticAuditLedger:                                                            # verified: audit.py:70
      # self.entries: deque[SignableAuditEntry]                                         # modifies audit.py:87
      async def append(self, entry: _E, *, required: bool = False) -> _E: ...           # modifies audit.py:95; _E = TypeVar bound to SignableAuditEntry
      async def verify(self, entry: SignableAuditEntry) -> bool: ...                    # modifies audit.py:126

  # parrot/semantic/accounting/audit.py  (new)
  AuditMode = Literal["required", "best_effort"]
  def audit_mode_from_env(env: Mapping[str, str] | None = None) -> AuditMode:
      """FINANCE_AUDIT_MODE, default 'required'."""
  def subject_digest(context: "PermissionContext | None") -> str:
      """sha256 of (user_id, tenant_id), or of 'anonymous' when there is no context."""
  def build_entry(*, context: "PermissionContext | None", tenant: str, model: AccountingModel,
                  compiled: CompiledMetricQuery, target: Literal["database", "duckdb"], tool: str,
                  outcome: str, assertion_status: str, row_count: int | None, duration_ms: int | None) -> AccountingAuditEntry: ...
  async def append_entry(ledger: "SemanticAuditLedger", entry: AccountingAuditEntry, *, mode: AuditMode) -> AccountingAuditEntry:
      """ledger.append(entry, required=(mode == 'required')); AccountingAuditError when the sink is missing or fails."""
  def rebuild_lineage(entry: AccountingAuditEntry, model: AccountingModel) -> Lineage:
      """Recompile from request_canonical; verify model_hash, plan_hash, sql_hash and lineage_ref before returning."""
  ```

### Module 8: `ModelCatalog`, `AccountingToolkit`, CLI
- **Path**: `packages/ai-parrot-semantic/src/parrot/semantic/accounting/catalog.py`, `toolkit.py`, `cli.py` (new);
  MODIFY `packages/ai-parrot-semantic/src/parrot/semantic/cache.py` and
  `packages/ai-parrot/src/parrot/cli/__init__.py`; `tests/accounting/test_toolkit.py`, `test_cli.py`
- **Responsibility**: `catalog.py` — `ModelCatalog(models_dir)` indexes every `<tenant>/<model>.yaml` spec and
  loads selected snapshots into `AccountingModel`s keyed `(tenant, model)`, exposes `metrics()` and `reload()`, and holds the
  per-model live flags of M9. `cache.py` — `CompileCache` annotations are widened to a `CacheableCompiled` protocol
  (anything with a `cache_key: str` of the existing shape); behaviour is unchanged. `toolkit.py` —
  `AccountingToolkit(AbstractToolkit)` with `tool_prefix = "finance"`; only the four tool methods are public
  coroutines (every helper is `_`-prefixed, because `_generate_tools` exposes each public coroutine). PBAC follows
  `DatasetManager._pre_execute`: the hook stores the `_permission_context` kwarg in core `_pctx_var`; with no guard
  **or** no context every metric is allowed; otherwise `list_metrics` filters through
  `policy_guard.filter_datasets(pctx, names)` and explain/query require `can_read_dataset`, raising
  `AuthorizationRequired`. Both forms of `validate_model` additionally require the reserved model resource
  `accounting:<tenant>:<model>:__validate__` and read access to every metric in that model. Deny the entire
  request before snapshot refresh, compilation, execution or disclosure if any check fails. This explicit
  model-validation privilege covers assertions over raw sets as well as metric references. The no-guard or
  no-context rule remains unchanged. Guard inputs are bare `accounting:...` names; actual policy YAML keys
  are `dataset:accounting:...` with action `dataset:read`, since the guard adds the prefix.
  Tenant resolution: explicit `tenant` argument → `pctx.tenant_id` → toolkit default.
  `query_metric` flow: resolve spec → authorize → load selected model → compile (cached) → pick runtime →
  execute → audit → return rows, lineage, `sql_hash`, `audit_id`, `chart_drift`. A model flagged by a `block`
  assertion makes `query_metric` raise. `cli.py` — click group `finance` with `validate <path> [--live]
  [--models-dir]` and `explain <path> <metric>`, registered lazily in the core CLI.

  **Snapshot acquisition:** require exactly one of `snapshot_provider` or `snapshot_manifests` at construction;
  never infer the account master from journal rows. `snapshot_provider(tenant, model, spec)` is an injected
  async callable returning `ChartSnapshot`; its host owns the account-master connection/table, column mapping
  and credentials. `snapshot_manifests` is a YAML-safe nested map `{tenant: {model: manifest_path}}`; adapt it to the same
  provider and re-read each file on refresh. Missing configuration/keys or provider failure fail closed; a failed
  refresh never clears previous flags or reports successful validation.
  Resolve identities and permissions from `catalog.specs()` before any snapshot or journal access. Listing uses
  PBAC-filtered specs and fetches no snapshots. Other tools then await private lock-protected
  `_ensure_loaded(tenant, model)` only for the authorized selection: fetch its snapshot, validate journal
  metadata, and publish the validated model atomically. Provider calls and manifest I/O stay outside compilation.
  Structural CLI checks intentionally pass no journal columns; they report that live column checks were skipped.
  `validate_model(live=True)` refreshes only its authorized `(tenant, model)`; scheduled validation explicitly
  iterates all configured models through a private trusted helper. Fresh snapshots detect drift without silently
  changing the loaded model/hash. Explicit reload validates replacements atomically and invalidates old hashes
  in the compile cache.
  CLI `validate` and `explain` require `--snapshot <manifest>` for the selected model; live validation re-reads it.
  Database journal credentials use the existing resolver. For dataframe-backed live CLI validation require
  `--journal-arrow <IPC file>` as an explicit journal frame, otherwise fail with an actionable usage error.
  Structural validation/explain require no live journal. MCP-local uses explicit manifest configuration;
  embedded hosts may inject a provider backed by a database or Arrow account master.
- **Depends on**: M4, M5, M6, M7.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-semantic/src/parrot/semantic/cache.py  (modifies)
  class CacheableCompiled(Protocol):
      """A compiled artefact with a canonical-JSON cache key whose first element is the model digest."""
      @property
      def cache_key(self) -> str: ...
  class CompileCache:                                                 # verified: cache.py:32
      def get(self, key: str) -> CacheableCompiled | None: ...        # modifies cache.py:52
      def put(self, compiled: CacheableCompiled) -> None: ...         # modifies cache.py:59

  # parrot/semantic/accounting/catalog.py  (new)
  SnapshotProvider = Callable[[str, str, AccountingModelSpec], Awaitable[ChartSnapshot]]
  # Arguments: tenant, model, spec; providers must honor the exact requested identity.
  class ModelCatalog:
      def __init__(self, models_dir: Path) -> None: ...
      def load(self, snapshots: Mapping[tuple[str, str], ChartSnapshot],
               columns: Mapping[tuple[str, str], Mapping[str, str]] | None = None) -> None:
          """Load only keys supplied in snapshots; validate the entire batch before atomic publication.
          Reject unknown keys and identity mismatches with tenant/model declared in YAML; preserve other models."""
      def reload(self, snapshots: Mapping[tuple[str, str], ChartSnapshot],
                 columns: Mapping[tuple[str, str], Mapping[str, str]] | None = None) -> None:
          """Validate replacements before atomic publication; caller invalidates replaced model hashes."""
      def specs(self) -> dict[tuple[str, str], AccountingModelSpec]:
          """Parsed YAML specs keyed (tenant, model) — available before snapshots exist."""
      def get(self, tenant: str, model: str) -> AccountingModel: ...
      def metrics(self, tenant: str) -> list[tuple[str, str, MetricDef]]:
          """(model, metric name, definition) from parsed specs for one tenant; no snapshot access."""
      def flags(self, tenant: str, model: str) -> "ModelLiveStatus | None": ...
      def set_flags(self, status: "ModelLiveStatus") -> None: ...

  # parrot/semantic/accounting/toolkit.py  (new)
  class AccountingToolkit(AbstractToolkit):                          # verified: parrot/tools/toolkit.py:225
      """Finance tools: the LLM picks metric + grain + filters + period; the compiler writes the SQL."""
      tool_prefix = "finance"                                        # attribute verified: toolkit.py:276
      def __init__(self, *, models_dir: Path | str | None = None,
                   snapshot_provider: "SnapshotProvider | None" = None,
                   snapshot_manifests: "Mapping[str, Mapping[str, Path | str]] | None" = None,
                   database_toolkit: "DatabaseQueryToolkit | None" = None,   # verified: databasequery/toolkit.py:115
                   frame_provider: "FrameProvider | None" = None,
                   engine: "DuckDBEngine | None" = None,
                   policy_guard: "DatasetPolicyGuard | None" = None,         # verified: auth/dataset_guard.py:56
                   signer: "AbstractKMSSigner | None" = None,
                   audit_storage: "Callable[[str], Awaitable[None]] | None" = None,
                   audit_mode: "AuditMode | None" = None, default_tenant: str | None = None,
                   duckdb_threads: int = 4, result_limit: int = 10_000, **kwargs: Any) -> None: ...
      async def list_metrics(self, tenant: str | None = None) -> list[dict]:
          """Catalog of metrics visible to the caller (PBAC-filtered)."""
      async def explain_metric(self, metric: str, model: str | None = None, tenant: str | None = None) -> str:
          """Formula, resolved accounts per set, and covering assertions, as plain text."""
      async def query_metric(self, metric: str, period_from: str, period_to: str, model: str | None = None,
                             grain: str | None = None, dimensions: list[str] | None = None,
                             filters: dict | None = None, cumulative: str | None = None,
                             tenant: str | None = None) -> dict:
          """Compile → execute (database or duckdb) → audit → rows + lineage + sql_hash + audit_id + chart_drift."""
      async def validate_model(self, model: str, tenant: str | None = None, live: bool = False) -> dict:
          """Require validation privilege and all metric reads; return only the selected model’s results.
          With live=True refresh its snapshot and run last-closed-month assertions plus drift."""
      async def _pre_execute(self, tool_name: str, /, **kwargs) -> None:
          """Per-call PBAC hook  # hook verified: toolkit.py:491; pattern: dataset_manager/tool.py:2846"""

  # parrot/semantic/accounting/cli.py  (new)
  @click.group("finance")
  def finance() -> None: """Accounting metrics layer commands."""   # LazyGroup resolves the attribute `finance`
  @finance.command("validate")  # args: path; --live; --models-dir; --snapshot (required); --journal-arrow
  def validate(...) -> None: """Exit 1 on any Problem; prints the full problem list, grouped by interval."""
  @finance.command("explain")   # args: path, metric; --snapshot (required)
  def explain(...) -> None: ...
  ```
  ```python
  # packages/ai-parrot/src/parrot/cli/__init__.py  (modifies — after the anchor `    "disconnect": "parrot.cli.connect",` at :214)
      "finance": "parrot.semantic.accounting.cli",
  # (modifies — after the anchor `    "ontology": "ai-parrot[ontology-store]: pip install ai-parrot[ontology-store]",` at :230)
      "finance": "ai-parrot-semantic[duckdb]: pip install ai-parrot-semantic[duckdb]",
  ```

### Module 9: Live validation and scheduler adapter
- **Path**: `packages/ai-parrot-semantic/src/parrot/semantic/accounting/live.py`;
  `packages/ai-parrot-server/src/parrot/scheduler/accounting_jobs.py` (new);
  `tests/accounting/test_live.py`, `packages/ai-parrot-server/tests/scheduler/test_accounting_jobs.py`
- **Responsibility**: `live.py` — `run_live_validation(toolkit)` is a trusted host-only entry point, never a tool.
  For every configured model in `catalog.specs()`, initialize it if needed and call the snapshot provider afresh,
  `detect_drift`, compile and execute every assertion for the last closed natural month, append one audit entry per
  assertion, and set the catalog flags (`chart_drift`, `assertion_failed`, `blocked`) so later `query_metric`
  results carry them. The server adapter wraps it in an object with a `@schedule(ScheduleType.DAILY, ...)` method
  and exposes `register_accounting_schedules(scheduler, toolkit_factory)`. The host application calls it on the
  scheduler it builds (`app["scheduler_manager"]`); neither the satellite nor `ai-parrot-server` constructs a
  scheduler, and no host file is modified by this feature. The factory returns the same configured toolkit
  instance serving queries, so its catalog flags persist; it must configure snapshot acquisition. No
  caller-controlled flag enables trusted scheduler access. The public tool calls a private one-model helper
  after authorization, never the all-model host entry point.
- **Depends on**: M8.
- **Interface Skeleton**:
  ```python
  # parrot/semantic/accounting/live.py  (new)
  class ModelLiveStatus(BaseModel, frozen=True):
      tenant: str; model: str; drift_accounts: tuple[str, ...]
      assertion_results: tuple[AssertionResult, ...]; audit_ids: tuple[str, ...]; blocked: bool; checked_at: datetime
  class LiveValidationReport(BaseModel, frozen=True):
      models: tuple[ModelLiveStatus, ...]
  def last_closed_month(today: date) -> Period: ...
  async def run_live_validation(toolkit: "AccountingToolkit", *, today: date | None = None) -> LiveValidationReport: ...

  # packages/ai-parrot-server/src/parrot/scheduler/accounting_jobs.py  (new)
  from parrot.scheduler.manager import schedule                      # verified: scheduler/manager.py:50
  from parrot.scheduler.base import ScheduleType, SchedulerManager   # verified: scheduler/base.py:91, :255
  class AccountingValidationJobs:
      def __init__(self, toolkit_factory: Callable[[], Any]) -> None: ...
      @schedule(ScheduleType.DAILY, hour=6, minute=0)
      async def validate_accounting_models(self) -> dict:
          """Lazy-imports parrot.semantic.accounting.live; returns the report as a dict."""
  def register_accounting_schedules(scheduler: SchedulerManager, toolkit_factory: Callable[[], Any]) -> int:
      """scheduler.register_object_schedules(AccountingValidationJobs(factory), "accounting")  # verified: scheduler/base.py:806"""
  ```

### Module 10: Documentation
- **Path**: `wiki/tools/accounting-metrics-layer.md` (new); MODIFY `wiki/tools/semantic-layer.md` and
  `packages/ai-parrot-semantic/README.md`
- **Responsibility**: the new page covers the model YAML reference (every key, the `amount_convention` table,
  selectors, intervals, retained natures), the request contract, allowed cumulative/grain combinations and
  partial buckets, exact evaluation/rounding/overflow semantics, determinism and golden-test policy,
  audit entry fields and `lineage_ref` rebuild, the governance posture (per-metric `DatasetPolicyGuard`, allow
  without a guard) next to the fail-closed posture of the `sl_*` tools, the `DuckDBEngine` API, and the MCP-local,
  CLI and host-scheduler wiring (`register_accounting_schedules(app["scheduler_manager"], factory)`), required
  snapshot provider/manifests, live CLI journal Arrow input, validation permissions and actual
  `dataset:accounting:...` policy keys. The scheduler factory returns the same toolkit used for queries.
  `semantic-layer.md` gains a short section pointing to it. The README `Layering` paragraph is replaced by the
  actual contract: the accounting compile path (models, grammar, loader, validation, compiler) imports on its own;
  its toolkit and runtimes use the shared ledger, executor and cache.
- **Depends on**: M8, M9.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_engine_requires_extra` | M1 | a missing `duckdb` module raises the `require_extra` error naming `ai-parrot[duckdb]` |
| `test_engine_register_and_execute_arrow` | M1 | a registered Arrow table is queryable; the result is a `pa.Table` |
| `test_engine_per_call_frames_isolated` | M1 | 8 concurrent `execute` calls using the same frame name with different data each see only their own frame |
| `test_engine_per_call_frame_shadows_and_is_removed` | M1 | a per-call frame shadows a long-lived table of the same name and is gone after the call |
| `test_engine_closed_raises` | M1 | `execute` after `close` raises `RuntimeError` |
| `test_to_arrow_pandas_polars_arrow` | M1 | pandas and Arrow convert; polars converts when installed (`importorskip`) |
| `test_to_arrow_rejects_object_and_float` | M1 | object-dtype decimal column ⇒ `FrameConversionError`; float ⇒ error unless `allow_float`, then `decimal128(38, 6)` |
| `test_import_isolation` | M2 | a subprocess importing `parrot.semantic.accounting` and compiling a metric has no `parrot.semantic.toolkit`, `parrot.semantic.governance` or `parrot.tools.databasequery` in `sys.modules` |
| `test_semantic_package_exports_unchanged` | M2 | `from parrot.semantic import SemanticQuery, SemanticQueryResult, SemanticLayerToolkit` still works |
| `test_amount_convention_required` | M2 | missing `amount_convention` ⇒ validation error; each convention enforces its columns/nature rules |
| `test_journal_source_rules` | M2 | table XOR dataframe; `table` requires `connection` and `driver` |
| `test_request_cumulative_fits_grain` | M2 | exact allowed matrix; all cumulative+week/None combinations rejected before execution; non-cumulative week accepted |
| `test_grammar_accepts_closed_language` | M3 | every production parses; AST equality |
| `test_grammar_rejects_everything_else` | M3 | `if`, function names, strings, `%`, inline SQL ⇒ `GrammarError` with position |
| `test_partition_intervals` | M4 | boundaries from `valid_from`/`valid_to` produce the expected half-open intervals |
| `test_completeness_per_interval` | M4 | account covered only after `valid_from` ⇒ `interval_gap` problem for the earlier interval |
| `test_overlap_and_allow_overlap` | M4 | shared account ⇒ `overlap` unless both sets list each other |
| `test_all_problems_reported` | M4 | a model with 5 defects raises one error listing 5 problems |
| `test_cycle_and_dangling` | M4 | `a = b + 1, b = a` ⇒ cycle; `sum(nope)` ⇒ dangling |
| `test_float_amount_rejected_unless_allowed` | M4 | float column ⇒ `float_amount`; `allow_float` ⇒ accepted with `float_cast` warning |
| `test_model_hash_changes_with_snapshot` | M4 | same YAML, extra account or changed nature ⇒ different `model_hash` |
| `test_resolved_natures_round_trip` | M4/M5 | from_column model survives JSON round-trip and compiles without snapshot access; mixed natures normalize correctly; mapping conflicts rejected |
| `test_exact_numeric_types` | M4/M6 | reject unsupported precision/scale and out-of-range frame values before lossy conversion |
| `test_plan_is_plain_json` | M5 | `MetricPlan.model_dump_json()` round-trips; the plan holds no sqlglot object; `plan_hash` is stable |
| `test_plan_golden` | M5 | plans equal `golden/plans/*.json` |
| `test_compile_deterministic` | M5 | 50 compiles ⇒ one distinct `sql_hash`; `IN` lists sorted |
| `test_compile_golden_<dialect>` | M5 | rendered SQL equals `golden/<dialect>/*.sql` for duckdb, postgres, bigquery |
| `test_sign_normalisation_per_convention` | M5 | the four conventions emit the expected `CASE` arms |
| `test_cumulative_window_shape` | M5 | widened lower bound; natural-window partition; bucket-aligned output filter retains partial first bucket; formulas remain in plan |
| `test_refuse_membership_change` | M5 | period (and ytd window) crossing `valid_from` ⇒ `PeriodSpansMembershipChange` naming the boundary |
| `test_self_check_rejects_foreign_columns` | M5 | SQL referencing an undeclared column or table fails `self_check` |
| `test_coalesce_and_no_sql_division` | M5 | empty aggregate ⇒ 0 per set; generated SQL contains no metric arithmetic; formula and zero-division warning remain in plan/lineage |
| `test_exact_formula_evaluation` | M6 | 9007199254740993 / 1 stays exact; 1/3 ⇒ 0.333333; nested cancellation before final rounding; both runtimes agree |
| `test_rounding_and_overflow` | M6 | positive/negative half-even ties, signed division, precision-38 limits, intermediate values beyond Decimal context, final overflow raises |
| `test_invalid_aggregate_values` | M6 | float, NaN, infinity and malformed numeric strings rejected; zero denominator propagates NULL and assertion is skipped |
| `test_plan_hash_formula_identity` | M5/M7 | same-set formulas may share SQL hash but have different plan hashes; replay rejects tampered plan hash |
| `test_assertion_audit_replay` | M5/M7/M9 | audit every assertion by index; deserialize kind-discriminated request and rebuild identical lineage/plan/SQL hashes; reject wrong model, index or cumulative period |
| `test_duckdb_runtime_uses_frame_provider` | M6 | the provider is awaited with the model's frame name; the result has `Decimal` amounts |
| `test_database_runtime_builds_governed_query` | M6 | a fake `Executor` records a `GovernedQuery` with the compiled SQL unchanged and all 10 fields set |
| `test_database_runtime_truncation_raises` | M6 | `truncated=True` ⇒ `AccountingExecutionError`; `SemanticExecutionError` is re-raised as one |
| `test_ledger_accepts_both_entry_types` | M7 | one `SemanticAuditLedger` signs and verifies a `SemanticAuditEntry` and an `AccountingAuditEntry` |
| `test_audit_entry_signed_and_verifiable` | M7 | `LocalHMACSigner`; `verify` true; tamper ⇒ false |
| `test_audit_required_fails_closed` | M7 | storage raises ⇒ `AccountingAuditError`; `best_effort` ⇒ entry returned |
| `test_audit_entry_fits_postgres_sink_keys` | M7 | the dumped entry carries `entry_id, created_at, user_id, tenant_id, model, outcome, signature` |
| `test_compile_cache_holds_metric_queries` | M8 | `CompileCache.put/get/invalidate_model` work with `CompiledMetricQuery`; existing `CompiledQuery` behaviour unchanged |
| `test_toolkit_tools_and_prefix` | M8 | `get_tools()` names are exactly the four `finance_*` tools |
| `test_toolkit_pbac_filtering` | M8 | guard allowing one metric ⇒ `list_metrics` shows one; `query_metric` on another ⇒ `AuthorizationRequired` |
| `test_toolkit_allows_without_guard_or_context` | M8 | existing allow posture applies consistently to all four tools |
| `test_validate_model_authorization` | M8 | missing validation privilege or any metric read ⇒ deny before refresh/execution/disclosure, including raw-set assertions; permit fully authorized single-model validation |
| `test_policy_resource_names` | M8 | real guard receives bare accounting names; evaluator sees dataset:accounting keys and dataset:read action |
| `test_snapshot_acquisition` | M8 | distinct journal/master sources; provider called with tenant/model/spec; manifest adapter; missing/XOR config and missing manifest keys fail closed |
| `test_snapshot_refresh_failure` | M8/M9 | failed refresh preserves previous flags/model/hash and reports failure; successful refresh does not silently reload model |
| `test_cli_snapshot_inputs` | M8 | --snapshot required; live dataframe needs --journal-arrow; explicit manifest refresh; actionable missing-input errors |
| `test_cli_validate_exit_codes` | M8 | `parrot finance validate` exits 1 with problems, 0 clean; the lazy command resolves |
| `test_live_validation_flags` | M9 | failed `flag` assertion ⇒ `assertion_failed` on results; `block` ⇒ `query_metric` raises |
| `test_register_accounting_schedules` | M9 | one registered job; trusted refresh uses configured provider and same toolkit instance; query sees flags; no public trusted-bypass parameter |

### Integration Tests

| Test | Description |
|---|---|
| `test_e2e_duckdb_pnl` | 10k-row synthetic journal with mixed natures, `troc_pnl`-shaped model: revenue/gross_margin/ebitda by month equal hand-computed Decimals; assertions pass |
| `test_e2e_duckdb_cumulative` | supported grains equal hand-computed cumulative sums; ratio uses cumulative sets; partial first/last buckets and month/quarter/year transitions covered |
| `test_weekly_cumulative_rejected` | Dec 31/Jan 1 and month-end journals: week+ytd/qtd/mtd rejected, no query issued; non-cumulative weekly grouping remains correct |
| `test_e2e_duckdb_file_through_executor` | the same model against a DuckDB **file** through `DatabaseRuntime` + the real `Executor`: rows equal the engine rows |
| `test_e2e_postgres_parity` | same model against Postgres (`PARROT_TEST_PG_DSN`, skipped when unset): rows equal DuckDB rows |
| `test_e2e_audit_trail` | every `query_metric` produces one verifiable entry whose `lineage_ref` rebuilds the same `Lineage` |

### Validation Contract

tests:
- packages/ai-parrot/tests/interfaces/test_duckdb_engine.py
- packages/ai-parrot-semantic/tests/accounting/test_import_isolation.py
- packages/ai-parrot-semantic/tests/accounting/test_models.py
- packages/ai-parrot-semantic/tests/accounting/test_grammar.py
- packages/ai-parrot-semantic/tests/accounting/test_loader_validation.py
- packages/ai-parrot-semantic/tests/accounting/test_compiler.py
- packages/ai-parrot-semantic/tests/accounting/test_golden.py
- packages/ai-parrot-semantic/tests/accounting/test_runtime.py
- packages/ai-parrot-semantic/tests/accounting/test_evaluation.py
- packages/ai-parrot-semantic/tests/accounting/test_audit.py
- packages/ai-parrot-semantic/tests/accounting/test_toolkit.py
- packages/ai-parrot-semantic/tests/accounting/test_cli.py
- packages/ai-parrot-semantic/tests/accounting/test_live.py
- packages/ai-parrot-semantic/tests/accounting/test_e2e_duckdb.py
- packages/ai-parrot-semantic/tests/test_audit.py
- packages/ai-parrot-semantic/tests/test_cache.py
- packages/ai-parrot-semantic/tests/test_packaging.py
- packages/ai-parrot-semantic/tests/test_toolkit.py
- packages/ai-parrot-server/tests/scheduler/test_accounting_jobs.py
markers: none

The four existing files (`test_audit.py`, `test_cache.py`, `test_packaging.py`, `test_toolkit.py`) guard the shipped
modules this feature widens (`audit.py`, `cache.py`, `__init__.py`).

### Test Data / Fixtures

```python
# packages/ai-parrot-semantic/tests/accounting/conftest.py  (new — the satellite's root conftest.py has no fixtures)
@pytest.fixture
def chart_snapshot() -> ChartSnapshot:
    """40 accounts: 4xxx credit (revenue, 4900 returns), 5xxx debit (cogs, 5900 excluded-from-cogs), 6xxx debit (opex),
    6810/6820 d&a valid_from 2025-01-01, 9999 suspense (excluded)."""

@pytest.fixture
def troc_pnl_yaml(tmp_path) -> Path:
    """<tmp>/troc/troc_pnl.yaml — the brainstorm's model, amount_convention: debit_positive, nature from_column,
    journal source `dataframe: journal`."""

@pytest.fixture
def journal_frame() -> "pa.Table":
    """10k postings 2025-01..2026-09, Decimal(18,2) amounts, dimensions entity/product_line/cost_center, both natures,
    reversals, one empty month."""

@pytest.fixture
def journal_duckdb_file(tmp_path, journal_frame) -> Path:
    """The same journal written to a DuckDB file, for the executor-path test."""

@pytest.fixture
def recording_storage() -> tuple[Callable[[str], Awaitable[None]], list[str]]: ...

@pytest.fixture
def permission_context() -> "PermissionContext":
    """A PermissionContext for user 'u1', tenant 'troc', role 'finance'."""
```

---

## 5. Acceptance Criteria

- [ ] AC1 Importing `parrot.semantic.accounting` and compiling a metric loads no module of the governed stack
  (`parrot.semantic.toolkit`, `parrot.semantic.governance`, `parrot.tools.databasequery`), proven in a subprocess;
  `from parrot.semantic import SemanticQuery, SemanticQueryResult, SemanticLayerToolkit` still works.
- [ ] AC2 `parrot.interfaces.duckdb_engine` imports without `duckdb` installed; constructing `DuckDBEngine` without
  it raises the `require_extra` error naming `ai-parrot[duckdb]`.
- [ ] AC3 A model without `amount_convention` does not load; each of the four conventions renders the documented
  normalisation, proven by golden SQL and DuckDB execution. A from_column model preserves immutable resolved
  natures through JSON round-trip, compiles without its input snapshot, and hashes nature changes.
- [ ] AC4 `load_model` reports **every** problem in one `ModelValidationError`; completeness, overlap and exclusions
  are checked **per membership interval**; a model with an unassigned account in any interval does not load.
- [ ] AC5 `model_hash` covers the resolved model and the chart snapshot; `sql_hash` covers dialect + SQL; 50 compiles
  of the same input yield one hash; golden files exist for duckdb, postgres and bigquery and are byte-identical to
  the renderer output.
- [ ] AC6 The grammar accepts exactly `sum(set)`, `+ − × ÷`, unary minus, parentheses, metric references and `==` for
  assertions; everything else raises `GrammarError` with a position.
- [ ] AC7 Requests (including the widened cumulative window) that cross a membership boundary are refused with
  `PeriodSpansMembershipChange` naming the boundary and a split suggestion; no SQL is produced.
- [ ] AC8 `cumulative: mtd|qtd|ytd` returns running totals over the natural calendar; a cumulative ratio equals the
  ratio of cumulative sums. The validator enforces the explicit allowed matrix, rejecting week and no-grain
  cumulative requests before execution; partial first/last buckets follow the documented contract.
- [ ] AC9 Empty aggregates yield 0 per set; zero denominators yield NULL plus a lineage warning. Exact source
  and aggregate values fit DECIMAL(38,6); shared formula evaluation uses exact rational intermediates and rounds
  final outputs once to scale 6 half-even, independent of Decimal context. Float aggregates and overflow fail
  closed. Float inputs require explicit warned conversion. High-precision ratios, ties, cancellation and overflow
  execute identically in both runtimes; final amounts are Decimal, and NULL assertions are skipped.
- [ ] AC10 The same `CompiledMetricQuery` executes on `DuckDBEngine` (Arrow-registered pandas frames, and polars
  when installed; per-thread cursors; 8 concurrent requests with isolated per-call frames) and through the semantic
  `Executor` against a DuckDB file, with equal rows; the Postgres parity test passes when a DSN is provided.
  `Executor`, `DatabaseQueryToolkit`, `DuckDBSource`, `SQLToolkit` and `DatasetManager` are unchanged.
- [ ] AC11 Every executed query appends a signed `AccountingAuditEntry` to a `SemanticAuditLedger`; the same ledger
  instance still accepts `SemanticAuditEntry`; under `FINANCE_AUDIT_MODE=required` a missing or failing sink
  prevents the result from being returned; `lineage_ref` rebuilds exact `Lineage` for both metric and assertion
  requests using their discriminated request identity and verified model/plan/SQL hashes.
- [ ] AC12 The rendered SQL passes the compiler self-check (only the declared journal table and declared columns)
  before it is returned, in every test.
- [ ] AC13 `AccountingToolkit` exposes exactly `finance_list_metrics`, `finance_explain_metric`,
  `finance_query_metric`, `finance_validate_model`; with a `DatasetPolicyGuard` and a permission context, metrics
  the subject may not read are hidden and blocked; with no guard or no context every metric is allowed; no result
  cache exists. Both structural and live validation require the model-validation resource and every metric
  read when guard/context exist; denied calls disclose no assertion values or drift details and perform no refresh.
- [ ] AC14 `parrot finance validate <model> [--live]` is registered lazily in the core CLI, exits non-zero on any
  problem, requires explicit --snapshot, and --live refreshes it and runs last-closed-month assertions plus drift.
  Dataframe-backed live CLI requires --journal-arrow; database-backed CLI uses the existing connection resolver.
- [ ] AC15 `register_accounting_schedules` registers a daily live validation on a `SchedulerManager`; its flags
  (`chart_drift`, `assertion_failed`) appear on subsequent results; a `block` assertion makes `query_metric` raise.
  Startup and refresh use an explicit provider or manifest mapping, never infer a master from the journal. The
  scheduler uses the same toolkit as queries; provider failure preserves flags and fails validation visibly.
- [ ] AC16 `duckdb` is declared as an optional extra of core (`ai-parrot[duckdb]`) and of the satellite, and nowhere
  as a hard dependency; `pyarrow` stays a core dependency; polars is declared nowhere;
  `packages/ai-parrot-semantic/tests/test_packaging.py` passes unchanged.
- [ ] AC17 `MetricPlan` round-trips through JSON, contains no sqlglot object, and `render_plan` needs nothing but
  the plan and a dialect; golden plan files exist under `tests/accounting/golden/plans/`. The compiled artifact
  retains the plan for exact evaluation, its hash covers numeric policy/formulas, and audit replay verifies it.
- [ ] AC18 `ruff check` passes on every touched file (TID251 included); the existing satellite tests listed in the
  Validation Contract pass; no breaking change to any existing public API.
- [ ] AC19 Documentation pages declared in §10 exist under `wiki/` (`parrot sdd techwiki check`).

---

## 6. Codebase Contract

> Verified against `dev` at `928605b5a4`. `SL` = `packages/ai-parrot-semantic/src/parrot/semantic`,
> `CORE` = `packages/ai-parrot/src/parrot`, `SRV` = `packages/ai-parrot-server/src/parrot`.
> `packages/*/build/` holds stale copies — never read or grep them.

### Verified Imports
```python
from parrot.semantic.audit import SemanticAuditLedger, SemanticAuditEntry, postgres_audit_storage  # SL/audit.py:70, :23, :158
from parrot.semantic.execution import Executor, ConnectionResolver          # SL/execution.py:52, :18
from parrot.semantic.models import GovernedQuery, CompiledQuery, Grain       # SL/models.py:202, :192, :12
from parrot.semantic.cache import CompileCache                               # SL/cache.py:32
from parrot.semantic.errors import SemanticError, SemanticExecutionError     # SL/errors.py:8, :35
from parrot.tools.databasequery.toolkit import DatabaseQueryToolkit          # CORE/tools/databasequery/toolkit.py:115
from parrot.tools.databasequery.base import AbstractDatabaseSource, QueryResult, MetadataResult, TableMeta, ColumnMeta
                                                                             # base.py:323, :148, :134, :118, :100
from parrot.tools.toolkit import AbstractToolkit                             # CORE/tools/toolkit.py:225
from parrot.auth import PermissionContext, DatasetPolicyGuard, AuthorizationRequired   # lazy re-exports: auth/__init__.py:33, :44, :50
from parrot.auth.context import _pctx_var                                    # CORE/auth/context.py:33 (NOT re-exported by parrot.auth)
from parrot.security import AbstractKMSSigner, LocalHMACSigner               # as imported at SL/audit.py:14
from parrot._imports import require_extra                                    # CORE/_imports.py:248
from parrot.scheduler.manager import schedule, AgentSchedulerManager         # SRV/scheduler/manager.py:50, :397
from parrot.scheduler.base import SchedulerManager, ScheduleType             # SRV/scheduler/base.py:255, :91
import sqlglot; from sqlglot import exp                                      # satellite pin sqlglot>=30.1,<31 (venv 30.23.0)
import pyarrow as pa                                                         # core dependency pyarrow>=25.0 (pyproject.toml:190; venv 26.0.0)
import yaml                                                                  # satellite dependency pyyaml>=6
```

### Existing Class Signatures
```python
# SL/audit.py
class SemanticAuditEntry(BaseModel):                                         # line 23 — not frozen; 29 fields (:30-58); NOT modified
    def canonical_bytes(self) -> bytes                                       # line 60 — model_dump(mode="json", exclude={"signature"}), sorted keys, compact
class SemanticAuditLedger:                                                   # line 70
    def __init__(self, signer: AbstractKMSSigner | None = None, storage: Callable[[str], Awaitable[None]] | None = None, max_entries: int = 10_000) -> None  # line 79
    self.entries: deque[SemanticAuditEntry] = deque(maxlen=max_entries)      # line 87
    @property def durable(self) -> bool                                      # line 90 — storage is not None
    async def append(self, entry: SemanticAuditEntry, *, required: bool = False) -> SemanticAuditEntry  # line 95 — sets entry.signature; storage(entry.model_dump_json()) at :117;
                                                                             #   required + missing/failing sink ⇒ SemanticExecutionError("audit_unavailable", details={"audit_id": ...})
    async def verify(self, entry: SemanticAuditEntry) -> bool                # line 126
def postgres_audit_storage(dsn_or_pool: str | Any, *, table: str = "semantic_audit_events") -> Callable[[str], Awaitable[None]]  # line 158
    # reads payload keys entry_id, created_at, user_id, tenant_id, model, outcome, signature (:179-190)

# SL/execution.py
class ConnectionResolver:                                                    # line 18; PREFIX = "PARROT_SEMANTIC_CONN_" (:21)
    def __init__(self, env: Mapping[str, str] | None = None) -> None         # line 23
    def resolve(self, connection: str, driver: str) -> dict[str, Any]        # line 26 — duckdb ⇒ creds.setdefault("read_only", True) (:46-48)
class Executor:                                                              # line 52
    def __init__(self, toolkit: DatabaseQueryToolkit, resolver: ConnectionResolver) -> None   # line 55; attributes self.toolkit, self.resolver
    async def run_with_columns(self, governed: GovernedQuery, *, connection: str) -> tuple[list[dict], int, bool, int, list[str]]  # line 60
        # (rows, row_count, truncated, duration_ms, columns); truncated = len(all_rows) > governed.limit (:85); rows cut to governed.limit (:86)
        # never inspects or rewrites the SQL; raises SemanticExecutionError(no_source | no_credentials | execution_failed)
    async def run(self, governed: GovernedQuery, *, connection: str) -> tuple[list[dict], int, bool, int]   # line 92

# SL/models.py
class GovernedQuery(BaseModel, frozen=True):                                 # line 202 — 10 required fields, no validators (:205-214):
    sql: str; dialect: str; driver: str; tables: tuple[str, ...]; rls_applied: tuple[str, ...]; masked_columns: tuple[str, ...]
    limit: int; subject_digest: str; members: tuple[str, ...]; physical_columns: tuple[str, ...]
class CompiledQuery(BaseModel, frozen=True)                                  # line 192 — sql, dialect, members, tables, cache_key
Grain = Literal["second", "minute", "hour", "day", "week", "month", "quarter", "year"]   # line 12

# SL/cache.py
class CompileCache:                                                          # line 32
    def __init__(self, max_entries: int = 512) -> None                       # line 35; self._data: OrderedDict[str, CompiledQuery] (:37)
    def get(self, key: str) -> CompiledQuery | None                          # line 52
    def put(self, compiled: CompiledQuery) -> None                           # line 59 — keyed by compiled.cache_key; _model_digest_of(cache_key) (:12) needs
                                                                             #   canonical JSON: a list whose first element is the model digest, or a dict with "model_digest"
    def invalidate_model(self, model_digest: str) -> int                     # line 73

# SL/errors.py
class SemanticError(Exception):                                              # line 8
    def __init__(self, code: str, message: str = "", *, details: dict[str, Any] | None = None) -> None   # line 17; .code, .details
class SemanticExecutionError(SemanticError)                                  # line 35

# SL/__init__.py  (whole file, lines 1-7)
"""Governed semantic queries using the native sqlglot compiler."""
from .version import __version__
from .models import SemanticQuery, SemanticQueryResult
from .toolkit import SemanticLayerToolkit
__all__ = ["__version__", "SemanticQuery", "SemanticQueryResult", "SemanticLayerToolkit"]

# CORE/tools/databasequery/toolkit.py
class DatabaseQueryToolkit(AbstractToolkit):                                 # line 115
    def __init__(self, **kwargs: Any) -> None                                # line 154
    def get_source(self, driver: str) -> AbstractDatabaseSource              # line 202 — cached instance
# CORE/tools/databasequery/base.py
class AbstractDatabaseSource(ABC):                                           # line 323; driver: str (:336); sqlglot_dialect: str | None = None (:337)
    async def get_metadata(self, credentials: dict[str, Any], tables: list[str] | None = None) -> MetadataResult   # line 429
    async def query(self, credentials: dict[str, Any], sql: str, params: dict[str, Any] | None = None) -> QueryResult   # line 446
class QueryResult(BaseModel): driver; rows: list[dict[str, Any]]; row_count: int; columns: list[str]; execution_time_ms: float   # line 148
class MetadataResult: driver; tables: list[TableMeta]; raw                   # line 134
class TableMeta: name; schema_name; columns: list[ColumnMeta]; row_count     # line 118
class ColumnMeta: name: str; data_type: str; nullable; primary_key; default  # line 100
# CORE/tools/databasequery/sources/duckdb.py — DuckDBSource (:32): one duckdb.connect(database=..., read_only=...) per call, closed in
#   finally (:111-156); _database() defaults to ":memory:" (:72-75); takes no existing connection. NOT modified, NOT used for frames.

# CORE/tools/toolkit.py
class AbstractToolkit(ServerManagedToolkit, ABC):                            # line 225
    exclude_tools: tuple[str, ...] = ()                                      # line 262
    tool_prefix: str | None = None                                           # line 276; prefix_separator: str = "_" (:279)
    async def _pre_execute(self, tool_name: str, /, **kwargs) -> None        # line 491 — called at :179 with hook_kwargs["_permission_context"] (:178),
                                                                             #   always present (may be None); stripped before the tool method runs (:197-198)
    def _generate_tools(self) -> None                                        # line 575 — every public coroutine attribute becomes a tool (:583-606)

# CORE/auth/dataset_guard.py
class DatasetPolicyGuard:                                                    # line 56
    def __init__(self, evaluator: "PolicyEvaluator", logger: Optional[logging.Logger] = None) -> None   # line 91
    async def filter_datasets(self, context: PermissionContext, dataset_names: list[str]) -> set[str]   # line 128 — ResourceType.DATASET, "dataset:read"
    async def can_read_dataset(self, context: PermissionContext, dataset_name: str) -> bool             # line 278
# CORE/auth/permission.py
class PermissionContext:                                                     # line 81 (dataclass); properties user_id (:132), tenant_id (:137), roles -> frozenset[str] (:142)
# CORE/auth/context.py
_pctx_var: contextvars.ContextVar["PermissionContext | None"]                # line 33 — no public accessor functions in this module
# CORE/auth/exceptions.py
class AuthorizationRequired(Exception)                                       # line 15 — AuthorizationRequired(tool_name=..., message=...)

# CORE/tools/dataset_manager/tool.py  (pattern only — NOT modified)
async def _pre_execute(self, tool_name: str, /, **kwargs) -> None            # line 2846 — pctx = kwargs.get("_permission_context") (:2871); _pctx_var.set(pctx) (:2872);
                                                                             #   `if not self._policy_guard or not pctx: return` (:2879-2880); can_read_dataset (:2895)
async def materialize(self, name: str, force_refresh: bool = False, **params) -> pd.DataFrame   # line 4270 — the natural frame_provider target

# CORE/_imports.py
def require_extra(extra: str, *modules: str) -> None                         # line 248 — error text says `pip install ai-parrot[<extra>]`; no call sites yet

# CORE/cli/__init__.py
class LazyGroup(click.Group)                                                 # line 19; get_command: getattr(mod, cmd_name.replace("-", "_")) (:99-100)
cli._lazy_commands = {                                                       # line 170 … last entry :214, closes :215
cli._lazy_extras = {                                                         # line 219 … last entry :230, closes :231

# CORE/mcp/toolkit_config.py
class ToolkitSection(BaseModel)                                              # line 21 — class_path (alias "class"), enabled, kwargs, include, exclude, llm, llm_kwargs, env (:51-58)
# .parrot/mcp-toolkits.yaml — entries live under a top-level `toolkits:` key (:1-5)

# SRV/scheduler/manager.py
def schedule(schedule_type: ScheduleType = ScheduleType.DAILY, *, success_callback=None, send_result=None, callbacks=None, **schedule_config)  # line 50
class AgentSchedulerManager(SchedulerManager)                                # line 397
# SRV/scheduler/base.py
class ScheduleType(Enum): ONCE, DAILY, WEEKLY, MONTHLY, INTERVAL, CRON, CRONTAB   # line 91
class SchedulerManager:                                                      # line 255; registered_name: str = "scheduler_manager" (:258)
    def register_object_schedules(self, obj: Any, name: str) -> int          # line 806
    def setup(self, app: web.Application) -> web.Application                 # line 1398 — app[self.registered_name] = self
# app.py (repository root, host application): Main.configure builds AgentSchedulerManager(bot_manager=...) and calls .setup(app) (:158-163)

# CORE/tools/repl_worker/transport.py — pattern for pandas → Arrow
table = pa.Table.from_pandas(df, preserve_index=True)                        # line 120
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `DuckDBEngine.__init__` | `require_extra("duckdb", "duckdb")` | lazy extra | `CORE/_imports.py:248` |
| `DatabaseRuntime.execute` | `Executor.run_with_columns(governed, connection=...)` | method call with a constructed `GovernedQuery` | `SL/execution.py:60`, `SL/models.py:202` |
| `DatabaseRuntime.dialect_for` | `Executor.toolkit.get_source(driver).sqlglot_dialect` | attribute | `toolkit.py:202`, `base.py:337` |
| `DatabaseRuntime.fetch_columns` | `AbstractDatabaseSource.get_metadata` + `ConnectionResolver.resolve` | method calls | `base.py:429`, `SL/execution.py:26` |
| `DuckDBRuntime.execute` | `DuckDBEngine.execute(sql, frames=...)`, `to_arrow` | M1 | (new) |
| `append_entry` | `SemanticAuditLedger.append(entry, required=...)` | method call | `SL/audit.py:95` |
| `AccountingToolkit` compile cache | `CompileCache.get / put / invalidate_model` | duck-typed `cache_key` | `SL/cache.py:52, :59, :73` |
| `AccountingToolkit._pre_execute` | `_pctx_var.set()` + `DatasetPolicyGuard.can_read_dataset` | ContextVar + method call | `auth/context.py:33`, `dataset_guard.py:278` |
| `AccountingToolkit.list_metrics` | `DatasetPolicyGuard.filter_datasets` | batch filter | `dataset_guard.py:128` |
| `parrot finance …` | `cli._lazy_commands` / `cli._lazy_extras` | dict entries | `cli/__init__.py:214`, `:230` |
| `parrot mcp-local finance` | `.parrot/mcp-toolkits.yaml` under `toolkits:` | config entry (documented) | `toolkit_config.py:21` |
| `register_accounting_schedules` | `SchedulerManager.register_object_schedules` + `@schedule` | object registration | `scheduler/base.py:806`, `scheduler/manager.py:50` |
| host wiring (documented) | `app["scheduler_manager"]` | `SchedulerManager.setup` | `scheduler/base.py:1398`, `app.py:158-163` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.semantic.accounting`~~, ~~`AccountingToolkit`~~, ~~`AccountingAuditEntry`~~, ~~`ChartSnapshot`~~,
  ~~`frame_provider`~~, ~~`tool_prefix = "finance"`~~, ~~any `FINANCE_*` setting~~ — zero matches in `packages/*/src`;
  this feature creates them.
- ~~`parrot.interfaces.duckdb_engine`~~, ~~`class DuckDBEngine`~~ — do not exist; nor do the directories
  `CORE/engines`, `CORE/duckdb`, `CORE/tools/duckdb`. (`CORE/interfaces/dataframes.py` exists and is unrelated — do
  not edit it.)
- ~~`fetch_arrow_table` / `.register(` anywhere in package sources~~ — the only file importing `duckdb` is
  `CORE/tools/databasequery/sources/duckdb.py`, and it registers nothing.
- ~~`DuckDBSource` accepting a connection or sharing an in-memory database~~ — it opens and closes a connection per
  query; a `:memory:` database is new and empty every time. Frames cannot reach it.
- ~~an engine registry or dispatch in `parrot.semantic.engines`~~ — `compile` instantiates `NativeCompiler`
  directly (`SL/engines/__init__.py:29-46`). The accounting compiler is not registered there.
- ~~window functions, `COALESCE`, `NULLIF`, effective dating or cumulative totals in `NativeCompiler`~~ — zero
  matches in `SL/engines/native.py` (541 lines); `exp.Case` appears only for filtered measures (`:405`, `:431`).
- ~~a `duckdb` extra in core~~ — `grep -n duckdb packages/ai-parrot/pyproject.toml` returns nothing; M1 adds it.
- ~~`polars` declared or imported anywhere~~ — absent from every `pyproject.toml` and from `packages/*/src`
  (installed in the venv as 1.27.1, undeclared). Never `import polars`.
- ~~a subject-digest helper in `SL/audit.py`~~ — none; M7 defines its own.
- ~~`SemanticAuditLedger.get()` / `.list()`~~ — the ledger has only `append`, `verify` and `durable`.
- ~~public accessor functions in `parrot/auth/context.py`~~ — only `_pctx_var` and `class UserContext`.
  `parrot.semantic.context.current_pctx()` (`SL/context.py:44`) reads the satellite's own variable, which the
  finance toolkit does not bind — do not use it there.
- ~~`_permission_context` reaching a tool method~~ — it is passed only to `_pre_execute` and stripped afterwards.
- ~~a `SchedulerManager(` construction in `packages/*/src`~~ — the scheduler is built by the host (`app.py:158`)
  and by the agentd service (`integrations/agentd/service.py:465`).
- ~~`docs/semantic/`~~ — does not exist; semantic docs live in `wiki/tools/semantic-layer.md`. `wiki/_index.yaml`
  lists sections only, so a new page under `wiki/tools/` needs no index edit.
- ~~a `test-semantic` CI job~~ — the satellite tests run as the step "Semantic-layer tests" (`ci.yml:668-671`).
- ~~a free `finance` extra name in core~~ — `packages/ai-parrot/pyproject.toml:269` defines `finance = [...]`
  (ta-lib, unrelated). The engine extra is `duckdb`.
- ~~an example toolkit block at `mcp/toolkit_config.py:130-133`~~ — those lines are a docstring now.
- ~~fixtures in `packages/ai-parrot-semantic/tests/conftest.py`~~ — the file is a single docstring.
- ~~`Grain` or `Metric` as accounting names~~ — taken by `SL/models.py:12` and `SL/model.py`; use
  `AccountingGrain` and `MetricDef`.

### Edit Sites (Blueprint Anchors)

Verified against: `928605b5a4`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/pyproject.toml` | MODIFY | `# Financial analysis (ta-lib requires libta-lib-dev)` | `pyproject.toml:268` | 1 |
| `packages/ai-parrot-semantic/src/parrot/semantic/__init__.py` | MODIFY | `from .toolkit import SemanticLayerToolkit` | `__init__.py:5` | 1 |
| `packages/ai-parrot-semantic/src/parrot/semantic/audit.py` | MODIFY | `class SemanticAuditLedger:` | `audit.py:70` | 1 |
| `packages/ai-parrot-semantic/src/parrot/semantic/audit.py` | MODIFY | `        self.entries: deque[SemanticAuditEntry] = deque(maxlen=max_entries)` | `audit.py:87` | 1 |
| `packages/ai-parrot-semantic/src/parrot/semantic/audit.py` | MODIFY | `    async def append(self, entry: SemanticAuditEntry, *, required: bool = False) -> SemanticAuditEntry:` | `audit.py:95` | 1 |
| `packages/ai-parrot-semantic/src/parrot/semantic/audit.py` | MODIFY | `    async def verify(self, entry: SemanticAuditEntry) -> bool:` | `audit.py:126` | 1 |
| `packages/ai-parrot-semantic/src/parrot/semantic/cache.py` | MODIFY | `class CompileCache:` | `cache.py:32` | 1 |
| `packages/ai-parrot/src/parrot/cli/__init__.py` | MODIFY | `    "disconnect": "parrot.cli.connect",` | `cli/__init__.py:214` | 1 |
| `packages/ai-parrot/src/parrot/cli/__init__.py` | MODIFY | `    "ontology": "ai-parrot[ontology-store]: pip install ai-parrot[ontology-store]",` | `cli/__init__.py:230` | 1 |
| `packages/ai-parrot-semantic/README.md` | MODIFY | `The accounting extension must remain independently importable.` | `README.md:9` | 1 |
| `wiki/tools/semantic-layer.md` | MODIFY | `## Example agents` | `semantic-layer.md:159` | 1 |
| `packages/ai-parrot/src/parrot/interfaces/duckdb_engine.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/interfaces/test_duckdb_engine.py` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/src/parrot/semantic/accounting/{__init__,models,errors,grammar,snapshot,loader,validation,compiler,evaluation,audit,catalog,toolkit,cli,live}.py` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/src/parrot/semantic/accounting/runtime/{__init__,duckdb,database}.py` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/tests/accounting/{__init__,conftest}.py`, `tests/accounting/test_*.py` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/tests/accounting/golden/{duckdb,postgres,bigquery}/*.sql`, `golden/plans/*.json` | CREATE | — | — | — |
| `packages/ai-parrot-server/src/parrot/scheduler/accounting_jobs.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/tests/scheduler/test_accounting_jobs.py` | CREATE | — | — | — |
| `wiki/tools/accounting-metrics-layer.md` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Import isolation**: `models.py`, `errors.py`, `grammar.py`, `snapshot.py`, `loader.py`, `validation.py` and
  `compiler.py` and `evaluation.py` import only the standard library, `pydantic`, `yaml`, `sqlglot`, `pyarrow` (inside functions) and
  each other. `audit.py`, `catalog.py`, `toolkit.py`, `live.py` and `runtime/*` may import `parrot.semantic.*`
  siblings, `parrot.auth`, `parrot.tools` and `parrot.interfaces.duckdb_engine`.
- **Lazy optional dependency**: `require_extra("duckdb", "duckdb")` inside `DuckDBEngine.__init__`, never at module
  import; `import duckdb` only inside functions.
- **Hashing**: `canonical_json` = `json.dumps(model_dump(mode="json"), sort_keys=True, separators=(",", ":"))`,
  Decimals as strings; `sha256` hex. The same function hashes models, requests, plans and audit entries.
- **sqlglot**: build with `exp.*` constructors only (`exp.Select`, `exp.Case`, `exp.Sum`, `exp.Coalesce`,
  `exp.DateTrunc`, `exp.Window`, `exp.In` with sorted `exp.Literal.string` values); never
  `sqlglot.parse_one(f"...")` with interpolated model data. Render `pretty=False`, `identify=False`.
- **Plan before SQL**: `render_plan` reads only the `MetricPlan`. Anything the renderer needs must be a plan field.
- **Dates**: half-open `[from, to + 1 day)` in SQL to be timestamp-safe; `Period.to` inclusive at the API.
- **Decimal**: exact `DECIMAL(38,6)` aggregates on every dialect; shared rational evaluator with scale-6
  half-even final outputs. Reject float aggregates and overflow; no SQL division or ambient-context rounding.
- **Threading**: one root connection per engine; a new `root.cursor()` per `asyncio.to_thread` call; a semaphore
  bounds concurrency; cursors are closed in `finally`.
- **PBAC**: copy `DatasetManager._pre_execute` semantics (no guard or no context ⇒ allow; `AuthorizationRequired`
  bubbles). Tool methods read the context from `_pctx_var`, set by the hook.
- **Executor reuse**: pass `compiled.sql` unchanged; never add a `LIMIT`; treat `truncated` as an error.
- **Tools**: in `AccountingToolkit` every non-tool coroutine starts with `_`.
- **Logging**: `self.logger`; never log SQL with account literals at INFO (DEBUG only); never log identities.
- Conventions: `.claude/rules/codebase-conventions.md` (aiohttp only, Pydantic v2, Google docstrings, 120 cols).

### Known Risks / Gotchas
- **Per-call frame isolation on DuckDB cursors** — the design assumes a frame registered on one cursor is not
  visible on another cursor of the same root connection. Nothing in this repository proves it.
  `test_engine_per_call_frames_isolated` must pass before any other M1 code is relied on; if cursors share
  registrations, the engine registers per-call frames under a unique internal name and exposes them to the query
  through a per-cursor temporary view (§8 Q1).
- **Two governance postures in one package** — finance metrics allow when no guard or no context is configured;
  `sl_*` queries fail closed. The wiki page and the toolkit docstring state it; both paths are tested.
- **Unbounded result fetch on the database target** — the SQL has no `LIMIT`, so the driver fetches every group
  before `Executor` reports truncation. Rollups are small, but a request grouped by a high-cardinality dimension at
  day grain can be large; `result_limit` (default 10 000) turns it into an error, not a partial answer.
- **`GovernedQuery` built outside `GovernancePipeline`** — `rls_applied` and `masked_columns` are empty by
  construction. The finance path applies no RLS or masking (Non-Goals); the entry in the audit ledger is an
  `AccountingAuditEntry`, so a reader can tell the two paths apart.
- **Audit identity** — `AccountingAuditEntry` stores `user_id` and `tenant_id` because the shipped Postgres sink
  reads those keys; the 2026-10-21 draft stored only a digest. `subject_digest` is kept as well.
- **Ledger retention** — the shared ledger keeps up to 10 000 entries in memory; accounting entries count toward it.
- **sqlglot rendering drift** — the satellite pin `>=30.1,<31` is shared with `NativeCompiler`; a bump changes both
  compilers. Golden files per dialect are the review artifact.
- **Account present in two sets** — error unless mutual `allow_overlap`.
- **Membership change inside the requested or cumulative window** — refused (`PeriodSpansMembershipChange`); never
  silently sliced.
- **Chart drift** — new accounts after load: `detect_drift` on `--live`/scheduled validation sets `chart_drift: true`
  on results; the loaded model keeps serving.
- **Metric referencing a set whose `valid_from` is after the period** — compile error, never an empty number.
- **Unknown dimension / filter column** — `RequestValidationError` before compilation.
- **Division by zero** — the shared evaluator returns NULL and lineage warns `division_by_zero_possible`;
  NULL assertion sides are skipped. No metric division is emitted in SQL.
- **NULL vs 0** — `COALESCE(SUM(...), 0)` per set so empty groups reconcile; assertions compare Decimals with
  `tolerance` (default 0).
- **pandas → Arrow copies** — `from_pandas` is not zero-copy; only Arrow → DuckDB registration is. Object or float
  amount columns raise `FrameConversionError` / a `float_amount` problem; `allow_float` casts to `DECIMAL(38,6)`
  with a lineage warning.
- **Lazy package `__init__`** — a module `__getattr__` changes when `toolkit.py` import errors surface (first
  attribute access instead of package import). `test_semantic_package_exports_unchanged` covers the names.
- **Audit fail-closed in dev** — the documented MCP-local example sets `FINANCE_AUDIT_MODE=best_effort`; production
  keeps `required`.
- **Scheduler ownership** — the host builds the scheduler; a deployment that never calls
  `register_accounting_schedules` has on-demand validation only.
- **Extra name collision** — core already has an unrelated `finance` extra (ta-lib); never add dependencies there.
- **CI coverage of the engine test** — the CI step syncs with `--extra duckdb`; the engine test still uses
  `pytest.importorskip("duckdb")` so a core-only environment skips it instead of failing.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `sqlglot` | `>=30.1,<31` (satellite pin, unchanged; venv 30.23.0) | AST construction, dialect rendering, self-check parse |
| `pyarrow` | `>=25.0` (core, already declared; venv 26.0.0) | DataFrame → DuckDB bridge, engine results |
| `duckdb` | `>=1.0` — **new optional extra in core** (`ai-parrot[duckdb]`); the satellite extra is unchanged (venv 1.5.6) | in-process engine |
| `pyyaml` | `>=6` (satellite, already declared) | model files |
| `pydantic` | v2 (core) | contracts |
| `polars` | not declared (venv 1.27.1) | accepted when present through `to_arrow()`; never imported, never a dependency |

Configuration keys (environment): `FINANCE_MODELS_DIR` (default `./models`), `FINANCE_DUCKDB_THREADS` (default 4),
`FINANCE_AUDIT_MODE` (`required` | `best_effort`, default `required`), `FINANCE_RESULT_LIMIT` (default 10000).
Database connections use the existing `PARROT_SEMANTIC_CONN_<NAME>_<KEY>` variables.

---

## Worktree Strategy

- **Isolation**: one feature worktree for this spec; the `sdd-coder` engine gives each task its own sub-worktree
  inside it.
- **Module dependency graph**:
  - M1 (core engine) and M2 (contracts) have no dependencies and run concurrently.
  - M3 → M2 (imports `GrammarError`).
  - M4 → M2, M3 (models; `parse_expr` / `references` for cycle and dangling checks).
  - M5 → M2, M3, M4 (`AccountingModel`, `metric_order`, `canonical_json`).
  - M6 → M1, M2, M5 (`DuckDBEngine` / `to_arrow`; `CompiledMetricQuery`; shared `evaluate_rows`).
  - M7 → M2, M5 (`CompiledMetricQuery`, discriminated requests, `compile_metric` / `compile_assertion` for replay).
  - M8 → M4, M5, M6, M7.
  - M9 → M8 (`AccountingToolkit`, `ModelCatalog` flags).
  - M10 → M8, M9.
  - M6 and M7 have no edge between them and run concurrently; so do M1 and the M2 → M3 → M4 → M5 chain.
- **Shared files**: `packages/ai-parrot-semantic/tests/accounting/conftest.py` is written once, by M2, with every
  fixture of §4, so no later module edits it. `SL/audit.py` (M7), `SL/cache.py` (M8), `SL/__init__.py` (M2),
  `CORE/cli/__init__.py` (M8) and `packages/ai-parrot/pyproject.toml` (M1) each have a single owner module.
  `packages/ai-parrot-semantic/README.md` is edited only by M10.
- **Exclusive resources**: none. No module rebuilds an extension, changes a lockfile or runs a migration; the new
  core extra is a `pyproject.toml` line and `duckdb` is already installed in the shared environment.
- **Cross-feature dependencies**: none must merge first. FEAT-880 is independent. FEAT-742 consumes `MetricPlan`
  after this feature lands. The DuckDB-backed dataset store (no id yet) depends on M1.

---

## Consequences

<!-- decision-audit: input_digest=sha256:7ee631cb368c97479e2195d418b2e07d10bb28916376d7748fbd22161390ebe3 evaluation_digest=sha256:7f8e45f688bcbbf4eee6b68871988b267685a6fb53888374f616fd5eb6cbb992 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- `SPEC_BLOCK_MISSING`; path: sdd/specs/accounting-metrics-layer.spec.md; message: no fenced yaml block under '## Decisions'

Coverage:
- Subsystems: auth, bots, clients, config, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, server, skills, tools
- Unmapped tags: accounting, arrow, audit, duckdb, semantic-layer, sqlglot
- Targets resolved: 0/0
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "auth",
      "bots",
      "clients",
      "config",
      "flows",
      "knowledge-graphindex",
      "knowledge-pageindex",
      "knowledge-wiki",
      "memory",
      "server",
      "skills",
      "tools"
    ],
    "targets_resolved": 0,
    "targets_total": 0,
    "unmapped_tags": [
      "accounting",
      "arrow",
      "audit",
      "duckdb",
      "semantic-layer",
      "sqlglot"
    ]
  },
  "diagnostics": [
    {
      "code": "SPEC_BLOCK_MISSING",
      "decision_id": null,
      "message": "no fenced yaml block under '## Decisions'",
      "path": "sdd/specs/accounting-metrics-layer.spec.md"
    }
  ],
  "evaluation_digest": "sha256:7f8e45f688bcbbf4eee6b68871988b267685a6fb53888374f616fd5eb6cbb992",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:7ee631cb368c97479e2195d418b2e07d10bb28916376d7748fbd22161390ebe3",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {},
    "rules_version": 1,
    "structural_revision": "sha256:b11fe8e33d80455017c18de7c66615b790b28eae29c88d3cc6defc398db393fb",
    "taxonomy_digest": "65548b9a71329b13ab44f4904dff99814e1aac0da4bb2b58171a7201e3a9ba39"
  },
  "status": "pass"
}
```

## 8. Open Questions

- [x] Package home — *Resolved in brainstorm, revised*: `parrot.semantic.accounting` in the `ai-parrot-semantic`
  satellite. The "standalone, this feature creates the skeleton" half is superseded: FEAT-704 created the satellite
  (semantic-layer spec U6, owner, 2026-10-25) and this feature extends it.
- [x] U1 Reuse or standalone — *Resolved in proposal (owner, 2026-11-11)*: reuse the shipped infrastructure —
  `SemanticAuditLedger` (generalising the entry), `Executor` / `ConnectionResolver` over `DatabaseQueryToolkit` and
  the compile cache; only model, grammar, validation and compiler are accounting-specific.
- [x] U2 Governance posture — *Resolved in proposal (owner, 2026-11-11)*: `DatasetPolicyGuard` with
  `accounting:<tenant>:<model>:<metric>` resources; no guard configured means allow, as in `DatasetManager`.
- [x] U3 DuckDB scope for FEAT-880 — *Resolved in proposal (owner, 2026-11-11)*: a reusable in-process DuckDB
  engine over Arrow is delivered here; the DuckDB-backed dataset store goes into its own feature that builds on it.
- [x] U4 Where models live — *Resolved in brainstorm and proposal*: git, `<models_dir>/<tenant>/<model>.yaml`,
  reviewed in PRs; `model_hash` is tied to a commit. Admin UI is v2.
- [x] Engine home — *Resolved (owner, 2026-11-11)*: core, `parrot.interfaces.duckdb_engine`, behind a new core
  `duckdb` extra, so a `DatasetManager` store can import it. The draft's "duckdb is only an extra of the satellite"
  is replaced by AC16.
- [x] polars in v1 — *Resolved (owner, 2026-11-11)*: accepted when installed, through `to_arrow()` with no import
  of polars and no declared dependency or extra; the test skips when polars is absent.
- [x] "Independently importable" — *Resolved (owner, 2026-11-11)*: kept for the compile path (model, grammar,
  validation, compiler); the package `__init__` becomes lazy and a subprocess test proves it. Toolkit and runtimes
  may import siblings.
- [x] FEAT-742 scope — *Resolved (owner, 2026-11-11)*: the accounting compiler is inside FEAT-742's scope. This
  spec keeps the IR portable (`MetricPlan`, golden plan files); the port itself belongs to the FEAT-742 proposal.
- [x] Effective-dated membership strategy — *Resolved in brainstorm*: refuse requests (including cumulative
  windows) that span a membership change in v1, with an actionable error. Slice + `UNION ALL` is v2.
- [x] Sign convention — *Resolved in brainstorm, refined by codex S4*: required key `amount_convention:
  debit_positive | credit_positive | debit_credit_columns | natural_balance`, no default; `nature` required only
  when normalising by nature.
- [x] Hierarchy selectors (`parent:`) — *Resolved in brainstorm*: v2.
- [x] Period semantics — *Resolved in brainstorm*: natural calendar by `posting_date`, plus cumulative YTD/QTD/MTD
  in v1. Fiscal calendars and closed-period flags stay non-goals.
- [x] Assertions at load vs. on schedule — *Resolved in brainstorm*: both — on demand
  (`parrot finance validate --live`) and a scheduled task over the last closed period + chart drift.
- [x] Audit payload — *Resolved in brainstorm, revised by U1*: a signed `AccountingAuditEntry` with hashes, the
  canonical request and a `lineage_ref`; lineage is rebuilt, never stored inline; `AuditLedgerEntry` is not
  extended. It is appended to the shared `SemanticAuditLedger` instead of a separate ledger;
  `FINANCE_AUDIT_MODE=required` fails closed by default.
- [x] Lowering into the generic layer — *Resolved in brainstorm*: deferred; not committed in this spec.
- [x] Q10 FEAT-704 amendment — *Closed*: moot. FEAT-704 created the skeleton and this revision is the edit the
  semantic-layer spec U6 asked for.
- [x] Q11 Server scheduler call site — *Resolved by research*: the scheduler is built by the host application
  (`app.py:158-163`, `AgentSchedulerManager(...).setup(app)`), reachable as `app["scheduler_manager"]`. The feature
  ships `register_accounting_schedules` and documents the host call; it edits no host file.
- [ ] Q1 Per-call frame isolation — does a frame registered on one DuckDB cursor stay invisible to other cursors of
  the same root connection? `test_engine_per_call_frames_isolated` decides; the fallback (unique internal names
  behind a per-cursor temporary view) is described in §7. — *Owner: M1 implementer*
- [ ] Q2 Should the root `app.py` call `register_accounting_schedules` when a models directory is configured? Out
  of scope here; the wiring is documented. — *Owner: Jesus*
- [ ] Q3 Feature id and spec for the DuckDB-backed dataset store that FEAT-880 deferred. — *Owner: Jesus*

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration doc** (never over this spec).
> Status: skipped (the revision proposal is `status: review`, not `accepted`; no new codex run for revision 0.2)
> · Transcript of the 2026-10-21 run: `sdd/state/FEAT-713/design_research/` (model `gpt-5.6-luna`)
>
> The table carries the 2026-10-21 suggestions forward with their disposition under this revision. No reviewer has
> seen the revision-specific decisions (shared ledger, executor reuse, core engine, `MetricPlan`).

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Make the chart of accounts an immutable, versioned input (architecture) | CONFIRM | unchanged: hashed `ChartSnapshot` folded into `model_hash` | §2 Data Models, M4 |
| S2 | One canonical IR with target-specific SQL renderings (alternative) | CONFIRM | strengthened: the IR is now the serialisable `MetricPlan` | §1 Goals, M5 |
| S3 | Do not treat toolkit validation as a semantic allowlist (risk) | CONFIRM | unchanged: compiler self-check on the rendered SQL | M5 `self_check`, AC12 |
| S4 | Specify the sign contract as data-shape semantics (api) | CONFIRM | unchanged: `amount_convention` with four normalisations | §2 sign table, AC3/AC9 |
| S5 | Validate effective-dated completeness per interval (architecture) | CONFIRM | unchanged | M4 `partition_intervals`, AC4 |
| S6 | Fix numeric and empty-result semantics before golden tests (testing) | CONFIRM | revision 0.3: exact set aggregates, shared rational evaluation, scale-6 half-even final outputs; reject floating aggregates | M5, M6, AC8/AC9 |
| S7 | Keep accounting execution separate from the DatasetManager catalog contract (architecture) | CONFIRM | unchanged: own `ModelCatalog`, frames through `frame_provider`, `DatasetManager` unmodified | M6, M8 |
| S8 | Exclude shared DatasetManager caches from accounting results (risk) | CONFIRM | unchanged: no result cache, compile cache only | Non-Goals, AC13 |
| S9 | Define a separate durable accounting audit contract (architecture) | CONFIRM (revised) | the entry stays separate and fail-closed; the ledger is shared by owner decision U1 | M7, AC11 |
| S10 | Separate structural assertion validation from live reconciliation (testing) | CONFIRM | unchanged | M4, M9, AC15 |
| S11 | Resolve ownership of the `parrot.semantic` satellite before creating it (architecture) | REJECT (obsolete) | FEAT-704 created the satellite; nothing left to resolve | — |

Summary: **10** confirmed · **1** rejected · **0** escalated.

---

## 10. Documentation

- **Policy**: `required`
- **Pages**:
  - `wiki/tools/accounting-metrics-layer.md` — create: model YAML reference, request contract, cumulative periods,
    determinism and golden files, audit entry and `lineage_ref`, governance posture, `DuckDBEngine` API, MCP-local /
    CLI / host-scheduler wiring.
  - `wiki/tools/semantic-layer.md` — update: a short section pointing to the accounting page and stating the two
    governance postures.
- **API modules** (informational — docstring completeness expectation):
  - `parrot.semantic.accounting`
  - `parrot.interfaces.duckdb_engine`

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-21 | Jesus Lara | Initial draft (standalone package, satellite skeleton created here) |
| 0.2 | 2026-11-11 | Jesus Lara | Rewritten on the shipped `ai-parrot-semantic`: M1 skeleton dropped; shared audit ledger, executor and compile cache; core `DuckDBEngine`; portable `MetricPlan` for FEAT-742; `DatasetPolicyGuard` posture and tenant directories kept |
| 0.3 | 2026-11-12 | Codex, at owner request | Resolve five review findings: retained natures, exact shared evaluator and numeric policy, supported cumulative grains/partial buckets, validation authorization, explicit snapshot acquisition and refresh. Update module interfaces, tests, ACs and docs together. |


## 11. Specification Review Resolutions (revision 0.3)

These are specification fixes authorized by the owner; implementation acceptance remains unchecked. The
revision supersedes conflicting revision-0.2 prose, including its SQL-side formula evaluation. The original
review probes are in `artifacts/logs/accounting_metrics_spec_review.log`.

| Ledger finding | Resolution | Verification contract |
|---|---|---|
| `issue:a07ef212ed98` — discarded account natures | Model retains sorted immutable resolved natures and hashes them; plan copies the selected subset | M4/M5 round-trip test, AC3/5 |
| `issue:90327faf562c` — floating division | SQL emits exact set aggregates; shared rational evaluator rounds final outputs once; reject float aggregates and overflow | M6 evaluation tests, AC9/10/17 |
| `issue:229e6b94db2f` — weekly cumulative boundaries | Reject cumulative week/None; explicit allowed matrix and partial-bucket output bounds | M2/M5 boundary tests, AC8 |
| `issue:1a91317c9437` — validation disclosure | Require validation privilege and all model metric reads before refresh/disclosure; scheduler is a separate trusted host path | M8 authorization tests, AC13 |
| `issue:8d5487de6ac1` — missing snapshot acquisition | Required provider XOR manifest map; explicit startup, CLI and scheduled refresh contracts | M8/M9 acquisition/failure tests, AC14/15 |
| Follow-up cross-check — assertion replay identity | Discriminated `AssertionRequest` carries a model-bound assertion index and period; replay dispatches by kind | M5/M7/M9 assertion replay test, AC11 |
