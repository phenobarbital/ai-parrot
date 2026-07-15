---
type: Wiki Entity
title: TemplateRegistry
id: class:parrot.outputs.templates.TemplateRegistry
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Registry of available templates.
---

# TemplateRegistry

Defined in [`parrot.outputs.templates`](../summaries/mod:parrot.outputs.templates.md).

```python
class TemplateRegistry
```

Registry of available templates.

## Methods

- `def register(self, template: ReportTemplate)` — Register a template.
- `def get(self, name: str) -> ReportTemplate` — Get a template by name.
- `def list(self) -> List[str]` — List available templates.
