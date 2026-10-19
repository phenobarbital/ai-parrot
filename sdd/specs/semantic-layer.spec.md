---
type: feature
base_branch: dev
projects: [ai-parrot-semantic, ai-parrot-server, ai-parrot]  # FEAT-576 — carried from the brainstorm
tags: [semantic-layer, sidemantic, sqlglot, rls, pbac, mcp]     # FEAT-576 — carried from the brainstorm
---

# Feature Specification: Semantic Layer — governed metric queries for agents (`ai-parrot-semantic`)

**Feature ID**: FEAT-704
**Date**: 2026-10-19
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.3.0
**Source**: `sdd/proposals/semantic-layer.brainstorm.md` (accepted 2026-10-19, Option B) ← `sdd/proposals/semantic-layer.proposal.md`

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

- G1. Declare metrics, dimensions, relationships and time grains once (sidemantic YAML or Apache
  Ossie 0.1.1 documents) and compile governed SQL for Postgres, BigQuery and DuckDB on demand,
  with no warehouse connection at compile time.
- G2. Governance is ai-parrot code and engine-independent: PBAC gate on every request, RLS pushed
  **below aggregation**, per-role member allowlist, column masking **and** column-usage rights
  enforced through full AST lineage, positive SQL allowlist, forced `LIMIT`, signed audit.
- G3. Governed-by-default, fail-closed: a model denies without a `PermissionContext` or without an
  available PBAC evaluator unless its policy explicitly sets `governed: false`.
- G4. Caches never carry governed SQL or authorization decisions; results are never shared across
  subjects; dataset hand-off is owner/session-bound and expiring.
- G5. One opt-in satellite distribution `ai-parrot-semantic` confines the AGPL-3.0 dependency
  (sidemantic) and the `parrot.semantic` namespace; core, `ai-parrot-tools` and `ai-parrot-server`
  never import sidemantic at module level.
- G6. Four surfaces over one implementation: `SemanticLayerToolkit` (`sl_*` tools), `parrot
  mcp-local semantic-layer`, aiohttp handlers in `ai-parrot-server`, and a guarded hand-off to a
  subject-scoped `DatasetManager`.
- G7. A native fallback compiler (sqlglot) covers the simple-aggregation subset so sidemantic can
  be bypassed per model (`engine: native`) or dropped later, with parity tests on DuckDB.

### Non-Goals (explicitly out of scope)

- Executing through sidemantic's own (sync) adapters; a result cache; cross-request result reuse.
- Symmetric aggregates, cumulative / time-comparison / cohort metrics in the **native** engine (sidemantic-only in v1).
- Pushing governance into the warehouse (views + native RLS) — rejected as brainstorm Option D.
- BSL-over-Ibis or Ibis-direct compilation — rejected as brainstorm Option A (Ibis NO-GO, TASK-1437).
- sidemantic's `SecurityPolicy` / `security:` blocks — rejected at load; RLS has exactly one semantics (ours).
- Changes to `DatabaseQueryToolkit`, `AuditLedgerEntry`, `RlsRegistry`, `DataPlanePolicyGuard` or
  `parrot/clients/base.py` — all are consumed as they are. The only core edits are M12's behavioural
  fix of `dataset_manager/sources/authorizing.py` and `handlers/datasets.py` (§8 Q6, `issue:90cf04ce8edd`),
  which changes no public signature.
- Dialects other than Postgres, BigQuery, DuckDB for **execution** (compile-only may emit any sqlglot dialect).
- A metric-authoring UI; Ossie **export**; dbt/LookML import beyond what sidemantic's auto-detect already provides (not tested in v1).

---

## 2. Architectural Design

### Overview

**Option B (brainstorm):** sidemantic (`==0.12.0`, AGPL accepted) owns the semantic core —
model/dimension/metric definitions, relationships with cardinalities and symmetric aggregates,
15-format directory loading (Apache Ossie included), and `compile(metrics, dimensions, filters,
order_by, limit, dialect)` → SQL with no connection. ai-parrot owns everything that decides *who
sees what*, written on **sqlglot** and applied identically to sidemantic output, native-compiler
output and (optional) free SQL:

1. **`SemanticQuery`** — the pydantic request contract (metrics · dimensions · time dimensions
   with grain · typed `and`/`or` filter tree · order · limit · offset · timezone · `saved_query`
   XOR `metrics`). Compiles to sidemantic filter strings or to the native AST builder.
2. **Compile** (`asyncio.to_thread`) via one internal `compile()` that dispatches on
   `model.engine ∈ {sidemantic, native}` — *no plugin protocol, no engine registry* (resolved
   brainstorm question). Output is an immutable `CompiledQuery` containing **no subject-derived
   content**; this is the only thing the LRU cache may store.
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
   digest). `sl_save_result_as_dataset` re-checks ownership/expiry/context and PBAC, then calls
   `add_dataframe()` on a **subject/session-scoped** `DatasetManager` obtained from a host-provided
   factory; without that factory the tool is not exposed.
7. **Surfaces** — `SemanticLayerToolkit(AbstractToolkit, tool_prefix="sl")`; `parrot mcp-local
   semantic-layer` from a `.parrot/mcp-toolkits.yaml` section (optional `static_subject` operator
   identity, logged and audited — resolved question); `SemanticLayerHandler(BaseView)` at
   `/api/v1/agents/semantic/{agent_id}` registered in `manager.py` (lazy import); the hand-off above.
8. **Licensing** — satellite `license = "MIT"` like the other satellites, with the AGPL-3.0
   dependency and its network clause documented in README and §7 (resolved question); written
   legal sign-off tracked in §8.

Resolved brainstorm decisions reflected in this design (see §8 for the trail): license field;
single `compile()` dispatch; separate audit ledger; governed-by-default; mcp-local
`static_subject`; satellite-side credential resolution; `sl_run_sql` shipped behind
`allow_raw_sql=False`; native subset as drafted; proposal committed.

### Component Diagram
```
 .parrot/mcp-toolkits.yaml ─► parrot mcp-local ─┐
 ai-parrot-server SemanticLayerHandler ─────────┤   (PermissionContext from navigator-auth session /
 Agent / AgentCrew tool call ───────────────────┤    _permission_context kwarg / static_subject)
                                                ▼
                               SemanticLayerToolkit  (sl_* tools, tool_prefix="sl")
                                 │ _pre_execute → ContextVar(pctx)
                                 ▼
   SemanticModelLoader ──► LoadedModel{layer, policy, schema_map, digests}
   (sidemantic dir + Ossie 0.1.1 + <model>.policy.yaml)     │
                                 │                           │
   RoleCatalog (role-filtered view, saved-query expansion) ◄─┘
                                 │  SemanticQuery (validated, expanded)
                                 ▼
   compile(query, model, dialect)  ── engine=sidemantic ─► sidemantic.SemanticLayer.compile
        │  (to_thread, pre-governance LRU)    └ engine=native ──► NativeCompiler (sqlglot AST)
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
                                   dataset_manager_factory(ctx) → DatasetManager.add_dataframe()
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.tools.toolkit.AbstractToolkit` / `ToolkitTool` | extends | `SemanticLayerToolkit` subclasses it; `_pre_execute` receives `_permission_context` (toolkit.py:174-178) and sets the satellite's ContextVar (DatasetManager pattern, tool.py:2663) |
| `parrot.tools.databasequery.toolkit.DatabaseQueryToolkit.get_source()` + `AbstractDatabaseSource.query()` | uses | execution bridge for `pg` / `bigquery` / `duckdb`; no change to the toolkit |
| `parrot.auth.dataplane_guard.DataPlanePolicyGuard.authorize_source()` / `.rls_predicates()` | uses | PBAC gate (`driver:connect`, `table:read`) on every request; satellite never passes `ctx=None` (guard would fail open) |
| `parrot.auth.rls_registry.RlsRegistry` / `RlsRule` / `RlsPredicate` | uses | RLS rules looked up by `(driver, {schema.table})`, rendered per subject; predicates re-parsed into sqlglot and pushed below aggregation |
| `parrot.auth.permission.PermissionContext` / `UserSession` | uses | subject identity; roles/tenant/metadata feed the subject digest and policy evaluation |
| `parrot.auth.context._pctx_var` | depends on | the same ContextVar `DatabaseQueryTool` reads (tool.py:598-600) is **set** by the toolkit's `_pre_execute` so downstream guards see the context |
| `parrot.security.query_validator.QueryValidator.validate_sql_ast()` | uses | negative base (multi-statement/DDL/DML rejection) run before the positive guard |
| `parrot.security.audit_ledger.AbstractKMSSigner` / `LocalHMACSigner` / `AzureKeyVaultSigner` | uses | signer for `SemanticAuditEntry`; `AuditLedger` itself is **not** used (its entry is credential-shaped) |
| `parrot.tools.dataset_manager.tool.DatasetManager.add_dataframe()` | uses | hand-off target, only through a host-provided subject/session-scoped manager |
| `parrot.tools.dataset_manager.sources.resolver.PhysicalResources` | uses | the resource shape `authorize_source` expects; built from the governed AST's tables (`"driver:schema.table"` strings) |
| `parrot.tools.dataset_manager.sources.dialects.driver_to_dialect()` + `parrot.knowledge.common.sql_dialects.SQLGLOT_DIALECT_MAP` | uses | driver ↔ sqlglot dialect mapping |
| `parrot.interfaces.database.get_default_credentials(driver)` | uses | default credentials per driver; `ConnectionResolver` layers a named-connection env prefix on top |
| `parrot mcp-local` (`parrot/mcp/local_cli.py`, `toolkit_config.ToolkitSection`) | config | new `semantic-layer:` section (`class`, `kwargs`, `env`); no server code |
| `ai-parrot-server` `manager/manager.py` router | extends | `SemanticLayerHandler` registered next to `DatasetManagerHandler` (manager.py:2571) behind a lazy `parrot.semantic` import |
| `ai-parrot-server` `handlers/datasets.py::_get_dataset_manager()` | reuses pattern | per-user, per-agent `DatasetManager` from the session is the hand-off factory in the HTTP surface |
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
    saved_query: str | None = None      # XOR metrics; expanded by RoleCatalog before compile

