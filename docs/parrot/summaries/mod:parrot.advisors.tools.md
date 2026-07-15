---
type: Wiki Summary
title: parrot.advisors.tools
id: mod:parrot.advisors.tools
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Product Advisor Tools - Tools for guided product selection.
relates_to:
- concept: func:parrot.advisors.tools.create_advisor_tools
  rel: defines
- concept: mod:parrot.advisors
  rel: references
- concept: mod:parrot.advisors.state
  rel: references
---

# `parrot.advisors.tools`

Product Advisor Tools - Tools for guided product selection.

## Functions

- `def create_advisor_tools(state_manager, catalog, question_set=None) -> list` — Factory function to create all advisor tools with shared dependencies.
