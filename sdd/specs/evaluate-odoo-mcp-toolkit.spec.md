---
type: feature
base_branch: dev
---

# Feature Specification: Evaluate Odoo MCP Toolkit — Phase 1

**Feature ID**: FEAT-147
**Date**: 2026-05-05
**Author**: Jesus Lara
**Status**: draft
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

### Goals

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

### Non-Goals (explicitly out of scope)

- Write-safety approval-token flow (existing `@requires_permission` is sufficient).
- `scan_addons_source`, `fit_gap_report`, `business_pack_report` — Phase 2.
- `diagnose_odoo_call`, `generate_json2_payload` — Phase 2.
- `upgrade_risk_report` — Phase 2.
- Chatter/messaging tools — Phase 2 or separate feature.
- MCP server exposure — OdooToolkit is an agent toolkit, not an MCP server.

---

## 2. Architectural Design

### Overview

All new capabilities are added as public async methods on the existing
`OdooToolkit` class. The smart-field selection logic lives in a new private
module `parrot_tools/odoo/smart_fields.py` so it can be unit-tested in
isolation. New Pydantic input/envelope models are added to the existing
`models/inputs.py` and `models/envelopes.py` files.

The diagnostic and introspection tools (`diagnose_access`,
`inspect_model_relationships`, `health_check`) are **read-only** — they never
mutate Odoo data. They use the existing `_execute` helper which delegates to
the transport layer.

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
  └── search_holidays()        ← NEW
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `OdooToolkit` (`toolkit.py`) | Modified | Add 10 new public methods + smart-field fallback in `search_records`/`get_record` |
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

### Module 8: Input Schemas & Envelopes

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/odoo/models/inputs.py` (modified)
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/odoo/models/envelopes.py` (modified)
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/odoo/models/entities.py` (modified)
- **Responsibility**: Add all new Pydantic models (input schemas, result envelopes,
  entity classes) described in §2 Data Models. Must be committed before other modules
  can import them.
- **Depends on**: None

### Module 9: Tests

- **Path**: `packages/ai-parrot/tests/test_odoo_toolkit.py` (modified)
- **Path**: `packages/ai-parrot/tests/test_odoo_smart_fields.py` (new)
- **Responsibility**: Unit tests for all new methods. Mock the transport layer
  (`_execute`). Test smart-field scoring in isolation.
- **Depends on**: All other modules

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
| `test_diagnose_access_allowed` | 6 | Reports ACL allowed |
| `test_diagnose_access_denied` | 6 | Reports ACL denied with rule details |
| `test_health_check` | 6 | Returns runtime posture without Odoo call |
| `test_search_employee` | 7 | Returns typed HrEmployee list |
| `test_search_holidays_date_range` | 7 | Filters by date range |
| `test_search_holidays_by_employee` | 7 | Adds employee_id to domain |

### Test Data / Fixtures

```python
@pytest.fixture
def mock_fields_metadata():
    """Simulated fields_get response with diverse field types."""
    return {
        "id": {"type": "integer", "string": "ID", "readonly": True},
        "name": {"type": "char", "string": "Name", "required": True},
        "state": {"type": "selection", "string": "Status"},
        "amount_total": {"type": "float", "string": "Total"},
        "image_1920": {"type": "binary", "string": "Image"},
        "__last_update": {"type": "datetime", "string": "Last Modified"},
        "partner_id": {"type": "many2one", "string": "Partner", "relation": "res.partner"},
        "line_ids": {"type": "one2many", "string": "Lines", "relation": "account.move.line"},
        "tag_ids": {"type": "many2many", "string": "Tags", "relation": "account.tag"},
        "notes": {"type": "html", "string": "Notes"},
        "create_uid": {"type": "many2one", "string": "Created by"},
        "write_date": {"type": "datetime", "string": "Last Updated"},
    }

@pytest.fixture
def mock_transport(mocker):
    """Mocked AbstractOdooTransport with execute_kw and version."""
    transport = mocker.AsyncMock(spec=AbstractOdooTransport)
    transport.uid = 2
    transport.name = "json2"
    return transport
