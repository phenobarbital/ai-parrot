---
type: Wiki Entity
title: RESTTool
id: class:parrot_tools.resttool.RESTTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Base class for creating REST API tools.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# RESTTool

Defined in [`parrot_tools.resttool`](../summaries/mod:parrot_tools.resttool.md).

```python
class RESTTool(AbstractTool)
```

Base class for creating REST API tools.

This tool allows LLMs to call REST APIs with natural language instructions like:
- "please, run via GET get_batch for batch_id=xyz"
- "create a new user with POST to /users endpoint"
- "update user 123 with PUT"

The tool automatically:
- Composes URLs from base_url + endpoint
- Handles JSON inputs/outputs
- Supports all HTTP methods
- Provides retry logic via HTTPService
- Returns structured responses

Example:
    class MyAPITool(RESTTool):
        name = "my_api"
        description = "Tool for accessing MyAPI service"
        base_url = "https://api.example.com/v1"

    # Usage by LLM
    result = await tool.run(
        endpoint="users/123",
        method="GET"
    )

## Methods

- `def get_schema(self) -> Dict[str, Any]` — Get the JSON schema for this tool.
