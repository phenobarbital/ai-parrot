---
type: Wiki Entity
title: GetMyTicketsInput
id: class:parrot_tools.jiratoolkit.GetMyTicketsInput
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Input for retrieving the CURRENT (authenticated) user's Jira tickets.
---

# GetMyTicketsInput

Defined in [`parrot_tools.jiratoolkit`](../summaries/mod:parrot_tools.jiratoolkit.md).

```python
class GetMyTicketsInput(BaseModel)
```

Input for retrieving the CURRENT (authenticated) user's Jira tickets.

INSTRUCT: Use this tool whenever the user asks for THEIR OWN tickets or
issues (e.g. "my tickets", "my open issues", "what am I assigned to",
"tickets assigned to me", "mis tickets"). Do NOT build a manual JQL
query in that case — this tool resolves the authenticated identity
server-side via ``assignee = currentUser()``.
