---
type: Concept
title: jira_accounts()
id: func:parrot.knowledge.ontology.tool_dispatcher.jira_accounts
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Render a comma-separated list of Jira accountIds for a JQL clause.
---

# jira_accounts

```python
def jira_accounts(team: list[dict[str, Any]]) -> str
```

Render a comma-separated list of Jira accountIds for a JQL clause.

Validates each element's ``jira_account_id`` field before inclusion.
Raises ``ValueError`` if any accountId has an unexpected shape.

Args:
    team: List of dicts, each expected to have a ``jira_account_id`` key.

Returns:
    Comma-separated string of quoted accountIds suitable for a JQL
    ``assignee in (...)`` clause. Members without a valid accountId are
    silently skipped.

Raises:
    ValueError: If any accountId fails the format validation
        (``[A-Za-z0-9:_\-]+``).
