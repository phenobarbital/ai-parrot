---
type: Concept
title: parse_qualifications_data()
id: func:parrot_tools.interfaces.workday.parsers.job_posting_parsers.parse_qualifications_data
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Parse Qualifications data (competencies).
---

# parse_qualifications_data

```python
def parse_qualifications_data(qualifications_data: Union[List, Dict, None]) -> Dict[str, List[str]]
```

Parse Qualifications data (competencies).

Args:
    qualifications_data: Qualifications data from the response

Returns:
    Dictionary with lists of competencies
