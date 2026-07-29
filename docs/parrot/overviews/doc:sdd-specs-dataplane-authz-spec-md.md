---
type: Wiki Overview
title: 'Feature Specification: Deterministic Data-Plane Authorization for DatasetManager'
id: doc:sdd-specs-dataplane-authz-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'FEAT-151 established a working PBAC spine for `DatasetManager`: a'
relates_to:
- concept: mod:parrot.auth.dataplane_guard
  rel: mentions
- concept: mod:parrot.auth.dataset_guard
  rel: mentions
- concept: mod:parrot.auth.exceptions
  rel: mentions
- concept: mod:parrot.auth.pbac
  rel: mentions
- concept: mod:parrot.auth.permission
  rel: mentions
- concept: mod:parrot.auth.resolver
  rel: mentions
- concept: mod:parrot.auth.rls_registry
  rel: mentions
- concept: mod:parrot.tools.databasequery.sources
  rel: mentions
- concept: mod:parrot.tools.databasequery.tool
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.sources.authorizing
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.sources.base
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.sources.dialects
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.sources.opaque
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.sources.resolver
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.sources.rls
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.tool
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: Deterministic Data-Plane Authorization for DatasetManager

**Feature ID**: FEAT-228
**Date**: 2026-06-08
**Author**: Jesus Lara
**Status**: approved
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

…(truncated)…
