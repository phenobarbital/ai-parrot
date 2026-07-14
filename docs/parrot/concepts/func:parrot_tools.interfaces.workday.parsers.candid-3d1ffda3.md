---
type: Concept
title: parse_candidate_skills_data()
id: func:parrot_tools.interfaces.workday.parsers.candidate_parsers.parse_candidate_skills_data
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Parse Skills, Competencies and Languages data for Candidate.
---

# parse_candidate_skills_data

```python
def parse_candidate_skills_data(candidate_data: Dict[str, Any]) -> Dict[str, Any]
```

Parse Skills, Competencies and Languages data for Candidate.

NOTE: Skills and Languages come from Resume_Data (inside Job_Application_Data),
NOT directly from candidate_data.
