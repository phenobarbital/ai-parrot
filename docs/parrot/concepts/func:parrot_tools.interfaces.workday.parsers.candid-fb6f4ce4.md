---
type: Concept
title: parse_candidate_reference()
id: func:parrot_tools.interfaces.workday.parsers.candidate_parsers.parse_candidate_reference
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Parse Candidate Reference data and related references (Pre-Hire, Worker).
---

# parse_candidate_reference

```python
def parse_candidate_reference(candidate_raw: Dict[str, Any], candidate_data: Dict[str, Any]=None) -> Dict[str, Any]
```

Parse Candidate Reference data and related references (Pre-Hire, Worker).

Args:
    candidate_raw: The top-level Candidate dict (contains Candidate_Reference)
    candidate_data: The Candidate_Data dict (contains Pre-Hire_Reference and Worker_Reference)

Note: In the XML structure:
    - Candidate_Reference is at the Candidate level
    - Pre-Hire_Reference and Worker_Reference are inside Candidate_Data
