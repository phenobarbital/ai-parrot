---
type: feature
base_branch: dev
---

# Feature Specification: Deterministic Data-Plane Authorization for DatasetManager

**Feature ID**: FEAT-228
**Date**: 2026-06-08
**Author**: Jesus Lara
**Status**: draft
**Target version**: 1.x (next minor)
**Depends on**: FEAT-151 (DatasetManager PBAC — DatasetPolicyGuard + `_pctx_var`)

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-151 established a working PBAC spine for `DatasetManager`: a
`PermissionContext` propagated via the module-level `_pctx_var` ContextVar, and
a three-layer `DatasetPolicyGuard` (`filter_datasets`, `filter_columns`,
`can_read_dataset`). This is sound for the **catalog model** — pre-registered,
stably-named datasets evaluated against `dataset:<name>` policies.

It is **porous for the ad-hoc execution surface**, which is where a real
"Finance data only for the Finance group / superusers" guarantee must hold:

1. **Alias-keyed enforcement.** `_pre_execute` evaluates `can_read_dataset(name)`,
   but `name` is chosen by the caller. A call like
   `fetch_dataset(name="sales_q3", query="SELECT * FROM finance.salaries",
   driver="bigquery")` evades a `dataset:finance` policy because the policy
   never sees `finance.salaries` — only the innocuous alias.
2. **No driver as a resource.** There is no resource/action expressing "block the
   whole `bigquery_finance` driver unless Finance/superuser". The taxonomy stops
   at `dataset:<name>`.
3. **`database_query` is ungated.** `DatabaseQueryTool` takes raw `driver`+`query`
   and is constrained only by a `bots/data.py` system prompt. That is
   **LLM-enforced security** — the property we must eliminate.
4. **No RLS.** Group membership is all-or-nothing per dataset. There is no
   mechanism for row-level filtering derived from subject attributes.

### Goals

- Move the Policy Enforcement Point (PEP) to the **physical-source boundary**,
  deriving resource identity from what the source *actually touches* (driver +
  parsed tables) rather than from the LLM-chosen alias.
- Add `driver` and `table` as first-class PBAC resource types alongside the
  existing `dataset` type.
- Add Row-Level Security (RLS) as a mandatory predicate injected from the signed
  subject context — deterministic, not LLM-dependent.
- Gate `DatabaseQueryTool` through the same enforcement chain.
- Support opaque (non-SQL) sources (Mongo, Iceberg, Delta, Airtable, Smartsheet)
  via `source:<type>:<identifier>` resources.
- Ensure fail-open backward compatibility when no guard is configured (matching
  FEAT-151 semantics).
- Enforce fail-closed on the sensitive path (SQL parse failure, missing session,
  evaluator error on a guarded driver → DENY).

### Non-Goals (explicitly out of scope)

- Redesigning the propagation chain (`PermissionContext` → `tool.execute` →
  `_current_pctx` → `_pctx_var`). It works; reused verbatim.
- Replacing the navigator-auth PBAC engine (`PolicyEvaluator`/PDP).
- Prompt-level / LLM-level enforcement. The `bots/data.py` system prompt stays
  as belt-and-suspenders only, never the boundary.
- Redesigning column masking — `filter_columns` (`dataset:column:read`) already
  covers it; RLS is the *row* axis, orthogonal.
- Authorizing non-data toolkits (Jira, MCP, etc.).
- *Runtime fallback-on-failure was rejected in brainstorm — see
  `sdd/proposals/brainstorm-dataplane-authz.md` Options A–C.*

---

## 2. Architectural Design

### Overview

**Chosen approach: Option D — `AuthorizingDataSource` decorator + central factory.**

Introduce `AuthorizingDataSource(inner: DataSource, guard, pctx_provider)` — a
decorator whose `.fetch()`:
1. Resolves physical resources from `inner` (driver + parsed tables via sqlglot).
2. Runs the enforcement chain (driver:connect → table:read/source:read → RLS).
3. Applies RLS predicate rewrite.
4. Delegates to `inner.fetch()`.

A central `_make_source()` factory in `DatasetManager.fetch_dataset` (and in
`DatabaseQueryTool._execute`) wraps every source in `AuthorizingDataSource` when
a guard is present. Sources are never instantiated "naked" on the agent path.

The existing `_pre_execute`/`can_read_dataset` alias check is retained as a
cheap L1 for pre-registered datasets.

#### Resource Taxonomy

Extend the existing `dataset:` / `dataset:<n>:<col>` keys with new
physical-resource types passed as **plain strings** to `PolicyEvaluator`
(no navigator-auth enum change needed — the Rust matcher handles non-enum types
generically):

