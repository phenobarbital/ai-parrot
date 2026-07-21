---
type: Wiki Overview
title: Deterministic Data-Plane Authorization for DatasetManager
id: doc:sdd-proposals-brainstorm-dataplane-authz-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Driver-level, table-level, dataset-level access control + Row-Level Security
  (RLS),
---

---
feature: dataplane-authz
slug: feat-dataplane-authz
type: brainstorm
base_branch: dev
status: draft            # blockers in §10 must be resolved before /sdd-spec
supersedes: null
depends_on: [FEAT-151]   # DatasetManager PBAC (DatasetPolicyGuard + _pctx_var)
date: 2026-06-07
---

# Deterministic Data-Plane Authorization for DatasetManager

Driver-level, table-level, dataset-level access control + Row-Level Security (RLS),
enforced at the **physical-source boundary**, transparent to the LLM, deterministic.

---

## 1. Problem Statement

FEAT-151 gave `DatasetManager` a working PBAC spine: a `PermissionContext`
propagated out-of-band via the module-level `_pctx_var` ContextVar, and a
three-layer `DatasetPolicyGuard` (`filter_datasets`, `filter_columns`,
`can_read_dataset`). This is **sound for the catalog model**: pre-registered,
stably-named datasets evaluated against `dataset:<name>` policies.

It is **porous for the ad-hoc execution surface**, which is exactly where a
real "Finance data only for the Finance group / superusers" guarantee must hold:

1. **Alias-keyed enforcement.** `_pre_execute` evaluates `can_read_dataset(name)`,
   but `name` is chosen by the caller. `fetch_dataset(name="sales_q3",
   query="SELECT * FROM finance.salaries", driver="bigquery")` evades a
   `dataset:finance` policy because the policy never sees `finance.salaries` —
   only the innocuous alias.
2. **No driver as a resource.** There is no resource/action expressing "block the
   whole `bigquery_finance` driver unless Finance/superuser". The taxonomy stops
   at `dataset:<name>`.
3. **`database_query` is ungated.** `DatabaseQueryTool` takes raw `driver`+`query`
   and (as of this writing) is constrained only by the `bots/data.py` system
   prompt ("DATASET ACCESS POLICY — NO BYPASS"). That is **LLM-enforced security**,
   the precise property we must eliminate.
4. **No RLS.** Group membership today is all-or-nothing per dataset. There is no
   mechanism to say "Finance sees all rows, regional managers see only their
   region" by injecting a mandatory predicate derived from subject attributes.

**Goal:** move the Policy Enforcement Point (PEP) to the physical-source boundary,
derive the resource identity from what the source *actually touches* (driver +
parsed tables) rather than from the LLM-chosen alias, add driver/table as
first-class resources, and add RLS as a mandatory predicate injected from the
signed subject context.

### Non-Goals

- **Not** redesigning the propagation chain (`PermissionContext` → `tool.execute`
  → `_current_pctx` → `_pctx_var`). It works; we reuse it verbatim.
- **Not** replacing the navigator-auth PBAC engine (`PolicyEvaluator`/`PDP`).
- **Not** prompt-level / LLM-level enforcement. The system prompt allow-list in
  `bots/data.py` stays as belt-and-suspenders only, never the boundary.
- **Not** redesigning column masking — `filter_columns` (`dataset:column:read`)
  already covers it; RLS is the *row* axis, orthogonal.
- **Not** authorizing non-data toolkits (Jira, MCP, etc.) — out of scope.

---

## 2. Constraints

- **Determinism.** Identity is read from `_pctx_var` (signed session origin),
  never from any LLM-supplied argument. The resource is resolved by us from the
  source definition, never trusted from the alias.
- **LLM transparency.** Denial surfaces as a structured forbidden `ToolResult`
  (L2) or a silent catalog drop (L1). The LLM cannot distinguish "absent" from
  "denied" at L1 and cannot bypass at L2.
- **Backwards-compatible opt-in.** No guard configured → no enforcement
  (fail-open). `navigator-auth` absent → fail-open (matches FEAT-151 semantics).
- **Fail-closed on the sensitive path.** SQL parse failure, missing session, or
  evaluator error on a guarded driver → DENY, no fetch.
- **`sqlglot` is already a dependency** (confirmed by user). Table extraction and
  RLS predicate injection use it; no new dependency.
