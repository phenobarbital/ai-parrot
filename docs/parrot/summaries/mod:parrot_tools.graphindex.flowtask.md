---
type: Wiki Summary
title: parrot_tools.graphindex.flowtask
id: mod:parrot_tools.graphindex.flowtask
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Flowtask component wrapper for the GraphIndex pipeline.
relates_to:
- concept: class:parrot_tools.graphindex.flowtask.GraphIndexComponent
  rel: defines
- concept: mod:parrot.knowledge.graphindex
  rel: references
- concept: mod:parrot.knowledge.graphindex.embed
  rel: references
- concept: mod:parrot.knowledge.graphindex.persist
  rel: references
- concept: mod:parrot.knowledge.graphindex.schema
  rel: references
- concept: mod:parrot.knowledge.ontology.schema
  rel: references
---

# `parrot_tools.graphindex.flowtask`

Flowtask component wrapper for the GraphIndex pipeline.

Bridges the Flowtask execution model to ``GraphIndexBuilder``, allowing
knowledge graph indexing to run as a Flowtask pipeline step.

Usage:
    ```python
    config = {
        "tenant_id": "my-tenant",
        "code_paths": ["/src"],
        "skill_paths": ["/skills"],
        "output_dir": "/reports",
    }
    async with GraphIndexComponent(config) as comp:
        result = await comp.run()
    ```

## Classes

- **`GraphIndexComponent`** — Flowtask component wrapper for the GraphIndex pipeline.
