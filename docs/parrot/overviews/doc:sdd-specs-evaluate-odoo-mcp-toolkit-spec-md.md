---
type: Wiki Overview
title: 'Feature Specification: Evaluate Odoo MCP Toolkit'
id: doc:sdd-specs-evaluate-odoo-mcp-toolkit-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The existing `OdooToolkit` covers CRUD operations, partner/sales/invoicing
  helpers,
relates_to:
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.interfaces.odoointerface
  rel: mentions
- concept: mod:parrot.tools.decorators
  rel: mentions
- concept: mod:parrot.tools.toolkit
  rel: mentions
- concept: mod:parrot_tools.odoo
  rel: mentions
- concept: mod:parrot_tools.odoo.models.entities
  rel: mentions
- concept: mod:parrot_tools.odoo.models.inputs
  rel: mentions
- concept: mod:parrot_tools.odoo.smart_fields
  rel: mentions
- concept: mod:parrot_tools.odoo.transport
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: Evaluate Odoo MCP Toolkit

**Feature ID**: FEAT-147
**Date**: 2026-05-05
**Author**: Jesus Lara
**Status**: approved
**Target version**: next

---

## 1. Motivation & Business Requirements

### Problem Statement

The existing `OdooToolkit` covers CRUD operations, partner/sales/invoicing helpers,
and binary uploads. However, agents interacting with Odoo lack several capabilities
that the `tuanle96/mcp-odoo` project demonstrates are essential for effective ERP
interaction:

- **No smart field selection**: When an agent omits `fields`, the toolkit returns
  *every* field, flooding the LLM context with hundreds of irrelevant columns
  (binary blobs, technical audit fields, etc.). The mcp-odoo project solves this
  with a scoring heuristic capped at a configurable max (default 15).
- **No server-side aggregation**: Agents must fetch raw records and aggregate
  client-side, wasting bandwidth and context tokens.
- **No domain builder**: Agents must construct raw Odoo domain triplets; a
  structured builder with validation would reduce errors.
- **No schema introspection beyond `fields_get`**: No way to get a catalog of
  models, inspect relationships, or diagnose access problems.
- **No diagnostic tools**: Agents cannot self-diagnose ACL issues, inspect model
  relationships, or report runtime health.
- **No HR convenience methods**: Employee search and leave/holiday queries require
  the agent to know internal model names and field layouts.
- **No call diagnostics**: Agents cannot preview/debug a failing `execute_kw` call
  or understand why a method returns an unexpected result without trial-and-error.
- **No JSON-2 payload preview**: When migrating from XML-RPC to Odoo 19+ JSON-2,
  there is no way to preview the translated request without executing it.
- **No addon source scanning**: Agents cannot inspect local custom addon code
  (manifests, model overrides, risky method patterns) without importing it.
- **No fit/gap analysis**: Agents cannot classify business requirements against
  installed Odoo modules to determine standard vs. customisation needs.
- **No business-pack discovery**: No quick way to check which modules, models, and
  capabilities are available for a given business domain (sales, CRM, HR, etc.).

### Goals

#### Phase 1 — Core Introspection & Smart Tools

- Adopt a **smart field selection** heuristic so `search_records` and `get_record`
  return an LLM-friendly field subset when the caller omits `fields`.
- Add **`aggregate_records`** for server-side `read_group` / `formatted_read_group`.
- Add **`build_domain`** to validate and construct domains from structured input.
- Add **`get_odoo_profile`** for a comprehensive server/environment snapshot.
- Add **`schema_catalog`** for a bounded, optionally field-enriched model catalog.
- Add **`inspect_model_relationships`** to summarise relational fields and write hints.
- Add **`diagnose_access`** to diagnose ACL and record-rule visibility issues.
- Add **`health_check`** for a non-secret runtime posture report.
- Add **`search_employee`** and **`search_holidays`** as typed HR convenience methods.

#### Phase 2 — Diagnostics, Audit & Planning

- Add **`diagnose_odoo_call`** to preview/debug an `execute_kw` call without
  executing it (model validation, transport compatibility, version warnings).
