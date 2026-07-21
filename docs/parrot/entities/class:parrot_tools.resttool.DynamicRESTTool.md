---
type: Wiki Entity
title: DynamicRESTTool
id: class:parrot_tools.resttool.DynamicRESTTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Dynamic REST tool that can be configured with custom endpoints.
relates_to:
- concept: class:parrot_tools.resttool.RESTTool
  rel: extends
---

# DynamicRESTTool

Defined in [`parrot_tools.resttool`](../summaries/mod:parrot_tools.resttool.md).

```python
class DynamicRESTTool(RESTTool)
```

Dynamic REST tool that can be configured with custom endpoints.

This allows creating REST tools without subclassing, by providing
endpoint definitions at initialization.

Example:
    tool = DynamicRESTTool(
        name="github_api",
        description="GitHub API tool",
        base_url="https://api.github.com",
        endpoints={
            "get_user": {
                "path": "users/{username}",
                "method": "GET",
                "description": "Get user information"
            },
            "create_issue": {
                "path": "repos/{owner}/{repo}/issues",
                "method": "POST",
                "description": "Create a new issue"
            }
        }
    )
