---
type: Concept
title: parse_candidate_education_data()
id: func:parrot_tools.interfaces.workday.parsers.candidate_parsers.parse_candidate_education_data
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Parse Education data for Candidate.
---

# parse_candidate_education_data

```python
def parse_candidate_education_data(candidate_data: Dict[str, Any]) -> Dict[str, Any]
```

Parse Education data for Candidate.
In Get_Candidates, education comes from Job_Application_Data -> Resume_Data -> Education_Data