```

---

## 5. Acceptance Criteria

- [ ] Smart field selection returns ≤ 15 fields by default when `fields` is omitted
- [ ] `search_records(model="res.partner")` (no fields) returns auto-selected fields
      and `metadata.field_selection_method == "auto"`
- [ ] `get_record(model="res.partner", record_id=1)` (no fields) uses smart selection
- [ ] `aggregate_records` calls `read_group` on Odoo 16-18 and `formatted_read_group`
      on Odoo 19+
- [ ] `aggregate_records` rejects unknown aggregator names with a clear error
- [ ] `build_domain` produces correct Odoo domain arrays from structured conditions
- [ ] `build_domain` rejects unsafe operators (e.g. SQL injection attempts)
- [ ] `get_odoo_profile` returns server version, user context, transport, and modules
- [ ] `schema_catalog` returns a bounded list of models filtered by `query`
- [ ] `schema_catalog(include_fields=True)` includes field metadata per model
- [ ] `inspect_model_relationships` groups fields into many2one/one2many/many2many
- [ ] `inspect_model_relationships` lists required fields and create/write hints
- [ ] `diagnose_access` queries `ir.model.access` and `ir.rule` for the given model
- [ ] `diagnose_access` returns a human-readable diagnosis string
- [ ] `health_check` returns runtime posture without making any Odoo network call
- [ ] `search_employee` returns typed `HrEmployee` list
- [ ] `search_holidays` filters by date range and optionally by employee_id
- [ ] All new methods have `@tool_schema` input schemas
- [ ] All new result types are Pydantic `BaseModel` subclasses
- [ ] All unit tests pass: `pytest packages/ai-parrot/tests/test_odoo_toolkit.py packages/ai-parrot/tests/test_odoo_smart_fields.py -v`
- [ ] No breaking changes to existing OdooToolkit public API
- [ ] No new external dependencies required

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports

```python
# Toolkit base class
from parrot.tools.toolkit import AbstractToolkit          # verified: packages/ai-parrot/src/parrot/tools/toolkit.py:168
from parrot.tools.decorators import tool_schema           # verified: packages/ai-parrot/src/parrot/tools/decorators.py:37
from parrot.tools.decorators import requires_permission   # verified: packages/ai-parrot/src/parrot/tools/decorators.py:9

# Odoo config and errors
from parrot.interfaces.odoointerface import (
    OdooConfig,                  # verified: used in toolkit.py:38
    OdooError,                   # verified: used in toolkit.py:39
    OdooAuthenticationError,     # verified: used in toolkit.py:36
    OdooConnectionError,         # verified: used in toolkit.py:38
    OdooRPCError,                # verified: used in toolkit.py:39
)

# Odoo config variables
from parrot.conf import (
    ODOO_DATABASE, ODOO_PASSWORD, ODOO_TIMEOUT,
    ODOO_URL, ODOO_USERNAME, ODOO_VERIFY_SSL,
)  # verified: toolkit.py:27-34

# Transport layer
from parrot_tools.odoo.transport import (
    AbstractOdooTransport,       # verified: transport/__init__.py:4
    Protocol,                    # verified: transport/__init__.py:4
    auto_detect_transport,       # verified: transport/__init__.py:4
    build_transport,             # verified: transport/__init__.py:4
)

# Entity models (existing)
from parrot_tools.odoo.models.entities import (
    _OdooEntity,                 # verified: models/entities.py:22
    Many2one,                    # verified: models/entities.py:19
    ResPartner,                  # verified: models/entities.py:34
)

# Input base class
from parrot_tools.odoo.models.inputs import (
    _OdooBaseInput,              # verified: models/inputs.py:19
    OdooDomain,                  # verified: models/inputs.py:16
)
```

### Existing Class Signatures

```python
# packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py
class OdooToolkit(AbstractToolkit):                        # line 127
    tool_prefix = "odoo"                                   # line 146

    async def _ensure_transport(self) -> AbstractOdooTransport:  # line 190
    async def _pre_execute(self, tool_name: str, **kwargs: Any) -> None:  # line 213
    async def _execute(                                    # line 228
        self, model: str, method: str,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
    ) -> Any:

    async def server_info(self) -> ServerInfoResult:       # line 282
    async def list_models(self) -> ModelsResult:           # line 307
    async def fields_get(self, model: str, attributes: Optional[list[str]] = None) -> dict[str, Any]:  # line 327
    async def search_records(self, model: str, domain=None, fields=None, limit=100, offset=0, order=None) -> SearchResult:  # line 340
    async def get_record(self, model: str, record_id: int, fields=None) -> RecordResult:  # line 367