- Add **`generate_json2_payload`** to convert XML-RPC-shaped input into JSON-2
  endpoint, headers, and named body — pure preview, no network call.
- Add **`scan_addons_source`** to scan local addon directories for manifests,
  custom models, risky method overrides, and security files without importing code.
- Add **`fit_gap_report`** to classify business requirements into standard,
  configuration, Studio, custom module, avoid, or unknown buckets.
- Add **`business_pack_report`** to report expected modules, models, and discovery
  calls for standard business domains (sales, CRM, inventory, accounting, HR).

### Non-Goals (explicitly out of scope)

- Write-safety approval-token flow (existing `@requires_permission` is sufficient).
- `upgrade_risk_report` — too version-specific; better maintained externally.
- Chatter/messaging tools — separate feature.
- MCP server exposure — OdooToolkit is an agent toolkit, not an MCP server.

---

## 2. Architectural Design

### Overview

All new capabilities are added as public async methods on the existing
`OdooToolkit` class. The implementation is split into two phases:

**Phase 1** adds core introspection and smart tools: smart-field selection
(in a new `smart_fields.py` module), aggregation, domain building, profile/
schema catalog, model relationship inspection, access diagnostics, health
check, and HR convenience methods.

**Phase 2** adds diagnostic, audit, and planning tools: call diagnostics,
JSON-2 payload preview, addon source scanning, fit/gap analysis, and
business-pack reporting. The audit tools (`scan_addons_source`) operate on
the local filesystem; the planning tools (`fit_gap_report`,
`business_pack_report`) are heuristic classifiers that optionally query
live Odoo metadata.

All tools across both phases are **read-only** — they never mutate Odoo data.
They use the existing `_execute` helper which delegates to the transport layer.
New Pydantic input/envelope models are added to the existing `models/inputs.py`
and `models/envelopes.py` files.

HR convenience methods follow the same pattern as `find_partner`: typed
entity models, default field lists, and Pydantic return types.

### Component Diagram

```
OdooToolkit (toolkit.py)
  │
  ├── smart_fields.py          ← NEW: select_smart_fields(), _smart_field_score()
  │
  ├── models/inputs.py         ← MODIFIED: new input schemas
  ├── models/envelopes.py      ← MODIFIED: new result envelopes
  ├── models/entities.py       ← MODIFIED: HrEmployee, HrLeave entities
  │
  ├── _execute(model, method, args, kwargs)  ← existing, reused
  │
  ├── [existing tools]         ← search_records, get_record gain smart-field fallback
  │
  ├── aggregate_records()      ← NEW
  ├── build_domain()           ← NEW (pure, no Odoo call)
  ├── get_odoo_profile()       ← NEW (extends server_info)
  ├── schema_catalog()         ← NEW
  ├── inspect_model_relationships() ← NEW
  ├── diagnose_access()        ← NEW
  ├── health_check()           ← NEW (pure, no Odoo call needed)
  ├── search_employee()        ← NEW
  ├── search_holidays()        ← NEW
  │
  │   ── Phase 2 ──────────────────────────────────────────────
  ├── diagnose_odoo_call()     ← NEW (pure, no Odoo call)
  ├── generate_json2_payload() ← NEW (pure, no Odoo call)
  ├── scan_addons_source()     ← NEW (filesystem only, no Odoo call)
  ├── fit_gap_report()         ← NEW (heuristic + optional live metadata)
  └── business_pack_report()   ← NEW (pack definitions + optional live check)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `OdooToolkit` (`toolkit.py`) | Modified | Add 15 new public methods (10 Phase 1 + 5 Phase 2) + smart-field fallback |
| `models/inputs.py` | Modified | Add input schemas for new tools |
| `models/envelopes.py` | Modified | Add result envelopes for new tools |
| `models/entities.py` | Modified | Add `HrEmployee`, `HrLeave` entity models |
| `AbstractOdooTransport` | Consumed | All new methods use `_execute` → `transport.execute_kw` |
| `@tool_schema` decorator | Consumed | New tools get input schemas via this decorator |
| `@requires_permission` | Not used | All new tools are read-only |

### Data Models

#### New Input Schemas

```python
class AggregateRecordsInput(_OdooBaseInput):
    model: str
    group_by: list[str]
    measures: Optional[list[str]] = None  # "field:agg" strings
    domain: Optional[OdooDomain] = None
    lazy: bool = False
    limit: Optional[int] = None
    offset: int = 0
    order: Optional[str] = None

