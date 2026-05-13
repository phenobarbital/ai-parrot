---
type: feature
base_branch: dev
---

# Feature Specification: Multi-Origin FormDesigner — Pluggable AbstractFormService

**Feature ID**: FEAT-166
**Date**: 2026-05-13
**Author**: Jesus Lara
**Status**: draft
**Target version**: parrot-formdesigner 0.3.0

> Source: `sdd/proposals/multi-origin-formdesigner.proposal.md` (research-grounded
> proposal, no brainstorm). Research audit: `sdd/state/FEAT-166/`.

---

## 1. Motivation & Business Requirements

### Problem Statement

`DatabaseFormTool` in `packages/parrot-formdesigner/src/parrot_formdesigner/tools/database_form.py`
mixes three concerns inside a single class: NetworkNinja-specific SQL + JSON mapping,
DB connectivity, and the AI-Parrot framework adapter wiring (`args_schema`, `_execute`,
`FormRegistry` side-effects). The SQL query, the `_FIELD_TYPE_MAP` (`FIELD_TEXT`,
`FIELD_YES_NO`, …), and every mapping helper (`_build_form_schema`, `_collect_select_options`,
`_map_question_to_field`, `_map_logic_groups`) only make sense against the NetworkNinja
schema (`networkninja.forms` + `networkninja.form_metadata`). Adding any other origin
(a second tenant DB, a REST endpoint, a CSV importer) today requires forking the tool.

### Goals

- Introduce a strategy pattern: `DatabaseFormTool` becomes a thin dispatcher; each
  origin lives in its own `AbstractFormService` subclass.
- Migrate the current NetworkNinja logic verbatim into a `NetworkninjaFormService`
  with zero behavior change for the default case.
- Make services pluggable at import time via a module-level registry mirroring the
  existing `parrot_formdesigner.controls.registry` precedent.
- Preserve backward compatibility for the single production caller
  (`api/handlers.py`) and for the public `DatabaseFormTool(registry=…)` constructor
  shape.

### Non-Goals (explicitly out of scope)

- REST API service implementation — explicitly excluded by the source. The ABC must
  be REST-friendly, but no REST service ships in this feature.
- Refactoring the legacy fallback at
  `packages/ai-parrot/src/parrot/forms/tools/database_form.py`. **Decision: freeze
  as-is.** The fallback only runs when `parrot-formdesigner` is not installed (not the
  default), and the user has chosen to keep it frozen as a legacy snapshot.
- Renaming the package-level `parrot_formdesigner.services/` (registry, storage, cache,
  validators, forwarder, submissions). Visual collision with the new
  `parrot_formdesigner.tools.services/` is acknowledged; renaming has high blast radius
  and no clear win.
- Plumbing `service` through the HTTP layer in `api/handlers.py`. The default
  `service="networkninja"` preserves current behavior; HTTP exposure is a follow-up
  if needed (see §8).
- Any changes to `FormSchema`, `FormRegistry`, `AbstractTool`, or `ToolResult` —
  these are stable contracts.

---

## 2. Architectural Design

### Overview

Split `DatabaseFormTool` into a **dispatcher** + a **strategy registry**:

- `parrot_formdesigner/tools/services/abstract.py` — `AbstractFormService(ABC)` with
  two abstract methods:
  - `async def fetch(self, **params) -> dict[str, Any]` — pull raw data from the source.
  - `def to_form_schema(self, raw: dict[str, Any]) -> FormSchema` — map to canonical model.
  The two-method split is intentional: future REST services override `fetch` only;
  `to_form_schema` stays unit-testable without I/O.

- `parrot_formdesigner/tools/services/registry.py` — module-level dict +
  `register_form_service(name, cls)` / `get_form_service(name)`. Pattern verbatim
  from `parrot_formdesigner/controls/registry.py:67-113`.

- `parrot_formdesigner/tools/services/networkninja.py` — `NetworkninjaFormService`
  owns the current `_FORM_QUERY`, `_FIELD_TYPE_MAP`, `_OPTION_FIELD_TYPES`, all
  `_build_*` / `_collect_*` / `_map_*` helpers, **and DSN resolution** (decided in
  the proposal Q&A: each service owns its own env var; the tool no longer carries
  `dsn`/`db` kwargs).