- **Remote-execution-safe.** Under `executor=` (qworker / RemoteAgentProxy) the
  `_pctx_var` does not cross the process boundary; the context must travel in the
  envelope, **signed**, and be re-established on the worker.
- Conversation in Spanish; **all code/specs/docs in English.**

---

## 3. Codebase Contract

> Anti-hallucination discipline: symbols below were read from the repo via
> `project_knowledge_search`. Re-anchor each with the grep command before editing.
> Anything not directly observed is flagged `⚠️ VERIFY` in §3.3.

### 3.1 Verified symbols (grep anchors)

| Symbol | File | grep anchor |
|---|---|---|
| `DatasetManager(AbstractToolkit)` | `parrot/tools/dataset_manager/tool.py` | `rg -n "class DatasetManager" packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` |
| `_pctx_var` (module ContextVar) | `parrot/tools/dataset_manager/tool.py` | `rg -n "_pctx_var" packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` |
| `DatasetManager._get_current_pctx` | same | `rg -n "_get_current_pctx" packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` |
| `DatasetManager._pre_execute` | same | `rg -n "async def _pre_execute" packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` |
| `DatasetManager.fetch_dataset` | same | `rg -n "async def fetch_dataset" packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` |
| `DatasetManager.materialize` | same | `rg -n "async def materialize" packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` |
| `DatasetManager.get_tools_filtered` | same | `rg -n "async def get_tools_filtered" packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` |
| `DatasetManager._policy_guard` attr | same | `rg -n "_policy_guard" packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` |
| `DataSource` (ABC) + `.fetch()` `.describe()` `.cache_key` `.has_builtin_cache` | `parrot/tools/dataset_manager/sources/` | `rg -n "class DataSource|def fetch|has_builtin_cache" packages/ai-parrot/src/parrot/tools/dataset_manager/sources/` |
| `SQLQuerySource(sql, driver, dsn, credentials)` | `parrot/tools/dataset_manager/sources/sql.py` | `rg -n "class SQLQuerySource" packages/ai-parrot/src/parrot/tools/dataset_manager/sources/sql.py` |
| `TableSource(table, driver, dsn, credentials, strict_schema, permanent_filter)` | `parrot/tools/dataset_manager/sources/table.py` | `rg -n "class TableSource" packages/ai-parrot/src/parrot/tools/dataset_manager/sources/table.py` |
| `QuerySlugSource(slug, permanent_filter)` | `parrot/tools/dataset_manager/sources/query_slug.py` | `rg -n "class QuerySlugSource" packages/ai-parrot/src/parrot/tools/dataset_manager/sources/query_slug.py` |
| `DatasetPolicyGuard` + `filter_datasets`/`filter_columns`/`can_read_dataset` | `parrot/auth/dataset_guard.py` | `rg -n "class DatasetPolicyGuard|async def (filter_datasets|filter_columns|can_read_dataset)" packages/ai-parrot/src/parrot/auth/dataset_guard.py` |
| `PBACPermissionResolver` + `can_execute`/`filter_tools` | `parrot/auth/resolver.py` | `rg -n "class PBACPermissionResolver|async def (can_execute|filter_tools)" packages/ai-parrot/src/parrot/auth/resolver.py` |
| `PermissionContext` / `UserSession` / `to_eval_context` | `parrot/auth/permission.py` | `rg -n "class PermissionContext|class UserSession|def to_eval_context" packages/ai-parrot/src/parrot/auth/permission.py` |
| `setup_pbac` | `parrot/auth/pbac.py` | `rg -n "def setup_pbac" packages/ai-parrot/src/parrot/auth/pbac.py` |
| `AuthorizationRequired` | `parrot/auth/exceptions.py` | `rg -n "class AuthorizationRequired" packages/ai-parrot/src/parrot/auth/exceptions.py` |
| `AbstractTool.execute` (pops `_permission_context`/`_resolver`, remote `executor=` dispatch) | `parrot/tools/abstract.py` | `rg -n "async def execute|_permission_context|executor" packages/ai-parrot/src/parrot/tools/abstract.py` |
| `ToolkitTool._execute` (re-injects `_current_pctx`) | `parrot/tools/toolkit.py` | `rg -n "class ToolkitTool|_current_pctx" packages/ai-parrot/src/parrot/tools/toolkit.py` |
| `AbstractToolkit._pre_execute/_post_execute` | `parrot/tools/toolkit.py` | `rg -n "async def _pre_execute|async def _post_execute" packages/ai-parrot/src/parrot/tools/toolkit.py` |
| `DatabaseQueryTool._execute/get_supported_drivers/test_connection` | `parrot/tools/databasequery/tool.py` | `rg -n "async def _execute|def get_supported_drivers|async def test_connection" packages/ai-parrot/src/parrot/tools/databasequery/tool.py` |
| `add_row_limit`, `_SQL_DRIVERS`, dialect frozensets | `parrot/tools/databasequery/base.py` | `rg -n "def add_row_limit|_SQL_DRIVERS|_SQL_NO_LIMIT_DRIVERS" packages/ai-parrot/src/parrot/tools/databasequery/base.py` |
| `normalize_driver` (canonical driver aliasing) | `parrot/tools/databasequery/sources.py` | `rg -n "def normalize_driver" packages/ai-parrot/src/parrot/tools/databasequery/sources.py` |