class BuildDomainInput(_OdooBaseInput):
    conditions: list[dict[str, Any]]  # {field, operator, value}
    logical_operator: str = "and"     # "and" | "or"

class GetOdooProfileInput(_OdooBaseInput):
    include_modules: bool = True
    module_limit: int = 100

class SchemaCatalogInput(_OdooBaseInput):
    query: Optional[str] = None
    models: Optional[list[str]] = None
    include_fields: bool = False
    limit: int = 50

class InspectModelRelationshipsInput(_OdooBaseInput):
    model: str

class DiagnoseAccessInput(_OdooBaseInput):
    model: str
    operation: str = "read"
    domain: Optional[OdooDomain] = None
    record_ids: Optional[list[int]] = None

class SearchEmployeeInput(_OdooBaseInput):
    name: str
    limit: int = 20

class SearchHolidaysInput(_OdooBaseInput):
    start_date: str   # YYYY-MM-DD
    end_date: str     # YYYY-MM-DD
    employee_id: Optional[int] = None

# ── Phase 2 Input Schemas ──────────────────────────────────

class DiagnoseOdooCallInput(_OdooBaseInput):
    model: str
    method: str
    args: Optional[list[Any]] = None
    kwargs: Optional[dict[str, Any]] = None
    transport: str = "auto"
    target_version: Optional[str] = None
    observed_error: Optional[str] = None

class GenerateJson2PayloadInput(_OdooBaseInput):
    model: str
    method: str
    args: Optional[list[Any]] = None
    kwargs: Optional[dict[str, Any]] = None
    base_url: Optional[str] = None
    database: Optional[str] = None

class ScanAddonsSourceInput(_OdooBaseInput):
    addons_paths: Optional[list[str]] = None
    max_files: int = 200
    max_file_bytes: int = 300_000

class FitGapReportInput(_OdooBaseInput):
    requirements: list[dict[str, Any]]
    business_context: Optional[dict[str, Any]] = None

class BusinessPackReportInput(_OdooBaseInput):
    pack: str  # "sales" | "crm" | "inventory" | "accounting" | "hr"
```

#### New Result Envelopes

```python
class AggregateResult(BaseModel):
    groups: list[dict[str, Any]]
    model: str
    group_by: list[str]
    measures: list[str]
    count: int

class DomainBuildResult(BaseModel):
    domain: list[Any]
    warnings: list[str]
    valid: bool

class OdooProfileResult(BaseModel):
    server_version: str
    server_serie: str
    odoo_url: str
    database: str
    uid: Optional[int]
    user_context: dict[str, Any]
    transport: str
    installed_modules: list[dict[str, Any]]

class SchemaCatalogResult(BaseModel):
    models: list[dict[str, Any]]
    total: int
    include_fields: bool

class ModelRelationshipsResult(BaseModel):
    model: str
    many2one: list[dict[str, Any]]
    one2many: list[dict[str, Any]]
    many2many: list[dict[str, Any]]
    required_fields: list[dict[str, Any]]
    create_hints: list[str]

class AccessDiagnosisResult(BaseModel):
    model: str
    operation: str
    acl_allowed: bool
    record_rules: list[dict[str, Any]]
    user_groups: list[str]
    diagnosis: str

class HealthCheckResult(BaseModel):
    toolkit_version: str
    transport: str
    connected: bool
    write_permissions: list[str]
    tool_count: int

# ── Phase 2 Result Envelopes ──────────────────────────────