```
driver:<driver>                      action: driver:connect
table:<driver>:<schema>.<table>      action: table:read
dataset:<name>                       action: dataset:read           # existing
dataset:<name>:<column>              action: dataset:column:read    # existing
source:<type>:<identifier>           action: source:read            # opaque sources
```

#### Enforcement Chain (deny-by-default, ordered)

```
0. mode = driver_class(driver)          # sensitive → slug_only pre-check
   if mode == "sensitive" and source is not QuerySlugSource:
        DENY (AuthorizationRequired)    # no free SQL on sensitive drivers
1. ctx = _pctx_var.get()                # None → fail-open (backwards compat)
2. resources = resolve_physical_resources(inner)   # sqlglot + read-only gate
3. driver:connect on driver:<d>         → DENY ⇒ AuthorizationRequired
4. table:read / source:read on each resource
   → DENY on ANY ⇒ AuthorizationRequired
5. rls = collect_rls_predicates(ctx, resources)    # from rls_registry
6. inner.fetch() with RLS predicate injected
```

#### Driver Enforcement Modes

Each driver carries an enforcement mode (parrot-side config):

| Mode | Behavior |
|---|---|
| `general` (default) | **Parsed + gated**: accept `query=`/`table=`, resolve physical resources, gate `driver:connect`+`table:read`, inject RLS |
| `sensitive` | **`slug_only`**: reject any non-`QuerySlugSource` with `AuthorizationRequired` before parsing; only pre-registered `query_slug` allowed |

Config source: `navconfig` / `parrot/conf.py` driver-class map,
e.g. `DATAPLANE_SENSITIVE_DRIVERS = {...}`.

### Component Diagram

```
                    LLM Tool Call
                         │
            ┌────────────┴────────────┐
            │                         │
   DatasetManager              DatabaseQueryTool
   .fetch_dataset()            ._execute()
            │                         │
            └────────┬────────────────┘
                     │
              _make_source() factory
                     │
           AuthorizingDataSource(inner)
                     │
      ┌──────────────┴───────────────────┐
      │                                  │
  resolve_physical_resources(inner)   driver_class check
      │  (sqlglot / per-type)            │ (sensitive → slug_only)
      │                                  │
      └──────────┬───────────────────────┘
                 │
    DataPlanePolicyGuard.authorize_source()
      │  driver:connect → table:read / source:read
      │
    rls_predicates() → collect from rls_registry
      │
    inject RLS (sqlglot AST rewrite / permanent_filter / Mongo filter)
      │
    inner.fetch()  ← actual DataSource
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `DatasetManager` (`parrot/tools/dataset_manager/tool.py`) | modifies | Add `_make_source()` factory; wrap sources in `AuthorizingDataSource` |
| `DatasetPolicyGuard` (`parrot/auth/dataset_guard.py`) | sibling | New `DataPlanePolicyGuard` shares the same `PolicyEvaluator` |
| `DatabaseQueryTool` (`parrot/tools/databasequery/tool.py`) | modifies | Route `_execute` through `AuthorizingDataSource`/resolver |
| `PermissionContext` (`parrot/auth/permission.py`) | uses | Read identity from `_pctx_var`; `to_eval_context()` for evaluator |
| `PolicyEvaluator` (navigator-auth) | calls | `check_access()` and `filter_resources()` with string resource types |
| `_pctx_var` ContextVar | reads | Existing propagation chain from FEAT-151 |
| `AbstractToolkit._pre_execute` (`parrot/tools/toolkit.py`) | keeps | L1 alias check retained for catalog datasets |
| `ToolkitTool._execute` (`parrot/tools/toolkit.py`) | unchanged | `_current_pctx` injection continues to work |
| `normalize_driver` (`parrot/tools/databasequery/sources/__init__.py`) | uses | Canonical driver names for dialect mapping |

### Data Models

```python
from pydantic import BaseModel, Field
from typing import Optional

class PhysicalResources(BaseModel):
    """Resolved physical resources for a DataSource."""
    driver: Optional[str] = None
    tables: set[str] = Field(default_factory=set)
    source_type: Optional[str] = None
    source_id: Optional[str] = None

class RlsPredicate(BaseModel):
    """A rendered RLS predicate ready for injection."""
    table: str
    sql_predicate: str
    bound_params: dict[str, list[str]] = Field(default_factory=dict)

class RlsRule(BaseModel):
    """Registry entry: template predicate keyed by (driver, table)."""
    driver: str
    table: str
    predicate_template: str
    subject_attribute: str
    description: str = ""
