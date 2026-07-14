---
type: Wiki Summary
title: parrot_tools.interfaces.gigsmart.models.gig
id: mod:parrot_tools.interfaces.gigsmart.models.gig
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Pydantic v2 models for GigSmart gigs (shifts) API surface.
relates_to:
- concept: class:parrot_tools.interfaces.gigsmart.models.gig.Gig
  rel: defines
- concept: class:parrot_tools.interfaces.gigsmart.models.gig.PostShiftInput
  rel: defines
- concept: class:parrot_tools.interfaces.gigsmart.models.gig.TransitionGigInput
  rel: defines
---

# `parrot_tools.interfaces.gigsmart.models.gig`

Pydantic v2 models for GigSmart gigs (shifts) API surface.

## Classes

- **`PostShiftInput(BaseModel)`** — Input for the ``postShift`` mutation.
- **`TransitionGigInput(BaseModel)`** — Input for the ``transitionGig`` mutation.
- **`Gig(BaseModel)`** — A GigSmart shift/gig resource.
