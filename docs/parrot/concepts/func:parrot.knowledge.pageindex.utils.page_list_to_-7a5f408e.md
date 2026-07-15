---
type: Concept
title: page_list_to_group_text()
id: func:parrot.knowledge.pageindex.utils.page_list_to_group_text
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Split page contents into groups respecting token limits.
---

# page_list_to_group_text

```python
def page_list_to_group_text(page_contents: list[str], token_lengths: list[int], max_tokens: int=20000, overlap_page: int=1) -> list[str]
```

Split page contents into groups respecting token limits.