### 3.2 navigator-auth ABAC surface (verified via lazy-import sites)

| Symbol | Import path | Notes |
|---|---|---|
| `PolicyEvaluator.check_access(ctx, resource_type, resource_name, action, env)` | `navigator_auth.abac.policies.evaluator` | returns obj w/ `.allowed`, `.matched_policy`, `.reason` |
| `PolicyEvaluator.filter_resources(ctx, resource_type, resource_names, action, env)` | same | returns obj w/ `.allowed` (list of allowed names) |
| `ResourceType` | `navigator_auth.abac.policies.resources` | members: `TOOL, KB, VECTOR, AGENT, MCP, URI, DATASET, WIDGET, CARD`. Accepts **plain strings** too (see §3.2bis) |
| `Environment` | `navigator_auth.abac.policies.environment` | |
| `EvalContext(username, groups, roles, programs)` | `navigator_auth.abac.context` | built from session userinfo |
| `PolicyEffect.DENY` | `navigator_auth.abac.policies.abstract` | default effect (deny-by-default) |
| **Rust PEP** `evaluate_single` / `filter_resources_batch` (PyO3) | `navigator_auth/rs_pep/src/lib.rs` | the *actual* matcher — Python `Resource`/`ResourcePattern` are not the hot path; engine errors **fail closed** (deny); honors `default_effect` |

> Caveat: read from `phenobarbital/navigator-auth` HEAD, not your pinned workspace
> version. The structural facts below (Rust engine, glob matching, no obligations)
> are unlikely to differ across versions, but pin-confirm `V5`/`V8`.

### 3.2bis Resolved unknowns (V1–V3) — verification log

**V1 — RESOLVED: no enum change needed; use string resource types.**
`ResourceType` lacks `DRIVER`/`TABLE`/`SOURCE`, but `PolicyEvaluator.check_access`
formats the resource as `f"{rt.value if hasattr(rt,'value') else rt}:{name}"` —
i.e. a **plain string `resource_type` flows through unchanged**. The Rust
`policy_covers_resource` splits any `"type:name"` generically. So we pass
`resource_type="driver"`, `"table"`, `"source"` as strings. (Adding enum members
to navigator-auth is optional tidiness, not a dependency.)

**V2 — RESOLVED: hierarchy is glob/regex in policy `resources`, not chained workaround.**
Rust `matches_pattern(pattern, name)` supports `*` (all), `?`/`*` globs
(`glob_match`), and full regex (auto-detected by metacharacters `^$()+{}[]|`).
`policy_covers_resource` matches `ptype == "*" || ptype == rtype` AND
`matches_pattern(pname, rname)`. Therefore:
- `resources: ["driver:bigquery_finance"]` — exact driver grant.
- `resources: ["driver:*"]` — all drivers.
- `resources: ["table:bigquery_finance:*"]` — all tables under that driver
  (glob `*` spans the remaining `:`/`.`).
- `resources: ["table:pg:sales\\..*"]` — regex per-schema.
Driver→table inheritance is **declarative via glob**. We keep `driver:connect` and
`table:read` as distinct *actions* (for the short-circuit gate), but §5.8's
"chained checks as a portability workaround" is no longer needed.

**V3 — RESOLVED: no obligations; RLS lives in a parrot-side registry.**
Rust `EvaluationResult` carries only `{allowed, effect, matched_policy, reason}`.
`PolicyDef` has `{name, effect, resources, actions, subjects, conditions,
priority, enforcing}` — `conditions` are *match inputs* (env/context gating),
**not output obligations**. A grant cannot return a predicate. RLS predicates
therefore live in `rls_registry.py`, keyable by `(driver, table)` **or** by the
returned `matched_policy` name (the engine reports the winning policy). Bonus:
`PolicyDef.enforcing` + `priority` are engine-native — `enforcing=false` gives a
free **shadow/dry-run** mode that aligns with the shadow-mode roadmap.

