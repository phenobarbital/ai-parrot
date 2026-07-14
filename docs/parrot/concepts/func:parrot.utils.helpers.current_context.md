---
type: Concept
title: current_context()
id: func:parrot.utils.helpers.current_context
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Return the RequestContext bound to the current asyncio task, if any.
---

# current_context

```python
def current_context() -> Optional[RequestContext]
```

Return the RequestContext bound to the current asyncio task, if any.

Returns:
    The active RequestContext if called within an AbstractBot.session()
    block, or None if no session is active for the current asyncio task.
