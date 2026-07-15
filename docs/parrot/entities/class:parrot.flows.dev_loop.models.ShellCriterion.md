---
type: Wiki Entity
title: ShellCriterion
id: class:parrot.flows.dev_loop.models.ShellCriterion
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Run an allow-listed shell command and assert its exit code.
---

# ShellCriterion

Defined in [`parrot.flows.dev_loop.models`](../summaries/mod:parrot.flows.dev_loop.models.md).

```python
class ShellCriterion(_AcceptanceCriterionBase)
```

Run an allow-listed shell command and assert its exit code.

The command head (first whitespace-separated token) is validated by
``BugIntakeNode`` against the ``ACCEPTANCE_CRITERION_ALLOWLIST``
setting at intake time.
