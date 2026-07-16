---
type: Concept
title: tool()
id: func:parrot.tools.decorators.tool
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Decorator to mark a function as a tool with automatic schema generation.
---

# tool

```python
def tool(_func: Optional[Callable]=None, *, name: Optional[str]=None, description: Optional[str]=None, schema: Optional[Dict[str, Any]]=None, auto_register: bool=False, requires_confirmation: bool=False, confirm_template: Optional[str]=None, confirm_window_seconds: int=0, allow_edit: bool=False)
```

Decorator to mark a function as a tool with automatic schema generation.

Automatically extracts:
- Name from function name (or use custom name)
- Description from docstring (or use custom description)
- Input schema from type hints (or use custom schema)

Args:
    name: Optional custom tool name (defaults to function name)
    description: Optional custom description (defaults to docstring)
    schema: Optional custom input schema (auto-generated from type hints if not provided)
    auto_register: If True, automatically register with active client/bot
    requires_confirmation: If True, the tool requires HITL confirmation before
        execution (via ConfirmationGuard in ToolManager — FEAT-235).
    confirm_template: Optional Python format string for the briefing shown to the
        human.  Placeholders: ``{tool}`` (tool name), ``{params}`` (all params as
        ``k=v``), plus any individual parameter name.  Falls back to a raw
        ``tool with: k=v`` listing when None or on a template error.
    confirm_window_seconds: Seconds during which an identical call (same tool,
        same args_hash) is skipped without re-asking.  ``0`` (default) means
        always re-ask — the safe per-call default.
    allow_edit: When True, the human is offered a FORM interaction to edit the
        parameter values before approving.  Edited values are re-validated against
        the tool's ``args_schema``.

Usage:
    @tool
    def get_weather(location: str) -> str:
        '''Get weather for a location.'''
        return f"Weather in {location}"

    @tool()
    def get_weather(location: str) -> str:
        '''Get weather for a location.'''
        return f"Weather in {location}"

    @tool(name="custom_name", description="Custom description")
    def my_function(param: int) -> str:
        return str(param)

    @tool(requires_confirmation=True, confirm_template="Check in {employee_id}?",
          confirm_window_seconds=60, allow_edit=True)
    def workday_checkin(employee_id: int, time: str) -> str:
        '''Register a check-in.'''
        return "ok"
