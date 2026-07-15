---
type: Wiki Summary
title: parrot.tools.decorators
id: mod:parrot.tools.decorators
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Module parrot.tools.decorators
relates_to:
- concept: func:parrot.tools.decorators.requires_permission
  rel: defines
- concept: func:parrot.tools.decorators.tool
  rel: defines
- concept: func:parrot.tools.decorators.tool_schema
  rel: defines
---

# `parrot.tools.decorators`

## Functions

- `def requires_permission(*permissions: str)` — Annotate a toolkit method or AbstractTool class with required permissions.
- `def tool_schema(schema: Type[BaseModel], description: Optional[str]=None)` — Decorator to specify a custom argument schema for a toolkit method.
- `def tool(_func: Optional[Callable]=None, *, name: Optional[str]=None, description: Optional[str]=None, schema: Optional[Dict[str, Any]]=None, auto_register: bool=False, requires_confirmation: bool=False, confirm_template: Optional[str]=None, confirm_window_seconds: int=0, allow_edit: bool=False)` — Decorator to mark a function as a tool with automatic schema generation.
