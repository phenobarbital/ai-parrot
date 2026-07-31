---
type: Concept
title: substitute_template_vars()
id: func:parrot_tools.scraping.advanced_actions.substitute_template_vars
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Recursively substitute loop template variables in *value*.
---

# substitute_template_vars

```python
def substitute_template_vars(value: Any, index: int, start_index: int=0, values: Optional[List[Any]]=None, value_name: str='value', current_value: Any=None) -> Any
```

Recursively substitute loop template variables in *value*.

Supported tokens (inside ``{...}``):
    - ``{i}``, ``{index}``, ``{iteration}`` — the current iteration,
      offset by *start_index*.
    - Arithmetic expressions — ``{i+1}``, ``{i-1}``, ``{i*2}``,
      ``{index+1}`` — evaluated by a strict arithmetic-only AST parser
      (:func:`_safe_arithmetic`), never a general ``eval``.
    - ``{value}`` (and ``{<value_name>}``) — the current value when
      iterating over a *values* list.

Non-string scalars (int, bool, None) pass through unchanged; dicts and
lists are walked recursively.

Args:
    value: The value to substitute (str, dict, list, or scalar).
    index: Current iteration counter (0-based).
    start_index: Offset applied to the exposed index (default 0).
    values: Optional list being iterated over; ``values[index]`` becomes
        the current value.
    value_name: Variable name exposed for the current value (default
        ``"value"``).
    current_value: Explicit current value. When given it takes precedence
        over ``values[index]`` (lets callers pass a single value without
        allocating a positional list).

Returns:
    The value with all template variables substituted.
