---
type: Concept
title: validate_and_truncate_physical_indices()
id: func:parrot.knowledge.pageindex.utils.validate_and_truncate_physical_indices
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Remove physical indices exceeding actual document length.
---

# validate_and_truncate_physical_indices

```python
def validate_and_truncate_physical_indices(toc_with_page_number: list[dict], page_list_length: int, start_index: int=1) -> list[dict]
```

Remove physical indices exceeding actual document length.