class CompiledQuery(BaseModel, frozen=True):
    """Pre-governance compiler output. MUST contain no subject-derived predicates or values."""
    sql: str
    dialect: str
    engine: Literal["sidemantic", "native"]
    members: tuple[str, ...]            # metrics + dimensions referenced
    tables: tuple[str, ...]             # "schema.table" physical tables referenced
    cache_key: str                      # (model digest, policy digest, canonical query, dialect, engine+version, connection id)

class GovernedQuery(BaseModel, frozen=True):
    sql: str
    dialect: str
    driver: str
    tables: tuple[str, ...]
    rls_applied: tuple[str, ...]        # rule descriptions applied (never values)
    masked_columns: tuple[str, ...]
    limit: int
    subject_digest: str

class SemanticQueryResult(BaseModel):
    columns: list[str]
    rows: list[dict]
    row_count: int
    truncated: bool
    duration_ms: int
    compiled_sql: str                   # governed SQL as executed
    audit_id: str
    result_id: str | None = None        # present only when the ResultHandleStore is enabled
```

```yaml
# <models_dir>/<model>.policy.yaml  (new side-file; schema in parrot/semantic/policy.py)
governed: true                 # default true; `false` opts the model out of PBAC/RLS/role checks
engine: sidemantic             # or: native
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
    async def save_result_as_dataset(self, result_id: str, name: str, description: str | None = None) -> dict  # only with a factory
