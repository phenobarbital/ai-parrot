---
type: Wiki Entity
title: TransitionGigInput
id: class:parrot_tools.interfaces.gigsmart.models.gig.TransitionGigInput
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Input for the ``transitionGig`` mutation.
---

# TransitionGigInput

Defined in [`parrot_tools.interfaces.gigsmart.models.gig`](../summaries/mod:parrot_tools.interfaces.gigsmart.models.gig.md).

```python
class TransitionGigInput(BaseModel)
```

Input for the ``transitionGig`` mutation.

Args:
    gig_id: Opaque ID of the gig to transition (e.g. ``"gig_..."``).
    action: The transition action to apply.
