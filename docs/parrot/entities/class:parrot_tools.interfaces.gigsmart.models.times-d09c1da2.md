---
type: Wiki Entity
title: SetEngagementDisputeApprovalInput
id: class:parrot_tools.interfaces.gigsmart.models.timesheet.SetEngagementDisputeApprovalInput
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Input for the ``setEngagementDisputeApproval`` mutation.
---

# SetEngagementDisputeApprovalInput

Defined in [`parrot_tools.interfaces.gigsmart.models.timesheet`](../summaries/mod:parrot_tools.interfaces.gigsmart.models.timesheet.md).

```python
class SetEngagementDisputeApprovalInput(BaseModel)
```

Input for the ``setEngagementDisputeApproval`` mutation.

Allows the requester to accept or reject a worker's dispute.

Args:
    dispute_id: Opaque ID of the dispute to resolve.
    accept: ``True`` to accept the dispute; ``False`` to reject it.
    response_note: Optional explanation of the resolution decision.
