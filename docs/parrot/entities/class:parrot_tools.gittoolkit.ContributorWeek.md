---
type: Wiki Entity
title: ContributorWeek
id: class:parrot_tools.gittoolkit.ContributorWeek
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: One week's slice of a contributor's activity.
---

# ContributorWeek

Defined in [`parrot_tools.gittoolkit`](../summaries/mod:parrot_tools.gittoolkit.md).

```python
class ContributorWeek(BaseModel)
```

One week's slice of a contributor's activity.

Mirrors the GitHub ``weeks[]`` entry from
``GET /repos/{owner}/{repo}/stats/contributors``.
