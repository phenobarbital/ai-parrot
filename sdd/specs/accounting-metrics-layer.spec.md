---
type: feature
base_branch: dev
projects: [ai-parrot-semantic, ai-parrot, ai-parrot-server, ci]
tags: [accounting, semantic-layer, sqlglot, duckdb, arrow, audit, finance]
---

# Feature Specification: Accounting Metrics Layer — chart-of-accounts rollups compiled to deterministic queries

**Feature ID**: FEAT-713
**Date**: 2026-10-21
**Author**: Jesus Lara
**Status**: draft
**Target version**: 1.3.0
**Source**: `sdd/proposals/accounting-metrics-layer.brainstorm.md` (accepted 2026-10-21, Option B; all nine Open Questions resolved the same day)

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

The generic semantic layer (FEAT-704) solves metric *naming* and *governance*, but its primitives (measures,
dimensions, joins) do not express the accounting invariants: completeness of the chart of accounts over the declared
buckets, debit/credit sign normalisation, effective-dated membership, and reconciliation assertions
(`revenue − expenses == net_income`). FEAT-704 is also **paused** until its AGPL-3.0 dependency (sidemantic) is
migrated away, so this layer cannot depend on it.

Who is affected: any agent using `SQLToolkit` or `DatasetManager` over a general ledger; finance users of client
deployments (TROC first); and the audit trail (a financial figure must be traceable to the exact query and model
version that produced it).

### Goals

- **The LLM never writes the aggregation.** It selects `metric + grain + filters + period`; the compiler produces the
  query ("probabilistic proposes, deterministic decides").
- **One canonical IR, two execution targets.** The same compiled AST is rendered per dialect and runs against the
  source database through `SQLToolkit` and against in-memory DataFrames through DuckDB. Each rendering has its own
  `sql_hash`; the `model_hash` is shared.
- **DuckDB in-process, Arrow as the bridge.** pandas/polars frames are registered into DuckDB via Arrow, never
  serialised; no pickle across trust boundaries.
- **A closed grammar.** `sum(set)`, `+ − × ÷`, parentheses, metric references. Nothing else.
- **Determinism as a contract.** Same `model_hash` + same canonical request + same dialect ⇒ byte-identical SQL.
  Sorted `IN` lists, model-derived aliases, no timestamps. Guarded by per-dialect golden tests and a pinned sqlglot.
- **Compile-time validation, never runtime surprises.** Completeness (per effective-dated interval), overlaps,
  cycles, dangling references, empty sets, sign-convention consistency and numeric types are checked when the model
  loads; a model that fails validation does not load.
- **Explainability.** Every result carries lineage: contributing sets, the concrete accounts each resolved to, the
  formula, and the assertions that cover the metric.
- **Multi-tenant, PBAC-filtered, audited.** Models are tenant-scoped under `<models_dir>/<tenant>/`; metric
  visibility is filtered through the existing `DatasetPolicyGuard`; every result is a signed `AccountingAuditEntry`.
- **Natural calendar with cumulative periods.** `posting_date` buckets by day/week/month/quarter/year plus
  YTD/QTD/MTD running totals over the natural calendar (client requirement).
- **No new heavy dependency.** `sqlglot` (pinned `>=30.1,<31`), `duckdb` (optional extra), `pyarrow` (already in
  core), Pydantic v2, PyYAML.

### Non-Goals (explicitly out of scope)

- Joins to dimension tables — the journal must already carry the dimensions, or a pre-joined view is pointed at.
- Fiscal calendars and period-close flags (cumulative periods over the **natural** calendar are in scope).
- Requests whose period (or cumulative window) spans an account-membership change — refused with an actionable
  error; slice + `UNION ALL` is a v2 option (brainstorm resolution).
- Hierarchy (`parent:`) selectors — v2 unless spike S3 proves explicit lists/prefix/range cannot reach zero
  unassigned accounts in one session.
- Multi-entity consolidation, intercompany eliminations, multi-currency / FX.
- Result caching of any kind (compile cache only — codex S8).
- Materialisation via Flowtask (brainstorm Option D) and lowering into the generic semantic layer (Option A) —
  both deferred until FEAT-704 resumes.
- Modifying `SQLToolkit`, `DatasetManager`, `AuditLedgerEntry` or `parrot/clients/base.py` — the layer is purely
  additive to core (see §2 Integration Points).
- A finance admin UI for editing models (models live in git).
- Any grammar node beyond `Sum`, `Ref`, `Num`, `Neg`, `BinOp`.

---

## 2. Architectural Design

### Overview

A small, self-contained package `parrot.semantic.accounting` inside a new PEP 420 satellite distribution
**`ai-parrot-semantic`** (brainstorm resolution: "standalone package, not an engine of FEAT-704"). The satellite
skeleton created here is a **byte-level mirror of the one on `origin/feat-FEAT-704-semantic-layer` minus sidemantic**
(same distribution name, same `version.py`, same `[tool.setuptools]` tables, same `release.py` entry) so that when
FEAT-704 resumes its merge touches only `pyproject.toml` dependencies, `__init__.py` exports and `README.md`.
`parrot.semantic.accounting` never imports anything from `parrot.semantic.*` outside itself.

Pipeline:

1. **Load** — `load_model(path | dict, snapshot)` validates the YAML with Pydantic, resolves selectors
   (`accounts`, `prefix`, `range`, `tag`, `except`) against an immutable, hashed `ChartSnapshot` (the account master —
   codex S1), partitions time by every `valid_from`/`valid_to` boundary and checks **completeness, overlap and
   exclusions per interval** (codex S5), then checks cycles, dangling references, empty sets, sign-convention
   consistency and numeric column types. Errors are collected and raised together as `ModelValidationError`.
   `model_hash = sha256(canonical JSON of the resolved model + snapshot_hash)`.
2. **Parse** — `parse_expr()` is a ~100-line Pratt parser producing a closed AST.
3. **Compile** — `compile(model, request, dialect)` inlines metric references, deduplicates sets and builds one
   `sqlglot.exp.Select`: inner scan with one `COALESCE(SUM(CASE WHEN account_id IN (...) THEN <normalised amount>
   END), 0) AS set_<name>` per distinct set, `WHERE posting_date >= :from AND posting_date < :to_exclusive` plus
   dimension filters, `GROUP BY <grain buckets>`; outer `SELECT` applies the metric arithmetic (ratios through
   `NULLIF`) and `ORDER BY` the grain. For `cumulative` requests the scan lower bound is widened to the start of the
   earliest window, every set column becomes `SUM(set_x) OVER (PARTITION BY <window key>, <dimensions> ORDER BY
   <grain>)`, the arithmetic is applied **after** the window (a YTD ratio is the ratio of YTD sums), and an outer
   filter drops rows before the requested `from`. A **self-check pass** re-parses the rendered SQL with sqlglot and
   asserts it references only the declared journal table and declared columns before anything is returned
   (codex S3). Output: `CompiledMetricQuery(sql, dialect, sql_hash, model_hash, lineage, assertions)`.
4. **Execute** — `DatabaseRunner` hands `compiled.sql` to the existing `SQLToolkit.execute_query()` (no toolkit
   change); `DuckDBRunner` registers Arrow tables on a root `duckdb` connection and executes on a per-thread cursor
   inside `asyncio.to_thread`. Both return an Arrow table plus the compiled metadata.
5. **Audit** — every executed query appends a signed `AccountingAuditEntry` (core signers; `storage(json_str)`
   contract). `FINANCE_AUDIT_MODE=required` (default) fails closed: if the durable append fails, the result is not
   returned (codex S9).
6. **Expose** — `AccountingToolkit` (`tool_prefix = "finance"`): `finance_list_metrics`, `finance_explain_metric`,
   `finance_query_metric`, `finance_validate_model`; served over MCP through the existing `parrot mcp-local`
   toolkit server; `parrot finance validate` CLI; a scheduled live validation registered by `ai-parrot-server`.

Resolved brainstorm decisions reflected in this design:

| Decision (brainstorm §Open Questions) | Where it lands |
|---|---|
| Home: `parrot.semantic.accounting`, standalone, satellite skeleton created here without sidemantic | M1, §7 |
| Models in git: `<models_dir>/<tenant>/<model>.yaml` | M4 loader, `FINANCE_MODELS_DIR` |
| Refuse requests spanning a membership change (incl. cumulative windows) | M4 interval partition + M5 `PeriodSpansMembershipChange` |
| Explicit required sign key, no default (refined by codex S4 into `amount_convention`) | §2 Data Models, M4 |
| `parent:` selectors v2 | Non-Goals |
| Natural calendar + YTD/QTD/MTD in v1 | M5 cumulative windows |
| Live assertions on demand **and** scheduled | M8 CLI, M9 scheduler adapter |
| Own signed `AccountingAuditEntry` + `lineage_ref`, lineage never inline | M7 |
| Lowering deferred | Non-Goals |

### Component Diagram