- `parrot_formdesigner/tools/database_form.py::DatabaseFormTool` — `_execute`
  collapses to: resolve service by name → instantiate → `await fetch()` →
  `to_form_schema()` → `registry.register()` → return `ToolResult`. The tool
  retains the `FormRegistry` coupling so services stay pure.

- `parrot_formdesigner/tools/database_form.py::DatabaseFormInput` — adds
  `service: str = "networkninja"` (LLM-visible default preserves current behavior)
  and optional `params: dict[str, Any] | None = None` overlay for service-specific
  extras (hybrid input shape decided in the proposal Q&A).

### Component Diagram

```
LLM tool-call
     │  args: {formid, orgid, service="networkninja", params?, persist}
     ▼
DatabaseFormTool._execute(**kwargs)             ← thin dispatcher
     │
     │   1. cls = get_form_service(service)     ← module-level registry
     │   2. svc = cls()                         ← service builds its own DSN
     │   3. raw = await svc.fetch(formid=…, orgid=…, **(params or {}))
     │   4. form = svc.to_form_schema(raw)
     │   5. await registry.register(form, persist=persist)
     │   6. return ToolResult(success=True, metadata={"form": form.model_dump()})
     ▼
AbstractFormService (ABC)
  ├── NetworkninjaFormService     ← ships in this feature
  └── <future RESTFormService>    ← out of scope, but enabled

(register_form_service("networkninja", NetworkninjaFormService) fires at import
 time inside parrot_formdesigner/tools/services/__init__.py)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.tools.abstract.AbstractTool` | extends (existing relationship) | `DatabaseFormTool` continues to subclass it. `args_schema = DatabaseFormInput` flows validated kwargs into `_execute`. |
| `parrot.tools.abstract.ToolResult` | returns | Unchanged return shape (`success`, `metadata={"form": …}`). |
| `parrot_formdesigner.core.schema.FormSchema` | produces | Service return type; **no changes to the model**. |
| `parrot_formdesigner.services.registry.FormRegistry` | uses | Tool keeps `await self._registry.register(form, persist=persist)`. The service never touches the registry. |
| `parrot_formdesigner.api.handlers.FormHandlers` | unchanged caller | Constructs `DatabaseFormTool(registry=self.registry)` — default `service="networkninja"` keeps current behavior. |
| `parrot_formdesigner.controls.registry` | pattern source | The new service registry mirrors this convention exactly (module-level dict + `register_*`). |
| `parrot.conf.default_dsn` | optional fallback | `NetworkninjaFormService` resolves DSN as: explicit constructor arg → `PARROT_NETWORKNINJA_DSN` env var → `parrot.conf.default_dsn`. |

### Data Models

```python
# parrot_formdesigner/tools/database_form.py

class DatabaseFormInput(BaseModel):
    """Input schema for DatabaseFormTool — service-aware."""

    service: str = Field(
        default="networkninja",
        description=(
            "Form source service name. Must be registered via "
            "register_form_service(...). Defaults to 'networkninja'."
        ),
    )
    formid: int = Field(..., ge=1, description="Numeric form identifier")
    orgid: int = Field(..., ge=1, description="Organization ID that owns the form")
    params: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Optional service-specific extras forwarded to "
            "AbstractFormService.fetch(**params)."
        ),
    )
    persist: bool = Field(
        default=False,
        description="Save the generated FormSchema to the registry storage",
    )
```

### New Public Interfaces

```python
# parrot_formdesigner/tools/services/abstract.py

from abc import ABC, abstractmethod
from typing import Any
from ...core.schema import FormSchema


class AbstractFormService(ABC):
    """Strategy interface for sourcing a FormSchema from any origin.

    Subclasses implement two methods:
    - ``fetch(**params)``        — retrieve raw data (DB row, REST payload, …).
    - ``to_form_schema(raw)``    — translate raw data into a FormSchema.

    Splitting fetch from mapping keeps the schema-mapping logic testable
    without I/O.
    """

    @abstractmethod
    async def fetch(self, **params: Any) -> dict[str, Any]:
        """Fetch raw form data from the underlying source."""

    @abstractmethod
    def to_form_schema(self, raw: dict[str, Any]) -> FormSchema:
        """Translate the raw payload into a canonical FormSchema."""
```

