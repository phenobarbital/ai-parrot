---
type: Wiki Entity
title: FakeJiraClient
id: class:parrot.eval.sandbox.fakes.FakeJiraClient
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: In-memory Jira client backed by a ``DictStateBackend``.
---

# FakeJiraClient

Defined in [`parrot.eval.sandbox.fakes`](../summaries/mod:parrot.eval.sandbox.fakes.md).

```python
class FakeJiraClient
```

In-memory Jira client backed by a ``DictStateBackend``.

Implements the subset of the ``pycontribs.jira.JIRA`` API that the
Jira triage benchmark exercises.  State is stored in the ``"issues"``
collection of *backend*.

Args:
    backend: ``DictStateBackend`` holding the issue store.

## Methods

- `def search_issues(self, jql_str: str, maxResults: int=50, fields: str='*all', **kwargs: Any) -> list[_FakeIssue]` — Search issues using a simple JQL-like filter.
- `def assign_issue(self, issue: Any, assignee: str | None) -> None` — Assign *issue* to *assignee*.
- `def transition_issue(self, issue: Any, transition: str, **kwargs: Any) -> None` — Transition *issue* to a new status.
- `def issue(self, key: str) -> _FakeIssue | None` — Fetch a single issue by key.
- `def create_issue(self, fields: dict[str, Any], **kwargs: Any) -> _FakeIssue` — Create a new issue.
- `def update_issue_field(self, key: str, fields: dict[str, Any]) -> None` — Update fields of an existing issue.
