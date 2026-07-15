---
type: Concept
title: parse_contact_data()
id: func:parrot_tools.interfaces.workday.parsers.worker_parsers.parse_contact_data
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Parse the contact information (email, address, phone) of the worker.
---

# parse_contact_data

```python
def parse_contact_data(worker_data: Dict[str, Any]) -> Dict[str, Any]
```

Parse the contact information (email, address, phone) of the worker.
Prioritizes personal addresses over business addresses.
