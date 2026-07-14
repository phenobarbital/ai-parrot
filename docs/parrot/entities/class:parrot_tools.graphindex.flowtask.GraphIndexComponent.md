---
type: Wiki Entity
title: GraphIndexComponent
id: class:parrot_tools.graphindex.flowtask.GraphIndexComponent
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Flowtask component wrapper for the GraphIndex pipeline.
---

# GraphIndexComponent

Defined in [`parrot_tools.graphindex.flowtask`](../summaries/mod:parrot_tools.graphindex.flowtask.md).

```python
class GraphIndexComponent
```

Flowtask component wrapper for the GraphIndex pipeline.

Implements the async context manager protocol so it can be used
with ``async with``, consistent with the Flowtask component pattern.

Args:
    config: Component configuration dict from the Flowtask pipeline
        definition.  Recognised keys:

        - ``tenant_id`` (required): Tenant identifier.
        - ``code_paths`` (optional, list): Paths to Python source.
        - ``loader_sources`` (optional, list): Document URIs.
        - ``skill_paths`` (optional, list): Paths to SKILL.md files.
        - ``ignore_file`` (optional, str): Path to ``.graphindexignore``.
        - ``output_dir`` (optional, str): Directory for report output.
        - ``model_name`` (optional, str): Embedding model name.
        - ``embedding_dimension`` (optional, int): Embedding vector dim.

## Methods

- `async def run(self) -> dict[str, Any]` — Execute the GraphIndex build pipeline.
