---
type: Wiki Overview
title: 'TASK-1129: DatabaseFormTool — dispatcher refactor + input update + version
  bump'
id: doc:sdd-tasks-completed-task-1129-database-form-tool-dispatcher-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements §3 Module 5 of the spec. Turns `DatabaseFormTool` into a thin
relates_to:
- concept: mod:parrot.tools.abstract
  rel: mentions
---

# TASK-1129: DatabaseFormTool — dispatcher refactor + input update + version bump

**Feature**: FEAT-166 — Multi-Origin FormDesigner — Pluggable AbstractFormService
**Spec**: `sdd/specs/multi-origin-formdesigner.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1128
**Assigned-to**: unassigned

---

## Context

Implements §3 Module 5 of the spec. Turns `DatabaseFormTool` into a thin
dispatcher and `DatabaseFormInput` into a service-aware input model. Deletes
every NetworkNinja-specific symbol from `database_form.py` (they now live in
`NetworkninjaFormService` per TASK-1127). Also bumps the package version to
`0.3.0` per the user's spec decision.

After this task, `_execute` is ~25 lines (dispatch + register), and the
NetworkNinja constants no longer appear in the tool module.

---

## Scope

- **`DatabaseFormInput`** (in `database_form.py`):
  - Add `service: str = Field(default="networkninja", description=...)`.
  - Add `params: dict[str, Any] | None = Field(default=None, description=...)`.
  - Keep `formid`, `orgid`, `persist` unchanged.

- **`DatabaseFormTool.__init__`** (in `database_form.py`):
  - Drop `db: Any | None = None` and `dsn: str | None = None` kwargs.
  - Signature becomes `__init__(self, registry: FormRegistry, **kwargs: Any) -> None`.
  - Update the docstring accordingly.

- **`DatabaseFormTool._execute`** (in `database_form.py`):
  Replace the current body with the 6-step dispatcher described in spec §2:
  1. `cls = get_form_service(service)` — on `KeyError`, return
     `ToolResult(success=False, status="error", result=None, error=<msg>, metadata={"error": <msg>})`
     where `<msg>` lists registered services.
  2. `service_instance = cls()` (services own their own config; the tool
     no longer forwards `dsn`/`db`).
  3. `raw = await service_instance.fetch(formid=formid, orgid=orgid, **(params or {}))`.
  4. `form = service_instance.to_form_schema(raw)`.
  5. `await self._registry.register(form, persist=persist)`.
  6. Return `ToolResult(success=True, status="success", result={"form_id": form.form_id, "title": str(form.title)}, metadata={"form": form.model_dump()})`.
  Wrap steps 3-5 in a try/except (`json.JSONDecodeError`, `RuntimeError`, broad
  `Exception`) preserving the current error-result shape at
  `database_form.py:257-283`.

- **Delete from `database_form.py`** (all moved to `NetworkninjaFormService` in TASK-1127):
  - `_FORM_QUERY` (lines 43-58)
  - `_FIELD_TYPE_MAP` and `_OPTION_FIELD_TYPES` (lines 66-105)
  - `_fetch_form_row` (lines 289-314)
  - `_get_dsn` (lines 179-201)
  - `_build_form_schema`, `_build_metadata_index`, `_build_question_id_index`,
    `_collect_select_options`, `_map_block_to_section`,
    `_map_question_to_field`, `_map_logic_groups` (lines 320-731).
  - The matching imports that become unused (`ConditionOperator`,
    `DependencyRule`, `FieldCondition`, `FieldOption`, `FormField`,
    `FormSection`, `FieldType`).

- **Version bump**: update
  `packages/parrot-formdesigner/src/parrot_formdesigner/version.py` to
  `__version__ = "0.3.0"`.

- Add a small dispatcher test suite at
  `packages/parrot-formdesigner/tests/unit/test_database_form_tool_dispatch.py`:
  unknown service → failing `ToolResult`; default service is invoked with
  correct args (using a stub registered under a unique name); resulting
  `FormSchema` is registered; constructor backward-compat
  (`DatabaseFormTool(registry=…)` works); `dsn=`/`db=` kwargs raise
  `TypeError`.

**NOT in scope**: relocating the existing 27 mapping tests (TASK-1130);
changing `api/handlers.py` (must continue to work unmodified — that's an
acceptance criterion).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/tools/database_form.py` | MODIFY | Slim to dispatcher + new `DatabaseFormInput` fields; delete all networkninja-specific symbols |
| `packages/parrot-formdesigner/src/parrot_formdesigner/version.py` | MODIFY | `__version__ = "0.3.0"` |
| `packages/parrot-formdesigner/tests/unit/test_database_form_tool_dispatch.py` | CREATE | Dispatcher-level unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Inside the refactored database_form.py (only these are needed)
from __future__ import annotations
import logging
from typing import Any
from pydantic import BaseModel, Field

