---
type: Concept
title: dialect_hint()
id: func:parrot.tools.dataset_manager.sources.table.dialect_hint
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Return concise SQL-dialect guidance for ``driver`` (empty if unknown).
---

# dialect_hint

```python
def dialect_hint(driver: str) -> str
```

Return concise SQL-dialect guidance for ``driver`` (empty if unknown).

The driver is normalized first, so aliases like ``bq``/``postgres``/
``mariadb`` resolve to their canonical dialect hint.