```python
# parrot_formdesigner/tools/services/registry.py

import logging
from .abstract import AbstractFormService

logger = logging.getLogger(__name__)

_SERVICE_REGISTRY: dict[str, type[AbstractFormService]] = {}


def register_form_service(
    name: str,
    service_cls: type[AbstractFormService],
) -> None:
    """Register (or overwrite) a form-service class under ``name``.

    Idempotent: re-registering the same name overwrites and logs a warning.
    """
    if name in _SERVICE_REGISTRY:
        logger.warning(
            "register_form_service: overwriting existing entry for name=%s",
            name,
        )
    _SERVICE_REGISTRY[name] = service_cls


def get_form_service(name: str) -> type[AbstractFormService]:
    """Resolve a registered form-service class by name.

    Raises:
        KeyError: if no service is registered under ``name``.
    """
    try:
        return _SERVICE_REGISTRY[name]
    except KeyError as exc:
        raise KeyError(
            f"Unknown form service '{name}'. "
            f"Registered: {sorted(_SERVICE_REGISTRY)}"
        ) from exc


def list_form_services() -> list[str]:
    """Return registered service names in registration order."""
    return list(_SERVICE_REGISTRY.keys())
```

```python
# parrot_formdesigner/tools/services/networkninja.py
# (full signatures only — implementation is the migrated current logic)

class NetworkninjaFormService(AbstractFormService):
    """NetworkNinja PostgreSQL form-source service.

    Owns the SQL query against ``networkninja.forms`` + ``networkninja.form_metadata``
    and the question_blocks → FormSchema mapping.
    """

    def __init__(
        self,
        db: Any | None = None,
        dsn: str | None = None,
    ) -> None: ...

    async def fetch(
        self,
        *,
        formid: int,
        orgid: int,
        **_: Any,
    ) -> dict[str, Any]: ...

    def to_form_schema(self, raw: dict[str, Any]) -> FormSchema: ...
```

```python
# parrot_formdesigner/tools/services/__init__.py
"""Form-source services for DatabaseFormTool.

NOTE: this is parrot_formdesigner.tools.services (nested under tools/),
NOT the package-level parrot_formdesigner.services/ (which holds the
FormRegistry, storage, cache, etc.). The two paths are distinct Python
packages; they only share the name.
"""

from .abstract import AbstractFormService
from .registry import (
    register_form_service,
    get_form_service,
    list_form_services,
)
from .networkninja import NetworkninjaFormService

register_form_service("networkninja", NetworkninjaFormService)

__all__ = [
    "AbstractFormService",
    "NetworkninjaFormService",
    "register_form_service",
    "get_form_service",
    "list_form_services",
]
```

---

## 3. Module Breakdown

### Module 1: AbstractFormService ABC
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/tools/services/abstract.py`
- **Responsibility**: Define the two abstract methods (`fetch`, `to_form_schema`) and
  the return contract (`FormSchema` Pydantic instance).
- **Depends on**: `parrot_formdesigner.core.schema.FormSchema` (existing).

### Module 2: Service registry
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/tools/services/registry.py`
- **Responsibility**: Module-level `_SERVICE_REGISTRY` dict + `register_form_service`,
  `get_form_service`, `list_form_services`. Idempotent registration with overwrite
  warning. Pattern verbatim from `parrot_formdesigner/controls/registry.py:67-113`.
- **Depends on**: Module 1.

### Module 3: NetworkninjaFormService
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/tools/services/networkninja.py`
- **Responsibility**: Holds the migrated `_FORM_QUERY`, `_FIELD_TYPE_MAP`,
  `_OPTION_FIELD_TYPES`, and all current `_build_*` / `_collect_*` / `_map_*` helpers
  from `database_form.py`. Implements `fetch()` (DB query via `asyncdb`) and
  `to_form_schema()` (the existing transformation pipeline). Owns DSN resolution:
  constructor arg → `PARROT_NETWORKNINJA_DSN` env var → `parrot.conf.default_dsn`.
- **Depends on**: Module 1, Module 2 (for self-registration via the package init).

### Module 4: Services sub-package init
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/tools/services/__init__.py`
- **Responsibility**: Re-export the public API and register the built-in
  `"networkninja"` service at import time. Documents the name distinction with the
  package-level `parrot_formdesigner.services/`.
- **Depends on**: Modules 1-3.

