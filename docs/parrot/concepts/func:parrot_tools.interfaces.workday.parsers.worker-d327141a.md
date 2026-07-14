---
type: Concept
title: parse_benefits_and_roles()
id: func:parrot_tools.interfaces.workday.parsers.worker_parsers.parse_benefits_and_roles
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Parse benefit enrollments, roles, and worker documents.
---

# parse_benefits_and_roles

```python
def parse_benefits_and_roles(worker_data: Dict[str, Any], worker_id: Optional[str]=None, document_directory: Optional[str]=None) -> Dict[str, Any]
```

Parse benefit enrollments, roles, and worker documents.

Args:
    worker_data: Worker data dictionary
    worker_id: Worker/Employee ID for organizing saved files
    document_directory: Base directory to save document files

Returns:
    Dictionary with benefits, roles, and document information
