---
type: Concept
title: get_shutoff_date()
id: func:parrot.models.openai.get_shutoff_date
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Return the API shutoff date for ``model``, or None if not deprecated.
---

# get_shutoff_date

```python
def get_shutoff_date(model: Union[str, OpenAIModel]) -> Optional[date]
```

Return the API shutoff date for ``model``, or None if not deprecated.

Resolves direct keys and alias strings, but ignores aliases that are
themselves current ``OpenAIModel`` values.