### Module 5: DatabaseFormTool dispatcher refactor
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/tools/database_form.py`
- **Responsibility**:
  - `DatabaseFormInput` gains `service: str = "networkninja"` and optional
    `params: dict[str, Any] | None = None`.
  - `DatabaseFormTool.__init__` drops `db=`/`dsn=` kwargs (services own their own
    DSN). Keeps `registry: FormRegistry` as the only required arg.
  - `DatabaseFormTool._execute(...)` becomes the 6-step dispatcher described in
    §2 Component Diagram. Unknown service name returns a failing `ToolResult`
    with a clear `error` message (no exception leakage).
  - Module-level networkninja constants and helpers are deleted (migrated to
    Module 3).
- **Depends on**: Modules 1, 2, 4 (imports `get_form_service` from the new
  sub-package; the registration of `"networkninja"` happens at sub-package import).

### Module 6: Test split
- **Paths**:
  - `tests/forms/test_networkninja_form_service.py` (new) — relocated copies of
    the 27 mapping tests from `tests/forms/test_database_form.py`, retargeted onto
    `NetworkninjaFormService`. Construct the service directly, patch `fetch()`
    with mock rows, call `to_form_schema(row)`, assert on the resulting
    `FormSchema`.
  - `tests/forms/test_database_form.py` (replaced) — shrinks to a small
    dispatcher-level suite:
    - Unknown service name returns `ToolResult(success=False, ...)`.
    - Default service is `"networkninja"` and the call reaches the service.
    - Service is invoked with the validated kwargs (`formid`, `orgid`, `params`).
    - Returned `FormSchema` is registered with `persist=persist`.
- **Depends on**: Modules 3 and 5.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_abstract_form_service_is_abstract` | Module 1 | Cannot be instantiated directly; subclass missing either method also fails. |
| `test_register_form_service_idempotent` | Module 2 | Re-registering the same name overwrites and emits a warning log line. |
| `test_register_form_service_distinct_names` | Module 2 | Two services under different names coexist; `list_form_services` returns insertion order. |
| `test_get_form_service_known` | Module 2 | Returns the registered class. |
| `test_get_form_service_unknown_raises` | Module 2 | `KeyError` with the list of registered names. |
| `test_networkninja_self_registers` | Module 4 | After `import parrot_formdesigner.tools.services`, `get_form_service("networkninja")` returns `NetworkninjaFormService`. |
| `test_networkninja_field_type_map_unchanged` | Module 3 | All previous mapping cases from `tests/forms/test_database_form.py::TestFieldTypeMapping` pass against the service. |
| `test_networkninja_conditional_logic_unchanged` | Module 3 | All previous `TestConditionalLogic` cases pass. |
| `test_networkninja_validation_mapping_unchanged` | Module 3 | All previous `TestValidationMapping` cases pass. |
| `test_networkninja_question_block_sections_unchanged` | Module 3 | All previous `TestQuestionBlockSections` cases pass. |
| `test_networkninja_full_form_generation_unchanged` | Module 3 | The end-to-end mock-row → FormSchema produces the same FormSchema as before refactor (golden comparison via `.model_dump()`). |
| `test_networkninja_dsn_resolution_order` | Module 3 | Constructor arg > `PARROT_NETWORKNINJA_DSN` > `parrot.conf.default_dsn`. |
| `test_database_form_input_defaults` | Module 5 | `DatabaseFormInput(formid=1, orgid=1)` → `service=="networkninja"`, `params is None`, `persist is False`. |
| `test_database_form_tool_unknown_service` | Module 5 | `service="bogus"` → `ToolResult(success=False, status="error")` with the error mentioning available services. |
| `test_database_form_tool_dispatches_to_service` | Module 5 | Registers a stub service under `"stub"`, calls the tool with `service="stub"`, asserts `fetch` and `to_form_schema` were each called once with the right args. |
| `test_database_form_tool_registers_resulting_form` | Module 5 | After successful dispatch, the resulting `FormSchema` is in the registry; `persist=True` triggers `storage.save` when storage is configured. |
| `test_database_form_tool_constructor_backward_compat` | Module 5 | `DatabaseFormTool(registry=registry)` still works (mirrors `api/handlers.py` usage). |
| `test_database_form_tool_no_dsn_kwarg` | Module 5 | The tool's `__init__` no longer accepts `dsn=` / `db=` (raises `TypeError`). Documents the intentional removal. |

