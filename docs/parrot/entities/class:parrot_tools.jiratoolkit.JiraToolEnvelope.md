---
type: Wiki Entity
title: JiraToolEnvelope
id: class:parrot_tools.jiratoolkit.JiraToolEnvelope
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Uniform return shape for all JiraToolkit read methods.
---

# JiraToolEnvelope

Defined in [`parrot_tools.jiratoolkit`](../summaries/mod:parrot_tools.jiratoolkit.md).

```python
class JiraToolEnvelope(TypedDict)
```

Uniform return shape for all JiraToolkit read methods.

Attributes:
    status: One of ``"ok"``, ``"empty"``, ``"not_found"``, or ``"error"``.
    data: The native success payload (issue dict, issues list wrapper, user
        list, etc.) on ``"ok"``/``"empty"``; ``None`` on ``"not_found"``/``"error"``.
    message: Human-readable detail; empty string on success.
    query: The key, JQL, or search string used in the call.