class OdooCallDiagnosisResult(BaseModel):
    model: str
    method: str
    method_safety: str           # "read_only" | "destructive" | "side_effect" | "unknown"
    transport_compatibility: str # "ok" | "warning" | "error"
    warnings: list[str]
    corrected_payload: Optional[dict[str, Any]] = None
    next_actions: list[str]

class Json2PayloadResult(BaseModel):
    endpoint: str               # e.g. "/json/2/res.partner/search_read"
    headers: dict[str, str]
    body: dict[str, Any]
    notes: list[str]

class AddonScanResult(BaseModel):
    addons_found: int
    addons: list[dict[str, Any]]  # manifest info, models, risky methods, views
    warnings: list[str]

class FitGapResult(BaseModel):
    requirements: list[dict[str, Any]]  # each with classification bucket
    summary: dict[str, int]             # count per bucket
    recommended_calls: list[str]        # suggested follow-up Odoo calls

class BusinessPackResult(BaseModel):
    pack: str
    expected_modules: list[dict[str, Any]]
    expected_models: list[str]
    installed: list[str]                # populated when live check is used
    missing: list[str]                  # populated when live check is used
```

#### New Entity Models

```python
class HrEmployee(_OdooEntity):
    name: Optional[str] = None
    job_id: Optional[Many2one] = None
    job_title: Optional[str] = None
    department_id: Optional[Many2one] = None
    parent_id: Optional[Many2one] = None
    work_email: Optional[str] = None
    work_phone: Optional[str] = None
    mobile_phone: Optional[str] = None
    company_id: Optional[Many2one] = None
    active: Optional[bool] = None

class HrLeave(_OdooEntity):
    employee_id: Optional[Many2one] = None
    holiday_status_id: Optional[Many2one] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    number_of_days: Optional[float] = None
    state: Optional[str] = None  # 'draft'|'confirm'|'validate'|'refuse'
    name: Optional[str] = None
```

### New Public Interfaces

```python
# All methods added to OdooToolkit class

async def aggregate_records(
    self, model: str, group_by: list[str],
    measures: list[str] | None = None,
    domain: list[Any] | None = None,
    lazy: bool = False, limit: int | None = None,
    offset: int = 0, order: str | None = None,
) -> AggregateResult: ...

def build_domain(
    self, conditions: list[dict[str, Any]],
    logical_operator: str = "and",
) -> DomainBuildResult: ...

async def get_odoo_profile(
    self, include_modules: bool = True,
    module_limit: int = 100,
) -> OdooProfileResult: ...

async def schema_catalog(
    self, query: str | None = None,
    models: list[str] | None = None,
    include_fields: bool = False, limit: int = 50,
) -> SchemaCatalogResult: ...

async def inspect_model_relationships(
    self, model: str,
) -> ModelRelationshipsResult: ...

async def diagnose_access(
    self, model: str, operation: str = "read",
    domain: list[Any] | None = None,
    record_ids: list[int] | None = None,
) -> AccessDiagnosisResult: ...

def health_check(self) -> HealthCheckResult: ...

async def search_employee(
    self, name: str, limit: int = 20,
) -> list[HrEmployee]: ...

async def search_holidays(
    self, start_date: str, end_date: str,
    employee_id: int | None = None,
) -> list[HrLeave]: ...

# ── Phase 2 methods ────────────────────────────────────────

def diagnose_odoo_call(
    self, model: str, method: str,
    args: list[Any] | None = None,
    kwargs: dict[str, Any] | None = None,
    transport: str = "auto",
    target_version: str | None = None,
    observed_error: str | None = None,
) -> OdooCallDiagnosisResult: ...

def generate_json2_payload(
    self, model: str, method: str,
    args: list[Any] | None = None,
    kwargs: dict[str, Any] | None = None,
    base_url: str | None = None,
    database: str | None = None,
) -> Json2PayloadResult: ...

def scan_addons_source(
    self, addons_paths: list[str] | None = None,
    max_files: int = 200,
    max_file_bytes: int = 300_000,
) -> AddonScanResult: ...

async def fit_gap_report(
    self, requirements: list[dict[str, Any]],
    business_context: dict[str, Any] | None = None,
) -> FitGapResult: ...

