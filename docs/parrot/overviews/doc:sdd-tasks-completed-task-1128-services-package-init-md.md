---
type: Wiki Overview
title: 'TASK-1128: Services sub-package init + self-registration'
id: doc:sdd-tasks-completed-task-1128-services-package-init-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements §3 Module 4 of the spec. Fills in the previously-empty
---

# TASK-1128: Services sub-package init + self-registration

**Feature**: FEAT-166 — Multi-Origin FormDesigner — Pluggable AbstractFormService
**Spec**: `sdd/specs/multi-origin-formdesigner.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1125, TASK-1126, TASK-1127
**Assigned-to**: unassigned

---

## Context

Implements §3 Module 4 of the spec. Fills in the previously-empty
`parrot_formdesigner/tools/services/__init__.py` with public re-exports and
the import-time registration of `"networkninja"`. This is the convention
established by `parrot_formdesigner/controls/builtin.py`, which registers
every built-in control at module load.

After this task, `import parrot_formdesigner.tools.services` is sufficient to
make `get_form_service("networkninja")` return `NetworkninjaFormService`.

---

## Scope

- Replace the empty stub in
  `packages/parrot-formdesigner/src/parrot_formdesigner/tools/services/__init__.py`
  with public re-exports:
  - `AbstractFormService`
  - `NetworkninjaFormService`
  - `register_form_service`, `get_form_service`, `list_form_services`
- Add a module-load-time call: `register_form_service("networkninja", NetworkninjaFormService)`.
- Add a docstring at the top of `__init__.py` explicitly distinguishing this
  sub-package from the package-level `parrot_formdesigner.services/` (avoid the
  name-collision foot-gun).
- Write a unit test that imports the sub-package and asserts
  `get_form_service("networkninja") is NetworkninjaFormService`.

**NOT in scope**: any changes to `database_form.py` (TASK-1129); test
relocation (TASK-1130).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/tools/services/__init__.py` | MODIFY | Replace stub with public exports + self-registration |
| `packages/parrot-formdesigner/tests/unit/test_form_services_package.py` | CREATE | Verify sub-package self-registers "networkninja" at import time |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Inside __init__.py
from .abstract import AbstractFormService                  # created by TASK-1125
from .registry import (                                    # created by TASK-1126
    register_form_service,
    get_form_service,
    list_form_services,
)
from .networkninja import NetworkninjaFormService          # created by TASK-1127

# For the test
from parrot_formdesigner.tools.services import (
    AbstractFormService,
    NetworkninjaFormService,
    register_form_service,
    get_form_service,
    list_form_services,
)
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/controls/builtin.py
# REFERENCE PATTERN — built-ins register at import time.
# Open and read the file to see how register_field_control(...) is called for each.
```

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/tools/__init__.py:current
# (the tools package init does NOT import the new sub-package automatically;
# users opt in by importing `parrot_formdesigner.tools.services` explicitly,
# which is exactly what TASK-1129's dispatcher will do.)

from .request_form import RequestFormTool
from .create_form import CreateFormTool
from .database_form import DatabaseFormTool
from .field_helpers import (
    get_form_field_schema_snippets,
    list_supported_form_field_types,
)

__all__ = [
    "RequestFormTool", "CreateFormTool", "DatabaseFormTool",
    "list_supported_form_field_types", "get_form_field_schema_snippets",
]
```

### Does NOT Exist

- ~~`parrot_formdesigner.services.AbstractFormService`~~ — the ABC is at
  `parrot_formdesigner.tools.services.AbstractFormService`. Two paths share
  the name `services` but are distinct packages.
- ~~`parrot_formdesigner.tools.AbstractFormService`~~ — must NOT re-export
  from the parent `tools/__init__.py`; users opt in by importing the nested
  sub-package.
- ~~`@form_service(name="networkninja")` decorator on the class~~ — registration
  is a plain function call in `__init__.py`, per `controls/builtin.py` precedent.

---

