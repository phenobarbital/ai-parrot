---
type: Wiki Entity
title: RequestContext
id: class:parrot.utils.helpers.RequestContext
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: RequestContext.
---

# RequestContext

Defined in [`parrot.utils.helpers`](../summaries/mod:parrot.utils.helpers.md).

```python
class RequestContext
```

RequestContext.

This class is a context manager for handling request-specific data.
It is designed to be used with the `async with` statement to ensure
proper setup and teardown of resources.

Attributes:
    request (web.Request): The incoming web request.
    app (Optional[Any]): An optional application context.
    llm (Optional[Any]): An optional language model instance.
    kwargs (dict): Additional keyword arguments for customization.
