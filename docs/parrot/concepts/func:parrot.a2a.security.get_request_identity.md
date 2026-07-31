---
type: Concept
title: get_request_identity()
id: func:parrot.a2a.security.get_request_identity
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Get the authenticated identity from a request.
---

# get_request_identity

```python
def get_request_identity(request: web.Request) -> Optional[CallerIdentity]
```

Get the authenticated identity from a request.
