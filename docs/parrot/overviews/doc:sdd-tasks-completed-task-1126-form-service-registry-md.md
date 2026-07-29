---
type: Wiki Overview
title: 'TASK-1126: Form-Service Registry'
id: doc:sdd-tasks-completed-task-1126-form-service-registry-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements §3 Module 2 of the spec. Adds the module-level registry that maps
---

# TASK-1126: Form-Service Registry

**Feature**: FEAT-166 — Multi-Origin FormDesigner — Pluggable AbstractFormService
**Spec**: `sdd/specs/multi-origin-formdesigner.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1125
**Assigned-to**: unassigned

---

## Context

Implements §3 Module 2 of the spec. Adds the module-level registry that maps
service names to `AbstractFormService` subclasses, plus `register_form_service`,
`get_form_service`, and `list_form_services` functions. Mirrors the existing
precedent at `parrot_formdesigner/controls/registry.py:67-113` exactly — no
decorators, no `importlib.import_module`, no `entry_points`.

---

## Scope

- Create `packages/parrot-formdesigner/src/parrot_formdesigner/tools/services/registry.py`
  with:
  - Module-level `_SERVICE_REGISTRY: dict[str, type[AbstractFormService]] = {}`.
  - `register_form_service(name: str, service_cls: type[AbstractFormService]) -> None`
    — idempotent; on overwrite, log a warning matching the wording style of
    `controls/registry.py:101` (use `logger.warning("register_form_service: overwriting existing entry for name=%s", name)`).
  - `get_form_service(name: str) -> type[AbstractFormService]` — raises `KeyError`
    with a helpful message listing registered names.
  - `list_form_services() -> list[str]` — returns the registered names in
    insertion order.
- Write unit tests covering: distinct names coexist; re-registering same name
  overwrites and emits a warning log line; `get_form_service` returns the
  registered class; unknown name raises `KeyError`; `list_form_services` returns
  insertion order.

**NOT in scope**: registering the built-in `"networkninja"` service (that
happens in TASK-1128); the service implementation (TASK-1127); the dispatcher
(TASK-1129).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/tools/services/registry.py` | CREATE | Module-level registry + register/get/list helpers |
| `packages/parrot-formdesigner/tests/unit/test_form_service_registry.py` | CREATE | Unit tests for registry behavior |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Relative imports from the new module
from .abstract import AbstractFormService  # created by TASK-1125

# For the test file
from parrot_formdesigner.tools.services.registry import (
    register_form_service,
    get_form_service,
    list_form_services,
)
from parrot_formdesigner.tools.services.abstract import AbstractFormService
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/controls/registry.py:67-113
# REFERENCE PATTERN — mirror this exactly

_REGISTRY: dict[str, FieldControlMetadata] = {}                # line 67

def register_field_control(field_type, *, label, …) -> None:   # line 70
    type_id = field_type.value if isinstance(field_type, FieldType) else field_type
    if type_id in _REGISTRY:
        logger.warning(
            "register_field_control: overwriting existing entry for type=%s",
            type_id,
        )
    _REGISTRY[type_id] = FieldControlMetadata(…)
```

### Does NOT Exist

- ~~`@register_form_service` decorator~~ — use plain function call, matching `register_field_control` precedent.
- ~~`from importlib import import_module` for resolution~~ — no precedent in this package. Plain dict lookup.
- ~~`entry_points` / `pluggy` integration~~ — out of scope.
- ~~`get_form_service` returning `None` on miss~~ — raise `KeyError` (more explicit).

---

## Implementation Notes

### Pattern to Follow

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/tools/services/registry.py
"""Form-service registry — name → AbstractFormService subclass.

Mirrors parrot_formdesigner/controls/registry.py:67-113. Module-level dict
preserves registration order for stable iteration.
"""

from __future__ import annotations

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

    Args:
        name: Identifier exposed to DatabaseFormInput.service.
        service_cls: AbstractFormService subclass.
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

### Key Constraints

- The module-level dict is a singleton; tests must clean up after themselves
  (use a fixture that snapshots and restores the registry).
- Logger name = `__name__` per project convention.
- No I/O; this module is pure data.

### References in Codebase

- `packages/parrot-formdesigner/src/parrot_formdesigner/controls/registry.py:67-113` — verbatim pattern source.

---

## Acceptance Criteria

- [ ] `parrot_formdesigner/tools/services/registry.py` exists with the three public functions.
- [ ] Re-registering the same name logs a warning whose message contains `"overwriting existing entry for name="`.
- [ ] `get_form_service("nonexistent")` raises `KeyError` whose message lists the registered names.
- [ ] `list_form_services()` returns names in insertion order.
- [ ] `pytest packages/parrot-formdesigner/tests/unit/test_form_service_registry.py -v` passes.
- [ ] `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/tools/services/registry.py` clean.

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_form_service_registry.py
import logging
import pytest

from parrot_formdesigner.tools.services.registry import (
    register_form_service,
    get_form_service,
    list_form_services,
    _SERVICE_REGISTRY,
)
from parrot_formdesigner.tools.services.abstract import AbstractFormService
from parrot_formdesigner.core.schema import FormSchema


class _StubService(AbstractFormService):
    async def fetch(self, **params):
        return {}

    def to_form_schema(self, raw):
        return FormSchema(form_id="x", title="x", sections=[])


class _OtherService(AbstractFormService):
    async def fetch(self, **params):
        return {}

    def to_form_schema(self, raw):
        return FormSchema(form_id="y", title="y", sections=[])


@pytest.fixture(autouse=True)
def clean_registry():
    """Snapshot/restore the module-level registry around each test."""
    snapshot = dict(_SERVICE_REGISTRY)
    _SERVICE_REGISTRY.clear()
    yield
    _SERVICE_REGISTRY.clear()
    _SERVICE_REGISTRY.update(snapshot)


class TestRegistry:
    def test_register_and_get(self):
        register_form_service("stub", _StubService)
        assert get_form_service("stub") is _StubService

    def test_multiple_services_coexist(self):
        register_form_service("a", _StubService)
        register_form_service("b", _OtherService)
        assert get_form_service("a") is _StubService
        assert get_form_service("b") is _OtherService

    def test_overwrite_emits_warning(self, caplog):
        register_form_service("dup", _StubService)
        with caplog.at_level(logging.WARNING):
            register_form_service("dup", _OtherService)
        assert any(
            "overwriting existing entry for name=dup" in rec.message
            for rec in caplog.records
        )
        assert get_form_service("dup") is _OtherService

    def test_get_unknown_raises_keyerror_with_listing(self):
        register_form_service("known", _StubService)
        with pytest.raises(KeyError) as exc:
            get_form_service("missing")
        assert "missing" in str(exc.value)
        assert "known" in str(exc.value)

    def test_list_form_services_returns_insertion_order(self):
        register_form_service("first", _StubService)
        register_form_service("second", _OtherService)
        register_form_service("third", _StubService)
        assert list_form_services() == ["first", "second", "third"]
```

---

## Completion Note

Implemented as specified. Created:
- `packages/parrot-formdesigner/src/parrot_formdesigner/tools/services/registry.py` — module-level `_SERVICE_REGISTRY` dict + `register_form_service`, `get_form_service`, `list_form_services` verbatim from the controls/registry.py pattern.
- `packages/parrot-formdesigner/tests/unit/test_form_service_registry.py` — 5 tests all passing.

All acceptance criteria met. Tests pass: 5/5.
