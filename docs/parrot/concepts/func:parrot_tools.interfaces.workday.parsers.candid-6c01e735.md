---
type: Concept
title: parse_candidate_experience_data()
id: func:parrot_tools.interfaces.workday.parsers.candidate_parsers.parse_candidate_experience_data
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Parse Experience data for Candidate.
---

# parse_candidate_experience_data

```python
def parse_candidate_experience_data(candidate_data: Dict[str, Any]) -> Dict[str, Any]
```

Parse Experience data for Candidate.
In Get_Candidates, experience comes from Job_Application_Data -> Resume_Data -> Experience_Data