```

---

## 3. Module Breakdown

> Define the discrete modules that will be implemented.
> These directly map to Task Artifacts in Phase 2.

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Distribution skeleton | yes | PEP 420 layout mirrors `packages/ai-parrot-embeddings`; exact pins and anchors in §6/§7 | — |
| M2: Query & result contracts | yes | pydantic v2 models above; validators enumerated in M2 skeleton; error hierarchy fixed | — |
| M3: Model policy side-file | yes | YAML schema above; unknown member ⇒ `SemanticPolicyError`; `governed` default `true` | — |
| M4: Loader + sidemantic engine | no | sidemantic API surface (`load_from_directory`, `compile`, filter-string grammar, `security:` detection) must be confirmed against the pinned wheel in the first task (spike) | engine API confirmation |
| M5: Native compiler | yes (after M4) | subset fixed in §2; sqlglot AST builder; fan-out ⇒ `SemanticValidationError` | — |
| M6: Governance pipeline | no | RLS push-down and lineage rules are security-critical; the thinking model owns the AST strategy | security design |
| M7: Role catalog + saved queries | yes | filter semantics fixed (`"*"` or list; `usage` list); suggestion = top-3 by difflib ratio | — |
| M8: Semantic audit ledger | yes | `SemanticAuditEntry` fields fixed below; `canonical_bytes` = sorted-key JSON without `signature` | — |
| M9: Execution bridge, compile cache, result handles | yes | `ConnectionResolver` env grammar fixed; LRU keyed by `CompiledQuery.cache_key`; handle fields fixed | — |
| M10: SemanticLayerToolkit | no | orchestration of M4–M9 with ContextVar + static_subject; exposure rules | integration surface |
| M11: HTTP handler + MCP config + docs | yes | `BaseView` pattern of `handlers/datasets.py`; YAML/JSON anchors in §6 | — |
| M12: Core request-scoped RLS fix (`issue:90cf04ce8edd`) | no | — | security-critical rewrite of an enforcement path; the thinking model owns the copy strategy |

### Module 1: `ai-parrot-semantic` distribution skeleton
- **Path**: `packages/ai-parrot-semantic/pyproject.toml`, `README.md`, `src/parrot/semantic/__init__.py`, `src/parrot/semantic/version.py`, `tests/__init__.py`, `tests/conftest.py`; MODIFY root `pyproject.toml`, `scripts/release.py`, `ruff.toml`, `.github/workflows/ci.yml`
- **Responsibility**: make `parrot.semantic` an installable PEP 420 satellite (`src/parrot/` has **no** `__init__.py`; only `src/parrot/semantic/__init__.py`), pinned `sidemantic==0.12.0`, `sqlglot>=30.1,<31`, `jsonschema>=4.20`, `pyyaml>=6`, `ai-parrot`; extras `bigquery` (`google-cloud-bigquery>=3.30`), `duckdb` (`duckdb>=1.0`); `license = "MIT"` + README section "License notice: sidemantic is AGPL-3.0" (network clause spelled out); workspace source entry; `release.py` `PACKAGES` entry; `ruff.toml` TID251 ban `"sidemantic"` with a per-file ignore for `packages/ai-parrot-semantic/**`; CI step running the satellite tests.
- **Depends on**: nothing (first task).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-semantic/src/parrot/semantic/version.py  (new)
  __version__ = "1.3.0"

  # packages/ai-parrot-semantic/src/parrot/semantic/__init__.py  (new — written once here, finalized by M10)
  """ai-parrot-semantic — governed semantic layer (sidemantic core + sqlglot governance)."""
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
  # ruff.toml  (modifies ruff.toml:125 banned-api table; ruff.toml:137 per-file-ignores)
  "sidemantic".msg = "AGPL-3.0 dependency confined to ai-parrot-semantic; import it only under packages/ai-parrot-semantic/."
  "packages/ai-parrot-semantic/**" = ["TID251"]
  ```

### Module 2: Query & result contracts + error taxonomy
- **Path**: `packages/ai-parrot-semantic/src/parrot/semantic/models.py`, `errors.py`
- **Responsibility**: the pydantic contracts in §2 Data Models and the exception hierarchy. Validators: `saved_query` XOR `metrics`; a `FilterGroup` never mixes metric leaves and dimension leaves (member kinds resolved later by M7, so the validator takes a `member_kinds: dict[str, Literal["metric","dimension"]]` argument via `SemanticQuery.validate_against(model_members)`); `offset > 0` requires `order_by`; `grain` required for time dimensions; `limit` ≥ 1.
- **Depends on**: M1.
- **Interface Skeleton**:
  ```python
  # parrot/semantic/errors.py  (new)
  class SemanticError(Exception): """Base for all semantic-layer errors; carries `code: str` and `details: dict`."""
  class SemanticValidationError(SemanticError): """Malformed or unsatisfiable SemanticQuery (unknown member, mixed filter group, missing grain, fan-out in native)."""
  class SemanticPolicyError(SemanticError): """Invalid model/policy definition (unknown member in policy, sidemantic `security:` block, bad RLS binding)."""
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
      governed: bool = True; engine: Literal["sidemantic", "native"] = "sidemantic"; connection: str
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

### Module 4: Model loader, Ossie import, sidemantic engine
- **Path**: `packages/ai-parrot-semantic/src/parrot/semantic/loader.py`, `ossie.py`, `engines/__init__.py`, `engines/sidemantic_engine.py`, `schemas/ossie-0.1.1.schema.json` (vendored)
- **Responsibility**: load a models directory into `LoadedModel`s (sidemantic `SemanticLayer` via its directory loader; Ossie documents validated against the vendored 0.1.1 JSON Schema first; `security:` blocks rejected); derive `ModelMember`s and the **physical schema map** (`schema.table` → columns/types) for `qualify`, lineage and RLS; compile a `SemanticQuery` with sidemantic (filter tree → sidemantic filter strings) into a `CompiledQuery`; the single `compile()` dispatch on `policy.engine`. The first task of this module is a bounded **spike** that confirms the sidemantic 0.12.0 API names used here against the installed wheel and records them in the task Completion Note (names below are the brainstorm's reading of the sidemantic docs and are marked `(unverified — check before use)` until then).
- **Depends on**: M2, M3.
- **Interface Skeleton**:
  ```python
  # parrot/semantic/loader.py  (new)
  class PhysicalSchema(BaseModel):
      driver: str; tables: dict[str, dict[str, str]]   # "schema.table" -> {column: sqlglot type}
      def sqlglot_schema(self) -> dict: """Nested mapping accepted by sqlglot.optimizer.qualify.qualify(schema=...)."""
  class LoadedModel(BaseModel, arbitrary_types_allowed=True):
      name: str; layer: Any  # sidemantic.SemanticLayer (unverified — check before use)
      policy: ModelPolicy; members: list[ModelMember]; schema: PhysicalSchema
      model_digest: str; policy_digest: str; engine_version: str
  class SemanticModelLoader:
      def __init__(self, models_dir: Path, *, driver: str) -> None: ...
      def load(self) -> dict[str, LoadedModel]:
          """Load every model + policy pair; raise SemanticPolicyError for `security:` blocks or policy/model mismatch."""
      def reload_if_changed(self) -> bool: """Re-read when any file mtime/digest changed; returns True when versions moved."""

  # parrot/semantic/ossie.py  (new)
  OSSIE_SPEC_VERSION = "0.1.1"
  def validate_ossie_document(doc: dict) -> None: """jsonschema-validate against the vendored schema; raise SemanticPolicyError with the first error path."""
  def is_ossie_document(doc: dict) -> bool

  # parrot/semantic/engines/sidemantic_engine.py  (new)
  def filter_tree_to_sidemantic(filters: FilterGroup | None, members: dict[str, ModelMember]) -> list[str]:
      """Translate the typed filter tree into sidemantic filter expressions; values rendered as typed literals via sqlglot."""
  def compile_sidemantic(query: SemanticQuery, model: LoadedModel, dialect: str) -> CompiledQuery:
      """Sync, CPU-only; called under asyncio.to_thread by engines.compile(). Never passes user_attributes (no sidemantic SecurityPolicy)."""

  # parrot/semantic/engines/__init__.py  (new)
  async def compile(query: SemanticQuery, model: LoadedModel, dialect: str, *, cache: "CompileCache | None" = None) -> CompiledQuery:
      """Dispatch on model.policy.engine ∈ {sidemantic, native}; LRU hit skips compilation only. No plugin protocol."""
  ```

### Module 5: Native fallback compiler
- **Path**: `packages/ai-parrot-semantic/src/parrot/semantic/engines/native.py`
- **Responsibility**: compile the v1 subset — metrics with `sum/count/count_distinct/avg/min/max`, dimensions, `DATE_TRUNC` grains (`exp.DateTrunc`), declared one-to-many joins (fan-out ⇒ `SemanticValidationError`), filter tree (WHERE vs HAVING), order/limit/offset — into a sqlglot AST rendered per dialect. Metric/dimension expressions come from the `LoadedModel` members (sidemantic model objects read for definitions only). Parity tests against the sidemantic engine on DuckDB fixtures.
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
          """Probe evaluator availability at construction (navigator-auth importable, guard not None); record `available`."""
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
      model: str; model_digest: str; policy_digest: str; engine: str; tool: str
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
      def verify(self, entry: SemanticAuditEntry) -> bool
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
      result_id: str; agent_id: str | None; user_id: str; tenant_id: str; session_id: str | None
      subject_digest: str   # SHA-256 over (user_id, tenant_id, sorted roles, sorted policy-relevant session.metadata items) — metadata is NOT part of UserSession's hash (permission.py:49), so it is hashed explicitly here
      model: str; model_digest: str; policy_digest: str; expires_at: datetime
      columns: list[str]; rows: list[dict]; audit_id: str; governed_sql: str
  class ResultHandleStore:
      def __init__(self, *, ttl_s: int = 900, max_entries: int = 256) -> None: ...
      def put(self, handle: ResultHandle) -> str: """Opaque random id (secrets.token_urlsafe)."""
      def claim(self, result_id: str, *, ctx: PermissionContext, subject_digest: str, model_digest: str, policy_digest: str) -> ResultHandle:
          """Owner, session, context digest and versions must all match and the handle must be unexpired; else SemanticResultError. Metadata alone is never authorization."""
  ```

### Module 10: `SemanticLayerToolkit`
- **Path**: `packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py`, `context.py`; finalize `__init__.py` exports
- **Responsibility**: the `AbstractToolkit` surface of §2 New Public Interfaces. `_pre_execute` stores `_permission_context` (or a `PermissionContext` built from `static_subject`, flagged) in a module-level ContextVar **and** in `parrot.auth.context._pctx_var`; every tool goes catalog-check → compile (cached) → govern → execute/return → audit. `run_sql` exposed only when `allow_raw_sql=True`; `save_result_as_dataset` only when `dataset_manager_factory` is provided (via `exclude_tools`, like `DatabaseQueryToolkit` does for `save_result`, toolkit.py:175-176). A `governed` model with no `dataplane_guard` makes the toolkit refuse to construct (fail closed at startup).
- **Depends on**: M3–M9.
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
          """Set ContextVars from kwargs['_permission_context'] or static_subject; log static use."""
      async def _post_execute(self, tool_name: str, result: Any, /, **kwargs) -> Any:   # toolkit.py:506 — serialize pydantic results to dicts
      # tools — see §2 New Public Interfaces for signatures/docstrings
      def reload(self) -> None: """Not a tool; re-run the loader and invalidate caches."""
      def _dataset_manager_for(self, ctx: PermissionContext) -> Awaitable[DatasetManager]: """Call the host factory; a factory returning a shared manager (same instance for two subjects) raises SemanticResultError."""
  ```

### Module 11: HTTP handler, MCP exposure, docs
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/semantic.py` (new); MODIFY `packages/ai-parrot-server/src/parrot/manager/manager.py`, `.parrot/mcp-toolkits.yaml`, `.mcp.json`; `docs/tools/semantic-layer.md` (new)
- **Responsibility**: `SemanticLayerHandler(BaseView)` with `GET` (catalog for the session subject), `POST …/compile`, `POST …/query`, `POST …/results/{result_id}/dataset`; `PermissionContext` from the navigator-auth session (same decorators as `handlers/datasets.py:20`); the hand-off factory is `DatasetManagerHandler._get_dataset_manager`'s per-user manager (datasets.py:162). Registration in `manager.py` guarded by `importlib.util.find_spec("parrot.semantic")`. MCP: a `semantic-layer:` section (class path, `kwargs` incl. `static_subject`, `env`) + `.mcp.json` entry mirroring `parrot-database-query`. Docs: `docs/tools/semantic-layer.md` (tools, policy file, AGPL notice, mcp-local identity).
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
  # .parrot/mcp-toolkits.yaml  (modifies .parrot/mcp-toolkits.yaml:121 — new sibling section before `database-query:`)
  semantic-layer:
    class: parrot.semantic.toolkit.SemanticLayerToolkit
    kwargs: {models_dir: /path/to/models, dialect: duckdb, static_subject: {user_id: operator, tenant_id: local, roles: [admin]}}
    env: {}
  ```

---

### Module 12: Core fix — request-scoped RLS in `AuthorizingDataSource`, cloned sources in `_clone_agent_dm` (§8 Q6)
- **Path**: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/authorizing.py`, `packages/ai-parrot-server/src/parrot/handlers/datasets.py`
- **Discovered-from**: `issue:90cf04ce8edd` (vulnerability, major) — the M12 task carries this line so `/sdd-done` closes the issue.
- **Responsibility**: make RLS injection **request-scoped**. Today `_apply_rls` (authorizing.py:153) rewrites the wrapped source in place (`self._inner.sql = rewritten_sql`, :191; `_permanent_filter` / `required_filter` mutations for Table/QuerySlug/Mongo), so predicates accumulate across fetches and leak to every holder of the same inner object; `_clone_agent_dm` (datasets.py:47) then hands the SAME `entry.source` to every per-user `DatasetManager` (:70). Fix: (1) `_apply_rls` returns a **per-call shallow copy** of the inner source (`copy.copy`, so pools/credentials are shared but the mutable filter state is not) with the rewritten SQL / a copied-and-extended `_permanent_filter` / merged mongo filter applied to the copy, and `fetch()` delegates to that copy; `self._inner` is never mutated. (2) `_clone_agent_dm` builds each `DatasetEntry` with `source=_clone_source(entry.source)` (shallow copy + fresh `dict` for `_permanent_filter` when present) so no two user managers share a source object. No public signature changes (AC17): `_apply_rls`'s return type goes `None → DataSource` (private).
- **Depends on**: nothing in M1–M11 (core-only; runs concurrently with the satellite tasks).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/tools/dataset_manager/sources/authorizing.py  (modify)
  import copy                                                             # add next to `import logging` (authorizing.py:27)
  class AuthorizingDataSource(DataSource):                                # line 41 — unchanged signature
      async def fetch(self, **params) -> pd.DataFrame:                    # line 74 — Step 5/6 become:
          # target = self._apply_rls(predicates, resources) if predicates else self._inner
          # return await target.fetch(**params)
      def _apply_rls(self, predicates: "list[RlsPredicate]", resources: "PhysicalResources") -> DataSource:   # was -> None
          """Return a request-scoped copy of ``self._inner`` with RLS applied; NEVER mutate ``self._inner``.
          scoped = copy.copy(self._inner); SQLQuerySource → scoped.sql = rewritten; TableSource/QuerySlugSource →
          scoped._permanent_filter = dict(self._inner._permanent_filter) then inject_rls_*(scoped, predicates);
          MongoSource → merged filter assigned on `scoped` only; unknown source type → return scoped unchanged (existing warning kept)."""

  # packages/ai-parrot-server/src/parrot/handlers/datasets.py  (modify)
  def _clone_source(source: "DataSource | None") -> "DataSource | None":  # new module-level helper above _clone_agent_dm (datasets.py:47)
      """Shallow-copy a DataSource for a per-user manager; copy `_permanent_filter` into a fresh dict when the source has one; None stays None."""
  def _clone_agent_dm(agent: object, logger: object) -> DatasetManager | None:   # line 47 — unchanged signature; `source=entry.source,` (:70) → `source=_clone_source(entry.source),`
  ```
- **Behavioural guarantees** (tested in §4): two consecutive `fetch()` calls on one `AuthorizingDataSource` apply exactly one RLS wrapper each and leave `inner.sql` untouched; two subjects with different predicates fetching through the same wrapper never see each other's predicate; `_clone_agent_dm` produces entries whose `source` objects are pairwise distinct and whose `_permanent_filter` dicts are not shared with the agent's entry.
- **Existing test to amend**: `packages/ai-parrot/tests/auth/test_authorizing_data_source.py::test_rls_injected_before_fetch` (line 189) asserts the buggy in-place mutation (`assert "_rls" in inner.sql`, :210) — rewrite it to assert the fetch target carries the wrapper while `inner.sql` is unchanged (use a `SQLQuerySource` subclass whose `fetch` records `self.sql`).

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_packaging_namespace` | M1 | `import parrot.semantic` works alongside core; `src/parrot/` has no `__init__.py`; version matches |
| `test_sidemantic_import_ban` | M1 | `ruff check` flags `import sidemantic` in a temp file under `packages/ai-parrot/src`, not under the satellite |
| `test_semantic_query_validators` | M2 | saved_query XOR metrics; mixed filter group rejected; offset needs order_by; grain required |
| `test_canonical_json_stable` | M2 | key order / whitespace independent |
| `test_policy_unknown_member_rejected` | M3 | misspelled metric/table/role binding → `SemanticPolicyError` |
| `test_policy_defaults_governed` | M3 | missing `governed` → `True`; `governed: false` honoured |
| `test_loader_rejects_security_block` | M4 | model with sidemantic `security:` → `SemanticPolicyError` |
| `test_ossie_schema_validation` | M4 | Apache Ossie 0.1.1 fixtures load; a schema-invalid doc fails with the error path |
| `test_sidemantic_compile_pg_bq_duckdb` | M4 | same query → three dialects, no connection, output has no subject values |
| `test_native_compiler_subset` | M5 | aggregations, grains, 1:N joins compile; many-to-many → `SemanticValidationError` |
| `test_native_vs_sidemantic_parity` | M5 | identical row sets on DuckDB fixtures for the subset |
| `test_pbac_gate_fail_closed` | M6 | ctx None / guard None / evaluator unavailable on governed → `SemanticAccessError`; ungoverned passes |
| `test_pbac_denied_table_blocks_sql` | M6 | `table:read` denied on one joined table → no SQL returned, source never called |
| `test_rls_pushdown_below_aggregation` | M6 | `SUM` over a tenant-filtered base scan equals the expected subset; wrapping strategy would differ |
| `test_rls_typed_literals_and_render_failure` | M6 | values are literals (quotes escaped); render failure → deny |
| `test_lineage_masked_column_inference` | M6 | `WHERE salary > x`, HAVING, JOIN, GROUP BY, ORDER BY, window, alias, CTE, derived → denied without usage rights |
| `test_masking_strategies` | M6 | null / hash / partial projections; catalog hides hidden members |
| `test_positive_guard` | M6 | unknown column/function/table, DDL/DML, multi-statement, missing LIMIT, over-cap LIMIT |
| `test_positive_guard_adversarial_matrix` | M6 | `SELECT *`, quoted/mixed-case identifiers, aliases, CTEs, nested subqueries, windows, joins, derived sensitive columns, `exp.Command`, comments — across postgres / bigquery / duckdb dialects |
| `test_compile_concurrent_to_thread` | M4 | 32 concurrent `compile()` calls through `asyncio.to_thread` on one `LoadedModel` produce identical SQL to the serial run (reentrancy gate, §8 Q2) |
| `test_dialect_sql_snapshots` | M4/M5 | normalized-AST snapshots of the fixture queries for postgres and bigquery (both engines) — a diff is a release gate, not a warning |
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
| `test_rls_not_persisted_across_fetches` | M12 | two `fetch()` calls → each fetch target has exactly one RLS wrapper; `inner.sql` unchanged (amends `test_rls_injected_before_fetch`) |
| `test_rls_two_subjects_isolated` | M12 | subjects A/B with different predicates through one `AuthorizingDataSource`; neither sees the other's predicate; Table/QuerySlug `_permanent_filter` of the inner untouched |
| `test_clone_agent_dm_copies_source` | M12 | `_clone_agent_dm` twice → source objects pairwise distinct from each other and from the agent's; `_permanent_filter` dicts not shared; `None` source preserved (`packages/ai-parrot-server/tests/handlers/test_datasets_clone.py`) |

### Integration Tests
| Test | Description |
|---|---|
| `test_e2e_duckdb_governed_query` | Models dir + policy → `sl_query_metrics` on an in-process DuckDB source; rows, audit entry, governed SQL recorded |
| `test_e2e_rls_two_subjects_same_roles` | Warm cache as user A; user B with same roles/tenant but different `programs` gets only their rows; cached AST unchanged |
| `test_e2e_pbac_denial_paths` | denial on `driver:connect` / `table:read` across compile-only, saved query, dimension values, raw SQL and cache hits → no SQL, no execution |
| `test_e2e_masked_inference_matrix` | the §4 lineage matrix end-to-end through `sl_run_sql` and structured filters |
| `test_e2e_handoff_two_users_two_sessions` | foreign/expired handles rejected; identical names isolated; read after policy change denied; shared manager cannot enable the tool |
| `test_e2e_native_engine_switch` | `engine: native` model produces parity results with sidemantic on DuckDB |
| `test_e2e_mcp_local_semantic_layer` | `parrot mcp-local semantic-layer --list` resolves the section; tool list matches exposure rules (stdio, no real LLM) |
| `test_e2e_dataset_manager_rls_two_users` | M12 end-to-end: one agent `DatasetManager` with a SQL source cloned for users A and B (`_clone_agent_dm`), fetched under each `PermissionContext` — rows differ per subject, the agent's source SQL is unchanged, repeated fetches do not stack predicates (`packages/ai-parrot/tests/auth/test_datasetmanager_authz_integration.py`) |

### Validation Contract

tests:
- packages/ai-parrot/tests/auth/test_authorizing_data_source.py
- packages/ai-parrot/tests/auth/test_datasetmanager_authz_integration.py
markers: none

> The two existing files above exercise M12's targets. No existing test exercises the satellite; its new
> files live under `packages/ai-parrot-semantic/tests/` and `packages/ai-parrot-server/tests/` and are each
> task's own `## Validation Commands`, added by the selector at merge/feature tier.

### Test Data / Fixtures
```python
# packages/ai-parrot-semantic/tests/conftest.py
@pytest.fixture
def duckdb_warehouse(tmp_path) -> str:
    """DuckDB file with sales.orders(region, tenant_id, order_date, amount), dim.customers(id, email, salary) and seeded rows."""

@pytest.fixture
def models_dir(tmp_path) -> Path:
    """sidemantic YAML `orders` model + `orders.policy.yaml` (roles analyst/admin, mask customers.email, RLS on sales.orders by programs) + an Ossie 0.1.1 document."""

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

- [ ] AC1 `pip install ai-parrot-semantic` (workspace member) installs `sidemantic==0.12.0`; `import parrot.semantic` works; no file under `packages/ai-parrot/`, `ai-parrot-tools/` or `ai-parrot-server/` imports `sidemantic` at module level, and `ruff check` enforces it (TID251).
- [ ] AC2 Compilation never opens a database connection and runs under `asyncio.to_thread`; the same `SemanticQuery` compiles to Postgres, BigQuery and DuckDB SQL.
- [ ] AC3 A model without `governed: false` denies compile, execute, dimension values, saved queries and raw SQL when `PermissionContext` is `None` or the PBAC evaluator is unavailable; `DataPlanePolicyGuard.authorize_source` is never called with `ctx=None` by the satellite.
- [ ] AC4 PBAC (`driver:connect`, `table:read`) is evaluated on every request including cache hits; a denial returns no SQL and calls no source.
- [ ] AC5 RLS predicates from `RlsRegistry` are injected at the base-table scan below aggregation; aggregate results equal the subset computed by hand; values appear only as typed literals; render failure denies.
- [ ] AC6 Column masking and usage rights: masked projections render per strategy; any filter/join/group/order/window/derived use of a masked or hidden column without usage rights is denied through aliases, CTEs and subqueries; unresolved lineage denies.
- [ ] AC7 The positive guard rejects unknown tables/columns/functions, DDL/DML, multi-statement SQL and `exp.Command`; `LIMIT` is injected (policy default) or clamped (policy max).
- [ ] AC8 The compile cache stores only pre-governance `CompiledQuery` objects (no subject values); governance re-runs on every hit; model/policy digest changes invalidate.
- [ ] AC9 Every request appends a signed `SemanticAuditEntry` (structured query, subject digest, model/policy digests, engine, compiled + governed SQL, dialect, outcome, rows, duration); verification of the signature succeeds; storage failures never fail the request.
- [ ] AC10 Result handles are opaque, bounded, expiring and owner/session/context/version-bound; `sl_save_result_as_dataset` rejects foreign/expired/stale handles, re-checks member rights and PBAC, and is not exposed without a subject-scoped `DatasetManager` factory; a factory returning a shared manager is refused.
- [ ] AC11 The native engine compiles the v1 subset and matches sidemantic row-for-row on the DuckDB parity fixtures; a many-to-many join on a native model is rejected.
- [ ] AC12 `sl_run_sql` exists only when `allow_raw_sql=True` and goes through the identical governance pipeline.
- [ ] AC13 `parrot mcp-local semantic-layer` serves the toolkit from a YAML section; `static_subject` use is logged and flagged in the audit entry.
- [ ] AC14 `SemanticLayerHandler` routes are registered only when `parrot.semantic` is importable and return 401 without a session.
- [ ] AC15 Apache Ossie 0.1.1 documents validate against the vendored schema and load; sidemantic `security:` blocks and unknown policy members are rejected at load.
- [ ] AC16 All unit + integration tests above pass with `PYTHONPATH=packages/ai-parrot-semantic/src:packages/ai-parrot/src` and in CI; `docs/tools/semantic-layer.md` and the satellite README (AGPL notice) exist.
- [ ] AC17 No public API of core, `ai-parrot-tools` or `ai-parrot-server` changes; `scripts/release.py` lists the new package.
- [ ] AC18 Release gates: concurrent-compile test, sidemantic↔native normalized-AST parity on the DuckDB fixtures, and postgres/bigquery SQL snapshots all pass; the positive-guard adversarial matrix passes for all three dialects.
- [ ] AC19 A governed model's catalog (`sl_list_models/metrics`, `sl_get_dimensions`, `sl_search_data_model`, `sl_list_saved_queries`) exposes nothing without an authorized subject; the model's declared resource manifest is authorized before compile and every compiled table is within it.
- [ ] AC20 (M12, `issue:90cf04ce8edd`) `AuthorizingDataSource.fetch()` never mutates its inner source: after N fetches `inner.sql` / `_permanent_filter` equal their constructor values and each fetch target carries exactly one RLS rewrite; `_clone_agent_dm` yields pairwise-distinct source objects per user manager; `test_authorizing_data_source.py` and `test_datasetmanager_authz_integration.py` pass; the ledger issue is closed by `/sdd-done`.
- [ ] AC21 (§8 Q3–Q5) `ModelPolicy.allowed_functions` only extends `DEFAULT_ALLOWED_FUNCTIONS`; `audit_required=None` resolves to `True` iff a durable `audit_storage` is configured and then withholds results on sink failure; `postgres_audit_storage` + `semantic_audit_events.sql` ship in the satellite and are documented.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.
> Verified against commit `ea2c1224b` (dev, 2026-10-19).

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
# M12 (core) — verified 2026-10-19
from parrot.tools.dataset_manager.sources.base import DataSource            # verified: sources/authorizing.py:32 (import site)
from parrot.tools.dataset_manager.sources.sql import SQLQuerySource          # verified: sources/sql.py:26; `self.sql = sql` at :53
from parrot.tools.dataset_manager.sources.rls import inject_rls_sql, inject_rls_table_source, inject_rls_query_slug   # verified: sources/rls.py:72,132,172 (table/slug variants mutate `source._permanent_filter` in place — rls.py:138,180)
from parrot.tools.dataset_manager import DatasetEntry, DatasetManager       # verified: handlers/datasets.py:32 (import site); DatasetEntry.__init__ dataset_manager/tool.py:144-153
from parrot.tools.dataset_manager.sources.dialects import driver_to_dialect  # verified: dialects.py:41
from parrot.tools.dataset_manager.sources.resolver import PhysicalResources, resolve_physical_resources  # verified: resolver.py:47,120
from parrot.tools.dataset_manager.sources.rls import inject_rls_sql          # verified: rls.py:72 (reference only — NOT used by the semantic layer)
from parrot.tools.dataset_manager import DatasetManager                      # verified: handlers/datasets.py:32 (import site); class at dataset_manager/tool.py:499
from parrot.interfaces.database import get_default_credentials               # verified: packages/ai-parrot/src/parrot/interfaces/database.py:501
from parrot.mcp.toolkit_config import ToolkitSection, MCPToolkitsConfig, load_toolkits_config  # verified: toolkit_config.py:20,80,90
from navigator.views import BaseView                                         # verified: packages/ai-parrot-server/src/parrot/handlers/datasets.py:19
from navigator_auth.decorators import is_authenticated, user_session         # verified: handlers/datasets.py:20
from navigator_session import get_session                                    # verified: handlers/datasets.py:21
import sqlglot; from sqlglot import exp; from sqlglot.optimizer.qualify import qualify   # sqlglot 30.23.0 installed; core floor "sqlglot>=20.0" (ai-parrot/pyproject.toml:182)
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/tools/dataset_manager/sources/authorizing.py   (M12)
class AuthorizingDataSource(DataSource):                                  # line 41
    def __init__(self, inner: DataSource, guard: "DataPlanePolicyGuard", pctx_provider: Callable[[], Optional["PermissionContext"]]) -> None   # line 58; self._inner = inner (:65)
    async def fetch(self, **params) -> pd.DataFrame                        # line 74; Step 5 `self._apply_rls(predicates, resources)` (:149), Step 6 `return await self._inner.fetch(**params)` (:151)
    def _apply_rls(self, predicates: "list[RlsPredicate]", resources: "PhysicalResources") -> None   # line 153; mutates self._inner.sql (:191), inject_rls_table_source(self._inner) (:199), inject_rls_query_slug(self._inner) (:207), self._inner.required_filter (:228,:232)
# packages/ai-parrot/src/parrot/tools/dataset_manager/sources/table.py / query_slug.py
#   TableSource.__init__(..., permanent_filter: Optional[Dict[str, Any]] = None)   # table.py:188; self._permanent_filter: Dict[str, Any] (:196)
#   QuerySlugSource: self._permanent_filter: Dict[str, Any]                 # query_slug.py:98
# packages/ai-parrot-server/src/parrot/handlers/datasets.py   (M12)
def _clone_agent_dm(agent: object, logger: object) -> DatasetManager | None   # line 47; `source=entry.source,` at :70 inside DatasetEntry(name=, source=, metadata=, is_active=, auto_detect_types=, cache_ttl=)

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
| `SemanticLayerToolkit._pre_execute` | `parrot.auth.context._pctx_var.set()` | ContextVar | `auth/context.py:33` |
| `PbacGate.authorize` | `DataPlanePolicyGuard.authorize_source(ctx, resources)` | method call, never with `ctx=None` | `auth/dataplane_guard.py:193` |
| `RlsPushdown.apply` | `RlsRegistry.lookup(driver, tables)` / `.render(rule, ctx)` | method calls | `auth/rls_registry.py:125,150` |
| `ModelPolicy.rls` | `RlsRule` | pydantic reuse; rules registered into the toolkit's `RlsRegistry.register()` | `auth/rls_registry.py:49,112` |
| `GovernancePipeline.govern` | `QueryValidator.validate_sql_ast(query, dialect, read_only=True)` | classmethod call | `security/query_validator.py:165` |
| `Executor.run` | `DatabaseQueryToolkit.get_source(driver)` → `AbstractDatabaseSource.query(credentials, sql)` | method calls | `databasequery/toolkit.py:202`, `base.py:446` |
| `ConnectionResolver.resolve` | `get_default_credentials(driver)` | function call | `interfaces/database.py:501` |
| `SemanticAuditLedger` | `AbstractKMSSigner.sign/verify`, `LocalHMACSigner` | constructor injection | `security/audit_ledger.py:135,143,154,166` |
| `SemanticLayerToolkit.save_result_as_dataset` | `DatasetManager.add_dataframe(...)` on the factory's manager | method call | `dataset_manager/tool.py:1091` |
| `SemanticLayerHandler` | `BaseView`, `is_authenticated`, `user_session`, `get_session` | same imports as `DatasetManagerHandler` | `handlers/datasets.py:19-21,141` |
| `manager.py` registration | `router.add_view(...)` | two new lines after the datasets views | `manager/manager.py:2571-2572` |
| `.parrot/mcp-toolkits.yaml` `semantic-layer:` | `ToolkitSection(class, kwargs, env)` → `parrot mcp-local semantic-layer` | config | `mcp/toolkit_config.py:50-57`, `local_cli.py:164` |
| `GovernancePipeline` dialects | `SQLGLOT_DIALECT_MAP` / `driver_to_dialect` | lookup | `knowledge/common/sql_dialects.py:6`, `dataset_manager/sources/dialects.py:41` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.semantic`~~, ~~`packages/ai-parrot-semantic/`~~ — created by this feature (M1). ~~`parrot_tools.semantic`~~ — must NOT be created (AGPL boundary).
- ~~`sidemantic`~~, ~~`boring_semantic_layer`~~, ~~`ibis`~~ — not installed in the venv (2026-10-19); only the satellite declares `sidemantic`. No `import ibis` in `packages/*/src` except the throwaway `dataset_manager/spatial/_ibis_probe.py`.
- sidemantic API names used in M4 (`SemanticLayer`, `load_from_directory`, `compile(metrics=, dimensions=, filters=, order_by=, limit=, dialect=)`, the `ossie` importer) are **(unverified — check before use)** until the M4 spike records them from the installed `sidemantic==0.12.0` wheel.
- ~~`SemanticQuery`~~, ~~`CompiledQuery`~~, ~~`GovernedQuery`~~, ~~`SemanticLayerToolkit`~~, ~~`sl_*` tools~~, ~~`SemanticAuditEntry`~~, ~~`ModelPolicy`~~, ~~`PbacGate`~~, ~~`RlsPushdown`~~, ~~`ResultHandleStore`~~ — none exist; names are fixed by this spec.
- ~~`AuditLedgerEntry.payload` / `.compiled_sql` / `.structured_query`~~ — `AuditLedgerEntry` has only credential-shaped fields; `AuditLedger.append()` requires `credential_material`. Decision: a separate `SemanticAuditEntry` ledger (M8).
- ~~RLS push-down below aggregation anywhere in core~~ — `inject_rls_sql` (rls.py:72) only **wraps** the statement; the semantic layer does not call it.
- ~~A positive table/column allowlist in core~~ — `QueryValidator.validate_sql_ast` and `SQLToolkit._check_query_safety` (`bots/database/toolkits/sql.py:578`) are negative guards.
- ~~Named-connection credentials in `DatabaseQueryToolkit`~~ — `__init__` accepts only `output_dir`/`static_dir`; credentials are the first positional argument of `AbstractDatabaseSource.query()`. Decision: `ConnectionResolver` in the satellite (M9).
- ~~`_post_execute` receiving `_permission_context`~~ — it receives tool params only (toolkit.py:195-198); read the context from the ContextVar set in `_pre_execute`.
- ~~`DataPlanePolicyGuard` failing closed on `ctx=None`~~ — it fails **open** (dataplane_guard.py:52, 193-200); `PbacGate` must deny before calling it.
- ~~`resolve_physical_resources(sql, driver)`~~ — it takes a `DataSource` (resolver.py:120); the satellite builds `PhysicalResources(driver=, tables={...})` from the AST itself.
- ~~`packages/ai-parrot-server/src/parrot/models/datasets.py`~~ — request models live in core `packages/ai-parrot/src/parrot/models/datasets.py`.
- ~~`UserInfoService.get_attributes()`~~ — only `get_profile(user_id)` / `get_profile_by_email(email)` exist (auth/userinfo.py:80,149,197).
- ~~An async API in sidemantic / BSL / MetricFlow~~ — none; compile in `asyncio.to_thread`.
- ~~`sidemantic-rs` as a requirement of `sidemantic==0.12.0`~~ — the published wheel does not require it (PyPI JSON 2026-10-19); `main` does — hence the exact pin.
- ~~An Apache Ossie Python SDK on PyPI~~ — `ossie` / `apache-ossie` / `osi-spec` do not exist; validation is the vendored JSON Schema + sidemantic's importer.
- ~~Server code changes for `mcp-local`~~ — a YAML `class:` section is sufficient (`toolkit_config.py:50`).
- ~~`ai-parrot-semantic` in `KNOWN_PROJECTS`~~ — `parrot.knowledge.wiki.ledger.sdd_meta.KNOWN_PROJECTS` does not list it (warns only); add it in M1 if the vocabulary is editable in-repo, otherwise leave the warning.
- ~~A `ruff.toml` entry banning `sidemantic`~~ — the TID251 table (ruff.toml:125-135) bans requests/httpx/starlette/fastapi/uvicorn/langchain*/langgraph/langsmith only; M1 adds `sidemantic`.
- ~~`DataSource.copy()` / `.clone()` / `model_copy()`~~ — `DataSource` subclasses are plain classes (not pydantic); M12 uses `copy.copy` + explicit `dict()` of `_permanent_filter`.
- ~~`MongoSource.required_filter` as a dict~~ — `MongoSource.__init__` takes `required_filter: bool` and stores `self._required_filter` (mongo.py:77,84); the attribute `authorizing.py:228,232` assigns is a dynamic one. M12 keeps that branch's semantics but applies it to the per-call copy only; redesigning the Mongo filter is out of scope.
- ~~`packages/ai-parrot-server/tests/handlers/test_datasets_clone.py`~~ — created by M12.
- ~~`asyncdb` as a satellite dependency~~ — `postgres_audit_storage` uses `asyncpg` directly (already a transitive dependency of `ai-parrot`).
- ~~A CI step running `packages/ai-parrot-semantic/tests`~~ — `ci.yml` runs `uv sync --all-packages` (line 27) and per-suite pytest steps (e.g. line 506); M1 adds the satellite step.

### Edit Sites (Blueprint Anchors)

Verified against: `ea2c1224b`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `pyproject.toml` | MODIFY | `ai-parrot-openlit-bridge = { workspace = true }` | `pyproject.toml:239` | 1 |
| `scripts/release.py` | MODIFY | `PACKAGES: list[Package] = [` | `scripts/release.py:116` | 1 |
| `ruff.toml` | MODIFY | `[lint.flake8-tidy-imports.banned-api]` | `ruff.toml:125` | 1 |
| `ruff.toml` | MODIFY | `[lint.per-file-ignores]` | `ruff.toml:137` | 1 |
| `.github/workflows/ci.yml` | MODIFY | `        run: uv run pytest packages/ai-parrot-tools/tests/tool_optimizations -q --tb=short` | `.github/workflows/ci.yml:506` | 1 |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | `from ..handlers.datasets import DatasetManagerHandler` | `manager.py:45` | 1 |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | `        router.add_view("/api/v1/agents/datasets/{agent_id}", DatasetManagerHandler)` | `manager.py:2571` | 1 |
| `.parrot/mcp-toolkits.yaml` | MODIFY | `  database-query:` | `.parrot/mcp-toolkits.yaml:121` | 1 |
| `.mcp.json` | MODIFY | `    "parrot-database-query": {` | `.mcp.json:64` | 1 |
| `packages/ai-parrot-semantic/pyproject.toml` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/README.md` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/src/parrot/semantic/__init__.py` | CREATE (M1), MODIFY (M10 exports) | `__all__ = ["__version__"]` (after M1) | — | — |
| `packages/ai-parrot-semantic/src/parrot/semantic/version.py` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/src/parrot/semantic/models.py` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/src/parrot/semantic/errors.py` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/src/parrot/semantic/policy.py` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/src/parrot/semantic/loader.py` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/src/parrot/semantic/ossie.py` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/src/parrot/semantic/schemas/ossie-0.1.1.schema.json` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/src/parrot/semantic/engines/__init__.py` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/src/parrot/semantic/engines/sidemantic_engine.py` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/src/parrot/semantic/engines/native.py` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/src/parrot/semantic/governance/{__init__,pbac,lineage,rls,masking,guard,pipeline}.py` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/src/parrot/semantic/catalog.py` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/src/parrot/semantic/audit.py` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/src/parrot/semantic/{execution,cache,results}.py` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/src/parrot/semantic/{toolkit,context}.py` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/tests/{__init__,conftest}.py` + `tests/test_*.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/src/parrot/handlers/semantic.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/tests/unit/test_semantic_handler.py` | CREATE | — | — | — |
| `docs/tools/semantic-layer.md` | CREATE | — | — | — |
| `packages/ai-parrot-semantic/src/parrot/semantic/sql/semantic_audit_events.sql` | CREATE (M8) | — | — | — |
| `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/authorizing.py` | MODIFY (M12) | `import logging` | `authorizing.py:27` | 1 |
| `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/authorizing.py` | MODIFY (M12) | `            self._apply_rls(predicates, resources)` | `authorizing.py:149` | 1 |
| `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/authorizing.py` | MODIFY (M12) | `            self._inner.sql = rewritten_sql` | `authorizing.py:191` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/datasets.py` | MODIFY (M12) | `def _clone_agent_dm(agent: object, logger: object) -> DatasetManager | None:` | `datasets.py:47` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/datasets.py` | MODIFY (M12) | `                source=entry.source,` | `datasets.py:70` | 1 |
| `packages/ai-parrot/tests/auth/test_authorizing_data_source.py` | MODIFY (M12) | `    async def test_rls_injected_before_fetch(` | `test_authorizing_data_source.py:189` | 1 |
| `packages/ai-parrot/tests/auth/test_datasetmanager_authz_integration.py` | MODIFY (M12) | — (append a test class) | — | — |
| `packages/ai-parrot-server/tests/handlers/test_datasets_clone.py` | CREATE (M12) | — | — | — |

- `__init__.py` of the satellite is the only file two modules touch (M1 creates, M10 finalizes); their tasks are serialized.
- `/sdd-task` MUST re-run `grep -c -F` for every MODIFY row; `grep` in this repo is aliased to `ugrep` by RTK, so use `-F` for anchors containing `(`, `[` or `{`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **ContextVar for the per-call subject** (`DatasetManager._get_current_pctx`, tool.py:2663; `DatabaseQueryTool`, tool.py:598-600): set in `_pre_execute`, read inside tools, never stored on `self`.
- **Toolkit exposure via `exclude_tools`** (`DatabaseQueryToolkit.__init__`, toolkit.py:175-176) for `run_sql` and `save_result_as_dataset`.
- **Satellite packaging** mirrors `packages/ai-parrot-embeddings/pyproject.toml` (setuptools, `dynamic = ["version"]`, `dependencies = ["ai-parrot"]`, `license = "MIT"`, `requires-python = ">=3.11,<3.14"`); PEP 420: no `src/parrot/__init__.py`.
- **Trusted provenance by node identity**: RLS and mask nodes injected by the pipeline are remembered by `id(node)` in the same pass; callers can never label SQL as trusted.
- **Fail closed everywhere governance is involved**; fail open is only acceptable for `governed: false` models, and never for hand-off ownership.
- **Credentials from env/navconfig only**; tool arguments never carry credentials or connection names.
- **Async-first**: compile and sqlglot passes run in `asyncio.to_thread`; execution via the async sources; `self.logger` logging; Pydantic v2; 120 cols; Google docstrings.
- **Worktree testing**: `PYTHONPATH=packages/ai-parrot-semantic/src:packages/ai-parrot/src pytest packages/ai-parrot-semantic/tests`; never `uv sync` inside a worktree; `sidemantic` is installed by the main-checkout operator once M1 lands.

### Known Risks / Gotchas
- **AGPL-3.0 network clause** (sidemantic): the satellite is opt-in and documents it; legal sign-off recorded in §8 Q1 (Jesus Lara, 2026-10-19). Keep every sidemantic import under `packages/ai-parrot-semantic/` (TID251 backstop, AC1).
- **Single maintainer, unlabeled breaking changes** in sidemantic: exact pin `==0.12.0`; upgrade only through a spike task that re-runs the parity and governance suites; `main` already adds a Rust wheel.
- **`SemanticLayer.compile` reentrancy unknown**: one layer per model, compile under an `asyncio.Lock` until the M4 spike proves it reentrant (§8 Q2); cache hits bypass the lock.
- **Wrapping RLS is wrong for aggregates**: never call `inject_rls_sql` from the semantic layer; AC5 pins push-down below aggregation with a numeric parity test.
- **`DataPlanePolicyGuard` fails open on `ctx=None` and on missing navigator-auth**: `PbacGate` denies before the call and probes availability at construction.
- **Schema drift**: compile succeeds, DB fails → `SemanticExecutionError` with the audit id; SQL goes to the audit, never to the LLM message.
- **Mixed WHERE/HAVING filter groups**, **grain missing**, **offset without order** → validation errors (M2).
- **Fan-out joins in native mode** → rejected; sidemantic's symmetric aggregates are the only v1 path for many-to-many.
- **Cache poisoning across subjects**: cache stores pre-governance SQL only; `cache_key` excludes subject data; AC8 + `test_e2e_rls_two_subjects_same_roles`.
- **Hand-off into a shared `DatasetManager`** would leak governed rows: factory must return a subject/session-scoped manager; shared instance detection refuses the tool (AC10). Hosts without downstream gates must not provide a factory.
- **RTK/ugrep** aliasing in this repo turns `grep` patterns into regex; use `-F` for anchors.
- **Dialect without a source** (e.g. `snowflake`): compile allowed, execution refused with a clear error.
- **`static_subject` is a single operator identity** for `parrot mcp-local`: every call runs as that subject, so the YAML must never grant it broader roles than the operator holds; a per-call signed identity envelope was considered (design research S9) and deferred — mcp-local is a local developer surface, the identity is explicit, logged and flagged in every audit entry.
- **Core `AuthorizingDataSource` mutates its inner SQL and HTTP clones share `entry.source`** (`sources/authorizing.py:191`, `handlers/datasets.py:70`): fixed by **M12** in this feature (§8 Q6, `issue:90cf04ce8edd`, AC20). Independently of the fix, the semantic layer never registers a *source*, only a copied DataFrame, and the host factory must hand out subject/session-scoped managers (AC10). Gotcha for M12: `copy.copy` shares connection objects by design — only the mutable filter state (`sql`, `_permanent_filter`, mongo filter) must be per-call.
- **`audit_required` auto-resolves to `True` with a durable sink** (§8 Q5): a misconfigured Postgres DSN makes every governed call fail closed with `audit_unavailable` — surface it at toolkit construction with a startup log line, and document `audit_required=False` as the explicit opt-out.
- **`allowed_functions` policy additions are a widening of the positive guard** (§8 Q4): review them like RLS text; the loader upper-cases names and rejects anything that is not a bare identifier.
- **Ossie 0.1.x is a moving spec**: version pinned in the vendored schema; a 0.2 document is rejected, not coerced.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `sidemantic` | `==0.12.0` (AGPL-3.0, 2026-09-13) | semantic model core, 15-format import (Ossie), metric compile; transitive: `antlr4-python3-runtime>=4.13.2`, `click>=8`, `duckdb>=1.0`, `jinja2>=3.1`, `pydantic>=2`, `pyyaml>=6`, `sqlglot>=30.1`, `typer>=0.18` |
| `sqlglot` | `>=30.1,<31` (MIT; venv 30.23.0) | AST guard, lineage, RLS push-down, masking, native compiler, dialect rendering |
| `jsonschema` | `>=4.20` | Apache Ossie 0.1.1 document validation |
| `pyyaml` | `>=6` (already in core) | policy side-files |
| `duckdb` | `>=1.0` (venv 1.5.6; extra `duckdb`) | sidemantic hard dependency; parity/e2e fixtures via `DuckDBSource` |
| `google-cloud-bigquery` | `>=3.30` (extra `bigquery`; venv 3.46.2) | BigQuery execution via the existing source |
| `asyncpg` | via `ai-parrot` (venv 0.32.0) | Postgres execution via the existing source |

---

## 8. Open Questions

> Questions that must be resolved before or during implementation.

- [x] License field of the satellite — *Resolved in brainstorm*: MIT for the satellite (`license = "MIT"` like the other satellites); the AGPL-3.0 dependency and its network clause are documented in the satellite README and the spec; written legal sign-off is tracked as a spec §8 item, not a blocker
- [x] "No abstraction" vs native fallback — *Resolved in brainstorm*: confirmed — one internal `compile()` dispatching on `model.engine ∈ {sidemantic, native}`; no plugin protocol, no third-party engine registry
- [x] Audit storage — *Resolved in brainstorm*: separate `SemanticAuditEntry` ledger in the satellite, reusing `AbstractKMSSigner`/`LocalHMACSigner` and the async `storage` callable contract; zero core change. Production sink wiring stays configurable (storage callable), default in-memory
- [x] Deny-by-default scope — *Resolved in brainstorm*: every model is governed by default — compile/execute deny without a `PermissionContext` or evaluator unless the policy file sets `governed: false`
- [x] `mcp-local` identity — *Resolved in brainstorm*: allowed — `.parrot/mcp-toolkits.yaml` may declare a `static_subject` (user, tenant, roles, metadata) for `parrot mcp-local semantic-layer`; it is logged on every call and recorded in the audit entry
- [x] Credentials for execution — *Resolved in brainstorm*: resolved inside the satellite — the model's `connection` name maps to a credentials dict via navconfig/env lookups in `parrot.semantic`; no change to `DatabaseQueryToolkit`
- [x] Free SQL (`sl_run_sql`) — *Resolved in brainstorm*: ship in v1, disabled by default (`allow_raw_sql=False`), on the same governance path (PBAC, lineage, RLS, positive guard, audit)
- [x] Native compiler v1 subset — *Resolved in brainstorm*: confirmed as drafted — simple aggregations, dimensions, `DATE_TRUNC` grains, declared one-to-many joins, filter tree, order/limit; no symmetric aggregates, no cumulative/time-comparison metrics
- [x] Commit the proposal doc — *Resolved in brainstorm*: yes — committed to `dev` together with this brainstorm acceptance
- [x] Q1 Written legal sign-off for the AGPL-3.0 dependency — *Resolved 2026-10-19*: approved by **Jesus Lara (2026-10-19)**. The satellite stays `license = "MIT"`; sidemantic's AGPL-3.0 network clause (hosted API) is documented in the satellite README and `docs/tools/semantic-layer.md` (M11). No further sign-off gates `/sdd-done` or the 1.3.0 tag.
- [x] Q2 sidemantic `SemanticLayer.compile` reentrancy and `load_from_directory` acceptance of Apache Ossie 0.1.1 fixtures — *Resolved 2026-10-19 (delegated)*: decided by the M4 spike task against the installed `sidemantic==0.12.0` wheel. Until the spike proves `compile` reentrant, the engine compiles under a per-model `asyncio.Lock` (safe default, §7). The spike's Completion Note records lock vs lock-free and the importer-fidelity outcome; the spec is not reopened for it.
- [x] Q3 Production sink for `SemanticAuditLedger.storage` — *Resolved 2026-10-19*: **Postgres table shipped by the satellite** — `parrot/semantic/sql/semantic_audit_events.sql` (DDL modelled on `security/security_events.sql`, one row per `SemanticAuditEntry`, JSONB payload + indexed `user_id`/`tenant_id`/`model`/`outcome`/`created_at`) and an opt-in `postgres_audit_storage(dsn_or_pool, table="semantic_audit_events")` factory returning the async `storage(json_str)` callable (M8). Default remains the in-memory ledger; the Postgres callable is wired by the host (toolkit kwarg `audit_storage` / YAML `kwargs`). The credential-ledger sink is NOT reused (two schemas in one table rejected).
- [x] Q4 Allowed-function allowlist default for the positive guard — *Resolved 2026-10-19*: `DEFAULT_ALLOWED_FUNCTIONS` (M6 `guard.py`) = aggregates `SUM, COUNT, COUNT DISTINCT, AVG, MIN, MAX` + `DATE_TRUNC, EXTRACT, COALESCE, CAST, LOWER, UPPER` + arithmetic / comparison / boolean operators (operators are sqlglot expression nodes, not `exp.Func`, and are always allowed). Per-model **additive** override: `ModelPolicy.allowed_functions: list[str]` (M3) — the effective set is `DEFAULT ∪ toolkit kwarg allowed_functions ∪ policy.allowed_functions`; nothing can remove a default, and DDL/DML/`exp.Command` stay denied regardless.
- [x] Q5 `audit_required` default — *Resolved 2026-10-19*: the toolkit kwarg becomes `audit_required: bool | None = None` and is **resolved at construction**: `None` → `True` when a durable `audit_storage` callable is configured, `False` when only the in-memory ledger is in use (it cannot fail). An explicit `True`/`False` always wins. With `True`, a storage failure raises `SemanticExecutionError('audit_unavailable')` and the governed result is withheld (M8/M10); AC9's "storage failures never fail the request" applies to the resolved-`False` case only.
- [x] Q6 Core finding (S2) `AuthorizingDataSource` in-place RLS rewrite + `_clone_agent_dm` shared `entry.source` — *Resolved 2026-10-19*: **folded into this feature as Module 12** (behavioural fix, no public signature change, so AC17 holds). Ledger issue `issue:90cf04ce8edd` is claimed by the M12 task (`**Discovered-from**: issue:90cf04ce8edd`) and closed by `/sdd-done` with the two-key evidence. M12 has no edge to M1–M11 and runs concurrently.

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
---

## Worktree Strategy

- **Isolation**: one feature worktree `feat-FEAT-704-semantic-layer` (from `origin/dev`); the
  `sdd-coder` engine gives each task its own sub-worktree inside it.
- **Module dependency graph** (edge = import/contract dependency, with evidence):
  - M2 → M1 (package must exist to import `parrot.semantic.errors`).
  - M3 → M2 (`ModelPolicy` embeds `SemanticQuery` in `SavedQuery` and reuses `ModelMember`).
  - M4 → M2, M3 (`LoadedModel` carries `ModelPolicy`; `compile()` returns `CompiledQuery`).
  - M5 → M4 (`NativeCompiler(LoadedModel)` uses `PhysicalSchema` and members).
  - M6 → M2, M3, M4 (`GovernancePipeline.govern(model: LoadedModel)`; `ModelPolicy.usage_allowed/mask_for`).
  - M7 → M3, M4 (`RoleCatalog(models: dict[str, LoadedModel])`).
  - M8 → M2 only (`SemanticAuditEntry` is self-contained).
  - M9 → M2, M6 (`Executor.run(GovernedQuery)`; `CompileCache(CompiledQuery)`).
  - M10 → M3…M9.  M11 → M10.
  - **M12 → nothing** (core-only edit of `sources/authorizing.py` + `handlers/datasets.py`; no satellite import). It may start in wave 1 alongside M1.
  - **Concurrent after M4**: M5, M6, M7, M8, M9 have no edges among themselves (M9 needs only `GovernedQuery`
    from M2/M6's contract, which is fixed in §2 — M9 may start on the model alone).
- **Shared files**: `packages/ai-parrot-semantic/src/parrot/semantic/__init__.py` (M1 create, M10
  finalize) — serialized. `handlers/datasets.py` is modified by M12 only (M11 creates `handlers/semantic.py` and
  edits `manager.py`, not `datasets.py`). No other file is touched by two modules.
- **Exclusive resources**: M1 changes `uv.lock`/workspace membership and requires the main-checkout
  operator to install `sidemantic` into the shared venv (`parallel: false`); M11's `manager.py`,
  `.parrot/mcp-toolkits.yaml`, `.mcp.json` edits are single-task.
- **Ordering inside M10**: the `run_sql` and `save_result_as_dataset` tools are the **last** tasks of the feature and depend on the
  governance/lineage/cache-isolation/hand-off security tests (§4) being green — governed metric queries ship first (design research S12).
- **Cross-feature dependencies**: none in flight touch the integration points (checked 2026-10-19
  over `sdd/tasks/index/*.json`). `FEAT-699` test-selector changes are already on `dev`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-19 | Jesus Lara | Initial draft from the accepted brainstorm (Option B), 9 brainstorm questions carried forward as resolved |
| 0.2 | 2026-10-19 | Jesus Lara | §8 Q1–Q6 resolved: AGPL sign-off recorded; Q2 delegated to the M4 spike; Postgres audit sink + `postgres_audit_storage` (M8); `DEFAULT_ALLOWED_FUNCTIONS` + additive `ModelPolicy.allowed_functions` (M3/M6); `audit_required=None` auto-resolution (M10); core fix `issue:90cf04ce8edd` folded in as **M12** (new tests, AC20–AC21, §6 anchors, validation contract now lists the two existing auth test files) |
