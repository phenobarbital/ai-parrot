---
type: Concept
title: exec_loop()
id: func:parrot_tools.scraping.advanced_actions.exec_loop
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Execute a :class:`Loop` action.
---

# exec_loop

```python
async def exec_loop(driver: AbstractDriver, loop_action: Loop, dispatch_step_fn: DispatchStepFn, base_url: str='', timeout: int=10) -> bool
```

Execute a :class:`Loop` action.

Supports fixed iteration counts, iteration over a ``values`` list with
``{value}`` substitution, JavaScript condition-controlled loops,
``break_on_error``, the ``max_iterations`` safety limit, and the
``start_index`` offset.

Args:
    driver: Browser driver implementing :class:`AbstractDriver`.
    loop_action: The :class:`Loop` model to execute.
    dispatch_step_fn: Callback dispatching a single step (enables
        recursive loop-within-loop execution).
    base_url: Base URL forwarded to each dispatched step.
    timeout: Default per-step timeout in seconds.

Returns:
    ``True`` when the loop completed; ``False`` when it stopped early due
    to a failed step while ``break_on_error`` is set.
