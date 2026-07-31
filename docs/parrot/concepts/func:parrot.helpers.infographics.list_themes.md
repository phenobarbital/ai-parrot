---
type: Concept
title: list_themes()
id: func:parrot.helpers.infographics.list_themes
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: List available infographic theme names.
---

# list_themes

```python
def list_themes(detailed: bool=False) -> Union[List[str], List[Dict[str, str]]]
```

List available infographic theme names.

Args:
    detailed: When True, return list of dicts with name and key
        colour tokens (primary, neutral_bg, body_bg).

Returns:
    Sorted list of names, or sorted list of detailed dicts when
    ``detailed=True``.
