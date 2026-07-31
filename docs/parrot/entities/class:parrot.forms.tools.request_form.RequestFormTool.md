---
type: Wiki Entity
title: RequestFormTool
id: class:parrot.forms.tools.request_form.RequestFormTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Platform-agnostic tool that requests a form to collect missing parameters.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# RequestFormTool

Defined in [`parrot.forms.tools.request_form`](../summaries/mod:parrot.forms.tools.request_form.md).

```python
class RequestFormTool(AbstractTool)
```

Platform-agnostic tool that requests a form to collect missing parameters.

The LLM should use this tool when it determines that:
- A tool needs to be executed but is missing required parameters
- The missing information is best collected via a structured form
- Multiple parameters need to be gathered at once

The tool generates a FormSchema using ToolExtractor and returns it in the
ToolResult metadata. Platform wrappers (Teams, Telegram, web) detect the
status="form_requested" signal and render the appropriate form UI.

Example:
    tool = RequestFormTool(tool_manager=manager)
    result = await tool.execute(
        target_tool="create_employee",
        known_values={"department": "Engineering"},
    )
    # result.status == "form_requested"
    # result.metadata["form"] == FormSchema dict
