---
type: Concept
title: parse_candidate_recruitment_data()
id: func:parrot_tools.interfaces.workday.parsers.candidate_parsers.parse_candidate_recruitment_data
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Parse Recruitment-specific data for Candidate (campos "planos" a partir de
  la
---

# parse_candidate_recruitment_data

```python
def parse_candidate_recruitment_data(candidate_data: Dict[str, Any]) -> Dict[str, Any]
```

Parse Recruitment-specific data for Candidate (campos "planos" a partir de la
postulación más reciente). Soporta Candidate_Job_Applied_To_Data y Job_Applied_To_Data.
