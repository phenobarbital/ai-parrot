---
type: Concept
title: project_trace_context()
id: func:parrot.tools.executors.abstract.project_trace_context
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Project a TraceContext into a JSON-safe dict.
---

# project_trace_context

```python
def project_trace_context(tc: 'TraceContext | None') -> Optional[Dict[str, Any]]
```

Project a TraceContext into a JSON-safe dict.

Returns ``None`` when *tc* is ``None`` so envelopes stay compact.