```

### New Public Interfaces

```python
class DataPlanePolicyGuard:
    """Sibling of DatasetPolicyGuard; same shared PolicyEvaluator.
    Resource types: driver / table / source.
    Action set: driver:connect, table:read, source:read.
    RLS predicate resolution."""

    def __init__(
        self,
        evaluator: "PolicyEvaluator",
        rls_registry: "RlsRegistry",
        sensitive_drivers: frozenset[str] = frozenset(),
        logger: Optional[logging.Logger] = None,
    ) -> None: ...

    async def can_connect_driver(
        self, ctx: PermissionContext, driver: str,
    ) -> bool: ...

    async def filter_tables(
        self, ctx: PermissionContext, driver: str, tables: list[str],
    ) -> set[str]: ...

    async def authorize_source(
        self, ctx: PermissionContext, resources: PhysicalResources,
    ) -> None: ...    # raises AuthorizationRequired

    async def rls_predicates(
        self, ctx: PermissionContext, resources: PhysicalResources,
    ) -> list[RlsPredicate]: ...


class AuthorizingDataSource(DataSource):
    """Decorator that wraps any DataSource with authorization + RLS."""

    def __init__(
        self,
        inner: DataSource,
        guard: DataPlanePolicyGuard,
        pctx_provider: Callable[[], Optional[PermissionContext]],
    ) -> None: ...

    async def fetch(self, **params) -> pd.DataFrame: ...


class RlsRegistry:
    """(driver, table) → predicate template with subject-attribute placeholders."""

    def register(self, rule: RlsRule) -> None: ...
    def lookup(
        self, driver: str, tables: set[str],
    ) -> list[RlsRule]: ...
```

---

## 3. Module Breakdown

### Module 1: Physical-Resource Resolver

- **Path**: `parrot/tools/dataset_manager/sources/resolver.py` (NEW)
- **Responsibility**: Pure function `resolve_physical_resources(source) → PhysicalResources`.
  Uses sqlglot for SQL sources, trivial extraction for table/slug sources,
  per-type strategies for opaque sources. Enforces the read-only gate
  (rejects DML/DDL at parse time).
- **Depends on**: Module 2 (dialect map), existing DataSource subclasses

### Module 2: Driver–Dialect Map

- **Path**: `parrot/tools/dataset_manager/sources/dialects.py` (NEW)
- **Responsibility**: `driver_to_dialect(driver: str) → str` mapping ai-parrot
  driver aliases to sqlglot 30.9.0 dialect identifiers. Uses `normalize_driver`
  from `parrot/tools/databasequery/sources`.
- **Depends on**: none (leaf module)

### Module 3: Opaque-Source Resolvers

- **Path**: `parrot/tools/dataset_manager/sources/opaque.py` (NEW)
- **Responsibility**: Per-type resource identifier extraction for Mongo, Iceberg,
  Delta, Airtable, Smartsheet. Returns `PhysicalResources` with `source_type`
  and `source_id` populated.
- **Depends on**: none (leaf module)

### Module 4: RLS Registry

- **Path**: `parrot/auth/rls_registry.py` (NEW)
- **Responsibility**: In-memory registry mapping `(driver, table)` to predicate
  templates. Renders predicates from `EvalContext` subject attributes. Values
  are always bound as query parameters (injection-safe by construction).
- **Depends on**: none (leaf module)

### Module 5: RLS Predicate Injection

- **Path**: `parrot/tools/dataset_manager/sources/rls.py` (NEW)
- **Responsibility**: Injects rendered RLS predicates into queries:
  - `SQLQuerySource`: sqlglot AST rewrite (wrap or push into base-table scans).
  - `TableSource`: extend existing `permanent_filter` mechanism.
  - `QuerySlugSource`: merge into slug conditions.
  - `MongoSource`: merge into query filter dict (`$and`).
  - API sources: `filterByFormula` or post-fetch row filter.
- **Depends on**: Module 4 (RLS registry), Module 2 (dialect map)

### Module 6: DataPlanePolicyGuard

- **Path**: `parrot/auth/dataplane_guard.py` (NEW)
- **Responsibility**: Sibling of `DatasetPolicyGuard`. Evaluates
  `driver:connect`, `table:read`, `source:read` via the shared
  `PolicyEvaluator`. Collects RLS predicates from the registry. Manages the
  `sensitive` driver class pre-check.
- **Depends on**: Module 4 (RLS registry), navigator-auth `PolicyEvaluator`

### Module 7: AuthorizingDataSource Decorator

- **Path**: `parrot/tools/dataset_manager/sources/authorizing.py` (NEW)
- **Responsibility**: Wraps any `DataSource` with the full enforcement chain
  (§2 Overview steps 0–6). Orchestrates resolver → guard → RLS injection →
  delegate to `inner.fetch()`.
- **Depends on**: Module 1, Module 5, Module 6

### Module 8: DatasetManager Integration

- **Path**: `parrot/tools/dataset_manager/tool.py` (MODIFIED)
- **Responsibility**: Add `_make_source()` factory that wraps every
  agent-facing source in `AuthorizingDataSource` when a `DataPlanePolicyGuard`
  is present. Wire `dataplane_guard` into `__init__` alongside the existing
  `policy_guard`. Ensure all internal `materialize()` callers route through
  the factory.
- **Depends on**: Module 7

### Module 9: DatabaseQueryTool Integration

- **Path**: `parrot/tools/databasequery/tool.py` (MODIFIED)
- **Responsibility**: Route `_execute` through `AuthorizingDataSource`/resolver.
  Gate `test_connection` and `get_supported_drivers` on `driver:connect`.
- **Depends on**: Module 7, Module 1

### Module 10: Remote Execution Context Signing (deferred)

- **Path**: TBD (depends on V6/V7 verification)
- **Responsibility**: Serialize `PermissionContext` into the `executor=` envelope
  as a signed claim; verify and re-establish `_pctx_var` on the worker side.
  Unsigned/invalid → fail-closed.
- **Depends on**: Module 6, signing infrastructure (V7 — does not exist yet)
- **Note**: This module is deferred until signing infrastructure is designed. The
  remaining modules are fully functional for local execution.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_physical_tables_simple_select` | Module 1 | Single-table SELECT resolves correctly |
