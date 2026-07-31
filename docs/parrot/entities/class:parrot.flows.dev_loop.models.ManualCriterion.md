---
type: Wiki Entity
title: ManualCriterion
id: class:parrot.flows.dev_loop.models.ManualCriterion
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Human-readable acceptance statement that the QA subagent must NOT run.
---

# ManualCriterion

Defined in [`parrot.flows.dev_loop.models`](../summaries/mod:parrot.flows.dev_loop.models.md).

```python
class ManualCriterion(BaseModel)
```

Human-readable acceptance statement that the QA subagent must NOT run.

Used for criteria that are inherently subjective or require human
judgement ("the dashboard renders without flicker", "the migration
note in the PR mentions both downtime and rollback"). The
:class:`QANode` filters these out before dispatch, then re-appends a
synthesized :class:`CriterionResult` with ``kind="manual"`` and
``passed=True`` so the deterministic gate does not block the flow.
The text is also embedded in the Jira ticket description and in
``QAReport.notes`` so the human reviewer can sign off explicitly.