try:
    from parrot.tools.abstract import AbstractTool, ToolResult  # verified: packages/ai-parrot/src/parrot/tools/abstract.py:36, 71
except ImportError as exc:
    raise ImportError(
        "parrot-formdesigner tools require the 'ai-parrot' package. "
        "Install it with: uv add ai-parrot"
    ) from exc

from ..services.registry import FormRegistry  # verified: packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py:116
from .services import get_form_service          # created by TASK-1126/1128
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/tools/abstract.py
class ToolResult(BaseModel):                                       # line 36
    success: bool                                                  # line 38
    status: str                                                    # line 39
    result: Any                                                    # line 40
    error: Optional[str] = None                                    # line 41
    metadata: Dict[str, Any]                                       # line 42

class AbstractTool(ABC):                                           # line 71
    name: str = None
    description: str = None
    args_schema: Type[BaseModel] = AbstractToolArgsSchema
    @abstractmethod
    async def _execute(self, **kwargs) -> Any: ...                 # line 200-201

# packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py
class FormRegistry:                                                # line 116
    async def register(
        self,
        form: FormSchema,
        *,
        persist: bool = False,
        overwrite: bool = True,
    ) -> None: ...                                                 # line 146

# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py:67-74
# (UNCHANGED — verify this caller still works after the refactor)
self._db_tool = DatabaseFormTool(registry=self.registry)
```

### Does NOT Exist

- ~~`get_form_service` raising a non-`KeyError` exception~~ — it raises
  `KeyError` (per TASK-1126). Catch that specifically.
- ~~`AbstractFormService` instance reuse across calls~~ — instantiate a new
  service per `_execute` call (services are cheap; this keeps state isolation
  trivial).
- ~~Passing the registry to `service_instance`~~ — services don't see the
  registry. Tool registers after `to_form_schema`.
- ~~`DatabaseFormTool(dsn=…)` / `DatabaseFormTool(db=…)` after this task~~ —
  these kwargs are removed; calling them must raise `TypeError`.

---

## Implementation Notes

### Pattern to Follow

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/tools/database_form.py (after refactor)
"""DatabaseFormTool — thin dispatcher over an AbstractFormService.

Resolves the requested service by name, runs fetch + to_form_schema, then
registers the resulting FormSchema in the FormRegistry.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

try:
    from parrot.tools.abstract import AbstractTool, ToolResult
except ImportError as exc:
    raise ImportError(
        "parrot-formdesigner tools require the 'ai-parrot' package. "
        "Install it with: uv add ai-parrot"
    ) from exc

from ..services.registry import FormRegistry
from .services import get_form_service


class DatabaseFormInput(BaseModel):
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


class DatabaseFormTool(AbstractTool):
    name: str = "database_form"
    description: str = (
        "Load a form definition from a configured form-source service into a "
        "FormSchema. Requires formid and orgid; service defaults to 'networkninja'."
    )
    args_schema = DatabaseFormInput

    def __init__(self, registry: FormRegistry, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._registry = registry
        self.logger = logging.getLogger(__name__)

    async def _execute(  # type: ignore[override]
        self,
        service: str = "networkninja",
        formid: int = 0,
        orgid: int = 0,
        params: dict[str, Any] | None = None,
        persist: bool = False,
        **kwargs: Any,
    ) -> ToolResult:
        # 1. Resolve service
        try:
            cls = get_form_service(service)
        except KeyError as exc:
            return ToolResult(
                success=False,
                status="error",
                result=None,
                error=str(exc),
                metadata={"error": str(exc)},
            )

        # 2-4. Instantiate + fetch + map
        try:
            svc = cls()
            raw = await svc.fetch(formid=formid, orgid=orgid, **(params or {}))
            form = svc.to_form_schema(raw)
        except json.JSONDecodeError as exc:
            self.logger.error("Malformed JSON for formid=%s: %s", formid, exc)
            return ToolResult(
                success=False, status="error", result=None,
                error=str(exc), metadata={"error": str(exc)},
            )
        except RuntimeError as exc:
            # service raised — e.g., form not found, DB error
            return ToolResult(
                success=False, status="error", result=None,
                error=str(exc), metadata={"error": str(exc)},
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.error(
                "DatabaseFormTool error for service=%s formid=%s: %s",
                service, formid, exc, exc_info=True,
            )
            return ToolResult(
                success=False, status="error", result=None,
                error=str(exc), metadata={"error": str(exc)},
            )

        # 5. Register
        await self._registry.register(form, persist=persist)

        self.logger.info(
            "Loaded form %s via service=%s (formid=%s, orgid=%s) — %d sections",
            form.form_id, service, formid, orgid, len(form.sections),
        )

        # 6. Return
        return ToolResult(
            success=True,
            status="success",
            result={"form_id": form.form_id, "title": str(form.title)},
            metadata={"form": form.model_dump()},
        )
```

