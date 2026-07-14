---
type: Wiki Entity
title: JiraInput
id: class:parrot_tools.jiratoolkit.JiraInput
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: 'Default input for Jira tools: holds auth + default project context.'
---

# JiraInput

Defined in [`parrot_tools.jiratoolkit`](../summaries/mod:parrot_tools.jiratoolkit.md).

```python
class JiraInput(BaseModel)
```

Default input for Jira tools: holds auth + default project context.

You usually do **not** pass this into every call; it's used to configure the
toolkit on initialization. It's defined here for consistency and as a type
you can reuse when wiring the toolkit into agents.