| `test_physical_tables_cte_excluded` | Module 1 | CTE aliases are not counted as physical tables |
| `test_physical_tables_subquery` | Module 1 | Tables inside subqueries are captured |
| `test_physical_tables_union` | Module 1 | UNION branches capture all tables |
| `test_physical_tables_join` | Module 1 | JOIN tables all captured |
| `test_read_only_gate_drop` | Module 1 | DROP statement raises `ReadOnlyViolation` |
| `test_read_only_gate_update` | Module 1 | UPDATE statement raises `ReadOnlyViolation` |
| `test_read_only_gate_insert` | Module 1 | INSERT statement raises `ReadOnlyViolation` |
| `test_parse_failure_raises` | Module 1 | Invalid SQL raises `ParseError` |
| `test_driver_to_dialect_known` | Module 2 | All known driver aliases map correctly |
| `test_driver_to_dialect_unknown` | Module 2 | Unknown driver returns `None` |
| `test_opaque_mongo_resolution` | Module 3 | Mongo source resolves to `source:mongo:db.coll` |
| `test_opaque_iceberg_resolution` | Module 3 | Iceberg source resolves correctly |
| `test_opaque_airtable_resolution` | Module 3 | Airtable source resolves to `source:airtable:base.table` |
| `test_rls_registry_lookup` | Module 4 | Registered predicates are returned for matching tables |
| `test_rls_registry_no_match` | Module 4 | Non-matching tables return empty list |
| `test_rls_render_predicate` | Module 4 | Template renders with subject attributes |
| `test_rls_inject_sql_wrap` | Module 5 | SQL query wrapped with RLS WHERE clause |
| `test_rls_inject_table_source` | Module 5 | TableSource permanent_filter extended |
| `test_rls_inject_mongo_filter` | Module 5 | Mongo filter merged with `$and` |
| `test_rls_bound_params_no_injection` | Module 5 | Crafted attribute value cannot inject SQL |
| `test_guard_can_connect_allowed` | Module 6 | Authorized driver returns True |
| `test_guard_can_connect_denied` | Module 6 | Unauthorized driver returns False |
| `test_guard_filter_tables` | Module 6 | Mixed allowed/denied tables filtered correctly |
| `test_guard_authorize_source_denied` | Module 6 | Unauthorized source raises `AuthorizationRequired` |
| `test_guard_sensitive_driver_rejects_raw_sql` | Module 6 | `sensitive` mode rejects non-slug sources |
| `test_guard_no_pctx_failopen` | Module 6 | Missing PermissionContext → allow (backwards compat) |
| `test_authorizing_source_full_chain` | Module 7 | Full chain: resolve → check → RLS → delegate |
| `test_authorizing_source_denied_no_fetch` | Module 7 | Denied source never calls `inner.fetch()` |

### Integration Tests

