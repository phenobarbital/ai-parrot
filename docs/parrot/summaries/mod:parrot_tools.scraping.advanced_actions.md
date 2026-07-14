---
type: Wiki Summary
title: parrot_tools.scraping.advanced_actions
id: mod:parrot_tools.scraping.advanced_actions
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Advanced action dispatch — Loop, Conditional, and template substitution.
relates_to:
- concept: func:parrot_tools.scraping.advanced_actions.exec_conditional
  rel: defines
- concept: func:parrot_tools.scraping.advanced_actions.exec_loop
  rel: defines
- concept: func:parrot_tools.scraping.advanced_actions.substitute_template_vars
  rel: defines
- concept: mod:parrot_tools.scraping.drivers.abstract
  rel: references
- concept: mod:parrot_tools.scraping.models
  rel: references
---

# `parrot_tools.scraping.advanced_actions`

Advanced action dispatch — Loop, Conditional, and template substitution.

Stateless async helpers extracted from the legacy ``WebScrapingTool`` so the
modern executor, the legacy tool, and the ``FlowExecutor`` can all share a
single implementation of Loop / Conditional dispatch (FEAT-222, Module 3).

The functions accept an :class:`AbstractDriver` plus a ``dispatch_step_fn``
callback for recursive step execution.  This decouples them from any specific
execution context (executor, tool, or flow engine).

The ``dispatch_step_fn`` callback signature mirrors
``executor._dispatch_step``::

    async def dispatch_step_fn(
        driver: AbstractDriver,
        step: ScrapingStep,
        url: str,
        timeout: int,
        step_extracted: Dict[str, Any],
    ) -> bool: ...

## Functions

- `def substitute_template_vars(value: Any, index: int, start_index: int=0, values: Optional[List[Any]]=None, value_name: str='value', current_value: Any=None) -> Any` — Recursively substitute loop template variables in *value*.
- `async def exec_loop(driver: AbstractDriver, loop_action: Loop, dispatch_step_fn: DispatchStepFn, base_url: str='', timeout: int=10) -> bool` — Execute a :class:`Loop` action.
- `async def exec_conditional(driver: AbstractDriver, cond_action: Conditional, dispatch_step_fn: DispatchStepFn, base_url: str='', timeout: int=10) -> bool` — Execute a :class:`Conditional` action.
