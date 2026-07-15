---
type: Wiki Entity
title: DatabaseFormTool
id: class:parrot_formdesigner.tools.database_form.DatabaseFormTool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Load a form definition from a configured form-source service into a FormSchema.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# DatabaseFormTool

Defined in [`parrot_formdesigner.tools.database_form`](../summaries/mod:parrot_formdesigner.tools.database_form.md).

```python
class DatabaseFormTool(AbstractTool)
```

Load a form definition from a configured form-source service into a FormSchema.

Resolves the requested service by name via the form-service registry,
runs ``fetch()`` to retrieve raw data, maps it via ``to_form_schema()``,
registers the result in the ``FormRegistry``, and returns it in
``ToolResult.metadata["form"]``.

Example:
    tool = DatabaseFormTool(registry=registry)
    result = await tool.execute(formid=42, orgid=7)
    form_schema = FormSchema(**result.metadata["form"])
