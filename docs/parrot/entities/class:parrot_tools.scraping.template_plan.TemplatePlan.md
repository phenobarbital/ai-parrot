---
type: Wiki Entity
title: TemplatePlan
id: class:parrot_tools.scraping.template_plan.TemplatePlan
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Parameterized plan template that produces ``ScrapingPlan``s via ``bind()``.
---

# TemplatePlan

Defined in [`parrot_tools.scraping.template_plan`](../summaries/mod:parrot_tools.scraping.template_plan.md).

```python
class TemplatePlan(BaseModel)
```

Parameterized plan template that produces ``ScrapingPlan``s via ``bind()``.

Attributes:
    name: Template name (also used for the produced plan's fingerprint).
    objective_template: Objective string with ``{{param}}`` placeholders.
    url_template: Target URL with ``{{param}}`` placeholders.
    params: Declared parameters.
    steps_template: Step dicts; string values are rendered recursively.
    selectors: Optional selector dicts (rendered recursively).
    tags: Tags carried into the produced plan.
    browser_config: Optional browser configuration carried into the plan.
    version: Template version.
    source: Provenance marker (``"llm"`` by default).
    created_at: Creation timestamp.

## Methods

- `def fingerprint(self) -> str` — Template-level fingerprint derived from the template name.
- `def bind(self, **kwargs: Any) -> ScrapingPlan` — Bind parameters and produce a concrete :class:`ScrapingPlan`.
