---
type: Wiki Summary
title: parrot_tools.qsource
id: mod:parrot_tools.qsource
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: QuerySource Tool for AI-Parrot
relates_to:
- concept: class:parrot_tools.qsource.QSourceTool
  rel: defines
- concept: class:parrot_tools.qsource.QuerySourceInput
  rel: defines
- concept: mod:parrot._imports
  rel: references
- concept: mod:parrot.exceptions
  rel: references
- concept: mod:parrot_tools.abstract
  rel: references
---

# `parrot_tools.qsource`

QuerySource Tool for AI-Parrot

A tool that integrates QuerySource QS library to execute queries and return
structured data as pandas DataFrames or custom structured outputs.

## Classes

- **`QuerySourceInput(BaseModel)`** — Input schema for QuerySource tool.
- **`QSourceTool(AbstractTool)`** — Tool for executing QuerySource queries and returning structured data.