# packages/ai-parrot-tools/src/parrot_tools/odoo/transport/base.py
class AbstractOdooTransport(ABC):                          # line 11
    config: OdooConfig                                     # line 19
    uid: int | None                                        # line 20
    async def authenticate(self) -> int:                   # line 23
    async def execute_kw(self, model, method, args=None, kwargs=None) -> Any:  # line 36
    async def version(self) -> dict[str, Any]:             # line 46
    async def close(self) -> None:                         # line 50
    @property
    def name(self) -> str:                                 # line 55

# packages/ai-parrot-tools/src/parrot_tools/odoo/models/entities.py
class _OdooEntity(BaseModel):                              # line 22
    model_config = ConfigDict(extra="allow", populate_by_name=True)  # line 25
    id: Optional[int]                                      # line 27
    display_name: Optional[str]                            # line 28

# packages/ai-parrot-tools/src/parrot_tools/odoo/models/inputs.py
class _OdooBaseInput(BaseModel):                           # line 19
    model_config = ConfigDict(extra="forbid", protected_namespaces=())  # line 22

# packages/ai-parrot-tools/src/parrot_tools/odoo/models/envelopes.py
class FieldSelectionMetadata(BaseModel):                   # line 14
    fields_returned: int                                   # line 17
    field_selection_method: str                             # line 18
    total_fields_available: Optional[int]                  # line 22
    note: Optional[str]                                    # line 24

class SearchResult(BaseModel):                             # line 52
    records: list[dict[str, Any]]                          # line 55
    total: int                                             # line 56
    limit: Optional[int]                                   # line 57
    offset: int                                            # line 58
    model: str                                             # line 59
    fields: Optional[list[str]]                            # line 60

class RecordResult(BaseModel):                             # line 63
    record: dict[str, Any]                                 # line 65
    model: str                                             # line 66
    metadata: Optional[FieldSelectionMetadata]             # line 67

