---
type: Wiki Entity
title: JiraConnectTool
id: class:parrot.tools.jira_connect_tool.JiraConnectTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Placeholder tool returning the Jira OAuth authorization URL.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# JiraConnectTool

Defined in [`parrot.tools.jira_connect_tool`](../summaries/mod:parrot.tools.jira_connect_tool.md).

```python
class JiraConnectTool(AbstractTool)
```

Placeholder tool returning the Jira OAuth authorization URL.

The LLM sees this tool exactly like any regular tool.  When it calls
``connect_jira``, the response carries the URL the user should open to
authorize their Jira account.