async def business_pack_report(
    self, pack: str,
) -> BusinessPackResult: ...
```

---

## 3. Module Breakdown

### Module 1: Smart Field Selection

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/odoo/smart_fields.py` (new)
- **Responsibility**: Provide `select_smart_fields(fields_metadata, max_fields=15)` that
  scores fields by type/name heuristics and returns the top N most useful ones. Technical
  fields (binary, html, audit timestamps, `__last_update`) score low; name/state/amount
  fields score high.
- **Depends on**: Nothing (pure function, no Odoo calls).

### Module 2: Smart Field Integration

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py` (modified)
- **Responsibility**: Wire smart-field fallback into `search_records` and `get_record`.
  When `fields` is `None`, call `fields_get` once (cached per model), then
  `select_smart_fields`. Update `FieldSelectionMetadata` to report `"auto"` method.
- **Depends on**: Module 1

### Module 3: Aggregate Records

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py` (modified)
- **Responsibility**: Add `aggregate_records` method. Detect Odoo version: use
  `formatted_read_group` for Odoo 19+, `read_group` for 16-18. Parse `"field:agg"`
  measure specs. Validate aggregator names against a whitelist.
- **Depends on**: Module 2 (needs transport; no dependency on smart fields)

### Module 4: Domain Builder

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py` (modified)
- **Responsibility**: Add `build_domain` method. Accepts structured `{field, operator,
  value}` dicts, validates operators against a safe whitelist, and constructs the Odoo
  domain array with proper `|`/`&` prefix operators. Pure function (synchronous) —
  no Odoo call.
- **Depends on**: None

### Module 5: Profile & Schema Catalog

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py` (modified)
- **Responsibility**: Add `get_odoo_profile` (server version + user context + installed
  modules) and `schema_catalog` (bounded model list with optional field metadata). Both
  are read-only and use `_execute`.
- **Depends on**: Module 1 (schema_catalog can use smart-field selection when
  `include_fields=True`)

### Module 6: Model Introspection & Diagnostics

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py` (modified)
- **Responsibility**: Add `inspect_model_relationships`, `diagnose_access`, and
  `health_check`. Relationship inspection uses `fields_get` to partition fields by
  type. Access diagnosis queries `ir.model.access` and `ir.rule`. Health check is
  pure (no Odoo call).
- **Depends on**: Module 2 (needs transport)

### Module 7: HR Convenience Methods

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py` (modified)
- **Responsibility**: Add `search_employee` (queries `hr.employee` via `name_search`
  or `search_read`) and `search_holidays` (queries `hr.leave` or
  `hr.leave.report.calendar` by date range). Return typed `HrEmployee`/`HrLeave`
  entities.
- **Depends on**: Module 2 (needs transport)

### Module 8: Input Schemas & Envelopes (Phase 1 + Phase 2)

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/odoo/models/inputs.py` (modified)
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/odoo/models/envelopes.py` (modified)
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/odoo/models/entities.py` (modified)
- **Responsibility**: Add all new Pydantic models (input schemas, result envelopes,
  entity classes) described in §2 Data Models for both phases. Must be committed
  before other modules can import them.
- **Depends on**: None

### Module 9: Phase 1 Tests

- **Path**: `packages/ai-parrot/tests/test_odoo_toolkit.py` (modified)
- **Path**: `packages/ai-parrot/tests/test_odoo_smart_fields.py` (new)
- **Responsibility**: Unit tests for all Phase 1 methods. Mock the transport layer
  (`_execute`). Test smart-field scoring in isolation.
- **Depends on**: Modules 1-7

---

### Module 10: Call Diagnostics (Phase 2)

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py` (modified)
- **Responsibility**: Add `diagnose_odoo_call` method. Validates model name format,
  classifies method safety (read_only/destructive/side_effect/unknown), checks
  transport compatibility (JSON-2 vs XML-RPC), flags Odoo 20 deprecation warnings,
  and suggests corrected payload shape. **Pure function** — no Odoo network call.
- **Depends on**: Module 2 (needs toolkit instance for config context)

