---
type: Wiki Entity
title: TemplateReportRenderer
id: class:parrot.outputs.formats.template_report.TemplateReportRenderer
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Renders AI output using Jinja2 templates via the TemplateEngine.
relates_to:
- concept: class:parrot.outputs.formats.base.BaseRenderer
  rel: extends
---

# TemplateReportRenderer

Defined in [`parrot.outputs.formats.template_report`](../summaries/mod:parrot.outputs.formats.template_report.md).

```python
class TemplateReportRenderer(BaseRenderer)
```

Renders AI output using Jinja2 templates via the TemplateEngine.

Supports both file-based templates and in-memory templates via add_template().

## Methods

- `def template_engine(self) -> TemplateEngine` — Lazy initialization of TemplateEngine if not provided.
- `def add_template(self, name: str, content: str) -> None` — Add an in-memory template to the engine.
- `async def render(self, data: Any, **kwargs: Any) -> str` — Renders data using a Jinja2 template asynchronously.
