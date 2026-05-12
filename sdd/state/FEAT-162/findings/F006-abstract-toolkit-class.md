---
id: F006
query_id: Q006
type: grep
intent: Locate AbstractToolkit and capture its auto-discovery rules + lifecycle exclusion list.
executed_at: 2026-05-12T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F006 — AbstractToolkit defined in `parrot/tools/toolkit.py` (NOT `parrot/tools/abstract`)

## Summary

The brainstorm claims `AbstractToolkit` lives at `parrot/tools/abstract`. That is
wrong: it is at `packages/ai-parrot/src/parrot/tools/toolkit.py:191`. The file
`parrot/tools/abstract.py` contains `AbstractTool`, `AbstractToolArgsSchema`, and
`ToolResult` — a separate module. Only one definition of `AbstractToolkit` exists
in the source tree (the `build/` copy is generated).

## Citations

- path: `packages/ai-parrot/src/parrot/tools/toolkit.py`
  lines: 191
  symbol: class AbstractToolkit(ABC)
  excerpt: |
    class AbstractToolkit(ABC):
        # Configuration
        input_class: Optional[Type[BaseModel]] = None
        return_direct: bool = False
        exclude_tools: tuple[str, ...] = ()
        tool_prefix: Optional[str] = None
        prefix_separator: str = "_"

- path: `packages/ai-parrot/src/parrot/tools/abstract.py`
  lines: 23-71
  symbol: AbstractTool, ToolResult, AbstractToolArgsSchema (NOT AbstractToolkit)
  excerpt: |
    class AbstractToolArgsSchema(BaseModel): ...
    class ToolResult(BaseModel): ...
    class AbstractTool(ABC): ...

## Notes

- The `build/` directory shadow file is build artefact — ignore.
- Brainstorm correction: `parrot.tools.abstract` exports `AbstractTool` /
  `ToolResult`, while `AbstractToolkit` lives in `parrot.tools.toolkit`.
