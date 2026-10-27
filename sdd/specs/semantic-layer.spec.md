---
type: feature
base_branch: dev
projects: [ai-parrot-semantic, ai-parrot, ai-parrot-server, ci]  # FEAT-576 — rev 0.3 adds `ci` (CI workflow edits), carried from the rev2 proposal
tags: [semantic-layer, sqlglot, clean-room, licensing, rls, pbac, mcp]  # FEAT-576 — rev 0.3 drops `sidemantic` (removed dependency), adds `clean-room`
---

# Feature Specification: Semantic Layer — governed metric queries for agents (`ai-parrot-semantic`)

**Feature ID**: FEAT-704
**Date**: 2026-10-19 (rev 0.4: 2026-10-25)
**Author**: Jesus Lara
**Status**: approved; rev 0.4 incorporates the requested specification-review fixes
**Target version**: 1.3.0
**Source**: `sdd/proposals/semantic-layer.brainstorm.md` (accepted 2026-10-19, Option B) ← `sdd/proposals/semantic-layer.proposal.md`
**Rev 0.3 source**: `sdd/proposals/semantic-layer-rev2.proposal.md` (status: review, 2026-10-25) — supersedes the
sidemantic-core design below; see Revision History. The unmerged `origin/feat-FEAT-704-semantic-layer`
branch (20/20 tasks, built against rev 0.2) is a **salvage source only**, never a merge base: it is 94
commits ahead of its merge-base with `dev` while `dev` is 1,386 commits ahead of the same point
(verified 2026-10-25). Rev 0.3 tasks run in a fresh worktree off `origin/dev`.

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

Agents that answer KPI questions today either write free SQL against `DatabaseQueryToolkit` /
`SQLToolkit` or call pre-registered QuerySource slugs. Free text-to-SQL produces *plausible but
wrong* numbers (dbt Labs 2026 benchmark: 84–90 % accuracy vs 98–100 % with a semantic layer, and
a semantic layer fails **loudly** on out-of-scope questions instead of inventing a figure). Slugs
are exact but rigid: every new breakdown is a new slug.

There is no place in ai-parrot where **metrics, dimensions, joins and time grains are declared
once** and compiled on demand, and there is no governance plane for such queries. Row-level
security (RLS) exists only as a *post-hoc wrapper* (`inject_rls_sql` wraps the whole statement in
`SELECT * FROM (...) WHERE pred`), which is **wrong for aggregates**: a tenant filter applied after
`SUM()`/`COUNT()` either filters nothing or leaks totals. There is no per-role metric/dimension
allowlist, no column masking, no column-usage control, no positive SQL allowlist, and no audit
record storing the compiled SQL next to the security context.

Affected: **end users** (wrong KPI answers, data leakage across tenants/programs), **developers**
(every dashboard agent re-invents metric definitions), **ops/security** (no auditable trail of
what SQL ran under which identity).

Facts the design rests on (from the research proposal and the brainstorm):
1. **No semantic-layer library is async** — compile-only in `asyncio.to_thread`, execute with our own async drivers.
2. **No RLS format is portable** (Apache Ossie defines none) — governance is ai-parrot code regardless of engine.
3. **Ibis is a recorded NO-GO** in this repo (TASK-1437 / FEAT-219; `dataset_manager/spatial/compiler.py:19`).

### Goals

- G1. Declare metrics, dimensions, relationships and time grains once (**(rev 0.3)** the own clean-room
  YAML format or Apache Ossie 0.1.1 documents) and compile governed SQL for Postgres, BigQuery and
  DuckDB on demand, with no warehouse connection at compile time.
- G2. Governance is ai-parrot code and engine-independent: PBAC gate on every request, RLS pushed
  **below aggregation**, per-role member allowlist, column masking **and** column-usage rights
  enforced through full AST lineage, positive SQL allowlist, forced `LIMIT`, signed audit.
- G3. Governed-by-default, fail-closed: a model denies without a `PermissionContext` or without an
  available PBAC evaluator unless its policy explicitly sets `governed: false`.
- G4. Caches never carry governed SQL or authorization decisions; results are never shared across
  subjects; dataset hand-off is owner/session-bound and expiring.
- G5. **(rev 0.3)** One opt-in satellite distribution `ai-parrot-semantic`, MIT-only, with **no AGPL-3.0
  dependency at all** — sidemantic is neither a dependency nor a reference (clean-room: only Cube, dbt
  MetricFlow and Apache Ossie 0.1.1 **public format documentation** informs the typed model schema). The
  repo-wide `sidemantic` import ban (TID251) carries no per-file exemption anywhere, including the satellite.
- G6. Four surfaces over one implementation: `SemanticLayerToolkit` (`sl_*` tools), `parrot
  mcp-local semantic-layer`, aiohttp handlers in `ai-parrot-server`, and a guarded hand-off to a
  subject/session-scoped dataset sink (M9H).
- G7. **(rev 0.3)** A single native sqlglot compiler is the sole engine — no dual-engine dispatch, no
  `engine` field on model/policy. v1 covers the subset in M5 (aggregations, `DATE_TRUNC` grains, declared
  one-to-many joins with fan-out rejection, filtered measures lowered to `FILTER (WHERE …)` / `CASE WHEN`,
  derived metrics over metrics) with golden-SQL snapshots + a DuckDB execution oracle + a cross-process
  determinism hash check replacing the former sidemantic-parity tests.

### Non-Goals (explicitly out of scope)

- **(rev 0.3)** Porting, adapting, or opening sidemantic's source code in any form — the clean-room rule
  is absolute: sidemantic is dropped as a dependency *and* as a code reference. Only the public Cube, dbt
  MetricFlow and Apache Ossie 0.1.1 format specs (read from their own documentation) inform the typed
  model schema; the branch's sidemantic-API glue (`loader.py` body, `sidemantic_engine.py`, the Ossie
  shim built against sidemantic's importer) is deleted, never adapted.
- A result cache beyond the pre-governance `CompileCache`; cross-request result reuse.
- Symmetric aggregates, cumulative / time-comparison / cohort metrics (no engine implements them in v1).
- Pushing governance into the warehouse (views + native RLS) — rejected as brainstorm Option D.
- **(rev 0.3)** BSL-over-Ibis or Ibis-direct compilation remains a non-goal. The recorded NO-GO
  (`TASK-1437`, cited at `dataset_manager/spatial/compiler.py:19`) concerned **connection/credential
  mapping** (asyncpg DSN ≠ libpq/psycopg format; BigQuery credentials need a `google.oauth2.Credentials`
  shim) — compile-only `ibis.to_sql()` was never evaluated. This spec adds no Ibis/BSL dependency; the
  NO-GO's scope is explicitly narrowed to connections so a later, scoped joins-phase spec may re-open
  compile-only BSL/Ibis usage without contradicting this record.
- **(rev 0.4)** No core edits except the DuckDB execution prerequisite M9D and its focused tests. Rev 0.2's M12 (behavioural fix of
  `dataset_manager/sources/authorizing.py` / `handlers/datasets.py`, `issue:90cf04ce8edd`) is dropped —
  **FEAT-738 (TASK-4678/4679, merged 2026-10-24) already shipped the identical request-scoped-RLS fix on
  `dev`**: `AuthorizingDataSource._apply_rls` now returns a per-call target instead of mutating
  `self._inner` (verified `authorizing.py:147,152`, 2026-10-25), and `test_authorizing_data_source.py`
  already asserts the non-mutating behavior. The semantic implementation stays in the satellite; M9D is the sole core-source exception; `DatabaseQueryToolkit`,
  `AuditLedgerEntry`, `RlsRegistry`, `DataPlanePolicyGuard`, `parrot/clients/base.py` are all consumed as
  they are.
- **(rev 0.3)** The Rust/PyO3 phase (deriving SemaFlow's `sql_ast.rs` + `dialect/{duckdb,postgres,bigquery}.rs`
  under MIT with attribution) is **out of scope for this spec**, tracked as its own reserved feature,
  **FEAT-742** (`semantic-layer-rust-compiler`, reserved 2026-10-25). This spec only fixes the IR/compiler
  shape FEAT-742 would later consume; no Rust code, crate, build step, or `THIRD_PARTY.md` entry is added here.
- Dialects other than Postgres, BigQuery, DuckDB for **execution** (compile-only may emit any sqlglot dialect).
- A metric-authoring UI; Ossie **export**; dbt/LookML import beyond the own-format loader and the vendored
  Ossie 0.1.1 schema.

---

## 2. Architectural Design

### Overview

