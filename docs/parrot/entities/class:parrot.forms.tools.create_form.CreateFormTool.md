---
type: Wiki Entity
title: CreateFormTool
id: class:parrot.forms.tools.create_form.CreateFormTool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Create a FormSchema from a natural language prompt using an LLM.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# CreateFormTool

Defined in [`parrot.forms.tools.create_form`](../summaries/mod:parrot.forms.tools.create_form.md).

```python
class CreateFormTool(AbstractTool)
```

Create a FormSchema from a natural language prompt using an LLM.

Supports:
- New form creation from a prompt
- Iterative refinement of an existing form
- Pydantic validation with up to 2 retries (error feedback to LLM)
- Circular dependency detection via FormValidator
- Optional registry persistence

Example:
    tool = CreateFormTool(client=llm_client, registry=registry)
    result = await tool.execute(prompt="Create a customer feedback form")
    form_schema = FormSchema(**result.metadata["form"])
