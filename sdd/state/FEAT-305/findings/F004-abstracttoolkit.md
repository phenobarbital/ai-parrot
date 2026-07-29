---
id: F004
query_id: Q004+Q008
type: read
intent: AbstractToolkit contract — how parrot turns methods into tools
executed_at: 2026-07-13T22:42:00Z
parent_id: null
depth: 0
---

# F004 — AbstractToolkit / ToolkitTool

## Summary

`AbstractToolkit` (parrot/tools/toolkit.py) auto-converts every public async
method into a `ToolkitTool` (an `AbstractTool` wrapper): name = method name,
description = docstring, args schema generated from type hints
(`_generate_args_schema_from_method`). Toolkit-level knobs: `exclude_tools`,
`tool_prefix` + `prefix_separator`, `confirming_tools` (HITL), and
`credential_provider` (CredentialBroker seam, FEAT-264). Lifecycle hooks
`_pre_execute` / `_prepare_kwargs` / `_post_execute` wrap each call.
`AbstractTool` lives in parrot/tools/abstract.py (905 lines) with
`AbstractToolArgsSchema` for Pydantic arg models.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/toolkit.py`
  lines: 207-296
  symbol: `AbstractToolkit`
  excerpt: |
    class AbstractToolkit(ABC):
        input_class: Optional[Type[BaseModel]] = None
        exclude_tools: tuple[str, ...] = ()
        tool_prefix: Optional[str] = None
        confirming_tools: frozenset = frozenset()
        credential_provider: Optional[str] = None

- path: `packages/ai-parrot/src/parrot/tools/toolkit.py`
  lines: 32-69, 150-204
  symbol: `ToolkitTool`
  excerpt: |
    # wraps a bound coroutine; _execute runs toolkit._pre_execute,
    # _prepare_kwargs, bound_method(**kwargs), toolkit._post_execute

- path: `packages/ai-parrot/src/parrot/tools/abstract.py`
  lines: 1-905
  symbol: `AbstractTool, AbstractToolArgsSchema`
  excerpt: |
    # base tool class; args_schema: Pydantic model; async _execute(**kwargs)