| Test | Description |
|---|---|
| `test_fetch_dataset_alias_spoofing_denied` | B1: `name="x"`, `query` hits guarded table → denied |
| `test_fetch_dataset_finance_user_allowed` | Finance user accessing finance table → allowed with RLS |
| `test_database_query_guarded_denied` | B3: `database_query` with guarded driver → denied |
| `test_cte_hidden_table_denied` | B7: Guarded table hidden in CTE → denied |
| `test_parse_failure_guarded_driver_denied` | AC5: Parse failure on guarded driver → DENY |
| `test_parse_failure_unguarded_open` | AC5: Parse failure on unguarded driver → open |
| `test_materialize_internal_enforced` | B4: Direct `materialize()` still enforced via Option D |
| `test_no_guard_configured_open` | AC8: No guard → everything open |
| `test_navigator_auth_absent_open` | AC8: navigator-auth not installed → open |
| `test_sensitive_driver_raw_sql_denied` | AC10: Sensitive driver + raw query → denied |
| `test_sensitive_driver_slug_allowed` | AC10: Sensitive driver + registered slug → gated normally |
| `test_dml_rejected` | AC12: DROP/UPDATE/INSERT → `ReadOnlyViolation` |
| `test_dialect_mismatch_denied` | AC14: Wrong dialect on guarded driver → DENY |

### Test Data / Fixtures

```python
import pytest
from parrot.auth.permission import PermissionContext, UserSession

@pytest.fixture
def finance_pctx() -> PermissionContext:
    """Finance user with group membership."""
    return PermissionContext(
        session=UserSession(
            username="finance_user",
            groups=["Finance"],
            programs=["northeast"],
        )
    )

@pytest.fixture
def unprivileged_pctx() -> PermissionContext:
    """User with no special data grants."""
    return PermissionContext(
        session=UserSession(
            username="basic_user",
            groups=["General"],
            programs=[],
        )
    )
```

---

## 5. Acceptance Criteria

- [ ] **AC1** — `fetch_dataset(name="x", query="SELECT * FROM finance.salaries",
  driver="bigquery_finance")` by a non-Finance subject ⇒
  `AuthorizationRequired` → forbidden `ToolResult`, **no driver round-trip**.
  (closes B1, B2)
- [ ] **AC2** — Same query by Finance subject ⇒ succeeds; rows restricted by
  any RLS predicate on the matched grant. (closes B6)
- [ ] **AC3** — `database_query` with a guarded driver/table ⇒ identical
  decision to `fetch_dataset`. (closes B3)
- [ ] **AC4** — sqlglot resolves tables inside CTEs, subqueries, and `UNION`;
  a guarded table hidden in a CTE is still denied. (closes B7)
- [ ] **AC5** — Parse failure on a guarded driver ⇒ DENY (fail-closed).
  Unguarded driver ⇒ open.
- [ ] **AC6** — Direct internal `materialize()` of a guarded dataset ⇒ still
  enforced (Option D wraps at construction). (closes B4)
- [ ] **AC7** — Remote (`executor=`) execution enforces identically;
  tampered/unsigned context ⇒ fail-closed. (closes B5 — deferred to Module 10)
- [ ] **AC8** — `navigator-auth` absent ⇒ fail-open; no `policy_guard` ⇒
  fail-open (FEAT-151 parity).
- [ ] **AC9** — RLS values bound as parameters; a crafted attribute value cannot
  inject SQL.
- [ ] **AC10** — `sensitive`-class driver + raw `query=`/`table=` ⇒
  `AuthorizationRequired` **before parsing**; only registered `query_slug`
  accepted, then gated. (closes B10)
- [ ] **AC11** — `general` driver + `query=` ⇒ parsed, table-gated,
  RLS-injected.
- [ ] **AC12** — DML/DDL passed as a query (`DROP`/`UPDATE`/`INSERT`/`MERGE`) ⇒
  `ReadOnlyViolation`, no execution. (closes B9)
- [ ] **AC13** — Opaque sources (Mongo/Iceberg/Delta/Airtable/Smartsheet) gated
  via `source:read`; Mongo/Iceberg/Delta apply server-side RLS;
  Airtable/Smartsheet apply `filterByFormula`/post-fetch and are blocked from
  post-fetch RLS when classed `sensitive`. (closes B8)
- [ ] **AC14** — Dialect mismatch on a guarded driver ⇒ DENY (fail-closed).
- [ ] All unit tests pass (`pytest tests/auth/ tests/tools/dataset_manager/ -v`)
- [ ] No breaking changes to existing public API
- [ ] Backwards-compatible: no guard configured → no enforcement

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports

