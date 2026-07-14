---
type: Wiki Entity
title: InfographicTemplateRegistry
id: class:parrot.models.infographic_templates.InfographicTemplateRegistry
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Registry of available infographic templates.
---

# InfographicTemplateRegistry

Defined in [`parrot.models.infographic_templates`](../summaries/mod:parrot.models.infographic_templates.md).

```python
class InfographicTemplateRegistry
```

Registry of available infographic templates.

Provides built-in templates and allows users to register custom ones.

## Methods

- `def register(self, template: InfographicTemplate) -> None` — Register a custom template.
- `def get(self, name: str) -> InfographicTemplate` — Get a template by name.
- `def list_templates(self) -> List[str]` — List all registered template names.
- `def list_templates_detailed(self) -> List[Dict[str, str]]` — List all templates with descriptions.
