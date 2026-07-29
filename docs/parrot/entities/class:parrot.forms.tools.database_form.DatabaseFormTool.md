---
type: Wiki Entity
title: DatabaseFormTool
id: class:parrot.forms.tools.database_form.DatabaseFormTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Load a form definition from PostgreSQL into a FormSchema.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# DatabaseFormTool

Defined in [`parrot.forms.tools.database_form`](../summaries/mod:parrot.forms.tools.database_form.md).

```python
class DatabaseFormTool(AbstractTool)
```

Load a form definition from PostgreSQL into a FormSchema.

Queries ``networkninja.forms`` + ``networkninja.form_metadata`` by
``formid`` and ``orgid``, translates field types, conditional logic, and
validation rules into a ``FormSchema``, registers it in the
``FormRegistry``, and returns it in ``ToolResult.metadata["form"]``.

Example:
    tool = DatabaseFormTool(registry=registry)
    result = await tool.execute(formid=42, orgid=7)
    form_schema = FormSchema(**result.metadata["form"])
