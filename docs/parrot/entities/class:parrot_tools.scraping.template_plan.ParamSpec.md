---
type: Wiki Entity
title: ParamSpec
id: class:parrot_tools.scraping.template_plan.ParamSpec
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Typed parameter definition for a :class:`TemplatePlan`.
---

# ParamSpec

Defined in [`parrot_tools.scraping.template_plan`](../summaries/mod:parrot_tools.scraping.template_plan.md).

```python
class ParamSpec(BaseModel)
```

Typed parameter definition for a :class:`TemplatePlan`.

Attributes:
    name: Parameter name, referenced as ``{{name}}`` in templates.
    type: One of ``string``, ``int``, ``date``, ``enum``, ``url``.
    required: Whether the parameter must be supplied to ``bind()``.
    default: Default value used when the parameter is omitted.
    choices: Allowed values (required when ``type == "enum"``).
    description: Human-readable description.