## Implementation Notes

### Pattern to Follow

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/tools/services/__init__.py
"""Form-source services for DatabaseFormTool.

This is **parrot_formdesigner.tools.services** (nested under tools/), NOT the
package-level parrot_formdesigner.services/ (which holds FormRegistry,
storage, cache, etc.). The two paths are distinct Python packages; they only
share the name. New form-source strategies live HERE.

Built-in services register at import time. Custom services can register via:

    from parrot_formdesigner.tools.services import register_form_service
    register_form_service("my_service", MyFormService)

before any DatabaseFormTool invocation that targets that service name.
"""

from .abstract import AbstractFormService
from .registry import (
    register_form_service,
    get_form_service,
    list_form_services,
)
from .networkninja import NetworkninjaFormService

# Built-in registrations (mirrors parrot_formdesigner/controls/builtin.py).
register_form_service("networkninja", NetworkninjaFormService)

__all__ = [
    "AbstractFormService",
    "NetworkninjaFormService",
    "register_form_service",
    "get_form_service",
    "list_form_services",
]
```

### Key Constraints

- The `register_form_service` call MUST happen at module top level (not inside
  a `try`/`except`) so any import error in `networkninja.py` fails loudly at
  import time, not silently at first use.
- Do NOT re-export anything from this sub-package via the parent
  `parrot_formdesigner.tools.__init__.py`. Keep the surface area scoped.
- The test must import `parrot_formdesigner.tools.services` (not the inner
  modules directly) to validate the side-effect of import.

### References in Codebase

- `packages/parrot-formdesigner/src/parrot_formdesigner/controls/builtin.py` — pattern source for import-time registration.
- `packages/parrot-formdesigner/src/parrot_formdesigner/controls/__init__.py` — pattern source for public re-export shape.

---

## Acceptance Criteria

- [ ] `parrot_formdesigner/tools/services/__init__.py` re-exports `AbstractFormService`, `NetworkninjaFormService`, `register_form_service`, `get_form_service`, `list_form_services`.
- [ ] `from parrot_formdesigner.tools.services import AbstractFormService, NetworkninjaFormService, get_form_service` works.
- [ ] After `import parrot_formdesigner.tools.services`, `get_form_service("networkninja")` returns `NetworkninjaFormService` (the class, not an instance).
- [ ] Docstring at the top of `__init__.py` documents the distinction with `parrot_formdesigner.services/`.
- [ ] `pytest packages/parrot-formdesigner/tests/unit/test_form_services_package.py -v` passes.
- [ ] `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/tools/services/__init__.py` clean.

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_form_services_package.py
"""Verifies the tools/services sub-package self-registers built-ins at import."""
import importlib

import pytest


def test_subpackage_exports_public_api():
    mod = importlib.import_module("parrot_formdesigner.tools.services")
    for name in [
        "AbstractFormService",
        "NetworkninjaFormService",
        "register_form_service",
        "get_form_service",
        "list_form_services",
    ]:
        assert hasattr(mod, name), f"{name} not exported"


def test_networkninja_is_registered_at_import_time():
    from parrot_formdesigner.tools.services import (
        get_form_service,
        NetworkninjaFormService,
    )
    cls = get_form_service("networkninja")
    assert cls is NetworkninjaFormService


def test_unknown_service_after_import_still_raises():
    from parrot_formdesigner.tools.services import get_form_service
    with pytest.raises(KeyError):
        get_form_service("definitely-not-registered")
```

---

## Completion Note

Implemented as specified. Modified/Created:
- `packages/parrot-formdesigner/src/parrot_formdesigner/tools/services/__init__.py` — replaced stub with full re-exports and import-time `register_form_service("networkninja", NetworkninjaFormService)` call. Added docstring distinguishing from `parrot_formdesigner.services/`.
- `packages/parrot-formdesigner/tests/unit/test_form_services_package.py` — 3 tests all passing.

All acceptance criteria met. Tests pass: 3/3.