```
<models_dir>/<tenant>/<model>.yaml ──┐
                                     ▼
            ChartSnapshot ──► loader.load_model() ──► AccountingModel (frozen, model_hash)
     (SQLToolkit introspection │                              │
      or Arrow table)          │        grammar.parse_expr()  │
                               │                              ▼
   MetricRequest ──────────────┴──────────► compiler.compile() ──► CompiledMetricQuery
                                                                   (sql, sql_hash, lineage, assertions)
                                              ┌───────────────────────┴───────────────────────┐
                                              ▼                                               ▼
                               runtime.DatabaseRunner                              runtime.DuckDBRunner
                               (SQLToolkit.execute_query)                     (Arrow register + per-thread cursor)
                                              └───────────────────────┬───────────────────────┘
                                                                      ▼
                                                      audit.AccountingAuditLedger (signed; fail-closed)
                                                                      ▼
                   AccountingToolkit (finance_*) ──► MCP (parrot mcp-local finance) · CLI (parrot finance) · scheduler job
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `SQLToolkit.execute_query(query, limit, timeout)` (`sql.py:297`) | uses | `DatabaseRunner` passes the rendered SQL string; no signature change. `RetryContext` return ⇒ `AccountingExecutionError`. |
| `SQLToolkit.database_type` (`toolkits/base.py:139`) + `SQLGLOT_DIALECT_MAP` (`knowledge/common/sql_dialects.py:6`) | uses | resolves the sqlglot dialect for rendering. |
| `SQLToolkit.describe_table()` / `TableMetadata` (`knowledge/wiki/schema/table_metadata.py:31`) | uses | pre-compile check that `account_key`, `amount`/`debit`/`credit`, `posting_date`, dimension columns exist and are exact numeric where required. |
| `DatasetPolicyGuard.filter_datasets()` / `can_read_dataset()` (`auth/dataset_guard.py:128,278`) + `_pctx_var` (`auth/context.py:33`) | uses | metric visibility; resource names `accounting:<tenant>:<model>:<metric>`. No DatasetManager change (codex S7). |
| `DatasetManager` | **not modified** | frames reach the DuckDB runner through an injected `frame_provider` callable; the server wires it to a `DatasetManager` instance. |
| `parrot.security.audit_ledger` signers (`:135,166,199`) | uses | `AccountingAuditLedger` reuses `AbstractKMSSigner` and the `storage(json_str)` contract; `AuditLedgerEntry` untouched. |
| `parrot.cli` `LazyGroup._lazy_commands` (`cli/__init__.py:109-139`) | extends | `"finance": "parrot.semantic.accounting.cli"` + `_lazy_extras` hint. |
| `parrot mcp-local` toolkit server (`mcp/toolkit_server.py:137`, `.parrot/mcp-toolkits.yaml`) | config only | `finance:` section pointing at `parrot.semantic.accounting.toolkit.AccountingToolkit`. |
| `SchedulerManager.register_object_schedules()` (`scheduler/base.py:798`) + `@schedule` (`scheduler/manager.py:50`) | extends (server) | `accounting_jobs.py` adapter in `ai-parrot-server` registers the daily live validation. |
| root `pyproject.toml` `[tool.uv.sources]` (`:229-240`), `scripts/release.py` `PACKAGES` (`:116-187`), `.github/workflows/ci.yml`, `nightly-tests.yml:40` | extends | new workspace member, release entry, CI job. |
| FEAT-704 (`origin/feat-FEAT-704-semantic-layer`, paused) | coordinates | the skeleton mirrors its M1; its `parrot.semantic.models.CompiledQuery` name is reserved, hence `CompiledMetricQuery` here. |

### Data Models

```python
# packages/ai-parrot-semantic/src/parrot/semantic/accounting/models.py  (new) — all frozen Pydantic v2
from typing import Literal, Annotated
from decimal import Decimal
from datetime import date
from pydantic import BaseModel, ConfigDict, Field, model_validator

AmountConvention = Literal["debit_positive", "credit_positive", "debit_credit_columns", "natural_balance"]
Nature = Literal["debit", "credit"]
Grain = Literal["day", "week", "month", "quarter", "year"]
Cumulative = Literal["mtd", "qtd", "ytd"]

class JournalSource(BaseModel, frozen=True):
    table: str | None = None            # "schema.table"  — XOR dataframe
    dataframe: str | None = None        # catalog name resolved by frame_provider

class ChartOfAccounts(BaseModel, frozen=True):
    source: JournalSource
    account_key: str
    posting_date: str
    amount_convention: AmountConvention            # REQUIRED, no default (brainstorm resolution + codex S4)
    amount: str | None = None                      # required unless debit_credit_columns
    debit: str | None = None                       # required with debit_credit_columns
    credit: str | None = None
    nature: NatureSpec | None = None               # from_column | per-account map; required unless natural_balance
    dimensions: tuple[str, ...] = ()
    allow_float: bool = False                      # float amounts ⇒ validation error unless true (then CAST DECIMAL(38,6))

class NatureSpec(BaseModel, frozen=True):
    from_column: str | None = None
    accounts: dict[str, Nature] | None = None      # XOR from_column

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

class Metric(BaseModel, frozen=True):
    expr: str
    description: str = ""
    dimensions: tuple[str, ...] | None = None      # None ⇒ all chart dimensions
    unit: str | None = None

class Assertion(BaseModel, frozen=True):
    expr: str                                      # "<expr> == <expr>"
    tolerance: Decimal = Decimal("0")
    on_failure: Literal["flag", "block"] = "flag"  # codex S10

class Exclusion(BaseModel, frozen=True):
    accounts: tuple[str, ...]
    reason: str

class AccountingModelSpec(BaseModel, frozen=True):          # the YAML as written
    model: str
    version: str
    tenant: str
    chart_of_accounts: ChartOfAccounts
    sets: dict[str, AccountSet]
    metrics: dict[str, Metric]
    assertions: tuple[Assertion, ...] = ()
    excluded: tuple[Exclusion, ...] = ()

class ChartAccount(BaseModel, frozen=True):
    account_id: str
    nature: Nature | None
    parent_id: str | None = None
    tags: tuple[str, ...] = ()

class ChartSnapshot(BaseModel, frozen=True):                # immutable account master (codex S1)
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
    intervals: tuple[tuple[date | None, date | None], ...]  # membership partition (codex S5)
    sets: dict[str, ResolvedSet]
    model_hash: str

class Period(BaseModel, frozen=True):
    from_: date = Field(alias="from")
    to: date                                                # inclusive
    cumulative: Cumulative | None = None

class MetricRequest(BaseModel, frozen=True):
    metric: str
    grain: Grain | None = None                              # None ⇒ one row per dimension combination
    dimensions: tuple[str, ...] = ()
    filters: dict[str, str | int | tuple[str | int, ...]] = {}   # equality / IN on declared dimensions only
    period: Period
    @model_validator(mode="after")
    def _cumulative_fits_grain(self): ...                   # mtd needs grain ≤ month, qtd ≤ quarter, ytd ≤ year

class Lineage(BaseModel, frozen=True):
    metric: str
    formula: str                                            # fully inlined expression
    sets: tuple[ResolvedSet, ...]
    assertions: tuple[str, ...]                             # assertion exprs touching this metric
    warnings: tuple[str, ...] = ()                          # "division_by_zero_possible", "float_cast", "chart_drift"

class CompiledMetricQuery(BaseModel, frozen=True):          # NOT `CompiledQuery` — reserved by FEAT-704
    sql: str
    dialect: str
    sql_hash: str                                           # sha256(dialect + "\n" + sql)
    model_hash: str
    request: MetricRequest
    lineage: Lineage
    assertions: tuple["CompiledMetricQuery", ...] = ()

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

class AccountingAuditEntry(BaseModel):                      # audit.py — signed, versioned (codex S9)
    schema_version: Literal[1] = 1
    entry_id: str
    tenant: str
    subject_digest: str                                     # sha256 of PermissionContext identity, never the identity
    model: str
    version: str
    model_hash: str
    snapshot_hash: str
    sql_hash: str
    dialect: str
    target: Literal["database", "duckdb"]
    request_canonical: str                                  # canonical JSON of MetricRequest
    lineage_ref: str                                        # f"{model_hash}:{sql_hash}" — lineage is rebuilt, never stored
    assertion_status: Literal["passed", "failed", "skipped", "none"]
    row_count: int
    signature: str = ""
    created_at: datetime
    def canonical_bytes(self) -> bytes: ...                 # sorted-key JSON without signature
```

Sign normalisation (`amount_convention`), applied inside the `CASE` so every account is **positive in its natural
balance** (revenue positive, expenses positive; metrics subtract):

| convention | source shape | normalised amount |
|---|---|---|
| `debit_positive` | one `amount` column, debits > 0 | `amount` if nature = debit else `-amount` |
| `credit_positive` | one `amount` column, credits > 0 | `amount` if nature = credit else `-amount` |
| `debit_credit_columns` | two columns `debit`, `credit` | `debit - credit` if nature = debit else `credit - debit` |
| `natural_balance` | `amount` already in natural-balance sign | `amount` (nature optional) |

### New Public Interfaces

```python
# parrot.semantic.accounting  (public surface)
from parrot.semantic.accounting import (
    load_model, parse_expr, compile_metric,                 # loader / grammar / compiler
    AccountingModel, MetricRequest, CompiledMetricQuery, Lineage, MetricResult,
    DuckDBRunner, DatabaseRunner, AccountingAuditLedger, AccountingToolkit,
    AccountingError, ModelValidationError, GrammarError, RequestValidationError,
    PeriodSpansMembershipChange, AccountingExecutionError, AccountingAuditError,
)
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Satellite skeleton | yes | mirror of `origin/feat-FEAT-704-semantic-layer:packages/ai-parrot-semantic/{pyproject.toml,src/parrot/semantic/version.py}` minus sidemantic/jsonschema; anchors in §6 | — |
| M2: Contracts & errors | yes | Pydantic models above; error hierarchy fixed in M2 skeleton | — |
| M3: Grammar | yes | grammar fixed in §2; AST node set closed; `GrammarError(position)` | — |
| M4: Loader, snapshot, validation | no | interval partition + completeness semantics are the core invariant; the thinking model owns them | invariant design |
| M5: Compiler + golden tests | no | AST shape, cumulative windows and the self-check allowlist define the determinism contract | determinism design |
| M6: Runtimes (DuckDB, Database) | yes | Arrow registration + per-thread cursor pattern fixed; `execute_query` contract verified | — |
| M7: Audit ledger | yes | entry fields fixed above; `canonical_bytes` = sorted-key JSON without `signature`; fail-closed default | — |
| M8: Toolkit, MCP config, CLI | yes (after M4–M7) | tool names, PBAC resource naming, CLI anchors fixed | — |
| M9: Scheduled validation adapter | yes | `@schedule` + `register_object_schedules` verified; call site anchor marked unverified in §6 | — |
| M10: Docs | yes | `docs/semantic/accounting-metrics-layer.md` | — |

### Module 1: `ai-parrot-semantic` distribution skeleton (sidemantic-free)
- **Path**: `packages/ai-parrot-semantic/pyproject.toml`, `README.md`, `src/parrot/semantic/__init__.py`,
  `src/parrot/semantic/version.py`, `src/parrot/semantic/accounting/__init__.py`, `tests/__init__.py`,
  `tests/conftest.py`; MODIFY root `pyproject.toml`, `scripts/release.py`, `.github/workflows/ci.yml`,
  `.github/workflows/nightly-tests.yml`