class ServerInfoResult(BaseModel):                         # line 154
    server_version: str                                    # line 156
    server_serie: str                                      # line 157
    ...
    transport: str                                         # line 164
    uid: Optional[int]                                     # line 165
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `select_smart_fields()` | `OdooToolkit.search_records` | called when `fields is None` | `toolkit.py:340` |
| `select_smart_fields()` | `OdooToolkit.get_record` | called when `fields is None` | `toolkit.py:367` |
| `aggregate_records()` | `OdooToolkit._execute` | `self._execute(model, "read_group", ...)` | `toolkit.py:228` |
| `get_odoo_profile()` | `AbstractOdooTransport.version()` | transport version call | `transport/base.py:46` |
| `schema_catalog()` | `OdooToolkit._execute` | `self._execute("ir.model", "search_read", ...)` | `toolkit.py:228` |
| `inspect_model_relationships()` | `OdooToolkit.fields_get` | reuses existing `fields_get` | `toolkit.py:327` |
| `diagnose_access()` | `OdooToolkit._execute` | queries `ir.model.access` and `ir.rule` | `toolkit.py:228` |
| `search_employee()` | `OdooToolkit._execute` | `self._execute("hr.employee", ...)` | `toolkit.py:228` |
| `search_holidays()` | `OdooToolkit._execute` | `self._execute("hr.leave", ...)` | `toolkit.py:228` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot_tools.odoo.smart_fields`~~ — does not exist yet; must be created
- ~~`parrot_tools.odoo.diagnostics`~~ — does not exist; diagnostics go in toolkit.py
- ~~`OdooToolkit.get_odoo_profile()`~~ — does not exist yet
- ~~`OdooToolkit.aggregate_records()`~~ — does not exist yet
- ~~`OdooToolkit.build_domain()`~~ — does not exist yet
- ~~`OdooToolkit.schema_catalog()`~~ — does not exist yet
- ~~`OdooToolkit.inspect_model_relationships()`~~ — does not exist yet
- ~~`OdooToolkit.diagnose_access()`~~ — does not exist yet
- ~~`OdooToolkit.health_check()`~~ — does not exist yet
- ~~`OdooToolkit.search_employee()`~~ — does not exist yet
- ~~`OdooToolkit.search_holidays()`~~ — does not exist yet
- ~~`OdooToolkit._fields_cache`~~ — does not exist; must be added for smart-field caching
- ~~`HrEmployee` entity~~ — does not exist in `models/entities.py`; must be created
- ~~`HrLeave` entity~~ — does not exist in `models/entities.py`; must be created
- ~~`parrot.interfaces.odoointerface.formatted_read_group`~~ — no such wrapper; use `_execute` directly
- ~~`OdooToolkit._odoo_version`~~ — does not exist; version detection must use `server_info()` or transport

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Existing toolkit pattern**: Every public async method on `OdooToolkit` becomes a
  tool automatically. Use `@tool_schema(InputModel)` for input validation.
- **Envelope pattern**: Always return a Pydantic `BaseModel` result, never raw dicts.
- **Entity pattern**: HR entities follow `_OdooEntity` base with `extra="allow"`.
- **Default fields pattern**: Define `_HR_EMPLOYEE_DEFAULT_FIELDS` and
  `_HR_LEAVE_DEFAULT_FIELDS` as class-level tuples, same as `_PARTNER_DEFAULT_FIELDS`.
- **Read-only**: None of the new methods require `@requires_permission` — they are all
  read-only introspection/search tools.

### Smart Field Selection Algorithm

Port the scoring heuristic from mcp-odoo's `select_smart_fields`:

1. Always include `id` and `display_name`.
2. Score each field by type: `char`/`selection`/`many2one` → high; `float`/`integer`/`monetary`
   → medium; `text` → low; `binary`/`html` → skip.
3. Boost fields whose names match common patterns: `name`, `state`, `status`, `date`,
   `amount`, `email`, `phone`, `partner_id`, `user_id`.
4. Penalize technical fields: `create_uid`, `write_uid`, `create_date`, `write_date`,
   `__last_update`, `message_*`.
5. Return the top N (configurable, default 15).

### Aggregate Version Detection

`aggregate_records` needs to know if Odoo supports `formatted_read_group` (19+).
Strategy: call `server_info()` once (result is already cached after first call),
parse the `server_serie` to get the major version.

### Domain Builder Operator Whitelist

```python
SAFE_DOMAIN_OPERATORS = frozenset({
    "=", "!=", ">", ">=", "<", "<=",
    "in", "not in",
    "like", "not like", "ilike", "not ilike",
    "=like", "=ilike",
    "child_of", "parent_of",
})
```

### Known Risks / Gotchas

- **`hr.employee` may not be installed**: If the HR module is not installed on the
  target Odoo instance, `search_employee` and `search_holidays` will raise
  `OdooRPCError`. The tools should catch this and return a clear "module not installed"
  message rather than a raw traceback.
- **`formatted_read_group` availability**: Only exists in Odoo 19+. Fallback to
  `read_group` must be tested.
- **`ir.rule` visibility**: Some `ir.rule` records may not be readable by non-admin
  users. `diagnose_access` should handle `AccessError` gracefully.
- **Smart field caching**: The `fields_get` result should be cached per model per
  toolkit instance to avoid redundant RPC calls. Use a simple dict cache on the
  toolkit — no TTL needed since field schemas don't change within a session.
- **`hr.leave` vs `hr.leave.report.calendar`**: The mcp-odoo project uses
  `hr.leave.report.calendar` (a reporting view). We should prefer `hr.leave` for
  direct queries but fall back gracefully.

### External Dependencies

No new external dependencies. All functionality uses `aiohttp` (already present)
and Pydantic (already present).

---

## 8. Open Questions

- [ ] Should `schema_catalog` cache its results within the toolkit instance (like
      the mcp-odoo project does), or should each call be fresh? — *Owner: Jesus*
- [ ] For `search_holidays`, should we query `hr.leave` directly or use the
      `hr.leave.report.calendar` reporting model? The latter provides a flattened
      view but may not exist in all Odoo versions. — *Owner: Jesus*
- [ ] Should `health_check` be a synchronous method (no `async`) since it makes no
      network calls, or should it remain `async` for interface consistency with other
      toolkit methods? — *Owner: implementer*

---

## Worktree Strategy

- **Isolation unit**: `per-spec` (sequential tasks in one worktree).
- All modules modify the same files (`toolkit.py`, `models/*.py`), so parallel
  execution within this feature would create merge conflicts.
- **Cross-feature dependencies**: None. This feature extends OdooToolkit without
  requiring changes from other in-flight features.
- **Phase 2 note**: The follow-up spec (audit/planning tools) will also modify
  `toolkit.py` but should be sequenced after this feature merges to `dev`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-05 | Jesus Lara | Initial draft — Phase 1 scope |