### Integration Tests

| Test | Description |
|---|---|
| `test_end_to_end_networkninja_default` | Construct `DatabaseFormTool(registry)`, patch the network-ninja service's `fetch()` with a representative row, call `execute(formid=4, orgid=71)`, assert the returned `ToolResult` contains a `FormSchema` with the expected sections/fields. |
| `test_end_to_end_two_services_coexist` | Register a second stub service; verify both default and stub paths work in the same process without bleed-over. |

### Test Data / Fixtures

```python
# tests/forms/conftest.py (additions)

@pytest.fixture
def sample_networkninja_row() -> dict[str, Any]:
    """The canonical mock row currently used by tests/forms/test_database_form.py::sample_db_row."""
    ...   # carried over verbatim from the existing test file

@pytest.fixture
def stub_form_service() -> type[AbstractFormService]:
    """Returns a class registering one trivial form for dispatcher tests."""
    class StubFormService(AbstractFormService):
        async def fetch(self, **params): return {"params": params}
        def to_form_schema(self, raw) -> FormSchema:
            return FormSchema(form_id="stub-1", title="Stub", sections=[])
    return StubFormService
```

---

## 5. Acceptance Criteria

> Feature is complete when ALL of the following are true.

- [ ] `parrot_formdesigner/tools/services/` exists with `abstract.py`,
      `registry.py`, `networkninja.py`, and `__init__.py`.
- [ ] `AbstractFormService` is an `ABC` with abstract methods `fetch(**params)
      -> dict[str, Any]` and `to_form_schema(raw) -> FormSchema`.
- [ ] `register_form_service`, `get_form_service`, and `list_form_services`
      are public exports of `parrot_formdesigner.tools.services`.
- [ ] `NetworkninjaFormService` is registered under the name `"networkninja"`
      automatically at sub-package import time.
- [ ] `DatabaseFormInput` exposes a `service: str = "networkninja"` field and an
      optional `params: dict[str, Any] | None = None` field. `formid`, `orgid`,
      and `persist` retain their current shape.
- [ ] `DatabaseFormTool._execute` no longer contains any reference to
      `networkninja`, `_FORM_QUERY`, `_FIELD_TYPE_MAP`, `_build_*`, `_map_*`,
      `_collect_*`, or `_fetch_form_row`. All such symbols are deleted from
      `database_form.py`.
- [ ] `DatabaseFormTool.__init__` no longer accepts `dsn=` or `db=` kwargs.
- [ ] `DatabaseFormTool(registry=registry)` still works (i.e. `api/handlers.py`
      is unmodified and continues to function).
- [ ] When `DatabaseFormInput.service` names an unregistered service,
      `_execute` returns `ToolResult(success=False, status="error")` with an
      error message that lists registered services. No exception escapes.
- [ ] `NetworkninjaFormService` resolves DSN in this exact order: explicit
      constructor arg → `PARROT_NETWORKNINJA_DSN` env var → `parrot.conf.default_dsn`.
- [ ] All previous assertions from `tests/forms/test_database_form.py` (the 27
      mapping tests) pass against `NetworkninjaFormService` in
      `tests/forms/test_networkninja_form_service.py`.
- [ ] A new dispatcher-level test suite covers: unknown service, default service,
      service is invoked with validated kwargs, returned form is registered,
      constructor backward-compat, removed kwargs raise `TypeError`.
- [ ] `pytest tests/forms/` passes (full forms test suite).
- [ ] `pytest packages/parrot-formdesigner/` passes (package smoke tests).
- [ ] No changes to `FormSchema`, `FormRegistry`, `AbstractTool`, `ToolResult`.
- [ ] No changes to `packages/ai-parrot/src/parrot/forms/tools/database_form.py`
      (legacy fallback frozen as-is).
- [ ] `packages/parrot-formdesigner/src/parrot_formdesigner/version.py` is bumped
      to `0.3.0`.

---

## 6. Codebase Contract

> **Anti-hallucination anchor.** All entries verified by direct file reads during
> research phase `FEAT-166` (see `sdd/state/FEAT-166/findings/`).

### Verified Imports

