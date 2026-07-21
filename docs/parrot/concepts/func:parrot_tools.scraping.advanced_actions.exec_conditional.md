---
type: Concept
title: exec_conditional()
id: func:parrot_tools.scraping.advanced_actions.exec_conditional
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Execute a :class:`Conditional` action.
---

# exec_conditional

```python
async def exec_conditional(driver: AbstractDriver, cond_action: Conditional, dispatch_step_fn: DispatchStepFn, base_url: str='', timeout: int=10) -> bool
```

Execute a :class:`Conditional` action.

Evaluates the configured condition against the page and dispatches the
``actions_if_true`` or ``actions_if_false`` branch accordingly.

Supported ``condition_type`` values: ``exists``, ``not_exists``,
``text_contains``, ``text_equals``, ``attribute_equals`` (the latter
expects ``expected_value`` formatted as ``"attr=value"``).

Args:
    driver: Browser driver implementing :class:`AbstractDriver`.
    cond_action: The :class:`Conditional` model to evaluate.
    dispatch_step_fn: Callback dispatching a single step.
    base_url: Base URL forwarded to each dispatched step.
    timeout: Default per-step timeout in seconds.

Returns:
    ``True`` when the selected branch executed without failures (or there
    was no branch to run); ``False`` on an unknown condition type or when
    a dispatched sub-action failed.
