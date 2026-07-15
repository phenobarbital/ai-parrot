---
type: Wiki Summary
title: parrot.tools.dataset_manager.computed
id: mod:parrot.tools.dataset_manager.computed
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Computed Columns for DatasetManager.
relates_to:
- concept: class:parrot.tools.dataset_manager.computed.ComputedColumnDef
  rel: defines
- concept: func:parrot.tools.dataset_manager.computed.get_computed_function
  rel: defines
- concept: func:parrot.tools.dataset_manager.computed.list_computed_functions
  rel: defines
- concept: func:parrot.tools.dataset_manager.computed.register_computed_function
  rel: defines
---

# `parrot.tools.dataset_manager.computed`

Computed Columns for DatasetManager.

Provides:
- ``ComputedColumnDef``: Pydantic model describing a single computed column.
- ``COMPUTED_FUNCTIONS``: Global registry mapping function names to callables.
- Public API: ``register_computed_function``, ``get_computed_function``,
  ``list_computed_functions``.
- Built-in fallback functions that work without QuerySource installed:
  ``_builtin_math_operation``, ``_builtin_concatenate``.

All functions in the registry follow the QuerySource pattern::

    def fn(df: pd.DataFrame, field: str, columns: list, **kwargs) -> pd.DataFrame:
        ...

The function must return the DataFrame with the new column ``field`` added.

QuerySource functions are loaded lazily on first call to ``get_computed_function``
or ``list_computed_functions``; the built-ins are always available.

## Classes

- **`ComputedColumnDef(BaseModel)`** — Definition of a computed column applied post-materialization.

## Functions

- `def register_computed_function(name: str, fn: Callable) -> None` — Register a custom function in the computed-columns registry.
- `def get_computed_function(name: str) -> Optional[Callable]` — Look up a function by name from the registry.
- `def list_computed_functions() -> List[str]` — Return a sorted list of all registered function names.
