---
type: Wiki Summary
title: parrot.utils.helpers
id: mod:parrot.utils.helpers
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Module parrot.utils.helpers
relates_to:
- concept: class:parrot.utils.helpers.RequestContext
  rel: defines
- concept: func:parrot.utils.helpers.current_context
  rel: defines
---

# `parrot.utils.helpers`

## Classes

- **`RequestContext`** — RequestContext.

## Functions

- `def current_context() -> Optional[RequestContext]` — Return the RequestContext bound to the current asyncio task, if any.
