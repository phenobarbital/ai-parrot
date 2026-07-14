---
type: Concept
title: catalog_instructions()
id: func:parrot.outputs.a2ui.catalog.catalog_instructions
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Aggregate every component's embedded ``instructions`` for the LLM producer.
---

# catalog_instructions

```python
def catalog_instructions() -> str
```

Aggregate every component's embedded ``instructions`` for the LLM producer.

Returns:
    A newline-joined block of ``<name>: <instructions>`` lines, name-sorted.