- **Responsibility**: make `parrot.semantic` an installable PEP 420 satellite (`src/parrot/` has **no**
  `__init__.py`). `pyproject.toml` is the FEAT-704 branch file with `sidemantic` and `jsonschema` removed from
  `dependencies` and `bigquery` extra dropped; `version.py` is byte-identical to the FEAT-704 branch file;
  `__init__.py` exports only `__version__`; README carries a **Layering** section: "`parrot.semantic.accounting` is
  standalone; FEAT-704 adds the governed generic layer on top and must not be imported by it". Workspace source
  entry, `release.py` `PACKAGES` entry identical to FEAT-704's, CI job `test-semantic` patterned on `test-loaders`,
  nightly matrix entry.
- **Depends on**: nothing (first task).
- **Interface Skeleton**:
  ```toml
  # packages/ai-parrot-semantic/pyproject.toml  (new — mirror of origin/feat-FEAT-704-semantic-layer minus sidemantic)
  [project]
  name = "ai-parrot-semantic"
  dynamic = ["version"]
  description = "Semantic layers for AI-Parrot agents (accounting metrics; governed generic layer when FEAT-704 lands)"
  requires-python = ">=3.11,<3.14"
  license = "MIT"
  dependencies = ["ai-parrot", "sqlglot>=30.1,<31", "pyyaml>=6"]
  [project.optional-dependencies]
  duckdb = ["duckdb>=1.0"]
  [tool.setuptools.dynamic]
  version = {attr = "parrot.semantic.version.__version__"}
  [tool.setuptools.packages.find]
  where = ["src"]; include = ["parrot*"]; namespaces = true
  [tool.uv.sources]
  ai-parrot = { workspace = true }
  ```
  ```python
  # packages/ai-parrot-semantic/src/parrot/semantic/version.py  (new — identical to the FEAT-704 branch file)
  __title__ = "ai-parrot-semantic"; __version__ = "1.3.0"; __license__ = "MIT"  # + description/author fields

  # packages/ai-parrot-semantic/src/parrot/semantic/__init__.py  (new)
  """ai-parrot-semantic — semantic layers for AI-Parrot agents."""
  from .version import __version__
  __all__ = ["__version__"]
  ```
  ```toml
  # pyproject.toml  (modifies pyproject.toml:240 — append after `navrules = { workspace = true }`)
  ai-parrot-semantic = { workspace = true }
  ```
  ```python
  # scripts/release.py  (modifies scripts/release.py:186 — new Package entry before the closing `]` at :187)
  Package("ai-parrot-semantic",
          [("packages/ai-parrot-semantic/src/parrot/semantic/version.py", "python")],
          "packages/ai-parrot-semantic", aliases=["semantic"]),
  ```
  ```yaml
  # .github/workflows/ci.yml  (modifies — new job `test-semantic` appended after `test-loaders` :508-539, same steps:
  #   uv sync --package ai-parrot-semantic --extra duckdb; scaffold NavConfig; uv run pytest packages/ai-parrot-semantic/tests -q)
  # .github/workflows/nightly-tests.yml  (modifies :40 — add `- ai-parrot-semantic` to the matrix)
  ```

### Module 2: Contracts & error taxonomy
- **Path**: `packages/ai-parrot-semantic/src/parrot/semantic/accounting/models.py`, `errors.py`
- **Responsibility**: the frozen Pydantic models of §2 Data Models and the exception hierarchy. Validators:
  `JournalSource` table XOR dataframe; `amount_convention` ⇒ required columns (`amount` vs `debit`+`credit`) and
  `nature` required unless `natural_balance`; `nature.from_column` XOR `nature.accounts`; `AccountSet` has
  `accounts` or `select` (not neither); `valid_from < valid_to`; `MetricRequest.cumulative` fits `grain`;
  `Period.from_ <= Period.to`; filters only on declared dimensions (checked by M4 against the model).
- **Depends on**: M1.
- **Interface Skeleton**:
  ```python
  # parrot/semantic/accounting/errors.py  (new)
  class AccountingError(Exception): """Base of every accounting-layer error."""
  class ModelValidationError(AccountingError):
      """Model failed load-time validation. `problems: list[Problem]` carries EVERY problem, never only the first."""
      problems: list["Problem"]
  class Problem(BaseModel, frozen=True):
      code: Literal["unassigned_account", "empty_set", "overlap", "dangling_ref", "cycle", "nature_missing",
                    "nature_ambiguous", "float_amount", "column_missing", "interval_gap", "selector_no_match"]
      message: str; interval: tuple[date | None, date | None] | None = None; accounts: tuple[str, ...] = ()
  class GrammarError(AccountingError): """Expression syntax error; `position: int`."""
  class RequestValidationError(AccountingError): """Unknown metric/dimension/filter, cumulative/grain mismatch."""
  class PeriodSpansMembershipChange(RequestValidationError):
      """Requested period or cumulative window crosses a membership boundary; `boundary: date`, `suggestion: str`."""
  class AccountingExecutionError(AccountingError): """Runner failed; `audit_id` set when the attempt was audited."""
  class AccountingAuditError(AccountingError): """Durable audit append failed under FINANCE_AUDIT_MODE=required."""
  class DataFrameConversionError(AccountingError): """pandas/polars → Arrow conversion failed (object dtypes, floats)."""
  ```

### Module 3: Metric expression grammar
- **Path**: `packages/ai-parrot-semantic/src/parrot/semantic/accounting/grammar.py`
- **Responsibility**: tokenizer + Pratt parser for
  `expr := term (("+"|"-") term)* ; term := factor (("*"|"/") factor)* ; factor := "sum" "(" SET ")" | METRIC | NUMBER | "(" expr ")" | "-" factor`.
  Also `==` at the top level for assertions (`parse_assertion`). Produces a closed AST; `references(ast)` returns the
  set and metric names it uses.
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

### Module 4: Loader, chart snapshot and validation
- **Path**: `packages/ai-parrot-semantic/src/parrot/semantic/accounting/loader.py`, `snapshot.py`, `validation.py`
- **Responsibility**: `snapshot.py` builds a `ChartSnapshot` from (a) an account-master table through
  `SQLToolkit.execute_query`, (b) an Arrow table (DataFrame path), or (c) a YAML/CSV manifest file — the model's
  `chart_of_accounts.nature` and tags come from it. `loader.py` reads the YAML (`yaml.safe_load`), builds
  `AccountingModelSpec`, resolves selectors against the snapshot, builds the **interval partition** from every
  `valid_from`/`valid_to`, materialises `ResolvedSet`s, and runs `validation.validate(spec, resolved, snapshot)`
  which returns **all** problems: per interval — unassigned accounts (not in any valid set nor `excluded`),
  overlaps outside `allow_overlap`, empty sets; globally — dangling refs, cycles (topological sort over metric
  references), selectors matching nothing, nature missing (`by_*` conventions) or ambiguous (`natural_balance`
  with a nature map), float amount columns (`allow_float=False`), missing columns (`TableMetadata.columns`).
  `model_hash = sha256(canonical JSON(resolved model) + snapshot_hash)`. `detect_drift(model, fresh_snapshot)`
  returns accounts present in the fresh snapshot but unassigned in the loaded model.
- **Depends on**: M2, M3.
- **Interface Skeleton**:
  ```python
  # parrot/semantic/accounting/snapshot.py  (new)
  async def snapshot_from_toolkit(toolkit: "SQLToolkit", *, table: str, account_key: str, nature_column: str | None,
                                  parent_column: str | None = None, tags_column: str | None = None) -> ChartSnapshot:
      """SELECT DISTINCT account master rows via SQLToolkit.execute_query (verified: sql.py:297); sorted; hashed."""
  def snapshot_from_arrow(table: "pa.Table", *, account_key: str, nature_column: str | None, ...) -> ChartSnapshot: ...
  def snapshot_from_manifest(path: Path) -> ChartSnapshot:
      """YAML/CSV manifest: account_id, nature, parent_id, tags."""

  # parrot/semantic/accounting/loader.py  (new)
  def load_spec(source: Path | dict) -> AccountingModelSpec:
      """yaml.safe_load + Pydantic; raise ModelValidationError(problems) on schema errors."""
  def load_model(source: Path | dict, snapshot: ChartSnapshot) -> AccountingModel:
      """Resolve selectors, partition intervals, validate (ALL problems), hash. Raises ModelValidationError."""
  def canonical_json(obj: BaseModel) -> str:
      """Sorted keys, no whitespace, Decimals as strings — the hashing representation."""
  def detect_drift(model: AccountingModel, fresh: ChartSnapshot) -> tuple[str, ...]: ...

  # parrot/semantic/accounting/validation.py  (new)
  def partition_intervals(sets: Mapping[str, AccountSet]) -> tuple[tuple[date | None, date | None], ...]: ...
  def validate(spec: AccountingModelSpec, resolved: Mapping[str, ResolvedSet], snapshot: ChartSnapshot,
               columns: Mapping[str, str] | None) -> list[Problem]:
      """Every invariant listed in Module 4; never stops at the first problem."""
  def metric_order(spec: AccountingModelSpec) -> tuple[str, ...]:
      """Topological order of metrics; raises on cycle via Problem(code='cycle')."""
  ```

### Module 5: Compiler (sqlglot AST, cumulative windows, hashing, lineage, self-check) + golden tests
- **Path**: `packages/ai-parrot-semantic/src/parrot/semantic/accounting/compiler.py`,
  `packages/ai-parrot-semantic/tests/accounting/golden/{duckdb,postgres,bigquery}/*.sql`
- **Responsibility**: `compile_metric(model, request, dialect)`; request validation against the model (metric
  exists, dimensions ⊆ metric dimensions, filters on declared dimensions, period inside one membership interval —
  including the widened cumulative window — else `PeriodSpansMembershipChange(boundary, suggestion)`); inline
  metric refs via `metric_order`; dedupe sets; build the inner/outer `exp.Select` described in §2 Overview
  (`exp.DateTrunc` for grain buckets; `COALESCE(SUM(CASE …), 0)` per set; `NULLIF` denominators; window
  `SUM(...) OVER (PARTITION BY DATE_TRUNC(<window>, bucket), <dims> ORDER BY bucket)` for cumulative; literal
  `IN` lists sorted; aliases `set_<name>` / `m_<metric>`); render with `expression.sql(dialect=dialect, pretty=False)`;
  **self-check**: re-parse the rendered SQL, collect tables/columns with `sqlglot`, assert ⊆ {journal table} ×
  declared columns; `sql_hash = sha256(dialect + "\n" + sql)`. Assertions compile to the same shape with both sides
  as columns. Golden files are the review artifact for any sqlglot bump.