```python
# Existing — to be used verbatim
from parrot.tools.abstract import AbstractTool, ToolResult  # verified: packages/ai-parrot/src/parrot/tools/abstract.py:36, 71
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection  # verified: packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:21, 68, 108
from parrot_formdesigner.core.constraints import ConditionOperator, DependencyRule, FieldCondition  # used in current database_form.py line 33
from parrot_formdesigner.core.options import FieldOption  # used in current database_form.py line 34
from parrot_formdesigner.core.types import FieldType  # used in current database_form.py line 37
from parrot_formdesigner.services.registry import FormRegistry  # verified: packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py:116

# New — created by this feature
from parrot_formdesigner.tools.services import (
    AbstractFormService,
    NetworkninjaFormService,
    register_form_service,
    get_form_service,
    list_form_services,
)
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/tools/abstract.py
class ToolResult(BaseModel):                                       # line 36
    success: bool = Field(default=True, ...)                       # line 38
    status: str = Field(default="success", ...)                    # line 39
    result: Any                                                    # line 40
    error: Optional[str] = Field(default=None, ...)                # line 41
    metadata: Dict[str, Any] = Field(default_factory=dict, ...)    # line 42

class AbstractTool(ABC):                                           # line 71
    name: str = None
    description: str = None
    args_schema: Type[BaseModel] = AbstractToolArgsSchema          # line 87
    @abstractmethod
    async def _execute(self, **kwargs) -> Any: ...                 # line 200-201
    async def execute(self, *args, **kwargs) -> ToolResult: ...    # line 375 — validates args and forwards as kwargs

# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py
class FormSchema(BaseModel):                                       # line 108
    form_id: str                                                   # line 133
    version: str = "1.0"                                           # line 134
    title: LocalizedString                                         # line 135
    description: LocalizedString | None = None                     # line 136
    sections: list[FormSection]                                    # line 137
    submit: SubmitAction | None = None                             # line 138
    cancel_allowed: bool = True                                    # line 139
    meta: dict[str, Any] | None = None                             # line 140
    created_at: datetime | None = None                             # line 141
    tenant: str | None = None                                      # line 142

# packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py
class FormRegistry:                                                # line 116
    def __init__(self, storage: FormStorage | None = None) -> None: ...  # line 133
    async def register(
        self,
        form: FormSchema,
        *,
        persist: bool = False,
        overwrite: bool = True,
    ) -> None: ...                                                 # line 146
    async def get(self, form_id: str) -> FormSchema | None: ...    # line 214

# packages/parrot-formdesigner/src/parrot_formdesigner/tools/database_form.py (CURRENT — to be refactored)
class DatabaseFormInput(BaseModel):                                # line 113
    formid: int = Field(..., ge=1, ...)                            # line 122
    orgid: int = Field(..., ge=1, ...)                             # line 123
    persist: bool = Field(default=False, ...)                      # line 124

class DatabaseFormTool(AbstractTool):                              # line 135
    name: str = "database_form"                                    # line 149
    args_schema = DatabaseFormInput                                # line 154
    def __init__(
        self,
        registry: FormRegistry,
        db: Any | None = None,    # ← TO BE REMOVED
        dsn: str | None = None,   # ← TO BE REMOVED
        **kwargs: Any,
    ) -> None: ...                                                 # line 156
    async def _execute(  # line 207
        self,
        formid: int,
        orgid: int,
        persist: bool = False,
        **kwargs: Any,
    ) -> ToolResult: ...
```

### Reference Patterns (mirror these verbatim)

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/controls/registry.py
_REGISTRY: dict[str, FieldControlMetadata] = {}                    # line 67

def register_field_control(field_type, *, label, …) -> None:       # line 70
    type_id = field_type.value if isinstance(field_type, FieldType) else field_type
    if type_id in _REGISTRY:
        logger.warning("register_field_control: overwriting existing entry for type=%s", type_id)
    _REGISTRY[type_id] = FieldControlMetadata(…)