**V8 — RESOLVED: sqlglot 30.9.0 dialects + driver map fixed (§5.2).**
Dialect ids confirmed: `athena, bigquery, clickhouse, databricks, doris, dremio,
drill, druid, duckdb, dune, exasol, fabric, hive, materialize, mysql, oracle,
postgres, presto, prql, redshift, risingwave, singlestore, snowflake, solr, spark,
spark2, sqlite, starrocks, tableau, teradata, trino, tsql`. Table extraction
(`find_all(exp.Table)` minus `find_all(exp.CTE).alias_or_name`) tested against
CTEs / subqueries / derived tables / `UNION ALL`; read-only gate via top-node type
(`exp.Drop`/`exp.Update` detected) tested. Dialect-strict parsing rejects
cross-dialect SQL (BigQuery bare `UNION`) → fail-closed on mismatch.

### 3.3 ⚠️ VERIFY before /sdd-spec — remaining (V1–V3 resolved in §3.2bis)

| # | Unknown | Verification command / action |
|---|---|---|
| V4 | Is `materialize()` reachable **without** passing through `_pre_execute` (e.g. `PythonPandasTool` calling `dm.materialize(name)` directly, or QS `has_builtin_cache` path)? If yes, the alias-check is bypassable internally. | `rg -n "\.materialize\(|\.fetch_dataset\(" packages/ai-parrot/src/parrot` |
| V5 | Exact `DatasetManager.__init__` signature — does it already accept `policy_guard=`? | `rg -n "def __init__" packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` |
| V6 | Remote `executor=` envelope schema — what fields cross the wire, where is it deserialized in `parrot-agent-runtime`? | `rg -n "executor|envelope|RemoteAgentProxy" packages/ai-parrot/src/parrot/tools/abstract.py` and the runtime service handler |
| V7 | AuditLedger signing API (KMS) to sign/verify the remote context claim. | `rg -n "class AuditLedger|def sign|def verify" packages/ai-parrot/src/parrot` |
| V8 | sqlglot dialect identifiers for each driver alias (`pg`→`postgres`, `bq`→`bigquery`, `mssql`→`tsql`, …). | `python -c "import sqlglot; print(sqlglot.Dialect.classes.keys())"` |
| V9 | Which sources can emit raw SQL we must parse vs. opaque sources (Airtable, Smartsheet, Mongo, Iceberg, Delta) that need a different resource model. | review each `sources/*.py` `.fetch()` |

---

## 4. Threat / Bypass Inventory

| # | Bypass | Covered today? | This design |
|---|---|---|---|
| B1 | Alias spoofing (`name="benign"`, query hits `finance.*`) | ❌ | resource resolved from parsed tables, not alias |
| B2 | Whole-driver access for unprivileged subject | ❌ (no driver resource) | `driver:connect` checked first, fail-closed |
| B3 | `database_query` raw driver+query | ❌ (prompt only) | same guard wired into `DatabaseQueryTool` |
| B4 | Direct `materialize()` internal call skipping `_pre_execute` | ⚠️ V4 | enforce inside source boundary (Option D), not on the tool entry |
| B5 | Remote worker runs without identity | ❌ | signed context in envelope, re-established as `_pctx_var` |
| B6 | Row leakage to over-broad group | ❌ (no RLS) | mandatory predicate injection (RLS) |
| B7 | CTE / subquery / `UNION` hiding a guarded table | n/a | sqlglot `find_all(exp.Table)` walks the full AST, incl. CTEs/subqueries |
| B8 | Opaque source (Airtable/Mongo) referencing guarded data | n/a | `source:<type>:<id>` + `source:read`, per-type resolution (§5.2b) |
| B9 | DML/DDL smuggled as a "query" (`DROP`, `UPDATE`, …) | ❌ | read-only gate: non-`Select`/`Union` root → `ReadOnlyViolation` (§5.2) |
| B10 | Free SQL on a finance-class driver under a benign slug name | partial | `sensitive` driver class = `slug_only`, rejects raw SQL pre-parse (§5.2a) |

---

## 5. Architecture

