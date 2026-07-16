---
type: Concept
title: parse_worktags_data()
id: func:parrot_tools.interfaces.workday.parsers.cost_center_parsers.parse_worktags_data
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Parse Worktags data.
---

# parse_worktags_data

```python
def parse_worktags_data(worktags_data: Union[List, Dict, None]) -> List[str]
```

Parse Worktags data.

Args:
    worktags_data: Worktags data from the response
    
Returns:
    List of worktag IDs