```python
# Auth layer
from parrot.auth.permission import PermissionContext, UserSession   # verified: parrot/auth/__init__.py
from parrot.auth.dataset_guard import DatasetPolicyGuard             # verified: parrot/auth/__init__.py
from parrot.auth.exceptions import AuthorizationRequired             # verified: parrot/auth/__init__.py
from parrot.auth.resolver import PBACPermissionResolver              # verified: parrot/auth/__init__.py
from parrot.auth.pbac import setup_pbac                              # verified: parrot/auth/__init__.py

# DatasetManager
from parrot.tools.dataset_manager.tool import DatasetManager         # class at tool.py
from parrot.tools.dataset_manager.sources.base import DataSource     # abstract at sources/base.py

# DatabaseQueryTool
from parrot.tools.databasequery.tool import DatabaseQueryTool        # class at tool.py
from parrot.tools.databasequery.sources import normalize_driver      # function at sources/__init__.py

# navigator-auth (lazy imports — may not be installed)
# navigator_auth.abac.policies.evaluator.PolicyEvaluator
# navigator_auth.abac.context.EvalContext
```

### Existing Class Signatures

```python
# parrot/auth/dataset_guard.py
class DatasetPolicyGuard:
    def __init__(self, evaluator: "PolicyEvaluator", logger: Optional[logging.Logger] = None) -> None:  # line ~56
    async def filter_datasets(self, context: PermissionContext, dataset_names: list[str]) -> set[str]:   # line ~128
    async def filter_columns(self, context: PermissionContext, dataset_name: str, columns: list[str]) -> list[str]:  # line ~200
    async def can_read_dataset(self, context: PermissionContext, dataset_name: str) -> bool:             # line ~278

# parrot/auth/permission.py
@dataclass
class PermissionContext:                         # line ~80
    session: UserSession
    request_id: Optional[str] = None
    channel: Optional[str] = None
    trace_context: "Optional[TraceContext]" = None
    extra: dict[str, Any] = field(default_factory=dict)

def to_eval_context(context: "PermissionContext") -> "EvalContext":  # line ~166 (module-level function)

@dataclass
class UserSession:                               # (same file)
    username: str
    # groups, roles, programs fields

# parrot/auth/resolver.py
class PBACPermissionResolver(AbstractPermissionResolver):  # line ~247
    def __init__(self, evaluator: "PolicyEvaluator", logger: Optional[logging.Logger] = None) -> None:
    async def can_execute(self, context: PermissionContext, tool_name: str, required_permissions: set[str]) -> bool:   # line ~289
    async def filter_tools(self, context: PermissionContext, tools: list[Any]) -> list[Any]:   # line ~341

# parrot/tools/dataset_manager/tool.py
class DatasetManager(AbstractToolkit):           # line ~527
    def __init__(
        self,
        df_prefix: str = "df",
        generate_guide: bool = True,
        include_summary_stats: bool = False,
        auto_detect_types: bool = True,
        policy_guard: Optional["DatasetPolicyGuard"] = None,  # line 533
        **kwargs,
    ):

# parrot/tools/dataset_manager/sources/base.py
class DataSource(ABC):                            # line ~23
    def __init__(self, routing_meta: Dict | None = None) -> None:
    async def prefetch_schema(self) -> Dict[str, str]:
    @abstractmethod
    async def fetch(self, **params) -> pd.DataFrame:
    @abstractmethod
    def describe(self) -> str:
    @property
    def has_builtin_cache(self) -> bool:
    @property
    @abstractmethod
    def cache_key(self) -> str:

# parrot/tools/dataset_manager/sources/sql.py
class SQLQuerySource(DataSource):                 # line ~26
    # __init__(self, sql, driver, dsn, credentials, ...)

# parrot/tools/dataset_manager/sources/table.py
class TableSource(DataSource):                    # line ~113
    # __init__(self, table, driver, dsn, credentials, strict_schema, permanent_filter, ...)

# parrot/tools/dataset_manager/sources/query_slug.py
class QuerySlugSource(DataSource):                # line ~51
    def __init__(self, slug: str, prefetch_schema_enabled: bool = True,
                 permanent_filter: Optional[Dict[str, Any]] = None) -> None:

# parrot/tools/dataset_manager/sources/mongo.py
class MongoSource(DataSource):                    # line ~70
    def __init__(self, collection: str, name: str, database: str,
                 credentials=None, dsn=None, required_filter=True) -> None:

# parrot/tools/dataset_manager/sources/composite.py
class CompositeDataSource(DataSource):            # line ~81
    def __init__(self, name: str, joins: List[JoinSpec],
                 dataset_manager: "DatasetManager", description: str = "") -> None:

# parrot/tools/dataset_manager/sources/airtable.py
class AirtableSource(DataSource):                 # line ~15
    def __init__(self, base_id: str, table: str, api_key=None, view=None) -> None:

# parrot/tools/dataset_manager/sources/smartsheet.py
class SmartsheetSource(DataSource):               # line ~14

# parrot/tools/dataset_manager/sources/iceberg.py
class IcebergSource(DataSource):                  # line ~70

# parrot/tools/dataset_manager/sources/deltatable.py
class DeltaTableSource(DataSource):               # line ~76

# parrot/tools/databasequery/tool.py
class DatabaseQueryTool(AbstractToolkit):          # line ~245
    def __init__(self, **kwargs):
    async def _execute(self, driver: str, query: str, credentials=None,
                       dsn=None, output_format="pandas", query_timeout=300,
                       max_rows=10000, **kwargs) -> Union[pd.DataFrame, str]:  # line ~535

# parrot/tools/databasequery/sources/__init__.py
_DRIVER_ALIASES: dict[str, str] = {               # line ~24
    "postgres": "pg", "postgresql": "pg", "mariadb": "mysql",
    "bq": "bigquery", "sqlserver": "mssql", "influxdb": "influx",
    "mongodb": "mongo", "elasticsearch": "elastic", "opensearch": "elastic",
}
def normalize_driver(driver: str) -> str:          # line ~45

# parrot/tools/toolkit.py
class AbstractToolkit:                             # (base class)
    async def _pre_execute(self, tool_name: str, **kwargs) -> None:     # line ~306
    async def _post_execute(self, tool_name: str, result: Any, **kwargs) -> Any:  # line ~321

class ToolkitTool:                                 # line ~150+
    async def _execute(self, **kwargs) -> Any:
        pctx = getattr(self, "_current_pctx", None)         # line ~176
        hook_kwargs["_permission_context"] = pctx            # line ~178
        await toolkit._pre_execute(self.name, **hook_kwargs)
```

