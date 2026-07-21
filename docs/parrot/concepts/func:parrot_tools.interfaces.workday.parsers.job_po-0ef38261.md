---
type: Concept
title: parse_job_posting_sites()
id: func:parrot_tools.interfaces.workday.parsers.job_posting_parsers.parse_job_posting_sites
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Parse Job Posting Sites data.
---

# parse_job_posting_sites

```python
def parse_job_posting_sites(sites_data: Union[List, Dict, None]) -> Dict[str, List[str]]
```

Parse Job Posting Sites data.

Args:
    sites_data: Job Posting Sites data from response

Returns:
    Dictionary with lists of site names and IDs