- **Depends on**: M2, M3, M4.
- **Interface Skeleton**:
  ```python
  # parrot/semantic/accounting/compiler.py  (new)
  def compile_metric(model: AccountingModel, request: MetricRequest, dialect: str) -> CompiledMetricQuery:
      """Deterministic: same (model_hash, canonical request, dialect) ⇒ byte-identical sql. Raises RequestValidationError /
      PeriodSpansMembershipChange. Never returns SQL that fails the self-check."""
  def compile_assertion(model: AccountingModel, assertion: Assertion, period: Period, dialect: str) -> CompiledMetricQuery: ...
  def build_ast(model: AccountingModel, request: MetricRequest) -> "exp.Select":
      """Dialect-agnostic sqlglot expression (inner scan + outer arithmetic [+ window]); exposed for golden tests."""
  def self_check(sql: str, dialect: str, *, table: str, columns: frozenset[str]) -> None:
      """Re-parse and assert referenced tables/columns ⊆ declared; raise AccountingError otherwise (codex S3)."""
  def sql_dialect_for(toolkit_database_type: str) -> str:
      """SQLGLOT_DIALECT_MAP lookup (verified: knowledge/common/sql_dialects.py:6); 'duckdb' passthrough."""
  def canonical_request(request: MetricRequest) -> str: ...
  ```

### Module 6: Runtimes — DuckDB over Arrow, and SQLToolkit
- **Path**: `packages/ai-parrot-semantic/src/parrot/semantic/accounting/runtime/__init__.py`, `runtime/duckdb.py`,
  `runtime/database.py`, `runtime/arrow.py`
- **Responsibility**: `arrow.py` converts pandas (`pyarrow.Table.from_pandas`, `preserve_index=False`) and polars
  (`df.to_arrow()`) to Arrow, raising `DataFrameConversionError` on object-dtype amount columns or floats when
  `allow_float=False`; the amount column is cast to `decimal128(38, 6)` when `allow_float=True`. `duckdb.py` owns one
  root `duckdb.connect()` (in-memory), registers Arrow tables with `con.register(name, table)`, executes on
  `root.cursor()` inside `asyncio.to_thread`, bounded by a semaphore of `FINANCE_DUCKDB_THREADS` (default 4),
  returns `pa.Table` via `.fetch_arrow_table()`; `duckdb` is imported lazily through `parrot._imports.require_extra`
  so the package imports without the extra. `database.py` maps `toolkit.database_type` → dialect, calls
  `toolkit.execute_query(sql, limit=FINANCE_RESULT_LIMIT, timeout=...)`, converts the rows to Arrow; a `RetryContext`
  return ⇒ `AccountingExecutionError`.
- **Depends on**: M2, M5.
- **Interface Skeleton**:
  ```python
  # parrot/semantic/accounting/runtime/arrow.py  (new)
  def to_arrow(frame: "pd.DataFrame | pl.DataFrame", *, amount_columns: tuple[str, ...], allow_float: bool) -> "pa.Table": ...

  # parrot/semantic/accounting/runtime/duckdb.py  (new)
  class DuckDBRunner:
      """One root connection; per-thread cursors; never shares a cursor across threads."""
      def __init__(self, *, threads: int = 4) -> None: ...          # require_extra("duckdb", "duckdb")  verified: _imports.py:248
      async def execute(self, compiled: CompiledMetricQuery, frames: Mapping[str, "pa.Table"]) -> "pa.Table":
          """Register *frames* under their catalog names, run compiled.sql (dialect must be 'duckdb'), return Arrow."""
      async def close(self) -> None: ...

  # parrot/semantic/accounting/runtime/database.py  (new)
  class DatabaseRunner:
      """Executes through the existing SQLToolkit path — no toolkit modification."""
      def __init__(self, toolkit: "SQLToolkit", *, limit: int = 10_000, timeout: int = 60) -> None: ...
      @property
      def dialect(self) -> str: """sql_dialect_for(toolkit.database_type)  # verified: toolkits/base.py:139"""
      async def execute(self, compiled: CompiledMetricQuery) -> "pa.Table":
          """toolkit.execute_query(compiled.sql, limit=..., timeout=...)  # verified: sql.py:297; RetryContext ⇒ AccountingExecutionError."""
  ```

### Module 7: Accounting audit ledger
- **Path**: `packages/ai-parrot-semantic/src/parrot/semantic/accounting/audit.py`
- **Responsibility**: `AccountingAuditEntry` (fields in §2) and `AccountingAuditLedger(signer, storage, mode)`.
  `append()` builds the entry, signs `canonical_bytes()` with the core `AbstractKMSSigner`, awaits
  `storage(entry.model_dump_json())`; with `mode="required"` (default from `FINANCE_AUDIT_MODE`) a storage failure
  raises `AccountingAuditError` and the caller does not return the result; `mode="best_effort"` logs and continues.
  `lineage_ref = f"{model_hash}:{sql_hash}"`; `rebuild_lineage(ledger_entry, model)` recompiles and returns the
  `Lineage` for an audited entry. No in-memory retention beyond the returned entry.
- **Depends on**: M2, M5.
- **Interface Skeleton**:
  ```python
  # parrot/semantic/accounting/audit.py  (new)
  class AccountingAuditLedger:
      def __init__(self, signer: "AbstractKMSSigner | None" = None,      # verified: security/audit_ledger.py:135
                   storage: "Callable[[str], Awaitable[None]] | None" = None,   # same contract as AuditLedger (:327-333, :387)
                   mode: Literal["required", "best_effort"] = "required") -> None:
          """signer defaults to LocalHMACSigner() (verified: audit_ledger.py:166)."""
      async def append(self, *, tenant: str, subject_digest: str, compiled: CompiledMetricQuery, target: str,
                       row_count: int, assertion_status: str) -> AccountingAuditEntry:
          """Sign + store; raise AccountingAuditError when storage fails under mode='required'."""
      async def verify(self, entry: AccountingAuditEntry) -> bool: ...
  def subject_digest(context: "PermissionContext | None") -> str:
      """sha256 of (user_id, tenant) or 'anonymous'; never the raw identity."""
  ```

### Module 8: `AccountingToolkit`, MCP exposure, CLI
- **Path**: `packages/ai-parrot-semantic/src/parrot/semantic/accounting/toolkit.py`, `catalog.py`, `cli.py`;
  MODIFY `packages/ai-parrot/src/parrot/cli/__init__.py` (`_lazy_commands`, `_lazy_extras`);
  `.parrot/mcp-toolkits.yaml` (documented example, not committed if the file is local)
- **Responsibility**: `catalog.py` — `ModelCatalog(models_dir)` loads every `<tenant>/<model>.yaml` with its
  snapshot source, keeps `AccountingModel`s keyed `(tenant, model)`, exposes `metrics()` and `reload()`.
  `toolkit.py` — `AccountingToolkit(AbstractToolkit)` with `tool_prefix = "finance"`, constructor kwargs
  `models_dir`, `database_toolkit: SQLToolkit | None`, `frame_provider: Callable[[str], Awaitable[pd.DataFrame]] | None`,
  `policy_guard: DatasetPolicyGuard | None`, `ledger: AccountingAuditLedger | None`, `duckdb_threads`. Tools:
  `list_metrics(tenant=None)`, `explain_metric(metric, tenant=None)` (formula tree, resolved accounts per set,
  covering assertions — plain text), `query_metric(metric, period_from, period_to, grain=None, dimensions=(),
  filters=None, cumulative=None, tenant=None) -> dict` (rows + lineage + sql_hash + audit_id + chart_drift),
  `validate_model(model, tenant=None, live=False) -> dict`. PBAC: `_pre_execute` reads `_pctx_var`; list filters
  through `policy_guard.filter_datasets(pctx, names)` with names `accounting:<tenant>:<model>:<metric>`; explain/query
  check `can_read_dataset`; no guard configured ⇒ allow (same semantics as `DatasetManager`). Tenant resolution:
  explicit `tenant` kwarg → `pctx.tenant` → toolkit default. `cli.py` — click group `finance` with
  `validate <path> [--live] [--models-dir]` and `explain <path> <metric>`; registered lazily in core CLI.
- **Depends on**: M4, M5, M6, M7.
- **Interface Skeleton**:
  ```python
  # parrot/semantic/accounting/toolkit.py  (new)
  class AccountingToolkit(AbstractToolkit):                          # AbstractToolkit verified: parrot/tools/toolkit.py (core)
      """Finance tools: the LLM picks metric + grain + filters + period; the compiler writes the SQL."""
      tool_prefix = "finance"
      def __init__(self, *, models_dir: Path | str | None = None, database_toolkit: "SQLToolkit | None" = None,
                   frame_provider: "Callable[[str], Awaitable[pd.DataFrame]] | None" = None,
                   policy_guard: "DatasetPolicyGuard | None" = None,          # verified: auth/dataset_guard.py:56
                   ledger: AccountingAuditLedger | None = None, duckdb_threads: int = 4, **kwargs) -> None: ...
      async def list_metrics(self, tenant: str | None = None) -> list[dict]:
          """Catalog of metrics visible to the caller (PBAC-filtered)."""
      async def explain_metric(self, metric: str, tenant: str | None = None) -> str:
          """Formula, resolved accounts per set, and covering assertions, as plain text."""
      async def query_metric(self, metric: str, period_from: str, period_to: str, grain: str | None = None,
                             dimensions: list[str] | None = None, filters: dict | None = None,
                             cumulative: str | None = None, tenant: str | None = None) -> dict:
          """Compile → execute (database or duckdb) → audit → return rows + lineage + sql_hash + audit_id."""
      async def validate_model(self, model: str, tenant: str | None = None, live: bool = False) -> dict:
          """Load-time problems, and with live=True assertion results for the last closed natural month + drift."""
      async def _pre_execute(self, tool_name: str, /, **kwargs) -> None:
          """PBAC per-call hook — mirrors DatasetManager._pre_execute (verified: dataset_manager/tool.py:2762)."""

  # parrot/semantic/accounting/cli.py  (new)
  @click.group("finance")
  def finance() -> None: """Accounting metrics layer commands."""
  @finance.command("validate")  # args: path; --live; --models-dir; --dsn (optional, for live snapshots)
  def validate(...) -> None: """Exit 1 on any Problem; prints the full problem list, grouped by interval."""
  ```
  ```python
  # packages/ai-parrot/src/parrot/cli/__init__.py  (modifies cli/__init__.py:138 — insert before the closing `}` of _lazy_commands at :139)
      "finance": "parrot.semantic.accounting.cli",
  # (modifies cli/__init__.py:143-… — add to _lazy_extras)
      "finance": "ai-parrot-semantic[duckdb]: pip install ai-parrot-semantic[duckdb]",
  ```
  ```yaml
  # .parrot/mcp-toolkits.yaml  (documented example — served by `parrot mcp-local finance`; verified: mcp/toolkit_config.py:130-133)
  finance:
    class: parrot.semantic.accounting.toolkit.AccountingToolkit
    kwargs: { models_dir: "./models" }
    env: { FINANCE_AUDIT_MODE: best_effort }
  ```