### 5.1 Resource taxonomy & actions

Extend the existing `dataset:` / `dataset:<n>:<col>` keys with:

```
driver:<driver>                      action: driver:connect
table:<driver>:<schema>.<table>      action: table:read
dataset:<name>                       action: dataset:read           # existing
dataset:<name>:<column>              action: dataset:column:read    # existing
source:<type>:<identifier>           action: source:read            # opaque sources
```

RLS is **not** a new resource; it is a predicate attached to a `table:`/`dataset:`
grant (see §5.5).

`⚠️ V1` **resolved (§3.2bis):** these are passed as **plain string** `resource_type`
values (`"driver"`, `"table"`, `"source"`) — the evaluator and Rust matcher handle
non-enum types generically. No navigator-auth enum change required. Keys keep the
FEAT-151 prefix convention.

### 5.2 Physical-resource resolution (deterministic, sqlglot)

A pure, side-effect-free resolver maps a `DataSource` to the set of physical
resources it will touch. **No LLM input is trusted here.**

| Source mode | Resolution |
|---|---|
| `TableSource(table, driver)` | `{driver:<d>, table:<d>:<table>}` — trivial |
| `SQLQuerySource(sql, driver)` | parse `sql` with sqlglot (dialect = `driver`→§V8); `find_all(exp.Table)` over the full AST (CTEs, subqueries, JOINs, UNION); each → `table:<d>:<catalog.db.name>`; plus `driver:<d>` |
| `QuerySlugSource(slug)` | resource declared at slug-registration time, not inferred at runtime (slug → known query → known tables) |
| `InMemorySource` / `dataframe=` | no driver touch; governed by whatever grant admitted the DataFrame |
| Opaque (`Airtable`, `Smartsheet`, `Mongo`, `Iceberg`, `Delta`) | `source:<type>:<identifier>` — **shipped this feature** (V9), per-type extraction in §5.2b |

Parse failure on a **guarded** driver → DENY (fail-closed). For unguarded drivers
(no matching policy) the catalog stays open per backwards-compat.

**sqlglot recipe (V8 verified, sqlglot 30.9.0).** Resolution is pure and tested:

```python
import sqlglot
from sqlglot import exp

def physical_tables(sql: str, dialect: str) -> set[str]:
    tree = sqlglot.parse_one(sql, dialect=dialect)          # ParseError → caller DENIES
    if not isinstance(tree, (exp.Select, exp.Union, exp.Subquery, exp.With)):
        raise ReadOnlyViolation(type(tree).__name__)        # reject DROP/UPDATE/INSERT/... (read-only gate)
    cte_names = {c.alias_or_name for c in tree.find_all(exp.CTE)}
    tables = set()
    for t in tree.find_all(exp.Table):
        if t.name in cte_names:                             # CTE reference, not physical
            continue
        tables.add(".".join(p for p in (t.catalog, t.db, t.name) if p))
    return tables
```

Verified behaviors: physical tables inside CTE bodies, subqueries, derived tables,
and `UNION ALL` branches are all captured; CTE aliases and derived-table aliases are
**excluded**; `DROP`/`UPDATE` parse to `exp.Drop`/`exp.Update` so the read-only gate
is deterministic. Dialect-strict parsing can reject SQL valid in another engine
(e.g. BigQuery rejects bare `UNION`), so picking the right dialect matters — and
a mismatch fails **closed** (DENY), never open.

**Driver → sqlglot dialect map** (right column = sqlglot 30.9.0 dialect ids;
left = ai-parrot driver aliases, `⚠️ VERIFY` against `normalize_driver`):

| ai-parrot driver | sqlglot dialect |
|---|---|
| `pg` / `postgres` / `postgresql` | `postgres` |
| `mysql` / `mariadb` | `mysql` |
| `bigquery` / `bq` | `bigquery` |
| `mssql` / `sqlserver` | `tsql` |
| `oracle` | `oracle` |
| `snowflake` | `snowflake` |
| `redshift` | `redshift` |
| `clickhouse` | `clickhouse` |
| `duckdb` | `duckdb` |
| `sqlite` | `sqlite` |
| `trino` / `presto` | `trino` / `presto` |
| `spark` / `databricks` | `spark` / `databricks` |

Unknown/unmapped driver on a guarded source → fail-closed (no fetch).

### 5.2b Opaque-source resolution (V9 — shipped)

