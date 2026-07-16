---
type: Wiki Entity
title: Candidate
id: class:parrot_tools.interfaces.workday.models.candidate.Candidate
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Pydantic model for a Workday Candidate record.
---

# Candidate

Defined in [`parrot_tools.interfaces.workday.models.candidate`](../summaries/mod:parrot_tools.interfaces.workday.models.candidate.md).

```python
class Candidate(BaseModel)
```

Pydantic model for a Workday Candidate record.
Based on Get_Candidates operation from Recruiting API v45.0
https://community.workday.com/sites/default/files/file-hosting/productionapi/Recruiting/v45.0/Get_Candidates.html

NOTE: Get_Candidates returns LIMITED data compared to Get_Applicants.
Many fields available in Get_Applicants are NOT available here.