### Module 9: Scheduled live validation (server adapter)
- **Path**: `packages/ai-parrot-semantic/src/parrot/semantic/accounting/live.py`;
  `packages/ai-parrot-server/src/parrot/scheduler/accounting_jobs.py` (new)
- **Responsibility**: `live.py` — `run_live_validation(catalog, runners, ledger) -> LiveValidationReport`: for every
  model, take a fresh snapshot, `detect_drift`, compile and execute every assertion for the last closed natural
  month, append one audit entry per assertion, and mark the catalog entry `chart_drift` / `assertion_failed` so
  subsequent `query_metric` results carry the flags (a `block` assertion makes `query_metric` raise). The server
  adapter wraps it in an object with a `@schedule(ScheduleType.DAILY, ...)` method and registers it with
  `SchedulerManager.register_object_schedules(obj, "accounting")`; the satellite never imports the server.
- **Depends on**: M4, M5, M6, M7, M8 (`ModelCatalog`).
- **Interface Skeleton**:
  ```python
  # parrot/semantic/accounting/live.py  (new)
  class LiveValidationReport(BaseModel, frozen=True):
      models: tuple[ModelLiveStatus, ...]       # per model: drift accounts, assertion results, audit ids
  async def run_live_validation(catalog: ModelCatalog, *, database_toolkit: "SQLToolkit | None",
                                frame_provider=None, ledger: AccountingAuditLedger) -> LiveValidationReport: ...

  # packages/ai-parrot-server/src/parrot/scheduler/accounting_jobs.py  (new)
  from parrot.scheduler.manager import schedule            # verified: scheduler/manager.py:50
  from parrot.scheduler.base import ScheduleType, SchedulerManager   # verified: scheduler/base.py:90, :254
  class AccountingValidationJobs:
      def __init__(self, toolkit_factory: Callable[[], "AccountingToolkit"]) -> None: ...
      @schedule(ScheduleType.DAILY, hour=6, minute=0)
      async def validate_accounting_models(self) -> dict:
          """Lazy-imports parrot.semantic.accounting.live; returns the report as a dict for the scheduler result."""
  def register_accounting_schedules(scheduler: SchedulerManager, toolkit_factory) -> int:
      """scheduler.register_object_schedules(AccountingValidationJobs(factory), "accounting")  # verified: scheduler/base.py:798"""
  ```

### Module 10: Documentation
- **Path**: `docs/semantic/accounting-metrics-layer.md`, `packages/ai-parrot-semantic/README.md` (sections)
- **Responsibility**: model YAML reference (every key, the `amount_convention` table, selectors, intervals),
  the request contract, cumulative-period semantics, determinism/golden-test policy, audit entry fields and
  `lineage_ref` rebuild, MCP/CLI/scheduler wiring, and the FEAT-704 layering contract.
