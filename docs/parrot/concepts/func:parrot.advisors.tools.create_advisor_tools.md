---
type: Concept
title: create_advisor_tools()
id: func:parrot.advisors.tools.create_advisor_tools
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Factory function to create all advisor tools with shared dependencies.
---

# create_advisor_tools

```python
def create_advisor_tools(state_manager, catalog, question_set=None) -> list
```

Factory function to create all advisor tools with shared dependencies.

Usage:
    tools = create_advisor_tools(
        state_manager=my_state_manager,
        catalog=my_catalog,
        question_set=my_questions
    )
    
    agent.register_tools(tools)