**Rev 0.3 (amends rev 0.2's "Option B"):** sidemantic is dropped entirely — as a dependency and as a
code reference (clean-room). ai-parrot owns the **whole** semantic core now: a typed, frozen Pydantic v2
model graph (`SemanticModel` / `Dimension` / `Metric` / `Relationship`, §3 M4) authored from the *public*
Cube, dbt MetricFlow and Apache Ossie 0.1.1 format specs, loaded from the own YAML format and Ossie
documents, and compiled by **one native sqlglot compiler** (§3 M5, promoted from "fallback" to sole
engine — 87% already exists on the salvage branch, see §6). Governance, written on **sqlglot** and
applied identically to compiled output and (optional) free SQL, is unchanged from rev 0.2 and entirely
engine-neutral:

1. **`SemanticQuery`** — the pydantic request contract (metrics · dimensions · time dimensions
   with grain · typed `and`/`or` filter tree · order · limit · offset · timezone · `saved_query`
   exclusive with explicit query members). Compiles directly to the native sqlglot AST builder.
2. **Compile** (`asyncio.to_thread`) via one internal `compile()` — **no dispatch, no `engine` field,
   no plugin protocol, no engine registry** (rev 0.3 drops even the two-way dispatch rev 0.2 kept).
   Output is an immutable `CompiledQuery` containing **no subject-derived content**; this is the only
   thing the LRU cache may store.
3. **Govern** — a sqlglot pass over a *clone* of the compiled AST, run on **every** request
   including cache hits, compile-only requests, saved queries, dimension-value lookups, raw
   SQL **and catalog exposure** (a governed model's members are never listed without an
   authorized subject). Authorization is **two-phase**: (a) *before* compile, the model's declared
   resource manifest (connection driver + every physical table of its schema map) is authorized
   via `DataPlanePolicyGuard.authorize_source(ctx, resources)`; (b) *after* compile,
   `qualify(schema)` → `PhysicalResources` from the AST → every table must be ⊆ the authorized
   manifest, else deny. The satellite requires `ctx` and an available evaluator; `None` never
   reaches the guard's fail-open branch. Then → **column-usage
   lineage** (projection rights ≠ usage rights; unresolved lineage fails closed) → **RLS push-down**
   (rules via `RlsRegistry.lookup/render`, injected as filtered base scans below aggregation, typed
   literals) → **masking** of projected sensitive columns → **positive guard** (single `Select`,
   allowlisted tables/columns/functions, no `Command`/DDL/DML, forced `LIMIT ≤ cap`) → `GovernedQuery`.
4. **Execute** through `DatabaseQueryToolkit.get_source(driver).query(credentials, sql)`;
   credentials resolved **inside the satellite** from the model's `connection` name via
   navconfig/env (resolved question) — never from tool arguments.
5. **Audit** — a signed `SemanticAuditEntry` (own ledger in the satellite reusing
   `AbstractKMSSigner` + the async `storage` callable contract; resolved question) with the
   structured query, subject digest, model/policy versions, engine, compiled and governed SQL,
   dialect, row count, duration, outcome.
6. **Hand-off** — results are retained only when enabled, under opaque `result_id` handles in a
   bounded TTL store bound to (agent, user, tenant, session, model/policy versions, subject
   digest). `sl_save_result_as_dataset` re-checks ownership/expiry/context and PBAC, then publishes through a host-provided **guarded, subject/session-scoped** dataset sink (M9H), which reauthorizes every downstream read. A plain `DatasetManager.add_dataframe()` target is refused; without a conforming sink the tool is not exposed.
7. **Surfaces** — `SemanticLayerToolkit(AbstractToolkit, tool_prefix="sl")`; `parrot mcp-local
   semantic-layer` from a `.parrot/mcp-toolkits.yaml` section (optional `static_subject` operator
   identity, logged and audited — resolved question); `SemanticLayerHandler(BaseView)` at
   `/api/v1/agents/semantic/{agent_id}` registered in `manager.py` (lazy import); the hand-off above.
8. **Licensing** — **(rev 0.3)** satellite `license = "MIT"` like the other satellites, now with
   **no AGPL dependency to document**: the README's former "License notice: sidemantic is AGPL-3.0"
   section is removed; §8 Q1's legal sign-off is now moot (recorded as superseded, not re-litigated).

Resolved brainstorm decisions reflected in this design (see §8 for the trail): license field;
separate audit ledger; governed-by-default; mcp-local `static_subject`; satellite-side credential
resolution; `sl_run_sql` shipped behind `allow_raw_sql=False`; native subset as drafted; proposal
committed. **(rev 0.3)** additionally resolved: no sidemantic dependency or reference (clean-room);
single compiler with no dispatch; branch is salvage-only; one-to-many joins kept in v1 (U4); FEAT-704
rev 0.3 creates the satellite skeleton, FEAT-713 extends it (U6); Rust phase gets its own reserved
FEAT-742 (U3); Ibis NO-GO scope-narrowed to connections (U5).

### Component Diagram
```
 .parrot/mcp-toolkits.yaml ─► parrot mcp-local ─┐
 ai-parrot-server SemanticLayerHandler ─────────┤   (PermissionContext from navigator-auth session /
 Agent / AgentCrew tool call ───────────────────┤    _permission_context kwarg / static_subject)
                                                ▼
                               SemanticLayerToolkit  (sl_* tools, tool_prefix="sl")
                                 │ trusted wrapper → ContextVars; _pre_execute validates
                                 ▼
   SemanticModelLoader ──► LoadedModel{model: SemanticModel, policy, schema_map, digests}
   (own YAML dir + Ossie 0.1.1 + <model>.policy.yaml, clean-room)     │
                                 │                           │
   RoleCatalog (role-filtered view, saved-query expansion) ◄─┘
                                 │  SemanticQuery (validated, expanded)
                                 ▼
   compile(query, model, dialect)  ── NativeCompiler (sqlglot AST, sole engine)
        │  (to_thread, pre-governance LRU)
        ▼  CompiledQuery (immutable, subject-free)
   GovernancePipeline.govern(compiled, ctx, model)   ← also for sl_run_sql(sql)
        qualify → PhysicalResources → PbacGate.authorize (DataPlanePolicyGuard.authorize_source)
        → ColumnLineage usage rights → RlsPushdown (RlsRegistry.lookup/render) → Masking → PositiveGuard
        ▼  GovernedQuery
   Executor ──► DatabaseQueryToolkit.get_source(driver).query(credentials, sql)   (asyncpg / BigQuery / DuckDB)
        │            ▲ ConnectionResolver(model.connection) → credentials dict
        ▼
   SemanticAuditLedger.append(SemanticAuditEntry)   ResultHandleStore (TTL, owner-bound)
                                                          │ sl_save_result_as_dataset
                                                          ▼
                                   dataset_manager_factory(identity) → GovernedDatasetSink.publish() → guarded reads
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.tools.toolkit.AbstractToolkit` / `ToolkitTool` | extends | `SemanticLayerToolkit` subclasses it; `_pre_execute` receives `_permission_context` (toolkit.py:174-178); validates identity bound by the satellite execution wrapper (M10) |
| `parrot.tools.databasequery.toolkit.DatabaseQueryToolkit.get_source()` + `AbstractDatabaseSource.query()` | uses | execution bridge for `pg` / `bigquery` / `duckdb`; no change to the toolkit |
| `parrot.auth.dataplane_guard.DataPlanePolicyGuard.authorize_source()` / `.rls_predicates()` | uses | PBAC gate (`driver:connect`, `table:read`) on every request; satellite never passes `ctx=None` (guard would fail open) |
| `parrot.auth.rls_registry.RlsRegistry` / `RlsRule` / `RlsPredicate` | uses | RLS rules looked up by `(driver, {schema.table})`, rendered per subject; predicates re-parsed into sqlglot and pushed below aggregation |
| `parrot.auth.permission.PermissionContext` / `UserSession` | uses | subject identity; roles/tenant/metadata feed the subject digest and policy evaluation |
| `parrot.auth.context._pctx_var` | depends on | the same ContextVar `DatabaseQueryTool` reads (tool.py:598-600) is **bound and reset** by the satellite wrapper so downstream guards see only the current context |
| `parrot.security.query_validator.QueryValidator.validate_sql_ast()` | uses | negative base (multi-statement/DDL/DML rejection) run before the positive guard |
| `parrot.security.audit_ledger.AbstractKMSSigner` / `LocalHMACSigner` / `AzureKeyVaultSigner` | uses | signer for `SemanticAuditEntry`; `AuditLedger` itself is **not** used (its entry is credential-shaped) |
| `parrot.tools.dataset_manager.tool.DatasetManager.add_dataframe()` | uses | not a sufficient hand-off target by itself; M9H requires a guarded host sink |
| `parrot.tools.dataset_manager.sources.resolver.PhysicalResources` | uses | the resource shape `authorize_source` expects; built from the governed AST's tables (`"driver:schema.table"` strings) |
| `parrot.tools.dataset_manager.sources.dialects.driver_to_dialect()` + `parrot.knowledge.common.sql_dialects.SQLGLOT_DIALECT_MAP` | uses | driver ↔ sqlglot dialect mapping |
| `parrot.interfaces.database.get_default_credentials(driver)` | uses | default credentials per driver; `ConnectionResolver` layers a named-connection env prefix on top |
| `parrot mcp-local` (`parrot/mcp/local_cli.py`, `toolkit_config.ToolkitSection`) | config | new `semantic-layer:` section (`class`, `kwargs`, `env`); no server code |
| `ai-parrot-server` `manager/manager.py` router | extends | `SemanticLayerHandler` registered next to `DatasetManagerHandler` (manager.py:2571) behind a lazy `parrot.semantic` import |
| `ai-parrot-server` `handlers/datasets.py::_get_dataset_manager()` | reuses pattern | per-user/session ownership precedent only; does not provide the M9H semantic read gate |
| root `pyproject.toml` `[tool.uv.sources]`, `scripts/release.py` `PACKAGES`, `ruff.toml` TID251, `.github/workflows/ci.yml` | modifies | workspace member, release list, `sidemantic` import ban outside the satellite, CI test step |

### Data Models
```python
# packages/ai-parrot-semantic/src/parrot/semantic/models.py  (new)
from typing import Literal, Annotated
from pydantic import BaseModel, ConfigDict, Field, model_validator

Grain = Literal["second", "minute", "hour", "day", "week", "month", "quarter", "year"]
FilterOp = Literal["equals", "not_equals", "in", "not_in", "contains", "gt", "gte", "lt", "lte",
                   "between", "is_set", "not_set", "in_date_range", "before_date", "after_date"]

class TimeDimension(BaseModel):
    name: str
    grain: Grain | None = None          # required when the dimension is a time dimension
    date_range: tuple[str, str] | None = None   # ISO-8601 inclusive bounds

class FilterLeaf(BaseModel):
    member: str                         # metric or dimension name; kind resolved against the model
    op: FilterOp
    values: list[str | int | float | bool] = Field(default_factory=list)

class FilterGroup(BaseModel):
    op: Literal["and", "or"]
    items: list["FilterLeaf | FilterGroup"]
    # validator: a group never mixes metric (HAVING) and dimension (WHERE) leaves

class OrderBy(BaseModel):
    member: str
    grain: Grain | None = None
    desc: bool = False

class SemanticQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")   # credential-like or unknown fields are rejected (never carried by a query)
    model: str
    metrics: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    time_dimensions: list[TimeDimension] = Field(default_factory=list)
    filters: FilterGroup | None = None
    order_by: list[OrderBy] = Field(default_factory=list)
    limit: int | None = None            # None → policy default; clamped to policy max
    offset: int = 0                     # requires order_by
    timezone: str | None = None
    saved_query: str | None = None      # exclusive with explicit members; expanded before compile

class CompiledQuery(BaseModel, frozen=True):
    """Pre-governance compiler output. MUST contain no subject-derived predicates or values."""
    sql: str
    dialect: str
    # (rev 0.3) no `engine` field — the native compiler is the sole engine; `compiler_version` below
    # replaces the old "engine+version" cache-key component (invalidates on compiler codegen changes).
    members: tuple[str, ...]            # metrics + dimensions referenced
    tables: tuple[str, ...]             # "schema.table" physical tables referenced
    cache_key: str                      # (model digest, policy digest, canonical query, dialect, compiler_version, connection id)

class GovernedQuery(BaseModel, frozen=True):
    sql: str
    dialect: str
    driver: str
    tables: tuple[str, ...]
    rls_applied: tuple[str, ...]        # rule descriptions applied (never values)
    masked_columns: tuple[str, ...]
    limit: int
    subject_digest: str
    members: tuple[str, ...]            # exact semantic provenance including dependencies
    physical_columns: tuple[str, ...]   # resolved qualified lineage; never inferred from output aliases

class SemanticQueryResult(BaseModel):
    columns: list[str]
    rows: list[dict]
    row_count: int
    truncated: bool
    duration_ms: int
    compiled_sql: str                   # pre-RLS compiled SQL (run_sql: the caller's SQL); governed SQL with RLS literals is audit-only (issue:22fbd14d96a9)
    audit_id: str
    result_id: str | None = None        # present only when the ResultHandleStore is enabled
```

```yaml
# <models_dir>/<model>.policy.yaml  (new side-file; schema in parrot/semantic/policy.py)
governed: true                 # default true; `false` opts the model out of PBAC/RLS/role checks
# (rev 0.3) no `engine:` key — the native compiler is the only engine
connection: warehouse_pg       # named connection resolved by ConnectionResolver
limits: {default: 1000, max: 10000}
roles:
  analyst: {metrics: [revenue, orders], dimensions: [region, order_month], usage: [region]}
  admin:   {metrics: "*", dimensions: "*", usage: "*"}
masks:
  customers.email: {strategy: hash, projection_roles: [analyst], usage_roles: []}
rls:                           # RlsRule entries (driver/table/predicate_template/subject_attribute)
  - {driver: pg, table: sales.orders, predicate_template: "region IN (:subject.programs)", subject_attribute: programs}
saved_queries:
  - {name: monthly_revenue, verified_by: jesus@…, verified_at: 2026-10-19, query: {metrics: [revenue], time_dimensions: [{name: order_date, grain: month}]}}
```

### New Public Interfaces
```python
# parrot.semantic (satellite)
class SemanticLayerToolkit(AbstractToolkit):                      # tool_prefix = "sl"
    def __init__(self, *, models_dir, dialect, dataplane_guard=None, rls_registry=None,
                 database_toolkit=None, signer=None, audit_storage=None,
                 allow_raw_sql=False, static_subject=None, dataset_manager_factory=None,
                 result_ttl_s=900, result_store_max=256, **kwargs) -> None: ...
    async def list_models(self) -> list[dict]
    async def list_metrics(self, model: str) -> list[dict]
    async def get_dimensions(self, model: str, metrics: list[str] | None = None) -> list[dict]
    async def get_dimension_values(self, model: str, dimension: str, metrics: list[str] | None = None, limit: int = 50) -> SemanticQueryResult
    async def search_data_model(self, text: str, model: str | None = None) -> list[dict]
    async def list_saved_queries(self, model: str) -> list[dict]
    async def compile_query(self, query: SemanticQuery) -> dict          # governed SQL + explanation, no execution
    async def query_metrics(self, query: SemanticQuery) -> SemanticQueryResult
    async def run_sql(self, model: str, sql: str) -> SemanticQueryResult  # only when allow_raw_sql=True
    async def save_result_as_dataset(self, result_id: str, name: str, description: str | None = None) -> dict  # only with a conforming guarded sink factory
```

---

## 3. Module Breakdown

> Define the discrete modules that will be implemented.
> These directly map to Task Artifacts in Phase 2.

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Distribution skeleton | yes | PEP 420 layout mirrors `packages/ai-parrot-embeddings`; exact pins and anchors in §6/§7; **(rev 0.3)** no `sidemantic` dependency | — |
| M2: Query & result contracts | yes | pydantic v2 models above; validators enumerated in M2 skeleton; error hierarchy fixed; **(rev 0.3)** no `engine` field | — |
| M3: Model policy side-file | yes | YAML schema above; unknown member ⇒ `SemanticPolicyError`; `governed` default `true`; **(rev 0.3)** no `engine` field | — |
| M4: Typed model graph + loader (rev 0.3, clean-room) | no | own YAML format + Ossie 0.1.1 loader; `SemanticModel`/`Dimension`/`Metric`/`Relationship` fixed below; salvages `PhysicalSchema`/digests from the branch (`loader.py`, 386 lines, verified) | new clean-room schema design — public-spec authorship is a real design choice, not mechanical |
| M5: Sole native compiler | yes (after M4) | subset fixed in §2 + rev 0.3 additions (filtered measures, derived-over-metrics); salvaged `engines/native.py` (236 lines, verified) re-pointed to the typed graph; fan-out ⇒ `SemanticValidationError`; **fixes the LIKE-escape bug** (`issue:46e8f6219bf5`, verified present at `native.py:199-200` on the branch) | — |
| M6: Governance pipeline | no | RLS push-down and lineage rules are security-critical; the thinking model owns the AST strategy; **(rev 0.3)** salvaged as-is, engine-neutral | security design |
| M7: Role catalog + saved queries | yes | filter semantics fixed (`"*"` or list; `usage` list); suggestion = top-3 by difflib ratio; **(rev 0.3)** salvaged as-is | — |
| M8: Semantic audit ledger | yes | `SemanticAuditEntry` fields fixed below; `canonical_bytes` = sorted-key JSON without `signature`; **(rev 0.3)** `engine` field becomes a fixed `"native"` provenance value, salvaged as-is | — |
| M9: Execution bridge, compile cache, result handles | yes | `ConnectionResolver` env grammar fixed; LRU keyed by `CompiledQuery.cache_key`; handle fields and provenance fixed; salvage then apply rev 0.4 ownership changes | — |
| M10: SemanticLayerToolkit | no | orchestration of M4–M9 with ContextVar + static_subject; exposure rules; **(rev 0.4)** salvage then adapt to trusted identity/bootstrap and resolve `issue:3c4d154c0172` S3/S5 as mandatory security gates; track any remaining nits separately | integration surface |
| M9D: DuckDB prerequisite | yes | source API unchanged; real-file tests and thread-isolated connections | — |
| M9H: Guarded hand-off | no | protocol + read authorization + adapter conformance suite | security boundary |
| M11: HTTP handler + MCP config + docs | yes | `BaseView` pattern of `handlers/datasets.py`; YAML/JSON anchors in §6; **(rev 0.3)** drop the AGPL notice from docs/README | — |

**(rev 0.3) M12 removed** — superseded by FEAT-738 (TASK-4678/4679, merged 2026-10-24, PR #1801):
`AuthorizingDataSource._apply_rls` already returns a per-call target without mutating `self._inner`
(verified `authorizing.py:147,152`, 2026-10-25) and `_clone_agent_dm` already avoids sharing
`entry.source`; `test_authorizing_data_source.py` already asserts the non-mutating behavior. M9D is the sole core-source exception; M12 remains removed.

### Module 1: `ai-parrot-semantic` distribution skeleton
- **Path**: `packages/ai-parrot-semantic/pyproject.toml`, `README.md`, `src/parrot/semantic/__init__.py`, `src/parrot/semantic/version.py`, `tests/__init__.py`, `tests/conftest.py`; MODIFY root `pyproject.toml`, `scripts/release.py`, `ruff.toml`, `.github/workflows/ci.yml`
- **Responsibility**: make `parrot.semantic` an installable PEP 420 satellite (`src/parrot/` has **no** `__init__.py`; only `src/parrot/semantic/__init__.py`). **(rev 0.3)** pinned `sqlglot>=30.1,<31` (no `sidemantic` — dropped entirely), `jsonschema>=4.20`, `pyyaml>=6`, `ai-parrot`; extras `bigquery` (`google-cloud-bigquery>=3.30`), `duckdb` (`duckdb>=1.0`); `license = "MIT"`, no AGPL notice in README; workspace source entry; `release.py` `PACKAGES` entry; `ruff.toml` TID251 ban `"sidemantic"` **with no per-file ignore anywhere** (rev 0.2's exemption for `packages/ai-parrot-semantic/**` is removed — the ban now fires everywhere, including the satellite, since nothing in it needs sidemantic); CI step running the satellite tests.
- **Depends on**: nothing (first task).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-semantic/src/parrot/semantic/version.py  (new)
  __version__ = "1.3.0"

  # packages/ai-parrot-semantic/src/parrot/semantic/__init__.py  (new — written once here, finalized by M10)
  """ai-parrot-semantic — governed semantic layer (native sqlglot compiler + sqlglot governance)."""
  from .version import __version__
  __all__ = ["__version__"]
  ```
  ```toml
  # pyproject.toml  (modifies pyproject.toml:239 — append after `ai-parrot-openlit-bridge = { workspace = true }`)
  ai-parrot-semantic = { workspace = true }
  ```
  ```python
  # scripts/release.py  (modifies scripts/release.py:116 — new Package entry inside PACKAGES)
  Package("ai-parrot-semantic",
          [("packages/ai-parrot-semantic/src/parrot/semantic/version.py", "python")],
          "packages/ai-parrot-semantic", aliases=["semantic"]),
  ```
  ```toml
  # ruff.toml  (modifies ruff.toml:125 banned-api table — rev 0.3 adds NO per-file-ignore)
  "sidemantic".msg = "AGPL-3.0 removed from ai-parrot entirely (FEAT-704 rev2); do not reintroduce it anywhere, including the satellite."
  ```

### Module 2: Query & result contracts + error taxonomy
- **Path**: `packages/ai-parrot-semantic/src/parrot/semantic/models.py`, `errors.py`, `context.py` (identity model only)
- **Responsibility**: the pydantic contracts in §2 Data Models and the exception hierarchy. Validators: `saved_query` is exclusive with explicit members/filters/order; otherwise at least one metric, dimension or time dimension is required (dimension-value queries are valid); a `FilterGroup` never mixes metric leaves and dimension leaves (member kinds resolved later by M7, so the validator takes a `member_kinds: dict[str, Literal["metric","dimension"]]` argument via `SemanticQuery.validate_against(model_members)`); `offset > 0` requires `order_by`; `grain` required for time dimensions; `limit` ≥ 1.
- **Depends on**: M1.
- **Interface Skeleton**:
  ```python
  # parrot/semantic/errors.py  (new)
  class SemanticError(Exception): """Base for all semantic-layer errors; carries `code: str` and `details: dict`."""
  class SemanticValidationError(SemanticError): """Malformed or unsatisfiable SemanticQuery (unknown member, mixed filter group, missing grain, fan-out in native)."""
  class SemanticPolicyError(SemanticError): """Invalid model/policy definition (unknown member in policy, bad RLS binding, invalid own-format or Ossie document)."""
  class SemanticAccessError(SemanticError): """Denied: no PermissionContext, evaluator unavailable, PBAC denial, member not granted, usage right missing, unresolved lineage."""
  class SemanticExecutionError(SemanticError): """Database execution failed; `audit_id` set, SQL never included in the message."""
  class SemanticResultError(SemanticError): """Result handle unknown, foreign, expired or stale (context/policy changed)."""

  # parrot/semantic/models.py  (new)  — see §2 Data Models for fields
  class SemanticQuery(BaseModel):
      def canonical_json(self) -> str: """Sorted-key, whitespace-free JSON used in `CompiledQuery.cache_key`."""
      def validate_against(self, member_kinds: dict[str, str], time_dimensions: set[str]) -> None:
          """Raise SemanticValidationError for unknown members, mixed filter groups, missing grains."""
  class ModelMember(BaseModel): name: str; kind: Literal["metric", "dimension", "time_dimension", "entity"]; description: str = ""; grain: Grain | None = None; sensitive: bool = False
  ```

M2 also owns `context.py`'s identity model (M10 later adds the binding helpers; serialize these edits):

```python
class SemanticRequestIdentity(BaseModel, frozen=True):
    ctx: PermissionContext  # immutable snapshot of trusted session attributes, defensively copied
    channel: Literal["http", "agent", "mcp-local"]
    agent_id: str           # nonempty server-owned identifier
    session_id: str         # nonempty server-owned identifier, never request_id
```

### Module 3: Model policy side-file
- **Path**: `packages/ai-parrot-semantic/src/parrot/semantic/policy.py`
- **Responsibility**: parse and validate `<model>.policy.yaml` into `ModelPolicy`; compute `policy_digest`; answer role questions (`allowed_members(roles)`, `usage_allowed(roles, column)`, `mask_for(roles, column)`); reject unknown members (a misspelled binding must never silently remove a restriction); `governed` defaults to `true`.
- **Depends on**: M2.
- **Interface Skeleton**:
  ```python
  # parrot/semantic/policy.py  (new)
  class RoleGrant(BaseModel): metrics: list[str] | Literal["*"] = []; dimensions: list[str] | Literal["*"] = []; usage: list[str] | Literal["*"] = []
  class MaskRule(BaseModel): strategy: Literal["null", "hash", "partial"]; projection_roles: list[str] = []; usage_roles: list[str] = []
  class SavedQuery(BaseModel): name: str; query: SemanticQuery; verified_by: str; verified_at: date; description: str = ""
  class ModelPolicy(BaseModel):
      governed: bool = True; connection: str   # (rev 0.3) no `engine` field — the native compiler is the only engine
      limits: Limits = Limits(default=1000, max=10000)
      roles: dict[str, RoleGrant] = {}; masks: dict[str, MaskRule] = {}
      rls: list[RlsRule] = []            # RlsRule verified: packages/ai-parrot/src/parrot/auth/rls_registry.py:49
      saved_queries: list[SavedQuery] = []
      allowed_functions: list[str] = []   # §8 Q4 — ADDITIVE per-model extension of DEFAULT_ALLOWED_FUNCTIONS; upper-cased at load; cannot remove a default
      def digest(self) -> str: """SHA-256 of canonical JSON — part of every cache key and audit entry."""
      def allowed_members(self, roles: frozenset[str], members: list[ModelMember]) -> set[str]: """Union of grants over the subject's roles; empty set when no role matches."""
      def usage_allowed(self, roles: frozenset[str], column: str) -> bool: """True only when a matching grant lists the column in `usage` (or `"*"`); masked columns need `usage_roles`."""
      def mask_for(self, roles: frozenset[str], column: str) -> MaskRule | None: """Mask to apply in projection, or None when the column is unmasked for these roles."""
  def load_policy(path: Path, members: list[ModelMember], tables: set[str]) -> ModelPolicy:
      """Parse YAML; raise SemanticPolicyError on unknown members/tables, unknown roles syntax, or missing `connection` when `governed`.
      Every `rls[].predicate_template` is parsed with sqlglot at load (placeholders substituted by typed dummies): it must be a single
      boolean expression over columns of its `table`; anything else is a policy error, so RLS text is never trusted as raw SQL at runtime."""
  ```

### Module 4: Typed semantic model graph + loader, Ossie import (rev 0.3 — clean-room rewrite)
- **Path**: `packages/ai-parrot-semantic/src/parrot/semantic/model.py` (new), `loader.py` (new — a
  rewrite, not a port: the branch file of the same name is a **salvage reference only**, 386 lines,
  `LoadedModel` at line 58, `layer: Any` at line 64, `SemanticModelLoader` at line 73, verified
  2026-10-25), `ossie.py`, `schemas/ossie-0.1.1.schema.json` (vendored). **`engines/sidemantic_engine.py`
  is never created** (deleted from scope — it existed only on the branch, 169 lines, verified absent on dev).
- **Responsibility**: **(rev 0.3)** a frozen, clean-room `SemanticModel` graph (`Dimension` categorical/
  numeric/time+grain; `Metric` with `agg`/`sql`/optional `filter`/derived expression; `Relationship` with
  cardinality) authored from the *public* Cube, dbt MetricFlow and Apache Ossie 0.1.1 format
  documentation — never from sidemantic's code or API. The loader reads the own YAML format and Ossie
  documents (validated against the vendored 0.1.1 JSON Schema) into that graph; it salvages the branch's
  `PhysicalSchema` / `sqlglot_schema()` / digest-computation structure (engine-neutral plumbing) but
  rewrites the model-graph construction itself. Derives `ModelMember`s and the **physical schema map**
  (`schema.table` → columns/types) for `qualify`, lineage and RLS. No spike task: there is no third-party
  API to confirm (rev 0.2's M4 spike against the sidemantic wheel is dropped along with sidemantic).
- **Depends on**: M2, M3.
- **Interface Skeleton**:
  ```python
  # parrot/semantic/model.py  (new)
  class Dimension(BaseModel, frozen=True):
      name: str; kind: Literal["categorical", "numeric", "time"]; column: str
      grain: Grain | None = None   # required when kind == "time"
  class Metric(BaseModel, frozen=True):
      name: str; agg: Literal["sum", "count", "count_distinct", "avg", "min", "max"] | None = None
      column: str | None = None    # physical input for aggregate metrics; None only for count(*)
      sql: str | None = None       # derived-metric arithmetic over qualified metric names; mutually exclusive with agg/column/filter
      filter: "FilterGroup | None" = None   # filtered-measure (FILTER (WHERE …) / CASE WHEN, dialect-dependent)
  class Relationship(BaseModel, frozen=True):
      from_model: str; to_model: str; cardinality: Literal["one_to_many"]
      from_columns: tuple[str, ...]; to_columns: tuple[str, ...]  # paired physical keys
      join_type: Literal["inner", "left"] = "left"
  class SemanticModel(BaseModel, frozen=True):
      name: str; table: str; columns: dict[str, str]; primary_key: tuple[str, ...]
      dimensions: tuple[Dimension, ...]; metrics: tuple[Metric, ...]; relationships: tuple[Relationship, ...]
      def digest(self) -> str: """SHA-256 of canonical JSON — part of every cache key and audit entry."""

  # parrot/semantic/loader.py  (new — rewrite; salvages PhysicalSchema/digest plumbing only, see above)
  class PhysicalSchema(BaseModel):
      driver: str; tables: dict[str, dict[str, str]]   # "schema.table" -> {column: sqlglot type}
      def sqlglot_schema(self) -> dict: """Nested mapping accepted by sqlglot.optimizer.qualify.qualify(schema=...)."""
  class LoadedModel(BaseModel):
      name: str; model: SemanticModel   # (rev 0.3) was `layer: Any` (sidemantic graph) — now the typed graph
      related_models: dict[str, SemanticModel]
      policy: ModelPolicy; members: list[ModelMember]; schema: PhysicalSchema
      model_digest: str; policy_digest: str; compiler_version: str   # (rev 0.3) was `engine_version`
  class SemanticModelLoader:
      def __init__(self, models_dir: Path, *, driver: str) -> None: ...
      def load(self) -> dict[str, LoadedModel]:
          """Load every model + policy pair from the own YAML format and Ossie 0.1.1 documents; raise SemanticPolicyError for an unknown policy member or a policy/model mismatch."""
      def reload_if_changed(self) -> bool: """Re-read when any file mtime/digest changed; returns True when versions moved."""

  # parrot/semantic/ossie.py  (new)
  OSSIE_SPEC_VERSION = "0.1.1"
  def validate_ossie_document(doc: dict) -> None: """jsonschema-validate against the vendored schema; raise SemanticPolicyError with the first error path."""
  def is_ossie_document(doc: dict) -> bool

  # parrot/semantic/engines/__init__.py  (new)
  async def compile(query: SemanticQuery, model: LoadedModel, dialect: str, *, cache: "CompileCache | None" = None) -> CompiledQuery:
      """asyncio.to_thread wrapper around NativeCompiler(model).compile(query, dialect); LRU hit skips compilation only. No dispatch, no plugin protocol — the native compiler is the sole engine."""
  ```

### M4 model validation and join contract (rev 0.4)

- Own YAML uses exactly the fields above (`extra="forbid"` on all graph models); Ossie import lowers into the same graph. `columns` maps physical column names to sqlglot types and supplies the schema without a warehouse connection. Dimensions, metric inputs, keys and policy bindings must resolve against it. Collections are defensively copied; no loaded graph is mutated after publication.
- An aggregate has `agg` and no `sql`. `sum/avg/min/max/count_distinct` require `column`; `count` with no column means `COUNT(*)`, otherwise `COUNT(column)`. Its optional filter contains dimension leaves only. A derived metric has `sql` and no `agg`, `column` or `filter`; its closed grammar permits qualified metric references, numeric constants, parentheses and arithmetic only. Validate references, reject dependency cycles and expand dependencies in deterministic topological order. Divide-by-zero returns NULL using a compiler-owned CASE expression. Preserve dependency provenance for lineage and audit.
- Join key tuples are nonempty, equally sized and type-compatible. `from_model` is the one side: `from_columns` must equal its declared primary key; `to_columns` are the many-side foreign keys. Reject unknown models, self-joins, ambiguous paths and unsupported cardinalities at load/compile. The loader resolves a model directory as a graph; `LoadedModel` additionally carries `related_models: dict[str, SemanticModel]` for the reachable models. Its digest and physical manifest include the reachable graph, not only the root.
- Plan from the metric's row grain. Traversing many→one is safe; any traversal that can multiply rows contributing to an aggregate is rejected, including sibling many-side joins and mixed-grain metrics. Do not infer safety from `count_distinct`. A dimensions-only query may traverse declared joins and emits DISTINCT. Declaration of primary-key uniqueness is an authoring precondition, documented and exercised by fixtures; v1 does not inspect warehouse constraints.
- Example: `revenue={agg: sum, column: amount}` and `avg_order={sql: "orders.revenue / orders.order_count"}`; `customers(id)` → `orders(customer_id)` declares `from_columns: [id]`, `to_columns: [customer_id]`. Revenue grouped by customer attributes is safe; customer-level sums grouped by orders are rejected as fan-out.

### Module 5: Sole native compiler (rev 0.3 — promoted from "fallback")
- **Path**: `packages/ai-parrot-semantic/src/parrot/semantic/engines/native.py` — **salvaged from the
  branch** (236 lines, `NativeCompiler` at line 18, `compile` at line 26, `_joins_for` with fan-out
  rejection at lines 126-138, verified 2026-10-25), re-pointed from `LoadedModel.layer.graph` (6 call
  sites on the branch) to the typed `LoadedModel.model` graph of M4.
- **Responsibility**: compile the v1 subset — metrics with `sum/count/count_distinct/avg/min/max`, dimensions, `DATE_TRUNC` grains (`exp.DateTrunc`), declared one-to-many joins (fan-out ⇒ `SemanticValidationError`), filter tree (WHERE vs HAVING), order/limit/offset — into a sqlglot AST rendered per dialect. Metric/dimension expressions come from the typed `SemanticModel` (M4). **(rev 0.3 additions, per the rev2 proposal):** filtered measures lowered to `FILTER (WHERE …)` or `CASE WHEN` per dialect, and derived metrics computed over other metrics. **(rev 0.3 fix, mandatory — `issue:46e8f6219bf5`):** the branch's `contains` filter builds `exp.Like(this=column, expression=exp.Literal.string(f"%{value}%"))` with **no escaping** of `%`/`_` in the user value (verified present at `native.py:199-200`, 2026-10-25) — a value of `"%"` matches every row. This bug was originally opened against `sidemantic_engine.py::filter_tree_to_sidemantic` (now deleted); it reproduces identically in the sole surviving filter-translation path and must be fixed here: escape `\`, `%`, `_` in the value and add an `exp.Escape` clause, plus a regression test. Ledger issue `issue:46e8f6219bf5` is re-pointed to this file and closed by the fixing task. Golden-SQL snapshots (postgres/bigquery/duckdb) + a DuckDB execution oracle against hand-computed expectations + a cross-process determinism hash check replace the former sidemantic-parity tests (no sidemantic to compare against).
- **Depends on**: M2, M3, M4 (`LoadedModel`, `PhysicalSchema`).
- **Interface Skeleton**:
  ```python
  # parrot/semantic/engines/native.py  (new)
  NATIVE_AGGREGATIONS = ("sum", "count", "count_distinct", "avg", "min", "max")
  class NativeCompiler:
      def __init__(self, model: LoadedModel) -> None: ...
      def compile(self, query: SemanticQuery, dialect: str) -> CompiledQuery:
          """Build exp.Select; raise SemanticValidationError for unsupported metric types or many-to-many joins."""
      def _grain_expr(self, column: exp.Column, grain: Grain) -> exp.Expression: """exp.DateTrunc(unit=grain)."""
  ```

### Module 6: Governance pipeline (PBAC gate, lineage, RLS push-down, masking, positive guard)
- **Path**: `packages/ai-parrot-semantic/src/parrot/semantic/governance/__init__.py`, `pbac.py`, `lineage.py`, `rls.py`, `masking.py`, `guard.py`, `pipeline.py`
- **Responsibility**: the security-critical sqlglot pass of §2 step 3, applied to a **clone** of the compiled AST on every request. Order is fixed: `QueryValidator.validate_sql_ast(read_only=True)` → `qualify(schema)` → `PhysicalResources` from `exp.Table`s → `PbacGate.authorize` → `ColumnLineage` usage rights → `RlsPushdown` → `Masking` → `PositiveGuard` → render. Any failure raises `SemanticAccessError`/`SemanticValidationError`; no partial SQL leaves the pipeline.
- **Depends on**: M2, M3, M4 (`PhysicalSchema`); core `DataPlanePolicyGuard`, `RlsRegistry`, `PermissionContext`, `QueryValidator`.
- **Interface Skeleton**:
  ```python
  # parrot/semantic/governance/pbac.py  (new)
  class PbacGate:
      def __init__(self, guard: DataPlanePolicyGuard | None) -> None:   # DataPlanePolicyGuard verified: packages/ai-parrot/src/parrot/auth/dataplane_guard.py:45
          """Probe navigator_auth.abac.policies.environment and navigator_auth.abac.policies.evaluator at construction, and require a configured guard/evaluator; record `available`."""
      async def authorize_manifest(self, ctx: PermissionContext | None, model: "LoadedModel") -> PhysicalResources:
          """Phase (a): authorize the model's declared driver + all schema-map tables BEFORE compile; returns the authorized manifest."""
      async def authorize(self, ctx: PermissionContext | None, resources: PhysicalResources, *, governed: bool, manifest: PhysicalResources | None = None) -> None:   # PhysicalResources verified: resolver.py:47
          """Phase (b): governed and (ctx is None or not self.available) → SemanticAccessError; resources.tables ⊄ manifest.tables → SemanticAccessError; else guard.authorize_source(ctx, resources) (dataplane_guard.py:193) mapping AuthorizationRequired → SemanticAccessError."""
  def resources_from_ast(tree: exp.Expression, driver: str) -> PhysicalResources: """`tables={f"{driver}:{schema}.{table}"}` from every exp.Table after qualify."""

  # parrot/semantic/governance/lineage.py  (new)
  class ColumnUse(BaseModel): column: str; table: str; context: Literal["projection", "where", "having", "join", "group_by", "order_by", "window", "derived"]
  def resolve_column_uses(tree: exp.Expression, schema: PhysicalSchema) -> list[ColumnUse]:
      """Walk aliases, CTEs, subqueries and derived expressions back to physical columns; raise SemanticAccessError('unresolved_lineage') when any column cannot be resolved."""
  def enforce_usage_rights(uses: list[ColumnUse], policy: ModelPolicy, roles: frozenset[str], *, trusted_nodes: set[int]) -> None:
      """Deny any non-projection use of a masked/hidden column without usage rights; nodes injected by RLS/masking are trusted by identity, never by caller labels."""

  # parrot/semantic/governance/rls.py  (new)
  class RlsPushdown:
      def __init__(self, registry: RlsRegistry) -> None: ...                     # RlsRegistry verified: rls_registry.py:87
      def apply(self, tree: exp.Expression, ctx: PermissionContext, driver: str) -> tuple[exp.Expression, tuple[str, ...], set[int]]:
          """For each exp.Table with rules (registry.lookup, rls_registry.py:125) render (registry.render, :150) and wrap the scan as a filtered subquery BELOW any aggregation, preserving aliases, CTEs, joins and column visibility; bound values become typed exp.Literal (type taken from the schema map). Table functions, lateral/unnest sources, recursive CTEs or any construct the rewrite cannot place deterministically → SemanticAccessError — never a fall back to wrapping the outer statement. Returns (tree, applied rule descriptions, trusted node ids)."""

  # parrot/semantic/governance/masking.py  (new)
  def apply_masks(tree: exp.Expression, uses: list[ColumnUse], policy: ModelPolicy, roles: frozenset[str], dialect: str) -> tuple[exp.Expression, tuple[str, ...], set[int]]:
      """Rewrite projected masked columns per MaskRule.strategy (null / md5-hash / partial); returns masked column names and trusted node ids."""

  # parrot/semantic/governance/guard.py  (new)
  DEFAULT_ALLOWED_FUNCTIONS: frozenset[str] = frozenset({"SUM", "COUNT", "AVG", "MIN", "MAX", "DATE_TRUNC", "EXTRACT", "COALESCE", "CAST", "LOWER", "UPPER"})   # §8 Q4; COUNT DISTINCT is exp.Count(distinct=True); arithmetic/comparison/boolean are operator nodes, always allowed
  def effective_allowed_functions(policy: ModelPolicy, extra: frozenset[str] | None) -> frozenset[str]:
      """DEFAULT_ALLOWED_FUNCTIONS ∪ (extra or ∅) ∪ {f.upper() for f in policy.allowed_functions} — additive only (§8 Q4)."""
  class PositiveGuard:
      def __init__(self, schema: PhysicalSchema, allowed_functions: frozenset[str], limits: Limits) -> None: ...
      def check_and_limit(self, tree: exp.Expression) -> exp.Expression:
          """Exactly one exp.Select root (CTEs allowed); every table/column in schema; every function allowlisted; no exp.Command/DDL/DML; inject or clamp LIMIT; raise SemanticValidationError otherwise."""

  # parrot/semantic/governance/pipeline.py  (new)
  class GovernancePipeline:
      def __init__(self, *, pbac: PbacGate, rls: RlsPushdown, allowed_functions: frozenset[str]) -> None: ...
      async def govern(self, sql: str, *, model: LoadedModel, ctx: PermissionContext | None, roles: frozenset[str]) -> GovernedQuery:
          """Full pass of §2 step 3 on a parsed clone; used for compiled SQL, saved queries, dimension-value lookups and raw SQL alike."""
  ```

### Module 7: Role catalog and saved queries
- **Path**: `packages/ai-parrot-semantic/src/parrot/semantic/catalog.py`
- **Responsibility**: the role-filtered view the LLM sees (`list_models`, `list_metrics`, `get_dimensions`, `search_data_model`, `list_saved_queries`); member-right checks on **every** referenced member including filters, ordering and dimension-value requests (unlisted → `SemanticAccessError` with up to three suggestions among *allowed* members); saved-query expansion (`saved_query` → full `SemanticQuery`) before compile.
- **Depends on**: M2, M3, M4.
- **Interface Skeleton**:
  ```python
  # parrot/semantic/catalog.py  (new)
  class RoleCatalog:
      def __init__(self, models: dict[str, LoadedModel]) -> None: ...
      def visible_members(self, model: str, roles: frozenset[str], *, authorized: bool) -> list[ModelMember]: """Allowed, unmasked-or-projection-permitted members only; a governed model with authorized=False (no subject / PBAC manifest denied) exposes nothing — not even member names."""
      def check_query_rights(self, query: SemanticQuery, roles: frozenset[str]) -> None: """Every metric/dimension/time dimension/filter/order member must be allowed; else SemanticAccessError with `suggestions`."""
      def expand_saved_query(self, query: SemanticQuery) -> SemanticQuery: """Replace `saved_query` with the stored query (same model); unknown name → SemanticValidationError."""
      def search(self, text: str, roles: frozenset[str], model: str | None = None) -> list[dict]: """Case-insensitive substring + difflib ranking over visible members and descriptions."""
  ```

### Module 8: Semantic audit ledger
- **Path**: `packages/ai-parrot-semantic/src/parrot/semantic/audit.py`, `sql/semantic_audit_events.sql` (§8 Q3)
- **Responsibility**: `SemanticAuditEntry` (signed) and `SemanticAuditLedger` reusing core signers and the async `storage(json_str)` callable contract of `AuditLedger` (audit_ledger.py:327-336, 380-405). Separate from `AuditLedger` by decision; zero core change.
- **Depends on**: M2; core `AbstractKMSSigner`.
- **Interface Skeleton**:
  ```python
  # parrot/semantic/audit.py  (new)
  class SemanticAuditEntry(BaseModel):
      schema_version: int = 1
      entry_id: str; created_at: datetime; user_id: str; tenant_id: str; channel: str; agent_id: str | None
      subject_digest: str; roles: list[str]; static_subject: bool
      model: str; model_digest: str; policy_digest: str; engine: str = "native"; tool: str   # (rev 0.3) fixed provenance value, no dispatch
      structured_query: dict | None; raw_sql: bool
      compiled_sql: str | None; governed_sql: str | None; dialect: str; driver: str
      rls_applied: list[str]; masked_columns: list[str]; pbac: Literal["allow", "deny", "unavailable", "not_governed"]
      outcome: Literal["ok", "denied", "validation_error", "execution_error"]; error_code: str | None
      row_count: int | None; duration_ms: int | None; signature: str = ""
      def canonical_bytes(self) -> bytes: """Sorted-key JSON without `signature` (same approach as AuditLedgerEntry.canonical_bytes, audit_ledger.py:109)."""
  class SemanticAuditLedger:
      def __init__(self, signer: AbstractKMSSigner | None = None, storage: Callable[[str], Awaitable[None]] | None = None, max_entries: int = 10_000) -> None: ...   # AbstractKMSSigner verified: audit_ledger.py:135
      async def append(self, entry: SemanticAuditEntry, *, required: bool = False) -> SemanticAuditEntry:
          """Sign, keep in a bounded in-memory deque, forward JSON to `storage`. Storage failure is logged; when `required=True` it raises SemanticExecutionError('audit_unavailable') so the toolkit withholds results (toolkit kwarg `audit_required`, resolved per §8 Q5: None → True iff a durable `storage` is configured)."""
      async def verify(self, entry: SemanticAuditEntry) -> bool: """Await signer.verify(canonical_bytes, signature); never block the event loop."""
      @property
      def durable(self) -> bool: """True when a `storage` callable is configured — drives the `audit_required=None` resolution in M10."""
  def postgres_audit_storage(dsn_or_pool: str | Any, *, table: str = "semantic_audit_events") -> Callable[[str], Awaitable[None]]:
      """§8 Q3 — return an async `storage(json_str)` callable that INSERTs the entry into `table` (DDL: parrot/semantic/sql/semantic_audit_events.sql) via asyncpg (`asyncdb` is NOT used — the satellite depends only on `ai-parrot`'s asyncpg). Connection errors propagate to `append()`, which applies the `required` rule."""
  ```

### Module 9: Execution bridge, compile cache, result handles
- **Path**: `packages/ai-parrot-semantic/src/parrot/semantic/execution.py`, `cache.py`, `results.py`
- **Responsibility**: `ConnectionResolver` (named connection → credentials dict: env prefix `PARROT_SEMANTIC_CONN_<NAME>_<KEY>` overlaid on `parrot.interfaces.database.get_default_credentials(driver)`), `Executor` (run a `GovernedQuery` through `DatabaseQueryToolkit.get_source(driver).query(credentials, sql)`, time it, cap rows), `CompileCache` (LRU of **pre-governance** `CompiledQuery` only, keyed by `cache_key`; invalidated when model/policy digests change), `ResultHandleStore` (bounded, TTL, owner-bound handles; `claim()` re-verifies owner/session/context/policy versions).
- **Depends on**: M2, M6; core `DatabaseQueryToolkit`, `get_default_credentials`.
- **Interface Skeleton**:
  ```python
  # parrot/semantic/execution.py  (new)
  class ConnectionResolver:
      def __init__(self, env: Mapping[str, str] | None = None) -> None: ...
      def resolve(self, connection: str, driver: str) -> dict[str, Any]:
          """get_default_credentials(driver) (verified: packages/ai-parrot/src/parrot/interfaces/database.py:501) overlaid with PARROT_SEMANTIC_CONN_<CONNECTION>_<KEY> env vars; empty → SemanticExecutionError('no_credentials')."""
  class Executor:
      def __init__(self, toolkit: DatabaseQueryToolkit, resolver: ConnectionResolver) -> None: ...   # DatabaseQueryToolkit verified: toolkit.py:115
      async def run(self, governed: GovernedQuery, *, connection: str) -> tuple[list[dict], int, bool, int]:
          """source = toolkit.get_source(driver) (toolkit.py:202); rows = await source.query(credentials, sql) (base.py:446); returns (rows, row_count, truncated, duration_ms)."""

  # parrot/semantic/cache.py  (new)
  class CompileCache:
      def __init__(self, max_entries: int = 512) -> None: ...
      def get(self, key: str) -> CompiledQuery | None
      def put(self, compiled: CompiledQuery) -> None
      def invalidate_model(self, model_digest: str) -> int

  # parrot/semantic/results.py  (new)
  class ResultHandle(BaseModel):
      result_id: str; agent_id: str; user_id: str; tenant_id: str; session_id: str
      subject_digest: str   # SHA-256 over (user_id, tenant_id, sorted roles, sorted policy-relevant session.metadata items) — metadata is NOT part of UserSession's hash (permission.py:49), so it is hashed explicitly here
      model: str; model_digest: str; policy_digest: str; expires_at: datetime
      members: tuple[str, ...]  # exact semantic members referenced, including filters/order/dependencies
      physical_columns: tuple[str, ...]; physical_tables: tuple[str, ...]  # qualified lineage, including raw SQL
      columns: list[str]; rows: list[dict]; audit_id: str; governed_sql: str
  class ResultHandleStore:
      def __init__(self, *, ttl_s: int = 900, max_entries: int = 256) -> None: ...
      def put(self, handle: ResultHandle) -> str: """Opaque random id (secrets.token_urlsafe)."""
      def claim(self, result_id: str, *, identity: SemanticRequestIdentity, subject_digest: str, model_digest: str, policy_digest: str) -> ResultHandle:
          """identity.ctx user/tenant, identity.agent_id/session_id, context digest and versions must all match and the handle must be unexpired; else SemanticResultError. Metadata alone is never authorization."""
  ```

### M9D: DuckDB execution prerequisite (rev 0.4)

- **MODIFY** `packages/ai-parrot/src/parrot/tools/databasequery/sources/duckdb.py`; **CREATE** `packages/ai-parrot/tests/test_semantic_duckdb_source.py`.
- Restore the rev2 proposal §3 prerequisite, manually applying the behavior of branch commit `b9f9983d67` to current dev: execute the DuckDB Python API in `asyncio.to_thread` with a per-call connection closed in `finally`, preserving source signatures and QueryResult/RowResult contracts. Keep DuckDB optional through a lazy import with a clear missing-extra error. No other database source or core API changes.
- The old asyncdb path awaited synchronous `fetchall()`; do not substitute a fake source in the semantic integration tests. Test a real temporary database: query, query_row, metadata, empty result columns, named/positional parameters, error cleanup and event-loop responsiveness. Store logs under `artifacts/logs/`.
- **Depends on** M1 for the test environment; M9's DuckDB integration and M10 security suite depend on M9D. M12 stays removed: do not copy the branch's authorizing/dataset-handler edits or lockfile. Regenerate the task index to give M9D an explicit owner and dependency edges.

### M9H: Guarded dataset hand-off contract (rev 0.4)

- **CREATE** `packages/ai-parrot-semantic/src/parrot/semantic/handoff.py`. A plain `DatasetManager`, including the existing HTTP session manager, is not a valid hand-off target: `add_dataframe()` preloads an InMemorySource and does not revalidate semantic policy on reads.
- Replace the bare-manager factory contract with `dataset_manager_factory(identity: SemanticRequestIdentity) -> Awaitable[GovernedDatasetSink]`. This is a trusted host integration, never an LLM parameter. The sink has a nonempty opaque `scope_id`, an immutable owner tuple `(agent_id, user_id, tenant_id, session_id)`, and `async publish(name: str, handle: ResultHandle, authorize_read: Callable[[SemanticRequestIdentity], Awaitable[None]]) -> dict`. Scope reuse across different owners is refused.
- `authorize_read` is constructed by the satellite and closes over immutable provenance, not the original PermissionContext. It loads current model/policy versions, requires an unexpired handle, compares the current owner and subject digest, authorizes the current manifest through PBAC and checks **all** retained semantic members and physical-column usage. Any changed version/context, revoked grant, missing provenance or unavailable evaluator denies; never re-filter stale aggregates. Raw-SQL handles retain resolved physical lineage and must pass the same checks.
- The sink declares `guarded_reads: Literal[True]`; this is a host capability assertion, not proof of safety, so the conformance suite is mandatory. A conforming sink invokes `authorize_read` immediately before every exposure: list/describe/sample, cached reads, dataframe retrieval, SQL queries and exports. Derived datasets inherit provenance and the earliest expiry of all inputs. A publication stores a defensive snapshot; it never exposes the private manager, an unguarded source, dataframe reference or alternate dataset endpoint. On denial it withholds data and metadata; expiry/revocation removes cached copies. Authorization and publication/read use one immutable version snapshot; reject if reload changes that snapshot before return.
- The satellite ships the protocol, authorization callback and a reusable adapter conformance suite. Hosts must explicitly register an adapter that passes that suite; a raw manager or an adapter without guarded-read capability is rejected. No default adapter over `DatasetManagerHandler._get_dataset_manager()` is supplied. Without one, the save tool is absent and HTTP hand-off returns `handoff_unavailable`; normal query/compile surfaces remain usable. The suite exercises a representative host adapter and rejects a plain-manager factory; it does not assume metadata tags constitute enforcement.
- Hand-off tests cover read after expiry, model/policy change, PBAC revocation with unchanged roles, removed member rights, changed subject metadata, two users/two sessions, cached/derived outputs and missing identity. Creating a handle alone is not authorization to publish it.
- **Depends on** M2, M3, M6, M7, M9; M10/M11 hand-off integration depends on M9H. Host adapter implementation is opt-in host responsibility; this feature ships no unguarded fallback.

### Module 10: `SemanticLayerToolkit`
- **Path**: `packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py`, `context.py`, `bootstrap.py`; finalize `__init__.py` exports
- **Responsibility**: the `AbstractToolkit` surface of §2 New Public Interfaces. The trusted wrapper binds identity and both ContextVars; `_pre_execute` validates `_permission_context` against that binding; every tool goes catalog-check → compile (cached) → govern → execute → audit → return (compile/catalog omit execution). Context binding and cleanup follow the rev 0.4 contract below. `run_sql` exposed only when `allow_raw_sql=True`; `save_result_as_dataset` only when a conforming `dataset_manager_factory` is provided (via `exclude_tools`, like `DatabaseQueryToolkit` does for `save_result`, toolkit.py:175-176). A `governed` model with no `dataplane_guard` makes the toolkit refuse to construct (fail closed at startup).
- **Depends on**: M3–M9, M9D and M9H.
- **Interface Skeleton**:
  ```python
  # parrot/semantic/context.py  (new)
  _semantic_pctx_var: contextvars.ContextVar[PermissionContext | None]
  def current_pctx() -> PermissionContext | None

  # parrot/semantic/toolkit.py  (new)
  class StaticSubject(BaseModel): user_id: str; tenant_id: str; roles: list[str]; metadata: dict[str, Any] = {}
  class SemanticLayerToolkit(AbstractToolkit):               # AbstractToolkit verified: packages/ai-parrot/src/parrot/tools/toolkit.py:225
      tool_prefix = "sl"
      exclude_tools = ("reload",)
      def __init__(self, **kwargs: Any) -> None:
          """kwargs: models_dir, dialect, dataplane_guard, rls_registry, database_toolkit, signer, audit_storage,
          allow_raw_sql=False, static_subject=None, dataset_manager_factory=None, result_ttl_s=900, result_store_max=256,
          allowed_functions=None, audit_required=None. `audit_required` None → ledger.durable (§8 Q5); explicit bool wins. Raises SemanticPolicyError when a governed model exists and dataplane_guard is None."""
      async def _pre_execute(self, tool_name: str, /, **kwargs) -> None:   # hook contract verified: toolkit.py:491, pctx kwarg toolkit.py:174-178
          """Validate the bound trusted identity against kwargs['_permission_context']; never fall back to static identity here."""
      async def _post_execute(self, tool_name: str, result: Any, /, **kwargs) -> Any:   # toolkit.py:506 — serialize pydantic results to dicts
      # tools — see §2 New Public Interfaces for signatures/docstrings
      def reload(self) -> None: """Not a tool; re-run the loader and invalidate caches."""
      def _dataset_manager_for(self, identity: SemanticRequestIdentity) -> Awaitable[GovernedDatasetSink]: """Require the M9H guarded sink capability and exact owner tuple; reject raw/shared managers."""
  ```

### M10 trusted request identity and bootstrap (rev 0.4)

Uses `SemanticRequestIdentity` defined by M2 in `context.py`; no fields are added to core PermissionContext.

- Server/agent hosts bind this identity through a satellite async context manager around the complete call. It sets both satellite identity and `parrot.auth.context._pctx_var`, keeps reset tokens locally and resets in `finally`, including failures/cancellation. `_pre_execute` validates that its `_permission_context` matches the bound identity; it must not elevate a missing context to static identity. The `_post_execute` hook is not a cleanup boundary: core skips it on exceptions. HTTP dispatch uses the same binding around direct method calls.
- HTTP obtains agent identity from the resolved authorized agent route and session identity from the authenticated server session. Agent adapters supply the server-owned agent/conversation identifiers. `request_id` is not a session id. Caller JSON, tool arguments and arbitrary metadata cannot set these fields. When only a trusted PermissionContext is available, the wrapper binds that context without constructing SemanticRequestIdentity; `_pre_execute` may permit an otherwise authorized query, but retention is disabled and creating/claiming/publishing a handle is denied. Empty identifiers are invalid. Do not use null/default identifiers to collapse unrelated sessions.
- Default `SemanticLayerToolkit` rejects `static_subject` at construction. New satellite `LocalSemanticLayerToolkit` in `bootstrap.py` is the sole static-identity entry point; it is for trusted stdio configuration only and is forbidden in the HTTP handler/agent registry. It requires `static_subject`, configured `agent_id` and `guard_factory`, fixes channel to `mcp-local`, and creates a random process-session id once per instance. Requests cannot override these. Its tool execution wrapper supplies the configured static PermissionContext to the wrapped ToolkitTool call and binds/resets identity in `try/finally`; no core hook edits are needed. HTTP explicitly rejects this local-only class. Static use is logged/audited on every call.
- `guard_factory` is a trusted configuration-only dotted callable with signature `factory(*, rls_registry: RlsRegistry, **configured_kwargs) -> DataPlanePolicyGuard`; optional JSON `guard_factory_kwargs` hold non-secret policy locations only and are passed as additional keyword arguments to the factory. The satellite imports/calls it synchronously at startup and validates the guard and exact navigator-auth submodule availability. The host factory constructs the evaluator from its configured policy store; credentials remain environment-only. Missing factory, missing modules, invalid result or failed policy loading makes startup fail closed. Never synthesize an allow-all evaluator from the static subject's roles. Ordinary server instances receive their existing guard by dependency injection.
- `bootstrap.py` documents this host factory contract and ships a test fixture factory with explicit allow/deny policies. MCP tests start the actual local toolkit with governed models and this factory, then test a permitted and denied call. Tests also reject absent factory and operator-identity fallback on HTTP/agent calls. The generic MCP factory is unchanged: it instantiates the configured local subclass from YAML kwargs.
- Before publishing, require every handle member to remain allowed (including filters/order/derived dependencies), and check raw SQL's retained lineage. Output aliases are never reverse-guessed into member names. S3 and S5 from `issue:3c4d154c0172` are release gates, not optional salvage hardening.

### Module 11: HTTP handler, MCP exposure, docs
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/semantic.py` (new); MODIFY `packages/ai-parrot-server/src/parrot/manager/manager.py`, `.parrot/mcp-toolkits.yaml`, `.mcp.json`; `docs/tools/semantic-layer.md` (new)
- **Responsibility**: `SemanticLayerHandler(BaseView)` with `GET` (catalog for the session subject), `POST …/compile`, `POST …/query`, `POST …/results/{result_id}/dataset`; `PermissionContext` from the navigator-auth session (same decorators as `handlers/datasets.py:20`); the hand-off factory must be an explicitly configured M9H guarded sink; the existing session manager alone is not eligible. Obtain and bind trusted request identity per M10; reject local-only static toolkits. Registration in `manager.py` guarded by `importlib.util.find_spec("parrot.semantic")`. MCP: a `semantic-layer:` section (class path, `kwargs` incl. `static_subject`, `env`) + `.mcp.json` entry mirroring `parrot-database-query`. Docs: `docs/tools/semantic-layer.md` (tools, policy file, mcp-local identity). **(rev 0.3)** no AGPL notice — there is no AGPL dependency to document.
- **Depends on**: M10.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-server/src/parrot/handlers/semantic.py  (new)
  class SemanticLayerHandler(BaseView):                        # BaseView import verified: handlers/datasets.py:19
      async def get(self) -> web.Response: """Role-filtered catalog for {agent_id}."""
      async def post(self) -> web.Response: """Dispatch on the tail route: compile | query | results/{result_id}/dataset."""
      async def _toolkit(self, agent_id: str) -> "SemanticLayerToolkit": """Agent's configured toolkit (lazy import of parrot.semantic)."""
      async def _pctx(self) -> PermissionContext: """From the navigator-auth session; 401 when absent."""

  # packages/ai-parrot-server/src/parrot/manager/manager.py  (modifies manager.py:2571 — add after the DatasetManagerHandler views)
  if importlib.util.find_spec("parrot.semantic") is not None:
      from ..handlers.semantic import SemanticLayerHandler
      router.add_view("/api/v1/agents/semantic/{agent_id}", SemanticLayerHandler)
      router.add_view("/api/v1/agents/semantic/{agent_id}/{tail:.*}", SemanticLayerHandler)
  ```
  ```yaml
  # .parrot/mcp-toolkits.yaml  (modifies .parrot/mcp-toolkits.yaml:110 — new sibling section before `database-query:`; verified 2026-10-25, was :121 in rev 0.2)
  semantic-layer:
    class: parrot.semantic.bootstrap.LocalSemanticLayerToolkit
    kwargs:
      models_dir: /path/to/models
      dialect: duckdb
      agent_id: local-semantic
      static_subject: {user_id: operator, tenant_id: local, roles: [admin]}
      guard_factory: myapp.semantic_auth.build_guard  # host-supplied callable, required
      guard_factory_kwargs: {policy_dir: /path/to/policies}
    env: {}
  ```

---

### Module 12 — removed (rev 0.3)

Rev 0.2's M12 (`issue:90cf04ce8edd`, request-scoped RLS fix in `AuthorizingDataSource` /
`_clone_agent_dm`) is **superseded by FEAT-738** (TASK-4678/4679, merged 2026-10-24): the identical
fix already ships on `dev` — `_apply_rls` returns a per-call target instead of mutating `self._inner`
(verified `authorizing.py:147,152`, 2026-10-25) and `_clone_agent_dm` no longer shares `entry.source`
directly (verified `datasets.py:48,131`). `test_authorizing_data_source.py` already asserts the
fetch-target behavior rather than the old buggy in-place mutation. M9D is the sole core-source exception; M12 remains removed.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_packaging_namespace` | M1 | `import parrot.semantic` works alongside core; `src/parrot/` has no `__init__.py`; version matches |
| `test_sidemantic_import_ban_no_exemption` | M1 | `ruff check` flags `import sidemantic` under `packages/ai-parrot/src` AND under the satellite — no per-file ignore exists anywhere (rev 0.3) |
| `test_semantic_query_validators` | M2 | saved-query exclusivity and dimensions-only queries; mixed filter group rejected; offset needs order_by; grain required |
| `test_canonical_json_stable` | M2 | key order / whitespace independent |
| `test_policy_unknown_member_rejected` | M3 | misspelled metric/table/role binding → `SemanticPolicyError` |
| `test_policy_defaults_governed` | M3 | missing `governed` → `True`; `governed: false` honoured |
| `test_model_graph_clean_room_digest` | M4 | `SemanticModel` built from own YAML + Ossie fixtures only; digest is canonical-JSON SHA-256; no sidemantic import anywhere in the module |
| `test_ossie_schema_validation` | M4 | Apache Ossie 0.1.1 fixtures load; a schema-invalid doc fails with the error path |
| `test_native_compile_pg_bq_duckdb` | M4/M5 | same query → three dialects, no connection, output has no subject values |
| `test_native_compiler_subset` | M5 | aggregations, grains, 1:N joins, filtered measures (`FILTER`/`CASE WHEN`), derived metrics-over-metrics compile; many-to-many → `SemanticValidationError` |
| `test_contains_filter_escapes_like_wildcards` | M5 | `issue:46e8f6219bf5` — a filter value of `%` or `_` matches only its literal self, not every row/any char; `exp.Escape` clause present |
| `test_native_golden_sql_duckdb_oracle` | M5 | per-dialect golden-SQL snapshots + DuckDB execution against hand-computed expected rows replace the sidemantic parity oracle |
| `test_native_cross_process_determinism` | M5 | same (model digest, canonical query, dialect) across two processes → byte-identical SQL (no dict/set iteration order leak) |
| `test_pbac_gate_fail_closed` | M6 | ctx None / guard None / evaluator unavailable on governed → `SemanticAccessError`; ungoverned passes |
| `test_pbac_denied_table_blocks_sql` | M6 | `table:read` denied on one joined table → no SQL returned, source never called |
| `test_rls_pushdown_below_aggregation` | M6 | `SUM` over a tenant-filtered base scan equals the expected subset; wrapping strategy would differ |
| `test_rls_typed_literals_and_render_failure` | M6 | values are literals (quotes escaped); render failure → deny |
| `test_lineage_masked_column_inference` | M6 | `WHERE salary > x`, HAVING, JOIN, GROUP BY, ORDER BY, window, alias, CTE, derived → denied without usage rights |
| `test_masking_strategies` | M6 | null / hash / partial projections; catalog hides hidden members |
| `test_positive_guard` | M6 | unknown column/function/table, DDL/DML, multi-statement, missing LIMIT, over-cap LIMIT |
| `test_positive_guard_adversarial_matrix` | M6 | `SELECT *`, quoted/mixed-case identifiers, aliases, CTEs, nested subqueries, windows, joins, derived sensitive columns, `exp.Command`, comments — across postgres / bigquery / duckdb dialects |
| `test_dialect_sql_snapshots` | M5 | normalized-AST snapshots of the fixture queries for postgres and bigquery — a diff is a release gate, not a warning |
| `test_catalog_role_filtering_and_suggestions` | M7 | unlisted member → error with ≤3 suggestions among allowed members; empty catalog message |
| `test_saved_query_expansion` | M7 | expansion then rights check; unknown name |
| `test_audit_entry_signature` | M8 | sign/verify round-trip; storage callable receives JSON; storage failure logged not raised |
| `test_connection_resolver_env_overlay` | M9 | `PARROT_SEMANTIC_CONN_X_PASSWORD` overrides default; missing → `no_credentials` |
| `test_compile_cache_pre_governance_only` | M9 | cached SQL contains no predicate values; digest change invalidates |
| `test_result_handle_ownership` | M9 | foreign / expired / changed-context / changed-policy handles rejected |
| `test_toolkit_tool_exposure` | M10 | `sl_run_sql` absent unless `allow_raw_sql`; `sl_save_result_as_dataset` absent without factory; governed+no guard → constructor error |
| `test_toolkit_static_subject_logged` | M10 | mcp-local identity used, flagged in audit |
| `test_toolkit_shared_manager_rejected` | M10 | factory returning the same manager for two subjects → `SemanticResultError` |
| `test_handler_routes_and_401` | M11 | registration only when `parrot.semantic` importable; 401 without session |
| `test_mcp_toolkits_yaml_section` | M11 | `load_toolkits_config` parses the `semantic-layer` section into `ToolkitSection` |
| `test_policy_allowed_functions_additive` | M3/M6 | `allowed_functions: [REGEXP_REPLACE]` extends the default set; a policy cannot drop `SUM`; lower-case names normalised |
| `test_audit_required_resolution` | M10 | `audit_required=None` → `True` with `audit_storage`, `False` without; explicit bool wins; `True` + failing sink withholds the result |
| `test_postgres_audit_storage_insert` | M8 | `postgres_audit_storage` callable INSERTs the JSON row into a fake asyncpg pool; DDL file parses (sqlglot, postgres) |

### Review regression gates (rev 0.4)
| Test | Required evidence |
|---|---|
| `test_model_inputs_and_join_keys` | Own YAML/Ossie lowering preserves aggregate inputs, physical types, composite join keys; missing/invalid keys and derived cycles fail |
| `test_join_grain_safety` | Many→one sums equal hand-computed rows; one→many and sibling fan-out reject; graph digest changes when a related model changes |
| `test_identity_scope_and_cleanup` | Same user in two sessions/agents cannot claim the other's handle; missing identity disables retention; failure/cancellation restores both ContextVars |
| `test_static_subject_local_only` | HTTP/agent construction and calls cannot fall back to operator identity; local subclass cannot be attached to HTTP |
| `test_handoff_exact_provenance` | A visible unrelated member does not authorize handle members; aliases/raw SQL retain exact lineage |
| `test_guarded_sink_conformance` | Every read/list/metadata/cache/export/derived route checks current identity, grants, versions and expiry; plain-manager factories reject |
| `test_mcp_governed_bootstrap` | Actual config/factory startup and allow/deny calls; missing/invalid factory and unavailable evaluator fail closed |
| `test_semantic_duckdb_source` | M9D real-file source tests, no source mocks; integration suite uses repaired stock source |

### Integration Tests
| Test | Description |
|---|---|
| `test_e2e_duckdb_governed_query` | Models dir + policy → `sl_query_metrics` on an in-process DuckDB source; rows, audit entry, governed SQL recorded |
| `test_e2e_rls_two_subjects_same_roles` | Warm cache as user A; user B with same roles/tenant but different `programs` gets only their rows; cached AST unchanged |
| `test_e2e_pbac_denial_paths` | denial on `driver:connect` / `table:read` across compile-only, saved query, dimension values, raw SQL and cache hits → no SQL, no execution |
| `test_e2e_masked_inference_matrix` | the §4 lineage matrix end-to-end through `sl_run_sql` and structured filters |
| `test_e2e_handoff_two_users_two_sessions` | foreign/expired handles rejected; identical names isolated; read after policy change denied; shared manager cannot enable the tool |
| `test_e2e_mcp_local_semantic_layer` | `parrot mcp-local semantic-layer --list` resolves the section; tool list matches exposure rules (stdio, no real LLM) |

**(rev 0.3)** `test_e2e_native_engine_switch` and `test_e2e_dataset_manager_rls_two_users` are removed:
the former tested a sidemantic↔native engine switch that no longer exists (single engine, no switch);
the latter was M12's end-to-end test and M12 is superseded by FEAT-738 (already merged and tested on `dev`).

### Validation Contract

none — fallback

> **Rev 0.4** adds M9D source tests and M9H/M10 security tests to task validation commands. The task decomposition must include them explicitly; the existing M12 tests remain unrelated.
> **(rev 0.3)** No existing test on `dev` exercises this feature: M12 (the only module with existing-test
> coverage in rev 0.2) is dropped, superseded by FEAT-738. All new files live under
> `packages/ai-parrot-semantic/tests/` and `packages/ai-parrot-server/tests/` and are each
> task's own `## Validation Commands`, added by the selector at merge/feature tier.

### Test Data / Fixtures
```python
# packages/ai-parrot-semantic/tests/conftest.py
@pytest.fixture
def duckdb_warehouse(tmp_path) -> str:
    """DuckDB file with sales.orders(region, tenant_id, order_date, amount), dim.customers(id, email, salary) and seeded rows."""

@pytest.fixture
def models_dir(tmp_path) -> Path:
    """Own-format YAML `orders` model + `orders.policy.yaml` (roles analyst/admin, mask customers.email, RLS on sales.orders by programs) + an Ossie 0.1.1 document."""

@pytest.fixture
def pctx_factory():
    """Build PermissionContext(UserSession(user_id, tenant_id, roles, metadata={programs, groups})) for A/B subjects."""

@pytest.fixture
def allow_all_guard() / deny_table_guard():
    """DataPlanePolicyGuard doubles with a fake evaluator (allow / deny one table / unavailable)."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] AC1 `pip install ai-parrot-semantic` (workspace member) installs with **no AGPL-3.0 dependency at all**; `import parrot.semantic` works; no file anywhere in the repo, including `packages/ai-parrot-semantic/`, imports `sidemantic` at module level, and `ruff check` (TID251) enforces this with **no per-file exemption**.
- [ ] AC2 Compilation never opens a database connection and runs under `asyncio.to_thread`; the same `SemanticQuery` compiles to Postgres, BigQuery and DuckDB SQL.
- [ ] AC3 A model without `governed: false` denies compile, execute, dimension values, saved queries and raw SQL when `PermissionContext` is `None` or the PBAC evaluator is unavailable; `DataPlanePolicyGuard.authorize_source` is never called with `ctx=None` by the satellite.
- [ ] AC4 PBAC (`driver:connect`, `table:read`) is evaluated on every request including cache hits; a denial returns no SQL and calls no source.
- [ ] AC5 RLS predicates from `RlsRegistry` are injected at the base-table scan below aggregation; aggregate results equal the subset computed by hand; values appear only as typed literals; render failure denies.
- [ ] AC6 Column masking and usage rights: masked projections render per strategy; any filter/join/group/order/window/derived use of a masked or hidden column without usage rights is denied through aliases, CTEs and subqueries; unresolved lineage denies.
- [ ] AC7 The positive guard rejects unknown tables/columns/functions, DDL/DML, multi-statement SQL and `exp.Command`; `LIMIT` is injected (policy default) or clamped (policy max).
- [ ] AC8 The compile cache stores only pre-governance `CompiledQuery` objects (no subject values); governance re-runs on every hit; model/policy digest changes invalidate.
- [ ] AC9 Every request appends a signed `SemanticAuditEntry` (structured query, subject digest, model/policy digests, engine, compiled + governed SQL, dialect, outcome, rows, duration); awaited verification of the signature succeeds; storage failures do not fail requests only when resolved `audit_required=False`; otherwise results are withheld (AC21).
- [ ] AC10 Result handles are opaque, bounded, expiring and owner/session/context/version-bound; `sl_save_result_as_dataset` rejects foreign/expired/stale handles, re-checks member rights and PBAC, and is not exposed without an M9H guarded sink factory; raw/shared managers are refused and downstream reads reauthorize.
- [ ] AC11 The native compiler compiles the full v1 subset — including declared one-to-many joins with fan-out rejection, filtered measures, and derived metrics-over-metrics — and matches hand-computed expected rows on the DuckDB golden fixtures across all three dialects; a many-to-many join is rejected; `contains` filters correctly escape `%`/`_` LIKE wildcards (closes `issue:46e8f6219bf5`).
- [ ] AC12 `sl_run_sql` exists only when `allow_raw_sql=True` and goes through the identical governance pipeline.
- [ ] AC13 `parrot mcp-local semantic-layer` serves the toolkit from a YAML section; `static_subject` use is logged and flagged in the audit entry.
- [ ] AC14 `SemanticLayerHandler` routes are registered only when `parrot.semantic` is importable and return 401 without a session.
- [ ] AC15 Apache Ossie 0.1.1 documents validate against the vendored schema and load; unknown policy members are rejected at load.
- [ ] AC16 All unit + integration tests above pass with `PYTHONPATH=packages/ai-parrot-semantic/src:packages/ai-parrot/src` and in CI; `docs/tools/semantic-layer.md` and the satellite README exist (no AGPL notice).
- [ ] AC17 No public API of core, `ai-parrot-tools` or `ai-parrot-server` changes, and **(rev 0.4) only the DuckDB source and its focused tests may change in core** (M9D; M12 remains dropped); `scripts/release.py` lists the new package.
- [ ] AC18 Release gates: per-dialect golden-SQL snapshots (postgres/bigquery/duckdb), a DuckDB execution oracle against hand-computed expectations, and a cross-process determinism hash check all pass; the positive-guard adversarial matrix passes for all three dialects.
- [ ] AC19 A governed model's catalog (`sl_list_models/metrics`, `sl_get_dimensions`, `sl_search_data_model`, `sl_list_saved_queries`) exposes nothing without an authorized subject; the model's declared resource manifest is authorized before compile and every compiled table is within it.
- [ ] AC20 **(rev 0.3 — removed, superseded)**. `M12`/`issue:90cf04ce8edd` is dropped: FEAT-738
  (TASK-4678/4679, merged 2026-10-24) already ships the identical fix and test coverage on `dev`.
- [ ] AC21 (§8 Q3–Q5) `ModelPolicy.allowed_functions` only extends `DEFAULT_ALLOWED_FUNCTIONS`; `audit_required=None` resolves to `True` iff a durable `audit_storage` is configured and then withholds results on sink failure; `postgres_audit_storage` + `semantic_audit_events.sql` ship in the satellite and are documented.
- [ ] AC22 **(rev 0.3)** No file under `packages/ai-parrot-semantic/`, `ai-parrot/`, `ai-parrot-tools/` or
  `ai-parrot-server/` imports, vendors, or otherwise references sidemantic's source or API; the typed
  model schema (`model.py`) is authored only from the public Cube, dbt MetricFlow and Apache Ossie 0.1.1
  format documentation (clean-room).
- [ ] AC23 **(rev 0.3)** FEAT-742 (Rust/PyO3 phase) is reserved and referenced in Non-Goals and Known
  Risks; this spec adds no Rust code, crate, build step, dependency, or `THIRD_PARTY.md` entry.
- [ ] AC24 (rev 0.4) The M4 graph represents physical types, aggregate inputs, composite join keys and derived dependencies; invalid/cyclic references and fan-out fail deterministically with the review regression gates passing.
- [ ] AC25 (rev 0.4) Retained handles require trusted nonempty agent/session identity and exact member/physical provenance; missing or mismatched scope denies hand-off. ContextVars restore after success, error and cancellation.
- [ ] AC26 (rev 0.4) Static operator identity is available only through LocalSemanticLayerToolkit; configured guard-factory startup works with governed models and fails closed otherwise. S3/S5 are fixed with evidence before release.
- [ ] AC27 (rev 0.4) Hand-off uses only a conforming M9H sink. Every subsequent exposure rechecks current authorization, owner, subject, expiry and versions, including cached/derived results; no bare-manager fallback or alternate unguarded endpoint exists. Without a conforming host adapter the tool is absent and HTTP returns `handoff_unavailable`.
- [ ] AC28 (rev 0.4) M9D's DuckDB prerequisite is implemented and real-source tests pass before semantic E2E validation. The only core-source edits are the DuckDB source and focused tests; M12 stays removed.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.
> Verified against commit `ea2c1224b` (dev, 2026-10-19); **rev 0.3 re-verified against `71999bd06`
> (dev, 2026-10-25)**. `packages/ai-parrot-semantic/` is still absent on `dev` (re-confirmed 2026-10-25).

### Verified Imports
```python
from parrot.tools.toolkit import AbstractToolkit                              # verified: packages/ai-parrot/src/parrot/tools/toolkit.py:225
from parrot.tools.databasequery.toolkit import DatabaseQueryToolkit          # verified: packages/ai-parrot/src/parrot/tools/databasequery/toolkit.py:115
from parrot.tools.databasequery.base import AbstractDatabaseSource, QueryResult, ValidationResult, add_row_limit  # verified: base.py:323,148,86,213
from parrot.tools.databasequery.sources import get_source_class, normalize_driver   # verified: toolkit.py:38 (import site)
from parrot.auth import PermissionContext, UserSession, RlsRegistry, RlsRule, DataPlanePolicyGuard  # verified: packages/ai-parrot/src/parrot/auth/__init__.py:33,34,46,47,45 (lazy map)
from parrot.auth.rls_registry import RlsPredicate                            # verified: auth/__init__.py:48, rls_registry.py:70
from parrot.auth.context import _pctx_var                                    # verified: packages/ai-parrot/src/parrot/auth/context.py:33
from parrot.auth.exceptions import AuthorizationRequired                     # verified: packages/ai-parrot/src/parrot/auth/exceptions.py:12
from parrot.auth.permission import to_eval_context                           # verified: permission.py:209
from parrot.security import QueryLanguage, QueryValidator                    # verified: packages/ai-parrot/src/parrot/security/__init__.py:14 (import site), query_validator.py:19,29
from parrot.security import AuditLedgerEntry, AbstractKMSSigner, LocalHMACSigner, AuditLedger  # verified: security/__init__.py:50-55
from parrot.security.audit_ledger import AzureKeyVaultSigner                 # verified: audit_ledger.py:199 (not re-exported by __init__)
from parrot.knowledge.common.sql_dialects import SQLGLOT_DIALECT_MAP         # verified: packages/ai-parrot/src/parrot/knowledge/common/sql_dialects.py:6
from parrot.tools.dataset_manager import DatasetManager                      # verified: handlers/datasets.py:32 (import site); class at dataset_manager/tool.py:499
from parrot.interfaces.database import get_default_credentials               # verified: packages/ai-parrot/src/parrot/interfaces/database.py:501
from parrot.mcp.toolkit_config import ToolkitSection, MCPToolkitsConfig, load_toolkits_config  # verified: toolkit_config.py:20,80,90
from navigator.views import BaseView                                         # verified: packages/ai-parrot-server/src/parrot/handlers/datasets.py:19
from navigator_auth.decorators import is_authenticated, user_session         # verified: handlers/datasets.py:20
from navigator_session import get_session                                    # verified: handlers/datasets.py:21
import sqlglot; from sqlglot import exp; from sqlglot.optimizer.qualify import qualify   # sqlglot 30.23.0 installed; core floor "sqlglot>=20.0" (ai-parrot/pyproject.toml:182); satellite pins "sqlglot>=30.1,<31" (M1)
```

**(rev 0.3) M12 imports removed** — `DataSource`, `SQLQuerySource`, `inject_rls_*`, `DatasetEntry`,
`PhysicalResources`/`resolve_physical_resources`, `driver_to_dialect` were only needed by the dropped
M12 core fix. The satellite builds `PhysicalResources(driver=, tables={...})` directly from the compiled
AST (unchanged from rev 0.2 — this was never an M12 import).

### Branch Salvage Source (verified against `origin/feat-FEAT-704-semantic-layer`, 2026-10-25)
```python
# packages/ai-parrot-semantic/src/parrot/semantic/loader.py  (branch, 386 lines)
# class LoadedModel(BaseModel):         line 58
#     layer: Any                        line 64   (rev 0.3: replaced by `model: SemanticModel`)
# class SemanticModelLoader:            line 73
#   (PhysicalSchema / digest / scoping plumbing salvaged; sidemantic graph construction is rewritten)

# packages/ai-parrot-semantic/src/parrot/semantic/engines/native.py  (branch, 236 lines — SALVAGED for M5)
# class NativeCompiler:                 line 18
#   def compile(self, query, dialect):  line 26
#   def _joins_for(self, target_models): line 126-138  (fan-out rejection: `raise SemanticValidationError("fan_out")` at line 136)
#   LIKE-escape bug: `exp.Like(this=column, expression=exp.Literal.string(f"%{item.values[0]}%"))` at line 199-200,
#   NO escaping of `%`/`_` — must be fixed by M5 (closes issue:46e8f6219bf5)

# packages/ai-parrot-semantic/src/parrot/semantic/models.py  (branch) — `engine: Literal["sidemantic", "native"]` at line 148 — DROPPED in rev 0.3
# packages/ai-parrot-semantic/src/parrot/semantic/policy.py  (branch) — `engine: Literal["sidemantic", "native"] = "sidemantic"` at line 56 — DROPPED in rev 0.3
```
These are read with `git show origin/feat-FEAT-704-semantic-layer:<path>`, never checked out or merged.
The branch is 94 commits ahead of its merge-base with `dev`, while `dev` is 1,386 commits ahead of the
same point (verified 2026-10-25) — far too stale to rebase; only the files named above (plus governance,
toolkit, audit, cache, catalog, execution, results, ossie validation, and the HTTP handler — all
engine-neutral salvage candidates, adapted to rev 0.4 contracts per §3) are read from it.

### Existing Class Signatures

**(rev 0.3)** The M12 signatures (`AuthorizingDataSource`, `_clone_agent_dm`) are removed from this
contract — M12 is dropped. For the record, the fix FEAT-738 already shipped: `_apply_rls`
(`authorizing.py:152`) now returns a per-call target (`authorizing.py:147`: `target =
self._apply_rls(predicates, resources) if predicates else self._inner`) instead of mutating
`self._inner.sql` in place, and `_clone_agent_dm` (`datasets.py:48`) no longer passes `source=entry.source`
directly (verified 2026-10-25).

```python
# packages/ai-parrot/src/parrot/tools/databasequery/base.py
class AbstractDatabaseSource(ABC):                                        # line 323
    driver: str                                                           # line 336
    sqlglot_dialect: str | None = None                                    # line 337
    async def resolve_credentials(self, credentials: dict[str, Any] | None) -> dict[str, Any]   # line 339
    async def validate_query(self, query: str) -> ValidationResult        # line 362
    async def query(self, credentials: dict[str, Any], sql: str, params: dict[str, Any] | None = None, ...)  # line 446
    async def close(self) -> None                                         # line 515
def add_row_limit(...)                                                    # line 213 — string-level LIMIT injection (reference; the guard works on the AST)

# packages/ai-parrot/src/parrot/tools/databasequery/toolkit.py
class DatabaseQueryToolkit(AbstractToolkit):                              # line 115 — tool_prefix "dq"
    def __init__(self, **kwargs: Any) -> None                             # line 154 — accepts ONLY output_dir / static_dir (+ AbstractToolkit kwargs)
    def get_source(self, driver: str) -> AbstractDatabaseSource           # line 202 — cached; listed in exclude_tools
    async def cleanup(self) -> None                                       # line 220

# packages/ai-parrot/src/parrot/tools/toolkit.py
class ToolkitTool(AbstractTool):                                          # line 37
    # re-injects the popped context: hook_kwargs["_permission_context"] = pctx  → toolkit._pre_execute(...)   # lines 174-178
class AbstractToolkit(ServerManagedToolkit, ABC):                         # line 225
    exclude_tools: tuple[str, ...] = ()                                   # line 262
    tool_prefix: str | None = None                                        # line 276
    def __init__(self, **kwargs)                                          # line 357
    async def _pre_execute(self, tool_name: str, /, **kwargs) -> None     # line 491 — receives _permission_context
    async def _post_execute(self, tool_name: str, result: Any, /, **kwargs) -> Any   # line 506 — tool params only
    def get_tools(...)                                                    # line 522

# packages/ai-parrot/src/parrot/tools/abstract.py
class AbstractTool:
    async def execute(self, *args, **kwargs) -> ToolResult                # line 916 — pops "_permission_context" at line 939

# packages/ai-parrot/src/parrot/auth/permission.py
class UserSession:                                                        # line 21 (frozen dataclass)
    user_id: str; tenant_id: str; roles: frozenset[str]; metadata: dict[str, Any]   # lines 46-49
class PermissionContext:                                                  # line 81
    session: UserSession; request_id: Optional[str]; channel: Optional[str]; trace_context; extra: dict   # lines 122-126
def to_eval_context(context: "PermissionContext") -> "EvalContext"       # line 209 — userinfo: username, user_id, tenant_id, groups, roles, programs

# packages/ai-parrot/src/parrot/auth/context.py
_pctx_var: contextvars.ContextVar["PermissionContext | None"]            # line 33

# packages/ai-parrot/src/parrot/auth/rls_registry.py
class RlsRule(BaseModel):                                                 # line 49
    driver: str; table: str; predicate_template: str; subject_attribute: str; description: str = ""   # lines 63-67 (":subject.<attr>" placeholders; table "schema.table")
class RlsPredicate(BaseModel):                                            # line 70
    table: str; sql_predicate: str; bound_params: dict[str, list[str]]    # lines 82-84
class RlsRegistry:                                                        # line 87
    def register(self, rule: RlsRule) -> None                             # line 112
    def lookup(self, driver: str, tables: set[str]) -> list[RlsRule]      # line 125
    def render(self, rule: RlsRule, ctx: PermissionContext) -> RlsPredicate   # line 150 — missing attribute → sql_predicate "1=0"

# packages/ai-parrot/src/parrot/auth/dataplane_guard.py
class DataPlanePolicyGuard:                                               # line 45 — ctx None → FAIL-OPEN; ImportError navigator-auth → fail-open; evaluator error → fail-closed
    def __init__(self, evaluator, rls_registry, sensitive_drivers=..., logger=None)   # line 71
    async def can_connect_driver(...)                                     # line 113
    async def filter_tables(self, ctx: PermissionContext, driver: str, tables: list[str]) -> set[str]   # line 150
    async def authorize_source(self, ctx: Optional[PermissionContext], resources: "PhysicalResources") -> None   # line 193 — raises AuthorizationRequired
    async def rls_predicates(self, ctx: PermissionContext, resources: "PhysicalResources") -> "list[RlsPredicate]"   # line 316

# packages/ai-parrot/src/parrot/tools/dataset_manager/sources/resolver.py
class PhysicalResources(BaseModel):                                       # line 47
    driver: Optional[str]; tables: set[str]  # "driver:schema.table"; source_type: Optional[str]; source_id: Optional[str]
def resolve_physical_resources(source: "DataSource") -> PhysicalResources  # line 120 — takes a DataSource, not SQL; the satellite builds PhysicalResources directly

# packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py
class DatasetManager(...)                                                 # line 499
    def __init__(self, ...)                                               # line 550
    def add_dataframe(self, name: str, df: pd.DataFrame, description: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None,
                      is_active: bool = True, computed_columns: Optional[List[Any]] = None, usage_guidance: Optional[Dict[str, List[str]]] = None) -> str   # line 1091
    def _get_current_pctx(self) -> Optional["PermissionContext"]          # line 2663 — ContextVar pattern to copy

# packages/ai-parrot/src/parrot/security/query_validator.py
class QueryValidator:                                                     # line 29
    @classmethod def validate_sql_ast(cls, query: str, dialect: Optional[str] = None, read_only: bool = True,
                                      require_pk_in_where: bool = False, primary_keys: Optional[List[str]] = None) -> Dict[str, Any]   # line 165

# packages/ai-parrot/src/parrot/security/audit_ledger.py
class AuditLedgerEntry(BaseModel):                                        # line 80 — entry_id, user_id, channel, tool, provider, key_fingerprint, signature, created_at
    def canonical_bytes(self) -> bytes                                    # line 109
class AbstractKMSSigner(ABC):  sign(data) -> str (143); verify(data, signature) -> bool (154)   # line 135
class LocalHMACSigner(AbstractKMSSigner)                                  # line 166
class AzureKeyVaultSigner(AbstractKMSSigner)                              # line 199
class AuditLedger:                                                        # line 296
    def __init__(self, signer: Optional[AbstractKMSSigner] = None, storage: Optional[Any] = None)   # line 327 — storage: async callable(json_str), awaited at ~line 383
    async def append(self, *, user_id: str, channel: str, tool: str, provider: str, credential_material: Any) -> AuditLedgerEntry   # line 338

# packages/ai-parrot/src/parrot/knowledge/common/sql_dialects.py
SQLGLOT_DIALECT_MAP: Dict[str, str]                                       # line 6 — postgres/postgresql→postgres, bigquery, duckdb, mysql/mariadb→mysql, sqlite, mssql/sqlserver→tsql, oracle, clickhouse, redshift, snowflake

# packages/ai-parrot/src/parrot/mcp/local_cli.py / toolkit_config.py
def mcp_local(name, config_path, include, exclude, list_toolkits) -> None   # local_cli.py:164 (click command "mcp-local", lines 136-170)
class ToolkitSection(BaseModel):                                          # toolkit_config.py:20
    class_path: str = Field(..., alias="class"); enabled: bool = True; kwargs: dict; include; exclude; llm; llm_kwargs; env: dict[str, str]   # lines 50-57
def load_toolkits_config(root: Path, config_path: Path | None = None) -> MCPToolkitsConfig   # line 90

# packages/ai-parrot-server/src/parrot/handlers/datasets.py
class DatasetManagerHandler(BaseView):                                    # line 141 — get 179 / patch 259 / put 311 / post 383 / delete 563
    async def _get_dataset_manager(self, agent_id: str) -> DatasetManager # line 162 — per-user, per-agent manager from the session (hand-off factory precedent)
# packages/ai-parrot-server/src/parrot/manager/manager.py
from ..handlers.datasets import DatasetManagerHandler                     # line 45
router.add_view("/api/v1/agents/datasets/{agent_id}", DatasetManagerHandler)   # line 2571 (+ line 2572 with /{dataset_id})

# packages/ai-parrot/src/parrot/interfaces/database.py
def get_default_credentials(driver: str) -> dict[str, Any]                # line 501 — PG_HOST/PG_PORT/PG_DATABASE/PG_USER/PG_PWD via navconfig for "pg"
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `SemanticLayerToolkit` | `AbstractToolkit.__init__/_pre_execute/_post_execute/get_tools` | subclass + hook overrides | `tools/toolkit.py:225,357,491,506,522` |
| `SemanticLayerToolkit._pre_execute` | `kwargs["_permission_context"]` | re-injected by `ToolkitTool._execute` | `tools/toolkit.py:174-178` |
| `SemanticLayerToolkit` scoped wrapper | `parrot.auth.context._pctx_var` via scoped wrapper | ContextVar set/reset | `auth/context.py:33` |
| `PbacGate.authorize` | `DataPlanePolicyGuard.authorize_source(ctx, resources)` | method call, never with `ctx=None` | `auth/dataplane_guard.py:193` |
| `RlsPushdown.apply` | `RlsRegistry.lookup(driver, tables)` / `.render(rule, ctx)` | method calls | `auth/rls_registry.py:125,150` |
| `ModelPolicy.rls` | `RlsRule` | pydantic reuse; rules registered into the toolkit's `RlsRegistry.register()` | `auth/rls_registry.py:49,112` |
| `GovernancePipeline.govern` | `QueryValidator.validate_sql_ast(query, dialect, read_only=True)` | classmethod call | `security/query_validator.py:165` |
| `Executor.run` | `DatabaseQueryToolkit.get_source(driver)` → `AbstractDatabaseSource.query(credentials, sql)` | method calls | `databasequery/toolkit.py:202`, `base.py:446` |
| `ConnectionResolver.resolve` | `get_default_credentials(driver)` | function call | `interfaces/database.py:501` |
| `SemanticAuditLedger` | `AbstractKMSSigner.sign/verify`, `LocalHMACSigner` | constructor injection | `security/audit_ledger.py:135,143,154,166` |
| `SemanticLayerToolkit.save_result_as_dataset` | `GovernedDatasetSink.publish(...)` with a mandatory authorize-read callback (new satellite contract) | method call | `dataset_manager/tool.py:1091` |
| `SemanticLayerHandler` | `BaseView`, `is_authenticated`, `user_session`, `get_session` | same imports as `DatasetManagerHandler` | `handlers/datasets.py:19-21,141` |
| `manager.py` registration | `router.add_view(...)` | two new lines after the datasets views | `manager/manager.py:2571-2572` |
| `.parrot/mcp-toolkits.yaml` `semantic-layer:` | `ToolkitSection(class, kwargs, env)` → `parrot mcp-local semantic-layer` | config | `mcp/toolkit_config.py:50-57`, `local_cli.py:164` |
| `GovernancePipeline` dialects | `SQLGLOT_DIALECT_MAP` / `driver_to_dialect` | lookup | `knowledge/common/sql_dialects.py:6`, `dataset_manager/sources/dialects.py:41` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.semantic`~~, ~~`packages/ai-parrot-semantic/`~~ — still absent on `dev` (re-confirmed 2026-10-25); created by this feature (M1). ~~`parrot_tools.semantic`~~ — must NOT be created.
- **(rev 0.3)** ~~`sidemantic`~~ — dropped entirely; not a dependency anywhere, not a code reference anywhere (clean-room). ~~`boring_semantic_layer`~~, ~~`ibis`~~ — not installed in the venv. No `import ibis` in `packages/*/src` except the throwaway `dataset_manager/spatial/_ibis_probe.py`.
- **(rev 0.3)** ~~`engines/sidemantic_engine.py`~~ — never created; existed only on the salvage branch (169 lines) and is explicitly dropped. ~~A spike task confirming a sidemantic API~~ — no sidemantic API to confirm; M4 has no spike.
- ~~`SemanticQuery`~~, ~~`CompiledQuery`~~, ~~`GovernedQuery`~~, ~~`SemanticLayerToolkit`~~, ~~`sl_*` tools~~, ~~`SemanticAuditEntry`~~, ~~`ModelPolicy`~~, ~~`PbacGate`~~, ~~`RlsPushdown`~~, ~~`ResultHandleStore`~~, ~~`SemanticModel`/`Dimension`/`Metric`/`Relationship`~~ — none exist on `dev`; names are fixed by this spec.
- ~~`AuditLedgerEntry.payload` / `.compiled_sql` / `.structured_query`~~ — `AuditLedgerEntry` has only credential-shaped fields; `AuditLedger.append()` requires `credential_material`. Decision: a separate `SemanticAuditEntry` ledger (M8).
- ~~RLS push-down below aggregation anywhere in core~~ — `inject_rls_sql` (rls.py:72) only **wraps** the statement; the semantic layer does not call it.
- ~~A positive table/column allowlist in core~~ — `QueryValidator.validate_sql_ast` and `SQLToolkit._check_query_safety` (`bots/database/toolkits/sql.py:578`) are negative guards.
- ~~Named-connection credentials in `DatabaseQueryToolkit`~~ — `__init__` accepts only `output_dir`/`static_dir`; credentials are the first positional argument of `AbstractDatabaseSource.query()`. Decision: `ConnectionResolver` in the satellite (M9).
- ~~`_post_execute` receiving `_permission_context`~~ — it receives tool params only (toolkit.py:195-198); read the scoped ContextVar. It is not called on failure and cannot own cleanup.
- ~~`DataPlanePolicyGuard` failing closed on `ctx=None`~~ — it fails **open** (dataplane_guard.py:52, 193-200); `PbacGate` must deny before calling it.
- ~~`resolve_physical_resources(sql, driver)`~~ — it takes a `DataSource` (resolver.py:120); the satellite builds `PhysicalResources(driver=, tables={...})` from the AST itself.
- ~~`packages/ai-parrot-server/src/parrot/models/datasets.py`~~ — request models live in core `packages/ai-parrot/src/parrot/models/datasets.py`.
- ~~`UserInfoService.get_attributes()`~~ — only `get_profile(user_id)` / `get_profile_by_email(email)` exist (auth/userinfo.py:80,149,197).
- ~~An async API anywhere in this feature's compiler~~ — none; compile in `asyncio.to_thread`.
- ~~An Apache Ossie Python SDK on PyPI~~ — `ossie` / `apache-ossie` / `osi-spec` do not exist; validation is the vendored JSON Schema + the own loader (rev 0.3: not sidemantic's importer).
- ~~Server code changes for `mcp-local`~~ — the generic factory remains unchanged; YAML selects LocalSemanticLayerToolkit plus its required configured guard factory (M10).
- ~~`ai-parrot-semantic` in `KNOWN_PROJECTS`~~ — `parrot.knowledge.wiki.ledger.sdd_meta.KNOWN_PROJECTS` does not list it (warns only; `KNOWN_PROJECTS` defined at `sdd_meta.py:45`, re-verified 2026-10-25); leave this warning; changing the core vocabulary is outside the M9D-only core-source exception.
- **(rev 0.3)** ~~A `ruff.toml` per-file ignore for `sidemantic` under the satellite~~ — rev 0.2 would have added one; rev 0.3 adds the ban (`ruff.toml:125`) with **no exemption anywhere**, since the satellite no longer needs sidemantic. Re-verified 2026-10-25: `ruff.toml` has no `sidemantic` entry yet (added by M1).
- **(rev 0.3, M12 dropped)** ~~`AuthorizingDataSource` mutating `self._inner.sql` in place~~, ~~`_clone_agent_dm` sharing `entry.source`~~ — both already **fixed on `dev`** by FEAT-738 (TASK-4678/4679, merged 2026-10-24, verified `authorizing.py:147,152` and `datasets.py:48,131`, 2026-10-25). ~~`DataSource.copy()` / `.clone()` / `model_copy()`~~, ~~`packages/ai-parrot-server/tests/handlers/test_datasets_clone.py`~~ — moot; M9D is the only core-source exception.
- ~~`asyncdb` as a satellite dependency~~ — `postgres_audit_storage` uses `asyncpg` directly (already a transitive dependency of `ai-parrot`).
- ~~A CI step running `packages/ai-parrot-semantic/tests`~~ — `ci.yml` runs `uv sync --all-packages` (line 27) and per-suite pytest steps (e.g. line 506); M1 adds the satellite step.

### Edit Sites (Blueprint Anchors)

Verified against: `ea2c1224b`; **rev 0.3 anchors re-verified against `71999bd06` (dev, 2026-10-25)** —
two anchor lines shifted (`pyproject.toml`, `.github/workflows/ci.yml`; noted below), the rest held.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `pyproject.toml` | MODIFY | `ai-parrot-openlit-bridge = { workspace = true }` | `pyproject.toml:244` (was :239 in rev 0.2) | 1 |
| `scripts/release.py` | MODIFY | `PACKAGES: list[Package] = [` | `scripts/release.py:116` | 1 |
| `ruff.toml` | MODIFY | `[lint.flake8-tidy-imports.banned-api]` | `ruff.toml:125` | 1 |
| `.github/workflows/ci.yml` | MODIFY | `        run: uv run pytest packages/ai-parrot-tools/tests/tool_optimizations -q --tb=short` | `.github/workflows/ci.yml:531` (was :506 in rev 0.2) | 1 |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | `from ..handlers.datasets import DatasetManagerHandler` | `manager.py:45` | 1 |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | `        router.add_view("/api/v1/agents/datasets/{agent_id}", DatasetManagerHandler)` | `manager.py:2571` | 1 |
| `.parrot/mcp-toolkits.yaml` | MODIFY | `  database-query:` | `.parrot/mcp-toolkits.yaml:110` (was :121 in rev 0.2) | 1 |
| `.mcp.json` | MODIFY | `    "parrot-database-query": {` | `.mcp.json:64` | 1 |
| `packages/ai-parrot-semantic/pyproject.toml` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/README.md` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/src/parrot/semantic/__init__.py` | CREATE (M1), MODIFY (M10 exports) | `__all__ = ["__version__"]` (after M1) | — | — |
| `packages/ai-parrot-semantic/src/parrot/semantic/version.py` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/src/parrot/semantic/model.py` | CREATE (rev 0.3 — typed clean-room graph) | — | — | — |
| `packages/ai-parrot-semantic/src/parrot/semantic/models.py` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/src/parrot/semantic/errors.py` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/src/parrot/semantic/policy.py` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/src/parrot/semantic/loader.py` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/src/parrot/semantic/ossie.py` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/src/parrot/semantic/schemas/ossie-0.1.1.schema.json` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/src/parrot/semantic/engines/__init__.py` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/src/parrot/semantic/engines/native.py` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/src/parrot/semantic/governance/{__init__,pbac,lineage,rls,masking,guard,pipeline}.py` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/src/parrot/semantic/catalog.py` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/src/parrot/semantic/audit.py` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/src/parrot/semantic/{execution,cache,results}.py` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/src/parrot/semantic/context.py` | CREATE (M2), MODIFY (M10 binding helpers) | — | — | — |
| `packages/ai-parrot-semantic/src/parrot/semantic/{toolkit,bootstrap,handoff}.py` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/tests/{__init__,conftest}.py` + `tests/test_*.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/src/parrot/handlers/semantic.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/tests/unit/test_semantic_handler.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/tools/databasequery/sources/duckdb.py` | MODIFY (M9D) | `class DuckDBSource(AbstractDatabaseSource):` | duckdb.py:29 | 1 |
| `packages/ai-parrot/tests/test_semantic_duckdb_source.py` | CREATE (M9D) | — | — | — |
| `docs/tools/semantic-layer.md` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/src/parrot/semantic/sql/semantic_audit_events.sql` | CREATE (M8) | — | — | — |

**(rev 0.3)** `engines/sidemantic_engine.py` row removed — never created. All M12 rows removed
(`authorizing.py`, `datasets.py`, `test_authorizing_data_source.py`,
`test_datasetmanager_authz_integration.py`, `test_datasets_clone.py`) — M12 is dropped, superseded by FEAT-738. M9D separately restores the DuckDB prerequisite identified in the rev2 proposal.

- Shared files are serialized: `__init__.py` (M1 creates, M10 finalizes) and `context.py` (M2 creates identity model, M10 adds binding helpers).
- `/sdd-task` MUST re-run `grep -c -F` for every MODIFY row; `grep` in this repo is aliased to `ugrep` by RTK, so use `-F` for anchors containing `(`, `[` or `{`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **ContextVar for the per-call subject** (`DatasetManager._get_current_pctx`, tool.py:2663; `DatabaseQueryTool`, tool.py:598-600): bind/reset in the execution wrapper with `try/finally`, validate in `_pre_execute`, read inside tools, never store per-call identity on `self`.
- **Toolkit exposure via `exclude_tools`** (`DatabaseQueryToolkit.__init__`, toolkit.py:175-176) for `run_sql` and `save_result_as_dataset`.
- **Satellite packaging** mirrors `packages/ai-parrot-embeddings/pyproject.toml` (setuptools, `dynamic = ["version"]`, `dependencies = ["ai-parrot"]`, `license = "MIT"`, `requires-python = ">=3.11,<3.14"`); PEP 420: no `src/parrot/__init__.py`.
- **Trusted provenance by node identity**: RLS and mask nodes injected by the pipeline are remembered by `id(node)` in the same pass; callers can never label SQL as trusted.
- **Fail closed everywhere governance is involved**; fail open is only acceptable for `governed: false` models, and never for hand-off ownership.
- **Credentials from env/navconfig only**; tool arguments never carry credentials or connection names.
- **Async-first**: compile and sqlglot passes run in `asyncio.to_thread`; execution via the async sources; `self.logger` logging; Pydantic v2; 120 cols; Google docstrings.
- **Worktree testing**: `PYTHONPATH=packages/ai-parrot-semantic/src:packages/ai-parrot/src pytest packages/ai-parrot-semantic/tests`; never `uv sync` inside a worktree. **(rev 0.3)** no sidemantic install needed — the satellite has no AGPL dependency.

### Known Risks / Gotchas
- **(rev 0.3) Clean-room boundary**: the typed model schema is authored only from Cube / dbt MetricFlow / Apache Ossie 0.1.1 *public documentation*; never open or copy sidemantic's source, including the salvage branch's `loader.py` body or `sidemantic_engine.py`. §8 Q1's AGPL sign-off is now moot (no AGPL dependency exists).
- **(rev 0.3) Salvage drift**: `origin/feat-FEAT-704-semantic-layer` is 94 commits ahead of its merge-base with `dev` while `dev` is 1,386 commits ahead of the same point (verified 2026-10-25) — too stale to rebase. Only the named files (§6) are read via `git show`; core edits on the branch are never copied wholesale; M9D manually reapplies only the DuckDB fix against current dev.
- **(rev 0.3) LIKE-wildcard escaping (`issue:46e8f6219bf5`)**: the branch's `contains` filter translation builds `exp.Like` with an unescaped `%{value}%` pattern — a value of `"%"` matches every row. This bug moved with the code from `sidemantic_engine.py` (deleted) to `engines/native.py` (the sole surviving filter-translation path) and must be fixed there, not merely closed as moot.
- **Wrapping RLS is wrong for aggregates**: never call `inject_rls_sql` from the semantic layer; AC5 pins push-down below aggregation with a numeric parity test.
- **`DataPlanePolicyGuard` fails open on `ctx=None` and on missing navigator-auth**: `PbacGate` denies before the call and probes availability at construction.
- **Schema drift**: compile succeeds, DB fails → `SemanticExecutionError` with the audit id; SQL goes to the audit, never to the LLM message.
- **Mixed WHERE/HAVING filter groups**, **grain missing**, **offset without order** → validation errors (M2).
- **Fan-out joins in native mode** → rejected; U4 (2026-10-25) keeps declared one-to-many joins in v1; no many-to-many / symmetric-aggregate path exists in rev 0.3 (no sidemantic to provide one).
- **Cache poisoning across subjects**: cache stores pre-governance SQL only; `cache_key` excludes subject data; AC8 + `test_e2e_rls_two_subjects_same_roles`.
- **Hand-off into a shared `DatasetManager`** would leak governed rows: factory must return a guarded subject/session-scoped sink; M9H validates the owner tuple and rejects raw/shared managers (AC10). Hosts without a conforming read gate cannot enable hand-off.
- **RTK/ugrep** aliasing in this repo turns `grep` patterns into regex; use `-F` for anchors.
- **Dialect without a source** (e.g. `snowflake`): compile allowed, execution refused with a clear error.
- **`static_subject` is a single operator identity** for `parrot mcp-local`: every call runs as that subject, so the YAML must never grant it broader roles than the operator holds; a per-call signed identity envelope was considered (design research S9) and deferred — mcp-local is a local developer surface, the identity is explicit, logged and flagged in every audit entry.
- **(rev 0.3) M12 is dropped, not just deferred**: `AuthorizingDataSource`/`_clone_agent_dm` are already fixed on `dev` by FEAT-738 (TASK-4678/4679, merged 2026-10-24) — do not re-attempt this fix; it is out of scope for this feature entirely.
- **`audit_required` auto-resolves to `True` with a durable sink** (§8 Q5): a misconfigured Postgres DSN makes every governed call fail closed with `audit_unavailable` — surface it at toolkit construction with a startup log line, and document `audit_required=False` as the explicit opt-out.
- **`allowed_functions` policy additions are a widening of the positive guard** (§8 Q4): review them like RLS text; the loader upper-cases names and rejects anything that is not a bare identifier.
- **Ossie 0.1.x is a moving spec**: version pinned in the vendored schema; a 0.2 document is rejected, not coerced.
- **(rev 0.3) Open ledger findings on salvaged code**: `issue:3c4d154c0172` (toolkit/cache/pbac hardening — S1/S2/S4 already fixed on the branch at commit `d63ac6bf4`, salvage from that commit or later; S3/S5 + nits still open) S3/S5 are mandatory M10 acceptance gates in rev 0.4: static identity is local-only and hand-off authorizes the exact retained members. Close by evidence, or split genuinely remaining nits into a separate issue; never carry S3/S5 as nonblocking debt.
- **(rev 0.3) Rust phase is a separate feature (FEAT-742)**: do not derive SemaFlow code or add a Rust crate under this spec; FEAT-742 will need the compiler's IR shape fixed by M4/M5 to remain stable.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `sqlglot` | `>=30.1,<31` (MIT; venv 30.23.0) | AST guard, lineage, RLS push-down, masking, native compiler, dialect rendering |
| `jsonschema` | `>=4.20` | Apache Ossie 0.1.1 document validation |
| `pyyaml` | `>=6` (already in core) | policy side-files and the own model-graph format |
| `duckdb` | `>=1.0` (venv 1.5.6; extra `duckdb`) | golden/e2e fixtures via `DuckDBSource`; **(rev 0.3)** no longer a transitive requirement of sidemantic — now a direct, explicit dependency |
| `google-cloud-bigquery` | `>=3.30` (extra `bigquery`; venv 3.46.2) | BigQuery execution via the existing source |
| `asyncpg` | via `ai-parrot` (venv 0.32.0) | Postgres execution via the existing source |

**(rev 0.3) `sidemantic` row removed** — no longer a dependency (AGPL-3.0 dropped entirely, clean-room).

---

## 8. Open Questions

> Questions that must be resolved before or during implementation.

- [x] License field of the satellite — *Resolved in brainstorm, superseded by rev 0.3*: MIT for the satellite (`license = "MIT"` like the other satellites). Rev 0.2 documented the AGPL-3.0 dependency and its network clause; **rev 0.3 removes sidemantic entirely, so there is no AGPL dependency to document** — this question is moot, not re-litigated.
- [x] "No abstraction" vs native fallback — *Resolved in brainstorm, superseded by rev 0.3*: rev 0.2 kept one internal `compile()` dispatching on `model.engine ∈ {sidemantic, native}`. **Rev 0.3 drops the dispatch entirely** — the native compiler is the sole engine, no `engine` field, no plugin protocol, no third-party engine registry.
- [x] Audit storage — *Resolved in brainstorm*: separate `SemanticAuditEntry` ledger in the satellite, reusing `AbstractKMSSigner`/`LocalHMACSigner` and the async `storage` callable contract; zero core change. Production sink wiring stays configurable (storage callable), default in-memory
- [x] Deny-by-default scope — *Resolved in brainstorm*: every model is governed by default — compile/execute deny without a `PermissionContext` or evaluator unless the policy file sets `governed: false`
- [x] `mcp-local` identity — *Resolved in brainstorm*: allowed — `.parrot/mcp-toolkits.yaml` may declare a `static_subject` (user, tenant, roles, metadata) for `parrot mcp-local semantic-layer`; it is logged on every call and recorded in the audit entry
- [x] Credentials for execution — *Resolved in brainstorm*: resolved inside the satellite — the model's `connection` name maps to a credentials dict via navconfig/env lookups in `parrot.semantic`; no change to `DatabaseQueryToolkit`
- [x] Free SQL (`sl_run_sql`) — *Resolved in brainstorm*: ship in v1, disabled by default (`allow_raw_sql=False`), on the same governance path (PBAC, lineage, RLS, positive guard, audit)
- [x] Native compiler v1 subset — *Resolved in brainstorm*: confirmed as drafted — simple aggregations, dimensions, `DATE_TRUNC` grains, declared one-to-many joins, filter tree, order/limit; no symmetric aggregates, no cumulative/time-comparison metrics
- [x] Commit the proposal doc — *Resolved in brainstorm*: yes — committed to `dev` together with this brainstorm acceptance
- [x] Q1 Written legal sign-off for the AGPL-3.0 dependency — *Resolved 2026-10-19, superseded 2026-10-25*: approved by **Jesus Lara (2026-10-19)** for rev 0.2. **Rev 0.3 removes sidemantic entirely** (clean-room, no AGPL dependency) — the sign-off is moot. No sign-off gates `/sdd-done` or the 1.3.0 tag.
- [x] Q2 sidemantic `SemanticLayer.compile` reentrancy and `load_from_directory` acceptance of Apache Ossie 0.1.1 fixtures — *Resolved 2026-10-19, superseded 2026-10-25*: rev 0.2 delegated this to an M4 spike against the sidemantic wheel, with a per-model `asyncio.Lock` as a safe default pending the result. **Rev 0.3 drops sidemantic entirely — there is no third-party `compile()` reentrancy to prove, and no spike or lock is needed**: the sole native sqlglot compiler is a pure, stateless function per call. Apache Ossie 0.1.1 acceptance is validated by the vendored JSON Schema (M4), independent of any third-party importer.
- [x] Q3 Production sink for `SemanticAuditLedger.storage` — *Resolved 2026-10-19*: **Postgres table shipped by the satellite** — `parrot/semantic/sql/semantic_audit_events.sql` (DDL modelled on `security/security_events.sql`, one row per `SemanticAuditEntry`, JSONB payload + indexed `user_id`/`tenant_id`/`model`/`outcome`/`created_at`) and an opt-in `postgres_audit_storage(dsn_or_pool, table="semantic_audit_events")` factory returning the async `storage(json_str)` callable (M8). Default remains the in-memory ledger; the Postgres callable is wired by the host (toolkit kwarg `audit_storage` / YAML `kwargs`). The credential-ledger sink is NOT reused (two schemas in one table rejected).
- [x] Q4 Allowed-function allowlist default for the positive guard — *Resolved 2026-10-19*: `DEFAULT_ALLOWED_FUNCTIONS` (M6 `guard.py`) = aggregates `SUM, COUNT, COUNT DISTINCT, AVG, MIN, MAX` + `DATE_TRUNC, EXTRACT, COALESCE, CAST, LOWER, UPPER` + arithmetic / comparison / boolean operators (operators are sqlglot expression nodes, not `exp.Func`, and are always allowed). Per-model **additive** override: `ModelPolicy.allowed_functions: list[str]` (M3) — the effective set is `DEFAULT ∪ toolkit kwarg allowed_functions ∪ policy.allowed_functions`; nothing can remove a default, and DDL/DML/`exp.Command` stay denied regardless.
- [x] Q5 `audit_required` default — *Resolved 2026-10-19*: the toolkit kwarg becomes `audit_required: bool | None = None` and is **resolved at construction**: `None` → `True` when a durable `audit_storage` callable is configured, `False` when only the in-memory ledger is in use (it cannot fail). An explicit `True`/`False` always wins. With `True`, a storage failure raises `SemanticExecutionError('audit_unavailable')` and the governed result is withheld (M8/M10); AC9's "storage failures never fail the request" applies to the resolved-`False` case only.
- [x] Q6 Core finding (S2) `AuthorizingDataSource` in-place RLS rewrite + `_clone_agent_dm` shared `entry.source` — *Resolved 2026-10-19, superseded 2026-10-25*: rev 0.2 folded this in as Module 12. **FEAT-738 (TASK-4678/4679, merged 2026-10-24, PR #1801) independently shipped the identical fix on `dev`** — verified `authorizing.py:147,152` and `datasets.py:48,131`, 2026-10-25. M12 is dropped from rev 0.3; `issue:90cf04ce8edd` is already resolved on `dev` and needs no task here.
- [x] U2 Stay inside FEAT-704 (spec rev 0.3) or supersede with a new FEAT id? — *Resolved 2026-10-25 (owner)*: amend FEAT-704 to rev 0.3; TASK-4467/4468 re-scoped and TASK-4482 dropped by the next `/sdd-task` run; no new FEAT id for the generic semantic layer.
- [x] U3 Rust/PyO3 phase timing and location — *Resolved 2026-10-25 (owner)*: own FEAT now, crate inside the satellite. **FEAT-742** (`semantic-layer-rust-compiler`) reserved 2026-10-25; its crate will live at `packages/ai-parrot-semantic/rust/` (navrules-style: pyo3 0.29 abi3-py311, `extension-module` feature off for `cargo test`, `native_group` registration). Not specced here — a future `/sdd-spec` run owns FEAT-742's design.
- [x] U4 v1 join scope — *Resolved 2026-10-25 (owner)*: keep the branch's declared one-to-many joins with fan-out rejection in v1 (verified present and working at `engines/native.py:126-138` on the branch).
- [x] U5 BSL/Ibis vs the Ibis NO-GO — *Resolved 2026-10-25 (owner)*: a scoped re-opening note. The Ibis NO-GO (TASK-1437) is narrowed to connection/credential mapping; compile-only BSL/Ibis usage remains re-evaluable by a future, scoped joins-phase spec (see Non-Goals). No Ibis/BSL dependency is added by rev 0.3.
- [x] U6 Who creates `packages/ai-parrot-semantic/` first, FEAT-704 or FEAT-713? — *Resolved 2026-10-25 (owner)*: **FEAT-704 rev 0.3 creates the skeleton (M1)**; FEAT-713's M1 becomes "extend" (resolves `accounting-metrics-layer.spec.md` §8 Q10 — that edit is out of scope for this spec and must be made the next time FEAT-713's spec is touched).

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `gpt-5.6-luna` (codex-cli 0.163.0) · Status: completed
> · Transcript: `sdd/state/FEAT-704/design_research/`
> Every row is a suggestion the reviewer made; the disposition is the spec author's
> call (CONFIRM = folded into the spec, REJECT = reason recorded, ESCALATE = §8 question).
> All 23 cited paths passed containment and existence checks; evidence for S2 and S5 was re-read in source.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Add a strict semantic authorization boundary (architecture) | CONFIRM | `DataPlanePolicyGuard`/`AuthorizingDataSource` do fail open on `ctx=None` (dataplane_guard.py:52,193); the spec already denied before the guard, and now also gates **catalog exposure** | §2 step 3, M6 `PbacGate`, M7 `visible_members(authorized=)`, AC3, AC19 |
| S2 | Make RLS injection immutable and request-scoped (risk) | CONFIRM + ESCALATE | Verified: `authorizing.py:191` mutates `self._inner.sql`; `handlers/datasets.py:70` shares `entry.source`. The semantic pipeline works on a per-request AST clone and never registers a source; the core defect is outside scope → ledger issue | §2 step 3 (clone), M6, §7 risk, §8 Q6 |
| S3 | Replace string RLS templates with typed predicates and driver bind adapters (api) | CONFIRM (parse at load) / REJECT (driver bind adapters) | Templates are now sqlglot-parsed at policy load and rendered as typed `exp.Literal`s, which is injection-safe per dialect. Per-driver parameter adapters (`$1` / `@name` / `?`) across three sources are out of v1 scope and add no safety over typed literals | M3 `load_policy`, M6 `RlsPushdown` |
| S4 | Specify fail-closed AST push-down semantics (architecture) | CONFIRM | Rewrite each base `exp.Table` preserving aliases/CTEs/joins; table functions, lateral sources, recursive CTEs or unplaceable constructs deny — never fall back to wrapping | M6 `RlsPushdown.apply` docstring, AC5 |
| S5 | Disable subject-independent caches for governed results (risk) | CONFIRM | Already pre-governance-only; verified `UserSession.metadata` is excluded from hashing (permission.py:49), so the subject digest now hashes policy-relevant metadata explicitly | M9 `ResultHandle.subject_digest`, AC8 |
| S6 | Authorize model resources before compilation (architecture) | CONFIRM | Two-phase check: declared manifest authorized pre-compile, compiled tables must be ⊆ manifest post-compile | §2 step 3, M6 `PbacGate.authorize_manifest`, AC19 |
| S7 | Keep credentials out of `SemanticQuery` (api) | CONFIRM | `SemanticQuery` carries only `model`; `extra="forbid"` rejects credential-like fields; credentials resolve server-side (resolved brainstorm question) | §2 Data Models, M2, M9 `ConnectionResolver` |
| S8 | Create a semantic audit ledger contract (architecture) | CONFIRM + ESCALATE | Versioned `SemanticAuditEntry` (`schema_version`) with compiled/governed SQL, policy context, engine, outcome; whether to withhold results on durable-sink failure becomes `audit_required` (default `False`) and a §8 question | M8, M10 kwarg, §8 Q5 |
| S9 | Define authenticated identity transport for mcp-local (risk) | REJECT | The user resolved mcp-local identity as an explicit `static_subject` (logged, audited). A signed per-call identity envelope is a reasonable future hardening but out of v1 scope for a local developer surface; the limitation is recorded as a risk | §7 Known Risks |
| S10 | Add adversarial positive-guard and lineage fixtures (testing) | CONFIRM | `QueryValidator` is negative-only (query_validator.py:165); added the adversarial matrix across the three dialects | §4 `test_positive_guard_adversarial_matrix`, AC18 |
| S11 | Make compiler parity and reentrancy release gates (testing) | CONFIRM | Added concurrent-compile, normalized-AST parity and pg/bq snapshot tests as release gates | §4 (`test_compile_concurrent_to_thread`, `test_dialect_sql_snapshots`), AC18, §8 Q2 |
| S12 | Make free SQL and dataset hand-off later opt-in features (alternative) | CONFIRM (ordering) / REJECT (defer to another spec) | Both tools are already opt-in and off by default (resolved brainstorm question); their tasks are now ordered last and gated on the security suite rather than deferred to a separate spec | Worktree Strategy (ordering inside M10) |

Summary: **10** confirmed (two of them partially, with the rejected part recorded) · **2** rejected (S9; the deferral half of S12) · **2** escalated (S2 → Q6, S8 → Q5).

**Rev 0.3 note**: no new design-research pass ran for this amendment — `sdd/proposals/semantic-layer-rev2.proposal.md` carries `status: review` (not `accepted`), which does not meet the `codex` design-research preconditions (§3b of `/sdd-spec`). Status: **skipped (exploration doc status is 'review', not 'accepted')**. Two rev 0.2 items are now moot rather than resolved by new review: **S2**'s escalation (→ Q6) is superseded — the core defect it flagged is already fixed on `dev` by FEAT-738, independently of this spec. **S11**'s reentrancy half (`test_compile_concurrent_to_thread`) is superseded — there is no third-party engine to prove reentrant; the native compiler is a pure function. S11's parity/snapshot half stands, re-pointed from sidemantic-parity to the DuckDB execution oracle.
---

## Worktree Strategy

- **Isolation**: one feature worktree `feat-FEAT-704-semantic-layer` (from `origin/dev`); the
  `sdd-coder` engine gives each task its own sub-worktree inside it.
- **Module dependency graph** (edge = import/contract dependency, with evidence):
  - M2 → M1 (package must exist to import `parrot.semantic.errors`).
  - M3 → M2 (`ModelPolicy` embeds `SemanticQuery` in `SavedQuery` and reuses `ModelMember`).
  - M4 → M2, M3 (`LoadedModel` carries `ModelPolicy`; `compile()` returns `CompiledQuery`).
  - M5 → M4 (`NativeCompiler(LoadedModel)` uses the typed `SemanticModel`, `PhysicalSchema` and members).
  - M6 → M2, M3, M4 (`GovernancePipeline.govern(model: LoadedModel)`; `ModelPolicy.usage_allowed/mask_for`).
  - M7 → M3, M4 (`RoleCatalog(models: dict[str, LoadedModel])`).
  - M8 → M2 only (`SemanticAuditEntry` is self-contained).
  - M9 → M2, M6 (`Executor.run(GovernedQuery)`; `CompileCache(CompiledQuery)`).
  - M9D → M1; M9 DuckDB validation → M9D. M9H → M2, M3, M6, M7, M9.
  - M10 → M3…M9, M9D, M9H. M11 → M10; hand-off requires the guarded sink contract.
  - **(rev 0.3) M12 removed** — M9D is a separate prerequisite, not a revival of M12; every module depends transitively on M1.
  - **Concurrent after M4**: M5, M6, M7, M8, M9 have no edges among themselves (M9 needs only `GovernedQuery`
    from M2/M6's contract, which is fixed in §2 — M9 may start on the model alone).
- **Shared files**: `context.py` (M2 identity model, then M10 binding helpers) and `packages/ai-parrot-semantic/src/parrot/semantic/__init__.py` (M1 create, M10
  finalize) — serialized. **(rev 0.4)** M1 edits workspace/release/lint/CI configuration, M9D edits the DuckDB source and tests, and M11 creates
  `handlers/semantic.py` and edits `manager.py`; `handlers/datasets.py` is never touched — M12 is gone.
  No other file is touched by two modules. M9D exclusively owns its core source/test files.
- **Exclusive resources**: M1 changes `uv.lock`/workspace membership (`parallel: false`); **(rev 0.3)**
  no main-checkout operator install step is needed — there is no sidemantic (or any other new heavy
  dependency) to install into the shared venv. M11's `manager.py`, `.parrot/mcp-toolkits.yaml`,
  `.mcp.json` edits are single-task.
- **Ordering inside M10**: the `run_sql` and `save_result_as_dataset` tools are the **last** tasks of the feature and depend on the
  governance/lineage/cache-isolation/hand-off security tests (§4) being green — governed metric queries ship first (design research S12).
- **Cross-feature dependencies**: **FEAT-713** (`accounting-metrics-layer`, draft spec, not yet
  decomposed) extends the skeleton this feature creates (U6, 2026-10-25) — its own spec's §8 Q10 needs
  a follow-up edit (out of scope here) once this spec lands. **FEAT-742** (Rust/PyO3 phase, reserved
  2026-10-25) depends on this feature's IR/compiler shape but is not implemented by it. `FEAT-699`
  test-selector changes are already on `dev`.

---

## Rev 0.4 review resolution (2026-10-25)

This amendment incorporates the specification review including `semantic-layer-rev2.proposal.md`. It preserves the resolved one-to-many join scope (U4), FEAT-704 skeleton ownership (U6), FEAT-742 Rust deferral and the scoped Ibis note. It supersedes rev 0.3's blanket no-core-edit claim only for M9D and its optional treatment of S3/S5. It introduces no implementation changes by itself; task decomposition must be regenerated before coding, and ledger issues close only after implementation evidence.

| Review issue | Resolution | Validation |
|---|---|---|
| Aggregate/join fields missing | M4 inputs, schema, keys and graph/grain validation | AC24 |
| Downstream policy bypass after DataFrame hand-off | M9H guarded host sink; no default plain manager | AC27 |
| Session/agent ownership undefined | M10 trusted identity and M9 explicit claim scope | AC25 |
| MCP missing PBAC construction | M10 local subclass and configured guard factory | AC26 |
| DuckDB prerequisite dropped | M9D restored as the sole core-source exception | AC28 |
| S3/S5 treated as optional | Local-only static identity and exact retained member provenance are mandatory | AC25–AC26 |

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-19 | Jesus Lara | Initial draft from the accepted brainstorm (Option B), 9 brainstorm questions carried forward as resolved |
| 0.2 | 2026-10-19 | Jesus Lara | §8 Q1–Q6 resolved: AGPL sign-off recorded; Q2 delegated to the M4 spike; Postgres audit sink + `postgres_audit_storage` (M8); `DEFAULT_ALLOWED_FUNCTIONS` + additive `ModelPolicy.allowed_functions` (M3/M6); `audit_required=None` auto-resolution (M10); core fix `issue:90cf04ce8edd` folded in as **M12** (new tests, AC20–AC21, §6 anchors, validation contract now lists the two existing auth test files) |
| 0.3 | 2026-10-25 | Jesus Lara | **Amends via `sdd/proposals/semantic-layer-rev2.proposal.md`** (status: review). sidemantic (AGPL-3.0) dropped entirely — no dependency, no code reference (clean-room: typed model graph authored from Cube/dbt MetricFlow/Ossie 0.1.1 public docs). The branch-salvaged `engines/native.py` native compiler becomes the sole engine (no `engine` field, no dispatch); M4 rewritten as "typed model graph + loader", its sidemantic spike and `engines/sidemantic_engine.py` dropped. **M12 removed** — superseded by FEAT-738 (TASK-4678/4679, merged 2026-10-24); AC20 removed, §6 M12 anchors/imports removed, Validation Contract → `none — fallback`. Fixed `issue:46e8f6219bf5` (LIKE-wildcard escaping, carried from the deleted file into the surviving `native.py` path) as a mandatory M5 item; AC11/AC18 re-pointed to golden-SQL + DuckDB execution + cross-process determinism (no sidemantic parity oracle); §8 Q1/Q2/Q6 marked superseded; U2/U4/U6 resolved (amend FEAT-704; keep one-to-many joins; FEAT-704 creates the skeleton, FEAT-713 extends); U3 resolved — Rust/PyO3 phase gets its own reserved **FEAT-742**; U5 resolved — Ibis NO-GO scope-narrowed to connections, re-opening reserved for a future joins-phase spec. Design research: skipped (exploration doc status is `review`, not `accepted`). |
| 0.4 | 2026-10-25 | Codex, at owner request | Resolve all six specification-review findings: complete typed graph contracts; trusted scoped identity; guarded downstream hand-off; local MCP guard bootstrap; mandatory S3/S5 fixes; restore DuckDB prerequisite M9D. Align tests, acceptance criteria, edit sites and dependency graph. |

**Rev 0.4 contract clarification (owner-approved, 2026-10-25):** `SemanticAuditLedger.verify` is async, matching `AbstractKMSSigner.verify`; signing and verification must both be awaited. TASK-4474 tests awaited round-trip verification and tamper rejection without blocking the event loop.
