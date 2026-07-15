---
type: Concept
title: parse_worker_reference()
id: func:parrot_tools.interfaces.workday.parsers.worker_parsers.parse_worker_reference
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Extracts the main Worker_Reference WID from a Worker SOAP response.
---

# parse_worker_reference

```python
def parse_worker_reference(worker_response: Dict[str, Any]) -> Dict[str, Any]
```

Extracts the main Worker_Reference WID from a Worker SOAP response.
Ignores nested references in roles, managers, or organizations.
