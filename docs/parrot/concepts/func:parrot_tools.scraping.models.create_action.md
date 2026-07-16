---
type: Concept
title: create_action()
id: func:parrot_tools.scraping.models.create_action
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Factory function to create actions by type name
---

# create_action

```python
def create_action(action_type: str, **kwargs) -> BrowserAction
```

Factory function to create actions by type name
Useful for LLM-generated action sequences
