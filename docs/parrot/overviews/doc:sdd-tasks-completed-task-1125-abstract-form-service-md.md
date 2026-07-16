---
type: Wiki Overview
title: 'TASK-1125: AbstractFormService ABC'
id: doc:sdd-tasks-completed-task-1125-abstract-form-service-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements §3 Module 1 of the spec. Defines the strategy interface that every
---

# TASK-1125: AbstractFormService ABC

**Feature**: FEAT-166 — Multi-Origin FormDesigner — Pluggable AbstractFormService
**Spec**: `sdd/specs/multi-origin-formdesigner.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements §3 Module 1 of the spec. Defines the strategy interface that every
form-source service must satisfy. The two-method split (`fetch` + `to_form_schema`)
was decided in the proposal Q&A (U1) and is what allows future REST services to
override `fetch` only while keeping `to_form_schema` unit-testable without I/O.

---

## Scope

- Create `packages/parrot-formdesigner/src/parrot_formdesigner/tools/services/__init__.py`
  as an empty stub for now (it will be filled in by TASK-1128). This is required
  so the directory is a real Python package and TASK-1125's tests can import from it.
- Create `packages/parrot-formdesigner/src/parrot_formdesigner/tools/services/abstract.py`
  with `AbstractFormService(ABC)` exposing exactly two abstract methods:
  - `async def fetch(self, **params: Any) -> dict[str, Any]`
  - `def to_form_schema(self, raw: dict[str, Any]) -> FormSchema`
- Write unit tests covering: cannot instantiate the ABC; subclass missing either
  method also fails; a fully-implemented subclass instantiates and the methods
  are callable.

**NOT in scope**: the registry module (TASK-1126); the NetworkNinja
implementation (TASK-1127); any wiring inside `database_form.py` (TASK-1129).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/tools/services/__init__.py` | CREATE | Empty stub (single docstring) — filled in by TASK-1128 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/tools/services/abstract.py` | CREATE | `AbstractFormService(ABC)` |
| `packages/parrot-formdesigner/tests/unit/test_abstract_form_service.py` | CREATE | Unit tests for the ABC contract |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Relative import from the new module
from ...core.schema import FormSchema  # verified: packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:108

# For the test file
from parrot_formdesigner.tools.services.abstract import AbstractFormService
from parrot_formdesigner.core.schema import FormSchema
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:108-142
class FormSchema(BaseModel):
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
```

### Does NOT Exist

- ~~`parrot_formdesigner.tools.services.AbstractFormService`~~ — created by THIS task.
- ~~`AbstractFormService.build_form_schema()`~~ — rejected during proposal Q&A in
  favour of the two-method split. Do not add it.
- ~~`AbstractFormService.register()`~~ — registry coupling stays in the tool, not
  the service.

---

## Implementation Notes

### Pattern to Follow

Use stdlib `abc.ABC` and `abc.abstractmethod` directly — no metaclass tricks. The
module structure mirrors the lightweight ABC style already in
`packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py:29`
(`class FormStorage(ABC)`).

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/tools/services/abstract.py
"""AbstractFormService — strategy interface for form-source services."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ...core.schema import FormSchema


class AbstractFormService(ABC):
    """Strategy interface for sourcing a FormSchema from any origin.

    Subclasses implement two methods:
    - ``fetch(**params)``        — retrieve raw data (DB row, REST payload, …).
    - ``to_form_schema(raw)``    — translate raw data into a FormSchema.

    Splitting fetch from mapping keeps the schema-mapping logic testable
    without I/O. The FormRegistry coupling stays in DatabaseFormTool — the
    service must not call registry.register() itself.
    """

    @abstractmethod
    async def fetch(self, **params: Any) -> dict[str, Any]:
        """Fetch raw form data from the underlying source."""

    @abstractmethod
    def to_form_schema(self, raw: dict[str, Any]) -> FormSchema:
        """Translate the raw payload into a canonical FormSchema."""
```

### Key Constraints

- Use `from __future__ import annotations` for forward-reference style.
- Google-style docstrings (project convention).
- Pure ABC — no implementation logic.
- `fetch` is async; `to_form_schema` is sync (mapping is CPU-only, matches
  current pipeline in `database_form.py`).

### References in Codebase

- `packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py:29-113` — `FormStorage(ABC)` for ABC style reference.

---

## Acceptance Criteria

- [ ] `parrot_formdesigner/tools/services/__init__.py` exists (empty stub OK).
- [ ] `parrot_formdesigner/tools/services/abstract.py` exists with `AbstractFormService(ABC)`.
- [ ] `AbstractFormService` has exactly two abstract methods: `fetch(**params) -> dict[str, Any]` and `to_form_schema(raw) -> FormSchema`.
- [ ] `from parrot_formdesigner.tools.services.abstract import AbstractFormService` works.
- [ ] `pytest packages/parrot-formdesigner/tests/unit/test_abstract_form_service.py -v` passes.
- [ ] `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/tools/services/` clean.

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_abstract_form_service.py
from typing import Any

import pytest

from parrot_formdesigner.tools.services.abstract import AbstractFormService
from parrot_formdesigner.core.schema import FormSchema


class TestAbstractFormService:
    def test_abc_cannot_be_instantiated(self):
        """ABC must reject direct instantiation."""
        with pytest.raises(TypeError):
            AbstractFormService()  # type: ignore[abstract]

    def test_subclass_missing_fetch_cannot_instantiate(self):
        """Subclass that only implements to_form_schema must fail."""
        class Half(AbstractFormService):
            def to_form_schema(self, raw):
                return FormSchema(form_id="x", title="x", sections=[])

        with pytest.raises(TypeError):
            Half()  # type: ignore[abstract]

    def test_subclass_missing_to_form_schema_cannot_instantiate(self):
        """Subclass that only implements fetch must fail."""
        class Half(AbstractFormService):
            async def fetch(self, **params):
                return {}

        with pytest.raises(TypeError):
            Half()  # type: ignore[abstract]

    async def test_fully_implemented_subclass_works(self):
        """Concrete subclass instantiates and methods are callable."""
        class Concrete(AbstractFormService):
            async def fetch(self, **params: Any) -> dict[str, Any]:
                return {"params": params}

            def to_form_schema(self, raw: dict[str, Any]) -> FormSchema:
                return FormSchema(form_id="t-1", title="t", sections=[])

        svc = Concrete()
        raw = await svc.fetch(formid=1, orgid=2)
        assert raw == {"params": {"formid": 1, "orgid": 2}}
        form = svc.to_form_schema(raw)
        assert form.form_id == "t-1"
```

---

## Completion Note

Implemented as specified. Created:
- `packages/parrot-formdesigner/src/parrot_formdesigner/tools/services/__init__.py` — empty stub with docstring.
- `packages/parrot-formdesigner/src/parrot_formdesigner/tools/services/abstract.py` — `AbstractFormService(ABC)` with `fetch(**params)` (async) and `to_form_schema(raw)` (sync) abstract methods.
- `packages/parrot-formdesigner/tests/unit/test_abstract_form_service.py` — 4 tests all passing.

All acceptance criteria met. Tests pass: 4/4.
