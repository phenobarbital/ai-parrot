---
type: Wiki Summary
title: parrot_tools.gigsmart.toolkit
id: mod:parrot_tools.gigsmart.toolkit
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: GigSmartToolkit — AbstractToolkit exposing GigSmart API surfaces as LLM tools.
relates_to:
- concept: class:parrot_tools.gigsmart.toolkit.GigSmartToolkit
  rel: defines
- concept: mod:parrot_tools.decorators
  rel: references
- concept: mod:parrot_tools.gigsmart.schemas
  rel: references
- concept: mod:parrot_tools.interfaces.gigsmart.client
  rel: references
- concept: mod:parrot_tools.interfaces.gigsmart.config
  rel: references
- concept: mod:parrot_tools.interfaces.gigsmart.models.engagement
  rel: references
- concept: mod:parrot_tools.interfaces.gigsmart.models.gig
  rel: references
- concept: mod:parrot_tools.interfaces.gigsmart.models.location
  rel: references
- concept: mod:parrot_tools.interfaces.gigsmart.models.position
  rel: references
- concept: mod:parrot_tools.interfaces.gigsmart.models.timesheet
  rel: references
- concept: mod:parrot_tools.interfaces.gigsmart.queries.engagements
  rel: references
- concept: mod:parrot_tools.interfaces.gigsmart.queries.gigs
  rel: references
- concept: mod:parrot_tools.interfaces.gigsmart.queries.locations
  rel: references
- concept: mod:parrot_tools.interfaces.gigsmart.queries.messages
  rel: references
- concept: mod:parrot_tools.interfaces.gigsmart.queries.positions
  rel: references
- concept: mod:parrot_tools.interfaces.gigsmart.queries.timesheets
  rel: references
- concept: mod:parrot_tools.toolkit
  rel: references
---

# `parrot_tools.gigsmart.toolkit`

GigSmartToolkit — AbstractToolkit exposing GigSmart API surfaces as LLM tools.

Provides 23 async tool methods organised into 7 surfaces:
- Organizations (2): list_organizations, get_organization
- Locations (3): list_locations, place_autocomplete, add_organization_location
- Positions (3): list_positions, get_position, add_organization_position
- Gigs/Shifts (4): list_gigs, get_gig, post_shift, transition_gig
- Engagements (4): list_engagements, get_engagement, transition_engagement, list_engagement_states
- Timesheets (4): list_timesheets, get_timesheet, approve_timesheet, remove_timesheet_dispute
- Messages (1): add_conversation_message
- Utilities (2): search_gigs, get_gig_summary

Write mutations are gated via ``confirming_tools`` (HITL confirmation required).
Large result sets (>10 items) optionally spill to WorkingMemory DataFrames via
the optional ``WorkingMemoryToolkit`` composition.

## Classes

- **`GigSmartToolkit(AbstractToolkit)`** — LLM toolkit for interacting with the GigSmart staffing platform API.