Non-SQL sources resolve to `source:<type>:<identifier>` (action `source:read`) via a
small per-type strategy. RLS capability differs and is stated honestly:

| Source | Resource identifier | RLS mechanism | RLS caveat |
|---|---|---|---|
| `MongoSource` | `source:mongo:<db>.<collection>` | merge predicate into the query filter dict (`$and`) | native, server-side; strong |
| `IcebergSource` | `source:iceberg:<catalog>.<ns>.<table>` | predicate pushdown via the read engine | strong if engine supports pushdown |
| `DeltaTableSource` | `source:delta:<catalog.schema.table or path>` | predicate pushdown / partition filter | strong if pushdown supported |
| `AirtableSource` | `source:airtable:<base>.<table>` | `filterByFormula` if expressible, else post-fetch row filter | post-fetch = data enters process before filtering — acceptable for the process boundary, weaker than server-side; flag for sensitive bases |
| `SmartsheetSource` | `source:smartsheet:<sheet_id>` | post-fetch row filter | same caveat as Airtable |

For API sources (Airtable/Smartsheet) marked `sensitive`, prefer the `slug_only`
mode (§5.2a) or a registered server-side filter; do not rely on post-fetch RLS for
truly sensitive rows. Identifier unresolvable → fail-closed.

### 5.2a Driver class / enforcement mode (decision #1 — both supported)

Each driver carries an enforcement mode (parrot-side config, **not** a policy —
the engine can't distinguish ad-hoc from slug):

| Mode | Applies to | Behavior |
|---|---|---|
| `general` (default) | most drivers | **parsed + gated**: accept `query=`/`table=`, resolve physical resources (§5.2), gate `driver:connect`+`table:read`, inject RLS |
| `sensitive` | explicitly classed drivers (e.g. `bigquery_finance`) | **`slug_only`**: reject any non-`QuerySlugSource` (raw `query=`/`table=`) with `AuthorizationRequired` **before parsing**; only pre-registered `query_slug` whose tables/resources are declared at registration are allowed, then gated normally |

The mode check is the first step of the enforcement chain (§5.4 step 0), so a
`sensitive` driver gives the stronger "no free SQL" invariant while `general`
drivers keep the flexible parsed+gated path. Config source: `navconfig` /
`parrot/conf.py` driver-class map, e.g. `DATAPLANE_SENSITIVE_DRIVERS = {...}`.

### 5.3 PEP placement — chosen: Option D (`AuthorizingDataSource`)

| Option | Pros | Cons |
|---|---|---|
| A. keep `_pre_execute` on `name` | zero new code | insecure for ad-hoc (B1); alias-keyed |
| B. `_authorize_source()` in `fetch_dataset` | single point, sees raw args | must be re-added to `database_query` + every future entrypoint (B4) |
| C. inside each `DataSource.fetch()` | unskippable | enforcement scattered across N sources; easy to miss a new one |
| **D. `AuthorizingDataSource` decorator + central factory** ✅ | one enforcement site; composable; covers B4 because every agent-path source is wrapped at construction | requires a single `_make_source()` factory that **all** agent-facing construction routes through |

**Decision: D.** Introduce `AuthorizingDataSource(inner: DataSource, guard,
pctx_provider)` whose `.fetch()` (a) resolves physical resources from `inner`
(§5.2), (b) runs the enforcement chain (§5.4), (c) applies RLS rewrite (§5.5),
(d) delegates to `inner.fetch()`. A central `_make_source()` in `fetch_dataset`
(and the equivalent in `DatabaseQueryTool`) is the invariant that makes Option C
unnecessary: sources are never instantiated "naked" on the agent path. The
existing `_pre_execute`/`can_read_dataset` alias check is retained as a cheap L1
for pre-registered datasets.

### 5.4 Enforcement chain (deny-by-default, ordered)

```
0. mode = driver_class(driver)  # §5.2a
   if mode == "sensitive" and not isinstance(inner, QuerySlugSource):
        DENY (AuthorizationRequired)  # no free SQL on sensitive drivers, pre-parse
1. ctx = _pctx_var.get()         # None on direct/programmatic call → fail-open (HTTP-scoped, per FEAT-151)
2. resources = resolve_physical_resources(inner)     # §5.2 (read-only gate enforced here)
3. driver:connect  on driver:<d>           → DENY ⇒ AuthorizationRequired, no fetch
4. table:read / source:read  on each resource  → DENY on ANY ⇒ AuthorizationRequired

…(truncated)…