- **Depends on**: M8, M9.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_version_and_namespace` | M1 | `import parrot.semantic.accounting` works; `src/parrot/__init__.py` absent; `parrot.embeddings` still importable alongside |
| `test_amount_convention_required` | M2 | missing `amount_convention` ⇒ validation error; each convention enforces its columns/nature rules |
| `test_request_cumulative_fits_grain` | M2 | `mtd`+`quarter` rejected; `ytd`+`month` accepted |
| `test_grammar_accepts_closed_language` | M3 | every production parses; AST equality |
| `test_grammar_rejects_everything_else` | M3 | `if`, function names, strings, `%`, inline SQL ⇒ `GrammarError` with position |
| `test_partition_intervals` | M4 | boundaries from `valid_from`/`valid_to` produce the expected half-open intervals |
| `test_completeness_per_interval` | M4 | account covered only after `valid_from` ⇒ `interval_gap` problem for the earlier interval (codex S5) |
| `test_overlap_and_allow_overlap` | M4 | shared account ⇒ `overlap` unless both sets list each other |
| `test_all_problems_reported` | M4 | a model with 5 defects raises one error listing 5 problems |
| `test_cycle_and_dangling` | M4 | `a = b + 1, b = a` ⇒ cycle; `sum(nope)` ⇒ dangling |
| `test_float_amount_rejected_unless_allowed` | M4 | float column ⇒ `float_amount`; `allow_float` ⇒ accepted with `float_cast` warning |
| `test_model_hash_changes_with_snapshot` | M4 | same YAML, extra account in snapshot ⇒ different `model_hash` (codex S1) |
| `test_compile_deterministic` | M5 | 50 compiles ⇒ one distinct `sql_hash`; `IN` lists sorted |
| `test_compile_golden_<dialect>` | M5 | rendered SQL equals `golden/<dialect>/*.sql` for duckdb, postgres, bigquery |
| `test_sign_normalisation_per_convention` | M5 | the four conventions emit the expected `CASE` arms |
| `test_cumulative_window_shape` | M5 | ytd: widened lower bound, window partition by year, outer `from` filter, arithmetic after window |
| `test_refuse_membership_change` | M5 | period (and ytd window) crossing `valid_from` ⇒ `PeriodSpansMembershipChange` naming the boundary |
| `test_self_check_rejects_foreign_columns` | M5 | a tampered AST referencing an undeclared column fails `self_check` (codex S3) |
| `test_nullif_and_coalesce` | M5 | empty group ⇒ 0 per set; zero denominator ⇒ NULL + warning (codex S6) |
| `test_arrow_conversion` | M6 | pandas + polars frames ⇒ Arrow; object amount dtype ⇒ `DataFrameConversionError` |
| `test_duckdb_runner_threads` | M6 | 8 concurrent executes on one runner, per-thread cursors, identical results |
| `test_database_runner_uses_execute_query` | M6 | fake `SQLToolkit` records `execute_query(sql, limit, timeout)`; `RetryContext` ⇒ `AccountingExecutionError` |
| `test_audit_entry_signed_and_verifiable` | M7 | `LocalHMACSigner`; `verify` true; tamper ⇒ false |
| `test_audit_required_fails_closed` | M7 | storage raises ⇒ `AccountingAuditError`; `best_effort` ⇒ entry returned (codex S9) |
| `test_toolkit_tools_and_prefix` | M8 | `get_tools()` names are exactly the four `finance_*` tools |
| `test_toolkit_pbac_filtering` | M8 | guard allowing one metric ⇒ `list_metrics` shows one; `query_metric` on another ⇒ `AuthorizationRequired` |
| `test_cli_validate_exit_codes` | M8 | `parrot finance validate` exits 1 with problems, 0 clean; lazy command registered |
| `test_live_validation_flags` | M9 | failed `flag` assertion ⇒ `assertion_failed` on results; `block` ⇒ `query_metric` raises |

### Integration Tests

| Test | Description |
|---|---|
| `test_e2e_duckdb_pnl` | 10k-row synthetic journal with mixed natures, `troc_pnl`-shaped model: revenue/gross_margin/ebitda by month equal hand-computed Decimals; assertions pass |
| `test_e2e_duckdb_cumulative` | ytd/qtd/mtd rows equal cumulative sums of the monthly rows; ytd ratio equals ratio of ytd sums |
| `test_e2e_postgres_parity` | same model against Postgres (`PARROT_TEST_PG_DSN`, skipped when unset): rows equal DuckDB rows |
| `test_e2e_audit_trail` | every `query_metric` produces one verifiable entry whose `lineage_ref` rebuilds the same `Lineage` |

### Validation Contract

tests:
- packages/ai-parrot-semantic/tests/accounting/test_models.py
- packages/ai-parrot-semantic/tests/accounting/test_grammar.py
- packages/ai-parrot-semantic/tests/accounting/test_loader_validation.py
- packages/ai-parrot-semantic/tests/accounting/test_compiler.py
- packages/ai-parrot-semantic/tests/accounting/test_golden.py
- packages/ai-parrot-semantic/tests/accounting/test_runtime.py
- packages/ai-parrot-semantic/tests/accounting/test_audit.py
- packages/ai-parrot-semantic/tests/accounting/test_toolkit.py
- packages/ai-parrot-semantic/tests/accounting/test_e2e_duckdb.py
- packages/ai-parrot-server/tests/scheduler/test_accounting_jobs.py
markers: none

### Test Data / Fixtures

```python
# packages/ai-parrot-semantic/tests/conftest.py
@pytest.fixture
def chart_snapshot() -> ChartSnapshot:
    """40 accounts: 4xxx credit (revenue, 4900 returns), 5xxx debit (cogs, 5900 excluded-from-cogs), 6xxx debit (opex),
    6810/6820 d&a valid_from 2025-01-01, 9999 suspense (excluded)."""

@pytest.fixture
def troc_pnl_yaml(tmp_path) -> Path:
    """The brainstorm's troc_pnl model with amount_convention: debit_positive and nature from_column."""

@pytest.fixture
def journal_frame() -> "pa.Table":
    """10k postings 2025-01..2026-09, Decimal(18,2) amounts, dimensions entity/product_line/cost_center, both natures,
    reversals, one empty month."""

@pytest.fixture
def recording_storage() -> tuple[Callable[[str], Awaitable[None]], list[str]]: ...
```

---

## 5. Acceptance Criteria

- [ ] AC1 `ai-parrot-semantic` installs as a PEP 420 satellite (no `src/parrot/__init__.py`), `import parrot.semantic.accounting` works with and without the `duckdb` extra, and no module under it imports `sidemantic`, `parrot.semantic.*` outside `accounting`, or anything from `ai-parrot-server`.
- [ ] AC2 `version.py` and the `release.py` entry are identical to `origin/feat-FEAT-704-semantic-layer`'s; the FEAT-704 layering note is in the README.
- [ ] AC3 A model without `amount_convention` does not load; each of the four conventions renders the documented normalisation, proven by golden SQL and by DuckDB execution on the fixture.
- [ ] AC4 `load_model` reports **every** problem in one `ModelValidationError`; completeness, overlap and exclusions are checked **per membership interval**; a model with an unassigned account in any interval does not load.
- [ ] AC5 `model_hash` covers the resolved model and the chart snapshot; `sql_hash` covers dialect + SQL; 50 compiles of the same input yield one hash; golden files exist for duckdb, postgres and bigquery and are byte-identical to the renderer output.
- [ ] AC6 The grammar accepts exactly `sum(set)`, `+ − × ÷`, unary minus, parentheses, metric references and `==` for assertions; everything else raises `GrammarError` with a position.
- [ ] AC7 Requests (including the widened cumulative window) that cross a membership boundary are refused with `PeriodSpansMembershipChange` naming the boundary and a split suggestion; no SQL is produced.
- [ ] AC8 `cumulative: mtd|qtd|ytd` returns running totals over the natural calendar; a cumulative ratio equals the ratio of cumulative sums; the request validator rejects a cumulative window finer than the grain.
- [ ] AC9 Empty groups yield 0 per set; zero denominators yield NULL plus a lineage warning; amounts are exact numeric end to end (Decimal in results; float columns rejected unless `allow_float`).
- [ ] AC10 The same compiled AST executes on DuckDB (Arrow-registered pandas and polars frames, per-thread cursors, 8 concurrent requests) and through `SQLToolkit.execute_query` without any change to `SQLToolkit` or `DatasetManager`; Postgres parity test passes when a DSN is provided.
- [ ] AC11 Every executed query appends a signed `AccountingAuditEntry`; under `FINANCE_AUDIT_MODE=required` a storage failure prevents the result from being returned; `lineage_ref` rebuilds the exact `Lineage`.
- [ ] AC12 The rendered SQL passes the compiler self-check (only the declared journal table and declared columns) before it is returned, in every test.
- [ ] AC13 `AccountingToolkit` exposes exactly `finance_list_metrics`, `finance_explain_metric`, `finance_query_metric`, `finance_validate_model`; PBAC filtering through `DatasetPolicyGuard` hides and blocks metrics the subject may not read; no result cache exists.
- [ ] AC14 `parrot finance validate <model> [--live]` is registered lazily in the core CLI, exits non-zero on any problem, and `--live` runs assertions for the last closed natural month plus chart drift.
- [ ] AC15 The server adapter registers a daily live validation via `register_object_schedules`; flags from it (`chart_drift`, `assertion_failed`) appear on subsequent results; a `block` assertion makes `query_metric` raise.
- [ ] AC16 CI runs the satellite tests (`test-semantic` job + nightly matrix); `ruff check` passes with TID251 (no `requests`/`httpx`/langchain); docs in `docs/semantic/accounting-metrics-layer.md`.
- [ ] AC17 No breaking changes to any existing public API; `pyarrow` stays a core dependency; `duckdb` is only an extra of the satellite.

---

## 6. Codebase Contract

> Verified against `dev` at `633ef0006` (code unchanged through `e28e0c350`; only `sdd/` files moved).

### Verified Imports
```python
from parrot.bots.database.toolkits.sql import SQLToolkit                     # verified: bots/database/toolkits/sql.py:46
from parrot.bots.database.toolkits.base import DatabaseToolkit               # verified: bots/database/toolkits/base.py:82
from parrot.knowledge.common.sql_dialects import SQLGLOT_DIALECT_MAP         # verified: knowledge/common/sql_dialects.py:6 (__all__)
from parrot.knowledge.wiki.schema.table_metadata import TableMetadata, Completeness  # verified: table_metadata.py:31, :16
from parrot.bots.database.models import TableMetadata, Completeness          # re-export only — verified: bots/database/models.py:27-31
from parrot.security.audit_ledger import AbstractKMSSigner, LocalHMACSigner, AzureKeyVaultSigner  # verified: :135, :166, :199
from parrot.security import AbstractKMSSigner, LocalHMACSigner               # verified: security/__init__.py:50-56 (AzureKeyVaultSigner NOT exported)
from parrot.security.query_validator import QueryValidator                   # verified: security/query_validator.py:29 (validate_sql_ast :165)
from parrot.auth.dataset_guard import DatasetPolicyGuard                     # verified: auth/dataset_guard.py:56
from parrot.auth.permission import PermissionContext                         # verified: auth/permission.py:81
from parrot.auth.context import _pctx_var                                    # verified: auth/context.py:33-34 (ContextVar["PermissionContext | None"])
from parrot.tools.dataset_manager.tool import DatasetManager                 # verified: tools/dataset_manager/tool.py:499
from parrot._imports import lazy_import, require_extra, load_satellite_attr  # verified: _imports.py:110, :248, :183
from parrot.mcp.toolkit_server import create_toolkit_mcp_server              # verified: mcp/toolkit_server.py:137
from parrot.scheduler.manager import schedule                                # verified: ai-parrot-server scheduler/manager.py:50
from parrot.scheduler.base import SchedulerManager, ScheduleType             # verified: scheduler/base.py:254, :90
import sqlglot; from sqlglot import exp                                      # sqlglot 30.23.0 installed; core declares >=20.0 (pyproject.toml:182)
import pyarrow as pa                                                         # core dependency pyarrow>=25.0 (pyproject.toml:180); 26.0.0 installed
import yaml                                                                  # PyYAML>=6.0.2 (pyproject.toml:58)
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py
class SQLToolkit(DatabaseToolkit):                                           # line 46
    async def execute_query(self, query: str, limit: int = 1000, timeout: int = 30) -> Union[QueryExecutionResponse, RetryContext]  # line 297
    async def explain_query(self, query: str) -> str                         # line 384
    async def validate_query(self, sql: str) -> Dict[str, Any]               # line 520 — FROM/JOIN names only; not a column/function allowlist
    def _check_query_safety(self, sql: str) -> Optional[str]                 # line 578 — QueryValidator.validate_sql_ast(..., read_only=self.read_only) at :596
    # dialect lookup used internally: _SQLGLOT_DIALECT_MAP.get(self.database_type)   # line 595

# packages/ai-parrot/src/parrot/bots/database/toolkits/base.py
class DatabaseToolkit(AbstractToolkit, ABC):                                 # line 82
    database_type: str                                                       # set at line 139 (config default "postgresql", line 55)
    origin: str                                                              # line 140

# packages/ai-parrot/src/parrot/knowledge/common/sql_dialects.py
SQLGLOT_DIALECT_MAP: Dict[str, str]                                          # line 6; legacy alias _SQLGLOT_DIALECT_MAP line 23

# packages/ai-parrot/src/parrot/knowledge/wiki/schema/table_metadata.py
class Completeness(IntEnum): NAME_ONLY = 1; WITH_COLUMNS = 2; FULL = 3       # line 16
@dataclass class TableMetadata:                                              # line 31
    schema: str; tablename: str; table_type: str; full_name: str; comment: Optional[str]
    columns: List[Dict]; primary_keys: List[str]; foreign_keys: List[Dict]; indexes: List[Dict]
    completeness: Completeness; source: MetadataSource
    def satisfies(...)  # line 63;  def to_yaml_context(...)  # line 67

# packages/ai-parrot/src/parrot/security/audit_ledger.py
class AuditLedgerEntry(BaseModel)                                            # line 80 — credential-shaped; NOT extended
class AbstractKMSSigner(ABC):                                                # line 135
    async def sign(self, data: bytes) -> str                                 # line 142-143 (abstract)
    async def verify(self, data: bytes, signature: str) -> bool              # line 153-154 (abstract)
class LocalHMACSigner(AbstractKMSSigner): def __init__(self, secret: Optional[bytes] = None)   # line 166, 180
class AzureKeyVaultSigner(AbstractKMSSigner): def __init__(self, vault_url, key_name, key_version=None, credential=None, algorithm="RS256")  # line 199, 221
class AuditLedger:                                                           # line 296
    def __init__(self, signer: Optional[AbstractKMSSigner] = None, storage: Optional[Any] = None)  # line 327; storage = async callable (json_str) -> None, called at :387
    async def append(self, *, user_id, channel, tool, provider, credential_material) -> AuditLedgerEntry  # line 338 — storage errors only logged (:423-431)

# packages/ai-parrot/src/parrot/auth/dataset_guard.py
class DatasetPolicyGuard:                                                    # line 56
    async def filter_datasets(self, context: PermissionContext, dataset_names: list[str]) -> set[str]  # line 128
    async def can_read_dataset(self, context: PermissionContext, dataset_name: str) -> bool             # line 278

# packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py
class DatasetEntry:                                                          # line 129 — plain class (not Pydantic)
class DatasetManager(AbstractToolkit):                                       # line 499
    policy_guard kwarg                                                       # line 556; self._policy_guard line 581
    def add_dataframe(self, name: str, df: pd.DataFrame, ...) -> str         # line 1091 — pandas only
    async def list_datasets(self)                                            # line 2852 — filter_datasets at :2925-2926
    async def _pre_execute(self, tool_name: str, /, **kwargs) -> None        # line 2762 — per-call PBAC hook

# packages/ai-parrot/src/parrot/cli/__init__.py
class LazyGroup(click.Group)                                                 # line 19; self._lazy_commands line 30; get_command resolves getattr(mod, name.replace("-", "_")) :99-100
cli._lazy_commands = {                                                       # line 109 … closes at line 139
cli._lazy_extras = {                                                         # line 143

# packages/ai-parrot/src/parrot/mcp/toolkit_server.py
def create_toolkit_mcp_server(name: str, root: Path = Path.cwd(), **overrides: Any) -> StdioMCPServer   # line 137
# packages/ai-parrot/src/parrot/mcp/toolkit_config.py: ToolkitSection :20, MCPToolkitsConfig :80, load_toolkits_config :90; example :130-133

# packages/ai-parrot-server/src/parrot/scheduler/base.py
class ScheduleType(Enum): ONCE, DAILY, WEEKLY, MONTHLY, INTERVAL, CRON, CRONTAB   # line 90
class SchedulerManager:                                                      # line 254
    def register_object_schedules(self, obj: Any, name: str) -> int          # line 798 — scans @schedule methods (attribute _schedule_config)
    async def add_schedule(..., backend: str = "db", ...) -> JobDefinition   # line 434 — backend ∈ ("db","redis") only (sanitize.py:289); CANNOT create code jobs
# packages/ai-parrot-server/src/parrot/scheduler/manager.py
def schedule(schedule_type: ScheduleType = ScheduleType.DAILY, *, success_callback=None, send_result=None, callbacks=None, **schedule_config)  # line 50
class AgentSchedulerManager(SchedulerManager)                                # line 397; register_bot_schedules → register_object_schedules at :446

# packages/ai-parrot/src/parrot/_imports.py
def lazy_import(module_path: str, package_name: str | None = None, extra: str | None = None) -> ModuleType   # line 110
def load_satellite_attr(name: str, module_path: str, *, install: str, attr: str | None = None) -> object   # line 183
def require_extra(extra: str, *modules: str) -> None                         # line 248
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `DatabaseRunner.execute` | `SQLToolkit.execute_query(query, limit, timeout)` | method call with rendered SQL | `sql.py:297` |
| `DatabaseRunner.dialect` | `DatabaseToolkit.database_type` + `SQLGLOT_DIALECT_MAP` | attribute + dict lookup | `toolkits/base.py:139`, `sql_dialects.py:6` |
| `validation.validate` | `SQLToolkit.describe_table()` → `TableMetadata.columns` | pre-compile column check | `table_metadata.py:31` |
| `AccountingToolkit._pre_execute` | `_pctx_var.get()` + `DatasetPolicyGuard.can_read_dataset` | ContextVar + method call | `auth/context.py:33`, `dataset_guard.py:278` |
| `AccountingToolkit.list_metrics` | `DatasetPolicyGuard.filter_datasets` | batch filter | `dataset_guard.py:128` |
| `AccountingAuditLedger` | `AbstractKMSSigner.sign/verify`; `storage(json_str)` | same contract as `AuditLedger` | `audit_ledger.py:142-154`, `:327-333`, `:387` |
| `DuckDBRunner.__init__` | `parrot._imports.require_extra("duckdb", "duckdb")` | lazy extra | `_imports.py:248` |
| `parrot finance …` | `cli._lazy_commands` / `_lazy_extras` | dict entries | `cli/__init__.py:109-139`, `:143` |
| `parrot mcp-local finance` | `create_toolkit_mcp_server` + `.parrot/mcp-toolkits.yaml` | config section | `toolkit_server.py:137`, `toolkit_config.py:130-133` |
| `register_accounting_schedules` | `SchedulerManager.register_object_schedules` + `@schedule` | object registration | `scheduler/base.py:798`, `scheduler/manager.py:50` |
| release / workspace | `scripts/release.py PACKAGES`, root `[tool.uv.sources]` | list / table entries | `release.py:116-187`, `pyproject.toml:229-240` |

### Does NOT Exist (Anti-Hallucination)
- ~~`packages/ai-parrot-semantic/` on `dev`~~ — absent (exists only on `origin/feat-FEAT-704-semantic-layer`, tip `d63ac6bf4`, 20/20 tasks done there, unmerged, paused).
- ~~`parrot.semantic` on `dev`~~ — absent; this feature creates it.
- ~~`duckdb` in any `pyproject.toml`~~ — absent (installed in the venv as 1.5.6 but undeclared); `polars` also undeclared in core.
- ~~`SQLToolkit.dialect`~~ — the attribute is `database_type` (`toolkits/base.py:139`).
- ~~`SQLToolkit.execute_query(CompiledQuery)` / `execute(..., params=)`~~ — `execute_query` takes a SQL string only; bound params exist only on the private `_execute_asyncdb` (`sql.py:811`). Do not call it.
- ~~`_SQLGLOT_DIALECT_MAP` defined in `sql.py`~~ — `sql.py:27` re-imports it from the shim `parrot.tools.sql_dialects`; the definition is `knowledge/common/sql_dialects.py:6`.
- ~~`TableMetadata` defined in `bots/database/models.py`~~ — re-export only; definition in `knowledge/wiki/schema/table_metadata.py:31`.
- ~~`DatasetManager.add_dataframe(polars.DataFrame)`~~ — pandas only (`tool.py:1091`); `DatasetManager` never touches Arrow.
- ~~a Pydantic `DatasetEntry` in `dataset_manager/config.py`~~ — `DatasetEntry` is a plain class in `tool.py:129`; `config.py` holds YAML datasource specs only.
- ~~`AuditLedger.record()`~~ — the method is `append()` (`audit_ledger.py:338`); `AuditLedgerEntry` has no hash/lineage fields and is not extended.
- ~~`SchedulerManager.add_schedule(backend="code")`~~ — rejected by `sanitize.normalize_backend` (`BACKENDS = ("db","redis")`, `sanitize.py:289`); code jobs only via `register_object_schedules`.
- ~~a registry of free-standing scheduled functions~~ — none; `functions/__init__.py:238 CALLBACK_REGISTRY` holds callbacks, not jobs.
- ~~`_try_create_faiss_store` under `parrot/interfaces/`~~ — it is `parrot_tools/database/cache.py:13` (ai-parrot-tools).
- ~~an `ai-parrot-embeddings` test job in `ci.yml`~~ — none; embeddings run in `lancedb-vector-store.yml` and `nightly-tests.yml:40`. Pattern to copy: `test-loaders` (`ci.yml:508-539`).
- ~~a free `finance` extra name in core~~ — `packages/ai-parrot/pyproject.toml:255` already defines `finance = ["ta-lib==0.6.8", ...]` (unrelated); the DuckDB extra is `ai-parrot-semantic[duckdb]`, never `ai-parrot[finance]`.
- ~~`CompiledQuery` for this feature~~ — reserved by FEAT-704 (`parrot.semantic.models.CompiledQuery`); use `CompiledMetricQuery`.
- ~~golden SQL tests anywhere in the tree~~ — none; this feature introduces the pattern.

### Edit Sites (Blueprint Anchors)

Verified against: `633ef0006`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `pyproject.toml` | MODIFY | `navrules = { workspace = true }` | `pyproject.toml:240` | 1 |
| `scripts/release.py` | MODIFY | `            aliases=["openlit-bridge", "openlit"]),` | `release.py:186` | 1 |
| `.github/workflows/ci.yml` | MODIFY | `  test-loaders:` (append new job after this job's last step at :539) | `ci.yml:508` | 1 |
| `.github/workflows/nightly-tests.yml` | MODIFY | `          - ai-parrot-embeddings` | `nightly-tests.yml:40` | 1 |
| `packages/ai-parrot/src/parrot/cli/__init__.py` | MODIFY | `    "mcp-serve": "parrot.integrations.agentd.cli",` (last `_lazy_commands` entry; `}` at :139) | `cli/__init__.py:138` | 1 |
| `packages/ai-parrot/src/parrot/cli/__init__.py` | MODIFY | `cli._lazy_extras = {` | `cli/__init__.py:143` | 1 |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | scheduler setup call site for `register_accounting_schedules` — `(unverified — check before use; no `SchedulerManager(` construction found under manager/)` | — | — |
| `packages/ai-parrot-semantic/pyproject.toml` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/README.md` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/src/parrot/semantic/__init__.py` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/src/parrot/semantic/version.py` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/src/parrot/semantic/accounting/{__init__,models,errors,grammar,loader,snapshot,validation,compiler,audit,catalog,toolkit,cli,live}.py` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/src/parrot/semantic/accounting/runtime/{__init__,arrow,duckdb,database}.py` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/tests/{__init__,conftest}.py`, `tests/accounting/*.py`, `tests/accounting/golden/{duckdb,postgres,bigquery}/*.sql` | CREATE | — | — | — |
| `packages/ai-parrot-server/src/parrot/scheduler/accounting_jobs.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/tests/scheduler/test_accounting_jobs.py` | CREATE | — | — | — |
| `docs/semantic/accounting-metrics-layer.md` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Satellite layout**: copy `packages/ai-parrot-embeddings/pyproject.toml` structure (`setuptools`, `namespaces = true`,
  `where = ["src"]`, `[tool.uv.sources] ai-parrot = { workspace = true }`); no `src/parrot/__init__.py`.
- **Mirror FEAT-704's skeleton files** (`git show origin/feat-FEAT-704-semantic-layer:packages/ai-parrot-semantic/<file>`)
  and remove only sidemantic/jsonschema/bigquery. `version.py` must be byte-identical.
- **Lazy optional dependency**: `require_extra("duckdb", "duckdb")` inside `DuckDBRunner.__init__`, never at module
  import; the package must import cleanly without the extra.
- **Hashing**: `canonical_json` = `json.dumps(model_dump(mode="json"), sort_keys=True, separators=(",", ":"))`,
  Decimals as strings; `sha256` hex. The same function hashes models, requests and audit entries.
- **sqlglot**: build with `exp.*` constructors only (`exp.Select`, `exp.Case`, `exp.Sum`, `exp.Coalesce`,
  `exp.Nullif`, `exp.DateTrunc`, `exp.Window`, `exp.In` with sorted `exp.Literal.string` values); never
  `sqlglot.parse_one(f"...")` with interpolated model data. Render `pretty=False`, `identify=False`.
- **Dates**: half-open `[from, to + 1 day)` in SQL to be timestamp-safe; `Period.to` inclusive at the API.
- **Decimal**: DuckDB `DECIMAL(38,6)`; Postgres `NUMERIC`; results converted with `Decimal`, never `float`.
- **Threading**: one `duckdb` root connection per runner; `root.cursor()` per `to_thread` call; semaphore bound.
- **PBAC**: copy `DatasetManager._pre_execute` semantics (no guard ⇒ allow; `AuthorizationRequired` bubbles).
- **Logging**: `self.logger`; never log SQL with account literals at INFO (DEBUG only); never log identities.
- Conventions: `.claude/rules/codebase-conventions.md` (aiohttp only, Pydantic v2, Google docstrings, 120 cols).

### Known Risks / Gotchas
- **FEAT-704 merge collision** — mitigated by mirroring its M1 files; expected conflicts: `pyproject.toml`
  `dependencies`/extras, `__init__.py` exports, README. FEAT-704's M1 must be amended to "extend the existing
  skeleton" when it resumes (§8 Q10).
- **sqlglot rendering drift** — pin `>=30.1,<31` in the satellite (core only says `>=20.0`); golden files per
  dialect are the review artifact for any bump.
- **Account present in two sets** — error unless mutual `allow_overlap`; double counting is the second most common
  finance bug after omission.
- **Membership change inside the requested or cumulative window** — refused (`PeriodSpansMembershipChange`);
  never silently sliced.
- **Chart drift** — new accounts after load: `detect_drift` on `--live`/scheduled validation sets `chart_drift: true`
  on results; the loaded model keeps serving.
- **Metric referencing a set whose `valid_from` is after the period** — compile error, never an empty number.
- **Unknown dimension / filter column** — `RequestValidationError` before compilation.
- **Division by zero** — `NULLIF` emitted; result NULL + `division_by_zero_possible` warning in lineage.
- **NULL vs 0** — `COALESCE(SUM(...), 0)` per set so empty groups reconcile; assertions compare Decimals with
  `tolerance` (default 0).
- **DuckDB connection across threads** — never; per-thread cursors only.
- **pandas object/float amount columns** — `DataFrameConversionError` / `float_amount` problem; opt-in
  `allow_float` casts to `DECIMAL(38,6)` with a lineage warning.
- **`SQLToolkit.execute_query` limit** — default 1000 rows; the runner passes an explicit `limit` and reports
  truncation as `AccountingExecutionError` rather than returning partial groups.
- **PBAC resource naming** — metrics are filtered as dataset-typed resources named `accounting:<tenant>:<model>:<metric>`;
  a dedicated `ResourceType` is a follow-up, not a v1 blocker.
- **Audit fail-closed in dev** — `.parrot/mcp-toolkits.yaml` example sets `FINANCE_AUDIT_MODE=best_effort`; production
  keeps `required`.
- **Scheduler call site** — the exact server location that constructs the scheduler was not found under
  `manager/`; `/sdd-task` must locate it before writing M9's registration task (marked unverified in §6).
- **Name collision** — core already has an unrelated `finance` extra (`ta-lib`); never add dependencies there.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `sqlglot` | `>=30.1,<31` (satellite pin; venv 30.23.0) | AST construction, dialect rendering, self-check parse |
| `pyarrow` | `>=25.0` (core, already declared; venv 26.0.0) | zero-copy DataFrame → DuckDB bridge |
| `duckdb` | `>=1.0` (new optional extra `ai-parrot-semantic[duckdb]`; venv 1.5.6) | in-process engine for DataFrames |
| `pyyaml` | `>=6` (core declares `PyYAML>=6.0.2`) | model files |
| `pydantic` | v2 (core) | contracts |
| `polars` | not declared (venv 1.27.1) | accepted when present (`to_arrow()`); never imported eagerly, never added as a dependency |

Configuration keys (environment): `FINANCE_MODELS_DIR` (default `./models`), `FINANCE_DUCKDB_THREADS` (default 4),
`FINANCE_AUDIT_MODE` (`required` | `best_effort`, default `required`), `FINANCE_RESULT_LIMIT` (default 10000).

---

## 8. Open Questions

- [x] Package home — *Resolved in brainstorm*: `parrot.semantic.accounting` in the `ai-parrot-semantic` satellite, as a standalone package, not an engine of FEAT-704; FEAT-704 is paused until sidemantic (AGPL-3.0) is migrated away; this feature creates the satellite skeleton without sidemantic. *Refined in spec (codex S11 + §4 research)*: the skeleton mirrors `origin/feat-FEAT-704-semantic-layer`'s M1 files byte-for-byte minus sidemantic.
- [x] Where models live per tenant — *Resolved in brainstorm*: git, `<models_dir>/<tenant>/<model>.yaml`, reviewed in PRs; `model_hash` is tied to a commit. Admin UI is v2.
- [x] Effective-dated membership strategy — *Resolved in brainstorm*: refuse requests (including cumulative windows) that span a membership change in v1, with an actionable error. Slice + `UNION ALL` is v2. S4 validates the error.
- [x] Sign convention — *Resolved in brainstorm*: explicit required key, no default; `nature` required only when normalising by nature. *Refined in spec (codex S4)*: the key is `amount_convention: debit_positive | credit_positive | debit_credit_columns | natural_balance`, each with a defined normalisation (§2 table).
- [x] Hierarchy selectors (`parent:`) — *Resolved in brainstorm*: v2 by default; S3 promotes them to v1 only if explicit lists/prefix/range cannot reach zero unassigned accounts in one session.
- [x] Period semantics — *Resolved in brainstorm*: natural calendar by `posting_date`, plus cumulative YTD/QTD/MTD in v1 (client requirement). Fiscal calendars and closed-period flags stay non-goals.
- [x] Assertions at load vs. on schedule — *Resolved in brainstorm*: both: on demand (`parrot finance validate --live`) and a scheduled task over the last closed period + chart drift.
- [x] AuditLedger payload — *Resolved in brainstorm*: own signed `AccountingAuditEntry` (core signers, `storage(json_str)` contract) with hashes, canonical request and a `lineage_ref`; lineage is rebuilt deterministically from `model_hash` + request, never stored inline. `AuditLedgerEntry` is not extended. *Refined in spec (codex S9)*: `FINANCE_AUDIT_MODE=required` fails closed by default.
- [x] Lowering into the generic layer — *Resolved in brainstorm*: deferred until FEAT-704 resumes; not committed in either spec now.
- [ ] Q10 FEAT-704 amendment — when FEAT-704 resumes, its M1 ("Distribution skeleton") must become "extend the skeleton created by FEAT-713" and its `__init__.py` must keep `parrot.semantic.accounting` importable without sidemantic. Who edits `sdd/specs/semantic-layer.spec.md`, and when? — *Owner: Jesus* (escalated from codex S11; not blocking FEAT-713)
- [ ] Q11 Server scheduler call site — the exact location in `ai-parrot-server` where `register_accounting_schedules()` is invoked at startup (no `SchedulerManager(` construction found under `manager/`). Resolve in `/sdd-task` by locating the scheduler bootstrap; falls back to documenting manual registration if none exists. — *Owner: /sdd-task*

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration doc** (never over this spec).
> Model: `gpt-5.6-luna` (codex-cli 0.163.0) · Status: completed · Transcript: `sdd/state/FEAT-713/design_research/`
> All 12 `affected_paths` cited by the reviewer were checked for repository containment and existence (all present).

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Make the chart of accounts an immutable, versioned input (architecture) | CONFIRM | Completeness cannot be proven from `information_schema`; the brainstorm's snapshot becomes an explicit, hashed `ChartSnapshot` folded into `model_hash` | §2 Data Models, M4 `snapshot.py` |
| S2 | One canonical IR with target-specific SQL renderings (alternative) | CONFIRM | "Same SQL text on both targets" was loose wording; one `exp.Select` rendered per dialect, `sql_hash` per rendering, `model_hash` shared | §1 Goals, §2 Overview, M5 |
| S3 | Do not treat SQLToolkit validation as a semantic allowlist (risk) | CONFIRM | `validate_query` checks FROM/JOIN names only (`sql.py:520`); compiler gains a self-check pass re-parsing the rendered SQL against declared table/columns | M5 `self_check`, AC12 |
| S4 | Specify the sign contract as data-shape semantics (api) | CONFIRM | `by_nature \| signed` left debit-positive vs credit-positive undefined; replaced by `amount_convention` with four defined normalisations and exact-numeric requirement; keeps the brainstorm's "explicit, no default" resolution | §2 sign table, M2/M4, AC3/AC9 |
| S5 | Validate effective-dated completeness per interval (architecture) | CONFIRM | A global check can accept gaps at a boundary; membership partition + per-interval completeness/overlap | M4 `partition_intervals`, AC4 |
| S6 | Fix numeric and empty-result semantics before golden tests (testing) | CONFIRM | `COALESCE(SUM,0)`, `NULLIF`, Decimal end to end, tolerance on assertions, fixtures for reversals/empty months/ytd boundaries | M5, §4 fixtures, AC8/AC9 |
| S7 | Keep accounting execution separate from the DatasetManager catalog contract (architecture) | CONFIRM | `add_dataframe` is pandas-only and `DatasetEntry` has no metric kind (`tool.py:1091,129`); metrics live in their own `ModelCatalog`, frames arrive through an injected `frame_provider`; DatasetManager unmodified | §2 Integration Points, M8 `catalog.py` |
| S8 | Exclude shared DatasetManager caches from accounting results (risk) | CONFIRM | `DataSource.cache_key` is shared by design (`sources/base.py:13`); v1 has no result cache at all, compile cache only | Non-Goals, AC13 |
| S9 | Define a separate durable accounting audit contract (architecture) | CONFIRM | Already a brainstorm resolution; adds the explicit failure policy (`FINANCE_AUDIT_MODE=required` fails closed) and `schema_version` | M7, AC11 |
| S10 | Separate structural assertion validation from live reconciliation (testing) | CONFIRM | Structural checks at load; data assertions get `AssertionResult(status, tolerance, period)` and `on_failure: flag \| block` | M4, M9, AC15 |
| S11 | Resolve ownership of the `parrot.semantic` satellite before creating it (architecture) | CONFIRM + ESCALATE | Research found the satellite fully built on `origin/feat-FEAT-704-semantic-layer`; the skeleton here mirrors its files minus sidemantic (CONFIRM); the amendment of FEAT-704's spec is a human decision (ESCALATE) | M1, §7 Risks, §8 Q10 |

Summary: **11** confirmed · **0** rejected · **1** escalated (S11 is both confirmed and escalated).
