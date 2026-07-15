---
type: Wiki Entity
title: ToolNodeDefinition
id: class:parrot.models.crew_definition.ToolNodeDefinition
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Definition of a deterministic tool-execution node in a crew.
---

# ToolNodeDefinition

Defined in [`parrot.models.crew_definition`](../summaries/mod:parrot.models.crew_definition.md).

```python
class ToolNodeDefinition(BaseModel)
```

Definition of a deterministic tool-execution node in a crew.

A tool node is NOT an LLM agent: it invokes the referenced tool
directly with the declared ``args``/``kwargs`` (pass-through) and wraps
the result as an agent-execution result, so it participates in every
crew execution mode without spending LLM tokens.

String values inside ``args``/``kwargs`` may contain template
placeholders resolved deterministically at execution time:

- ``{input}`` — the node's input (previous output / initial task).
- ``{nodes.<node_name>.output}`` — a previously completed node's output.

Avoid dots in ``node_id``: they are ambiguous inside the
``{nodes.<node_name>.output}`` placeholder syntax.

Attributes:
    node_id: Unique identifier for the tool node within this crew.
    tool: Tool name/slug resolved via the tool resolver.
    name: Human-readable display name (defaults to ``node_id``).
    description: Optional description of the node's purpose.
    args: Positional arguments passed through to the tool.
    kwargs: Keyword arguments passed through to the tool.