```

The new `parrot_formdesigner.tools.services.registry` MUST follow this exact
shape (module-level dict, idempotent register with overwrite warning, ordered
iteration).

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `DatabaseFormTool._execute` | `get_form_service(service)` | function call | `parrot_formdesigner/tools/services/registry.py` (new) |
| `DatabaseFormTool._execute` | `AbstractFormService.fetch(**params)` | async method call | `parrot_formdesigner/tools/services/abstract.py` (new) |
| `DatabaseFormTool._execute` | `AbstractFormService.to_form_schema(raw)` | method call | `parrot_formdesigner/tools/services/abstract.py` (new) |
| `DatabaseFormTool._execute` | `FormRegistry.register(form, persist=…)` | async method call | `packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py:146` |
| `NetworkninjaFormService.fetch` | `asyncdb.AsyncDB("pg", dsn=…)` | constructor + `connection().queryrow()` | current `database_form.py:304-310` (carried over) |
| `parrot_formdesigner.tools.services.__init__` | `register_form_service("networkninja", NetworkninjaFormService)` | import-time call | new module |
| `parrot_formdesigner.api.handlers.FormHandlers.__init__` | `DatabaseFormTool(registry=self.registry)` | constructor | `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py:67-74` (unchanged) |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot_designer.tools.database_form`~~ — the user's brief used this path,
  but the canonical Python namespace is `parrot_formdesigner` (package
  `parrot-formdesigner`). Do not use `parrot_designer`.
- ~~`parrot_formdesigner.services.AbstractFormService`~~ — the new ABC lives at
  `parrot_formdesigner.tools.services.AbstractFormService`. The package-level
  `parrot_formdesigner.services/` already exists and houses
  `FormRegistry`/`FormStorage`/`FormCache` — do not add the new ABC there.
- ~~`from importlib import import_module` for service resolution~~ — no
  precedent in `parrot-formdesigner`. Use the module-level dict pattern.
- ~~`@register_form_service` decorator~~ — the precedent (`register_field_control`)
  is a plain function call, not a decorator. Match it.
- ~~`AbstractFormService.build_form_schema(**params)`~~ — rejected during proposal
  Q&A in favour of the two-method `fetch` + `to_form_schema` split.
- ~~`DatabaseFormTool(dsn=…)` / `DatabaseFormTool(db=…)`~~ — these kwargs are
  removed in this feature. The DSN now belongs to the service.
- ~~`parrot.forms.tools.database_form.NetworkninjaFormService`~~ — the legacy
  fallback at `packages/ai-parrot/src/parrot/forms/tools/database_form.py` is
  frozen and gets no new symbols (see §1 Non-Goals).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Module-level registry + plain function**, not decorators or `entry_points`,
  per `parrot_formdesigner/controls/registry.py:67-113`. Idempotent registration
  with overwrite-warn semantics.
- **Self-registration at sub-package import time** in
  `parrot_formdesigner/tools/services/__init__.py`, per
  `parrot_formdesigner/controls/builtin.py` (which calls `register_field_control`
  for every built-in at module load).
- **Async public methods**: `AbstractFormService.fetch` is async (matches the
  existing `_fetch_form_row` shape in `database_form.py:289`).
- **Pydantic for all I/O boundaries**: `DatabaseFormInput` validates LLM input;
  `FormSchema` validates service output.
- **Logger via `self.logger = logging.getLogger(__name__)`** in every new class
  (matches conventions across the package and `CLAUDE.md` non-negotiable rules).
- **Migrate the SQL verbatim**: the `_FORM_QUERY` (lines 43-58 of current
  `database_form.py`) moves into `NetworkninjaFormService` byte-for-byte. No
  rewording or restructuring of the query in this feature.
- **DSN resolution sequence**: explicit constructor arg → env var
  (`PARROT_NETWORKNINJA_DSN`) → `parrot.conf.default_dsn`. Mirror the order
  currently in `database_form.py:179-201`, but rename the env var.

### Known Risks / Gotchas

- **Two-`services/` confusion.** `parrot_formdesigner.services/` (package level —
  FormRegistry & friends) vs. `parrot_formdesigner.tools.services/` (this
  feature — the strategy registry). The new sub-package `__init__.py` MUST open
  with a comment documenting the distinction; the spec already includes that
  docstring text in §2.
- **Test migration footprint.** 27 tests live in `tests/forms/test_database_form.py`
  using `from parrot.forms import DatabaseFormTool`. The relocation moves the
  bulk to a new `tests/forms/test_networkninja_form_service.py`, but a small
  set must remain at the tool level. Mitigation: copy the existing
  `sample_db_row` fixture into a shared `tests/forms/conftest.py` and import
  it in both files so the fixture stays single-source.
