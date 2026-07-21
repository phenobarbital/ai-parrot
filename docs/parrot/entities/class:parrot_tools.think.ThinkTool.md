---
type: Wiki Entity
title: ThinkTool
id: class:parrot_tools.think.ThinkTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A metacognitive tool that forces explicit reasoning before action.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# ThinkTool

Defined in [`parrot_tools.think`](../summaries/mod:parrot_tools.think.md).

```python
class ThinkTool(AbstractTool)
```

A metacognitive tool that forces explicit reasoning before action.

This tool implements the "Thinking as a Tool" pattern, which converts
the agent's internal reasoning into an observable, recorded action.
The primary value is in the process (forcing deliberation) rather
than the output.

Use cases:
- Complex multi-step tasks requiring careful planning
- Debugging agent decision-making processes
- Improving response quality through deliberate thinking
- Auditing and understanding agent reasoning

When NOT to use:
- Simple, straightforward tasks where it adds unnecessary latency
- When using LLM's native extended_thinking (would be redundant)
- Highly structured workflows with predetermined reasoning

Attributes:
    name: Tool identifier ("think" by default)
    description: Tool description for the LLM
    args_schema: Pydantic model for input validation (ThinkInput)

Example:
    >>> think_tool = ThinkTool()
    >>> result = await think_tool.execute(
    ...     thoughts="Analyzing the CSV structure: I see columns for date, "
    ...              "amount, and category. I should parse dates first, "
    ...              "then aggregate by category for the monthly report."
    ... )
    >>> print(result.status)
    'success'
