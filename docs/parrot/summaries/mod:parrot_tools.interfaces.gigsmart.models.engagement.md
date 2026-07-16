---
type: Wiki Summary
title: parrot_tools.interfaces.gigsmart.models.engagement
id: mod:parrot_tools.interfaces.gigsmart.models.engagement
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Pydantic v2 models for GigSmart engagements API surface.
relates_to:
- concept: class:parrot_tools.interfaces.gigsmart.models.engagement.AddEngagementInput
  rel: defines
- concept: class:parrot_tools.interfaces.gigsmart.models.engagement.Engagement
  rel: defines
- concept: class:parrot_tools.interfaces.gigsmart.models.engagement.TransitionEngagementInput
  rel: defines
---

# `parrot_tools.interfaces.gigsmart.models.engagement`

Pydantic v2 models for GigSmart engagements API surface.

## Classes

- **`AddEngagementInput(BaseModel)`** — Input for the ``addEngagement`` mutation.
- **`TransitionEngagementInput(BaseModel)`** — Input for the single ``transitionEngagement`` mutation.
- **`Engagement(BaseModel)`** — A GigSmart engagement resource linking a worker to a gig.