- **Backward-compat kwargs removal.** Removing `dsn=`/`db=` from
  `DatabaseFormTool.__init__` is a deliberate breaking change at the test layer,
  not the production-caller layer (`api/handlers.py` never passed them).
  Mitigation: explicit acceptance criterion + dedicated unit test
  (`test_database_form_tool_no_dsn_kwarg`).
- **Legacy fallback drift.** The frozen copy in `packages/ai-parrot/src/parrot/forms/tools/database_form.py`
  will not gain the `service` parameter. Callers running without
  `parrot-formdesigner` installed get the old single-origin behavior. Mitigation:
  document in the version bump notes; this is an accepted Non-Goal.
- **Persistence side-effect placement.** `await registry.register(form, persist=persist)`
  STAYS in the tool, not the service. Easy to get wrong; covered by an
  acceptance criterion + integration test.
- **LLM tool-call discoverability.** Adding `service` to `DatabaseFormInput`
  surfaces it to any LLM that calls the tool. The default value
  (`"networkninja"`) means existing LLM agents are unaffected, but the
  description field on the Pydantic model is the only documentation the LLM
  sees — make it clear and short.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `asyncdb` | (existing) | DB connectivity inside `NetworkninjaFormService.fetch` (migrated from current `database_form.py:304`). No version bump. |
| `pydantic` | (existing) | `DatabaseFormInput`, `FormSchema`, `ToolResult` — already a transitive dep. |
| `navconfig` | (existing) | Logging convention; already used in `parrot.tools.abstract`. |

No new external dependencies.

---

## Worktree Strategy

- **Default isolation unit**: per-spec.
- **Rationale**: tasks have strong sequential dependencies (ABC → registry →
  NetworkninjaFormService → dispatcher refactor → test split). Parallelizing
  them across worktrees would create constant merge conflicts in
  `database_form.py` and the test directories.
- **Cross-feature dependencies**: none. No other in-flight spec touches
  `parrot_formdesigner/tools/`.
- **Recommended worktree branch**:
  ```bash
  git worktree add -b feat-166-multi-origin-formdesigner \
    .claude/worktrees/feat-166-multi-origin-formdesigner HEAD
  ```

---

## 8. Open Questions

### Resolved (carried forward from proposal Q&A)

- [x] **Should `AbstractFormService` expose one abstract method or two?** —
  *Resolved in proposal Q&A (U1)*: Two methods — `fetch(**params) -> dict[str, Any]`
  + `to_form_schema(raw) -> FormSchema`. More testable; future REST services
  override `fetch` only.

- [x] **How does `DatabaseFormTool` pass DB connectivity to the service?** —
  *Resolved in proposal Q&A (U2)*: Service owns its own DSN. Each service resolves
  its own env var (e.g. `PARROT_NETWORKNINJA_DSN`). The tool drops `dsn=`/`db=`
  kwargs from its constructor and from `DatabaseFormInput`.

- [x] **Shape of `DatabaseFormInput` across services?** —
  *Resolved in proposal Q&A (U3)*: Hybrid — keep `formid` + `orgid` at top level
  for LLM-friendly tool calls; add optional `params: dict[str, Any] | None`
  overlay for service-specific extras.

- [x] **What happens to the legacy fallback at
  `packages/ai-parrot/src/parrot/forms/tools/database_form.py`?** —
  *Resolved in spec Q&A*: Freeze as-is. Captured as a Non-Goal in §1. No new
  symbols, no refactor; the fallback continues to run only when
  `parrot-formdesigner` is not installed.

- [x] **Target version?** — *Resolved in spec Q&A*: `parrot-formdesigner 0.3.0`
  (minor bump; new public API is backward-compatible thanks to default
  `service="networkninja"`).

### Unresolved (defer to implementation or follow-up feature)

- [ ] **Should `api/handlers.py` surface `service` as an HTTP query parameter,
  or is the default `"networkninja"` sufficient for now?** — *Owner*: API
  consumer / follow-up feature. Does not block this spec.

- [ ] **Should the env-var naming convention be `PARROT_NETWORKNINJA_DSN` or
  `PARROT_FORMSERVICE_NETWORKNINJA_DSN` (longer but namespaced)?** — *Owner*:
  implementer. The spec defaults to the shorter `PARROT_NETWORKNINJA_DSN`;
  revisit if a second service ships with a name collision risk.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-13 | Jesus Lara | Initial draft scaffolded from FEAT-166 proposal. |