### Callers of `materialize()` (V4 — verified)

Internal `materialize()` calls that bypass `_pre_execute`:
- `composite.py:217` — `CompositeDataSource` calls `dm.materialize()` directly
- `tool.py:1576, 1620` — internal refresh paths
- `tool.py:3416, 4033, 4049, 4321, 4765` — various tool methods

**Implication**: Option D (wrapping at source construction) covers these because
the `AuthorizingDataSource` is applied when the source is built, not when
`_pre_execute` fires.

### Navigator-Auth ABAC Surface (from external dependency)

```python
# navigator_auth.abac.policies.evaluator
PolicyEvaluator.check_access(ctx, resource_type, resource_name, action, env)
    # returns obj with .allowed, .matched_policy, .reason
PolicyEvaluator.filter_resources(ctx, resource_type, resource_names, action, env)
    # returns obj with .allowed (list of allowed names)

# Rust PEP (hot path)
evaluate_single / filter_resources_batch  # PyO3
# Engine errors fail closed (deny); honors default_effect

# Resource type can be any string — Rust matcher splits "type:name" generically
# Glob (*), regex (^...), and exact matching supported in policy resources
```

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.auth.dataplane_guard`~~ — does not exist yet (Module 6 creates it)
- ~~`parrot.auth.rls_registry`~~ — does not exist yet (Module 4 creates it)
- ~~`parrot.tools.dataset_manager.sources.authorizing`~~ — does not exist yet (Module 7)
- ~~`parrot.tools.dataset_manager.sources.resolver`~~ — does not exist yet (Module 1)
- ~~`parrot.tools.dataset_manager.sources.dialects`~~ — does not exist yet (Module 2)
- ~~`parrot.tools.dataset_manager.sources.opaque`~~ — does not exist yet (Module 3)
- ~~`parrot.tools.dataset_manager.sources.rls`~~ — does not exist yet (Module 5)
- ~~`AuditLedger`~~ — does not exist anywhere in the codebase
- ~~`RemoteAgentProxy`~~ — not a class in the codebase; remote execution uses generic `executor` attribute on `AbstractToolkit`
- ~~`DatasetManager.dataplane_guard`~~ — does not exist yet (Module 8 adds it)
- ~~`DatasetManager._make_source()`~~ — does not exist yet (Module 8 adds it)
- ~~`ReadOnlyViolation`~~ — does not exist yet (Module 1 creates this exception)
- ~~`ResourceType.DRIVER / TABLE / SOURCE`~~ — do not exist in navigator-auth enum; use plain strings

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **`DatasetPolicyGuard` as template**: `DataPlanePolicyGuard` follows the same
  structural pattern — shared `PolicyEvaluator`, lazy import of navigator-auth,
  `to_eval_context()` bridge, `AuthorizationRequired` on denial.
- **`DataSource` decorator pattern**: `AuthorizingDataSource` wraps any
  `DataSource` subclass, delegating `describe()`, `cache_key`, and
  `has_builtin_cache` to the inner source transparently.
- **Async-first**: all guard methods are `async def`.
- **Pydantic models**: `PhysicalResources`, `RlsPredicate`, `RlsRule`.
- **Logging**: `self.logger` throughout, `DEBUG` for resolution details,
  `WARNING` for denials.

### Known Risks / Gotchas

- **sqlglot dialect mismatch**: Picking the wrong dialect for a driver can cause
  parse failures or incorrect table extraction. The driver→dialect map must be
  exhaustive for all guarded drivers. Fail-closed on unknown dialect.
- **CompositeDataSource bypass**: `CompositeDataSource` calls
  `dm.materialize()` directly (composite.py:217). Option D covers this because
  the underlying sub-sources are wrapped at construction, but
  `CompositeDataSource` itself must also be wrapped to ensure the composite
  join's tables are authorized.
- **Post-fetch RLS for API sources**: Airtable and Smartsheet apply RLS via
  `filterByFormula` or post-fetch row filtering. Post-fetch means data enters
  the process before filtering — acceptable for the process boundary but weaker
  than server-side. Block post-fetch RLS for `sensitive`-classed drivers.
- **Remote execution (Module 10 deferred)**: No signing infrastructure exists
  yet (`AuditLedger` not found). Until Module 10 is implemented, remote
  `executor=` calls on guarded drivers should fail-closed (no unsigned context
  accepted).
- **Edge cases in sqlglot**: Star-schema queries with deeply nested subqueries
  or vendor-specific syntax extensions may produce unexpected table sets. The
  test suite must cover diverse real-world SQL patterns per supported dialect.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `sqlglot` | `>=30.9.0` | SQL parsing, table extraction, AST rewrite for RLS, read-only gate (already a dependency) |
| `navigator-auth` | (existing pin) | PBAC engine — `PolicyEvaluator`, `EvalContext`, Rust PEP (already a dependency, optional) |

---

## 8. Open Questions

- [x] V1 — Does `PolicyEvaluator` accept non-enum resource types? — *Resolved in
  brainstorm*: Yes, plain string `resource_type` flows through unchanged. The Rust
  `policy_covers_resource` splits any `"type:name"` generically. No enum change needed.
- [x] V2 — How is driver→table hierarchy expressed? — *Resolved in brainstorm*:
  Glob/regex in policy `resources`. `table:bigquery_finance:*` covers all tables
  under that driver. No chained-check workaround needed.
- [x] V3 — Can the policy carry RLS predicates as obligations? — *Resolved in
  brainstorm*: No. Rust `EvaluationResult` has no obligations field. RLS lives in
  a parrot-side `rls_registry.py`.
- [x] V4 — Is `materialize()` reachable without `_pre_execute`? — *Resolved in
  spec research*: Yes, `CompositeDataSource` and several internal tool methods
  call `materialize()` directly. Option D covers this by wrapping at source
  construction time.
- [x] V5 — Does `DatasetManager.__init__` accept `policy_guard=`? — *Resolved in
  spec research*: Yes (line 533 of `tool.py`). A parallel `dataplane_guard`
  parameter will be added.
- [x] V8 — sqlglot dialect identifiers for each driver alias? — *Resolved in
  brainstorm*: Full dialect map verified against sqlglot 30.9.0. CTE/read-only
  gate behavior confirmed.
- [x] #1 — Sensitive-driver stance? — *Resolved in brainstorm*: Both modes
  supported via driver class. `general` = parsed+gated (default), `sensitive` =
  `slug_only`.
- [x] V9 — Opaque sources? — *Resolved in brainstorm*: Shipped this feature.
  `source:<type>:<id>` + `source:read`, per-type resolution.
- [ ] V6 — Remote `executor=` envelope schema: what fields cross the wire, where
  is deserialization in `parrot-agent-runtime`? — *Owner: Jesus*
- [ ] V7 — Signing API for the remote context claim: `AuditLedger` does not
  exist yet. Need to design or reuse `parrot/storage/artifact_signing.py`
  (`sign_artifact`/`verify_signature`) or a new KMS-backed signer. —
  *Owner: Jesus*

---

## Worktree Strategy

- **Isolation unit**: `per-spec` (sequential tasks in one worktree).
- All 10 modules are tightly coupled with shared data models and call chains.
  Module 10 (remote execution) is deferred but does not affect the others.
- **Suggested order**: M2 → M1 → M3 → M4 → M5 → M6 → M7 → M8 → M9.
  Modules 2, 3, and 4 are leaf modules and could be parallelized, but the
  integration tests require all modules present.
- **Cross-feature dependencies**: FEAT-151 must be merged first (it is —
  `DatasetPolicyGuard` and `_pctx_var` are in `dev`).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-06-08 | Jesus Lara | Initial draft from brainstorm |