### Module 11: JSON-2 Payload Generator (Phase 2)

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py` (modified)
- **Responsibility**: Add `generate_json2_payload` method. Translates XML-RPC-style
  positional args into the JSON-2 named-argument endpoint, headers, and body using a
  mapping table for common ORM methods (`search_read`, `create`, `write`, `unlink`,
  `read`, `search`, `search_count`, `fields_get`, `name_search`, etc.).
  **Pure function** — no network call.
- **Depends on**: None

### Module 12: Addon Source Scanner (Phase 2)

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py` (modified)
- **Responsibility**: Add `scan_addons_source` method. Scans local addon directories
  (restricted to configured paths) for `__manifest__.py` files, custom model class
  definitions, risky method overrides (`create`/`write`/`unlink`/`sudo`), automated
  actions, view XML files, and `ir.model.access.csv` security files. Uses AST parsing
  — **no addon code is imported or executed**. Filesystem only, no Odoo call.
- **Depends on**: None

### Module 13: Fit/Gap Report (Phase 2)

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py` (modified)
- **Responsibility**: Add `fit_gap_report` method. Classifies a list of business
  requirements into buckets: `standard` (covered by base Odoo), `configuration`
  (achievable via settings/views), `studio` (Odoo Studio customisation), `custom_module`
  (requires development), `avoid` (anti-pattern), or `unknown`. Uses a heuristic
  keyword matcher and optionally queries live Odoo for installed modules and available
  models/fields to improve classification.
- **Depends on**: Module 5 (can reuse `schema_catalog` for model evidence)

### Module 14: Business Pack Report (Phase 2)

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py` (modified)
- **Responsibility**: Add `business_pack_report` method. Defines expected modules,
  models, and discovery calls for five standard business domains: `sales`, `crm`,
  `inventory`, `accounting`, `hr`. Optionally queries live Odoo to check which
  expected modules are installed and which models are available. Reports
  installed/missing split.
- **Depends on**: Module 5 (can reuse `get_odoo_profile` for installed module list)

### Module 15: Phase 2 Tests

- **Path**: `packages/ai-parrot/tests/test_odoo_toolkit.py` (modified)
- **Path**: `packages/ai-parrot/tests/test_odoo_diagnostics.py` (new)
- **Responsibility**: Unit tests for all Phase 2 methods. `diagnose_odoo_call` and
  `generate_json2_payload` are pure functions (no mocks needed). `scan_addons_source`
  tests use a temporary directory with sample addon files. `fit_gap_report` and
  `business_pack_report` test both offline (no live Odoo) and mocked-live modes.
- **Depends on**: Modules 10-14

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_smart_field_score_ranking` | 1 | Name/state fields score higher than binary/html |
| `test_smart_field_max_cap` | 1 | Output never exceeds `max_fields` |
| `test_smart_field_always_includes_id_name` | 1 | `id` and `display_name` always included |
| `test_search_records_auto_fields` | 2 | When `fields=None`, uses smart selection |
| `test_search_records_explicit_fields` | 2 | When `fields` provided, uses them verbatim |
| `test_get_record_auto_fields` | 2 | Smart selection on single-record read |
| `test_aggregate_records_read_group` | 3 | Calls `read_group` for Odoo 16-18 |
| `test_aggregate_records_formatted` | 3 | Calls `formatted_read_group` for Odoo 19+ |
| `test_aggregate_invalid_aggregator` | 3 | Rejects unknown aggregator names |
| `test_build_domain_and_operator` | 4 | Correct `&` prefix for AND |
| `test_build_domain_or_operator` | 4 | Correct `\|` prefix for OR |
| `test_build_domain_invalid_operator` | 4 | Rejects unsafe domain operators |
| `test_get_odoo_profile` | 5 | Returns version + modules + context |
| `test_schema_catalog_with_query` | 5 | Filters models by substring |
| `test_schema_catalog_with_fields` | 5 | Includes field metadata when requested |
| `test_inspect_model_relationships` | 6 | Groups fields by relation type |

…(truncated)…