### Key Constraints

- `api/handlers.py` MUST work unmodified. Verify with a manual import check
  after the refactor: `python -c "from parrot_formdesigner.api.handlers import FormHandlers"` must succeed.
- `_execute` MUST NOT swallow the dispatch error silently — return an explicit
  failing `ToolResult` with a clear `error` and `metadata["error"]`.
- The version bump in `version.py` is a one-line change; do NOT touch
  `__title__`, `__author__`, or `__license__`.

### References in Codebase

- Current `database_form.py:207-283` — error-result shape to preserve.
- `packages/parrot-formdesigner/src/parrot_formdesigner/version.py` — version
  string lives in `__version__`.

---

## Acceptance Criteria

- [ ] `DatabaseFormInput` has fields `service`, `formid`, `orgid`, `params`, `persist` with the described defaults and validators.
- [ ] `DatabaseFormTool.__init__(registry, **kwargs)` no longer accepts `db=` or `dsn=`; calling with `dsn=…` raises `TypeError`.
- [ ] `DatabaseFormTool._execute` no longer references `networkninja`, `_FORM_QUERY`, `_FIELD_TYPE_MAP`, or any `_build_*`/`_map_*`/`_collect_*`/`_fetch_form_row`/`_get_dsn` symbol.
- [ ] Unknown service name → `ToolResult(success=False, status="error", ...)` with `error` listing registered services. No exception leaks.
- [ ] Default service `"networkninja"` reaches `NetworkninjaFormService.fetch(formid=…, orgid=…)`.
- [ ] After `await tool.execute(formid=…, orgid=…)`, the `FormSchema` is in the registry (`await registry.get(form_id)` returns it).
- [ ] `from parrot_formdesigner.api.handlers import FormHandlers` still imports clean.
- [ ] `parrot_formdesigner.version.__version__` equals `"0.3.0"`.
- [ ] `pytest packages/parrot-formdesigner/tests/unit/test_database_form_tool_dispatch.py -v` passes.
- [ ] `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/tools/database_form.py` clean.

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_database_form_tool_dispatch.py
"""Dispatcher-level tests for DatabaseFormTool (post-refactor)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot_formdesigner.core.schema import FormSchema
from parrot_formdesigner.services.registry import FormRegistry
from parrot_formdesigner.tools.database_form import DatabaseFormTool, DatabaseFormInput
from parrot_formdesigner.tools.services import (
    AbstractFormService,
    register_form_service,
    _SERVICE_REGISTRY,
)


class _StubService(AbstractFormService):
    last_params = None
    last_form: FormSchema | None = None

    async def fetch(self, **params):
        _StubService.last_params = params
        return {"params": params}

    def to_form_schema(self, raw):
        form = FormSchema(form_id="stub-1", title="Stub", sections=[])
        _StubService.last_form = form
        return form


@pytest.fixture
def registry():
    return FormRegistry()


@pytest.fixture
def stub_registered():
    register_form_service("__stub__", _StubService)
    yield
    _SERVICE_REGISTRY.pop("__stub__", None)


def test_input_defaults():
    inp = DatabaseFormInput(formid=1, orgid=1)
    assert inp.service == "networkninja"
    assert inp.params is None
    assert inp.persist is False


def test_constructor_backward_compat(registry):
    tool = DatabaseFormTool(registry=registry)
    assert tool is not None


def test_constructor_rejects_dsn_kwarg(registry):
    with pytest.raises(TypeError):
        DatabaseFormTool(registry=registry, dsn="postgres://x")


def test_constructor_rejects_db_kwarg(registry):
    with pytest.raises(TypeError):
        DatabaseFormTool(registry=registry, db=object())


@pytest.mark.asyncio
async def test_unknown_service_returns_failing_toolresult(registry):
    tool = DatabaseFormTool(registry=registry)
    result = await tool._execute(
        service="definitely-not-a-real-service",
        formid=1, orgid=1,
    )
    assert result.success is False
    assert result.status == "error"
    assert "definitely-not-a-real-service" in (result.error or "")


@pytest.mark.asyncio
async def test_dispatcher_invokes_service_with_validated_kwargs(
    registry, stub_registered,
):
    tool = DatabaseFormTool(registry=registry)
    result = await tool._execute(
        service="__stub__",
        formid=42, orgid=7,
        params={"extra": "value"},
    )
    assert result.success is True
    assert _StubService.last_params == {"formid": 42, "orgid": 7, "extra": "value"}


@pytest.mark.asyncio
async def test_dispatcher_registers_form_in_registry(
    registry, stub_registered,
):
    tool = DatabaseFormTool(registry=registry)
    await tool._execute(service="__stub__", formid=1, orgid=1)
    assert await registry.get("stub-1") is not None


@pytest.mark.asyncio
async def test_handlers_import_unchanged():
    """Verify api/handlers.py still imports clean after the refactor."""
    from parrot_formdesigner.api.handlers import FormHandlers  # noqa: F401
```

---

## Completion Note

Implemented as specified. Modified/Created:
- `packages/parrot-formdesigner/src/parrot_formdesigner/tools/database_form.py` — replaced with slim dispatcher (~170 lines). `DatabaseFormInput` gains `service` and `params`. `DatabaseFormTool.__init__` drops `db=`/`dsn=` (explicit TypeError). `_execute` is the 6-step dispatcher. All networkninja-specific symbols deleted.
- `packages/parrot-formdesigner/src/parrot_formdesigner/version.py` — bumped to `0.3.0`.
- `packages/parrot-formdesigner/tests/unit/test_database_form_tool_dispatch.py` — 8 tests all passing.

Note: `FormHandlers` in the spec's codebase contract was stale — the actual class in handlers.py is `FormAPIHandler`. Fixed the test accordingly. All 8 tests pass.
