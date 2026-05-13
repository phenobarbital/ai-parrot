---
id: F006
title: Existing registry / strategy patterns in parrot-formdesigner
source_queries: [Q005, Q008]
---

The package already has two precedent patterns for plug-and-play
sub-components. The new `services/` sub-package should follow the same
convention rather than inventing a third.

## Pattern A — module-level dict + register_*() function

`packages/parrot-formdesigner/src/parrot_formdesigner/controls/registry.py`
(lines 67-113):

```python
_REGISTRY: dict[str, FieldControlMetadata] = {}

def register_field_control(field_type, *, label, description, …) -> None:
    type_id = field_type.value if isinstance(field_type, FieldType) else field_type
    if type_id in _REGISTRY:
        logger.warning("register_field_control: overwriting existing entry for type=%s", type_id)
    _REGISTRY[type_id] = FieldControlMetadata(…)
```

Used by `controls/builtin.py` which imports and calls
`register_field_control(...)` for every built-in control at import time.

## Pattern B — module-level register function

`packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py` line 59:
`def register_renderer(format_key: str, renderer: AbstractFormRenderer) -> None`.

## Recommendation

Use **Pattern A** for `parrot_formdesigner.tools.services.registry`:

```python
_SERVICE_REGISTRY: dict[str, type[AbstractFormService]] = {}

def register_form_service(name: str, service_cls: type[AbstractFormService]) -> None:
    ...

def get_form_service(name: str) -> type[AbstractFormService]:
    ...
```

And register built-ins at import time, e.g. in
`parrot_formdesigner/tools/services/__init__.py`:

```python
from .networkninja import NetworkninjaFormService
register_form_service("networkninja", NetworkninjaFormService)
```

This avoids `importlib.import_module` runtime resolution (no usage of that
idiom anywhere in the package was found) and matches the codebase's existing
convention. It also makes 3rd-party services pluggable: any caller can
`register_form_service("my_db", MyDBFormService)` before the tool runs.
