---
type: Wiki Summary
title: parrot_tools.gigsmart.schemas
id: mod:parrot_tools.gigsmart.schemas
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Pydantic input schemas for GigSmartToolkit @tool_schema decorators.
relates_to:
- concept: class:parrot_tools.gigsmart.schemas.AddConversationMessageInput
  rel: defines
- concept: class:parrot_tools.gigsmart.schemas.AddOrganizationLocationInput
  rel: defines
- concept: class:parrot_tools.gigsmart.schemas.AddOrganizationPositionInput
  rel: defines
- concept: class:parrot_tools.gigsmart.schemas.ApproveTimesheetInput
  rel: defines
- concept: class:parrot_tools.gigsmart.schemas.GetEngagementInput
  rel: defines
- concept: class:parrot_tools.gigsmart.schemas.GetGigInput
  rel: defines
- concept: class:parrot_tools.gigsmart.schemas.GetGigSummaryInput
  rel: defines
- concept: class:parrot_tools.gigsmart.schemas.GetOrganizationInput
  rel: defines
- concept: class:parrot_tools.gigsmart.schemas.GetPositionInput
  rel: defines
- concept: class:parrot_tools.gigsmart.schemas.GetTimesheetInput
  rel: defines
- concept: class:parrot_tools.gigsmart.schemas.ListEngagementStatesInput
  rel: defines
- concept: class:parrot_tools.gigsmart.schemas.ListEngagementsInput
  rel: defines
- concept: class:parrot_tools.gigsmart.schemas.ListGigsInput
  rel: defines
- concept: class:parrot_tools.gigsmart.schemas.ListLocationsInput
  rel: defines
- concept: class:parrot_tools.gigsmart.schemas.ListOrganizationsInput
  rel: defines
- concept: class:parrot_tools.gigsmart.schemas.ListPositionsInput
  rel: defines
- concept: class:parrot_tools.gigsmart.schemas.ListTimesheetsInput
  rel: defines
- concept: class:parrot_tools.gigsmart.schemas.PlaceAutocompleteInput
  rel: defines
- concept: class:parrot_tools.gigsmart.schemas.PostShiftInput
  rel: defines
- concept: class:parrot_tools.gigsmart.schemas.RemoveTimesheetDisputeInput
  rel: defines
- concept: class:parrot_tools.gigsmart.schemas.SearchGigsInput
  rel: defines
- concept: class:parrot_tools.gigsmart.schemas.TransitionEngagementInput
  rel: defines
- concept: class:parrot_tools.gigsmart.schemas.TransitionGigInput
  rel: defines
---

# `parrot_tools.gigsmart.schemas`

Pydantic input schemas for GigSmartToolkit @tool_schema decorators.

One schema class per tool method — used to validate LLM tool call arguments
before they are forwarded to the GraphQL client.

## Classes

- **`ListOrganizationsInput(BaseModel)`** — Input for list_organizations tool.
- **`GetOrganizationInput(BaseModel)`** — Input for get_organization tool.
- **`ListLocationsInput(BaseModel)`** — Input for list_locations tool.
- **`PlaceAutocompleteInput(BaseModel)`** — Input for place_autocomplete tool.
- **`AddOrganizationLocationInput(BaseModel)`** — Input for add_organization_location tool.
- **`ListPositionsInput(BaseModel)`** — Input for list_positions tool.
- **`GetPositionInput(BaseModel)`** — Input for get_position tool.
- **`AddOrganizationPositionInput(BaseModel)`** — Input for add_organization_position tool.
- **`ListGigsInput(BaseModel)`** — Input for list_gigs tool.
- **`GetGigInput(BaseModel)`** — Input for get_gig tool.
- **`PostShiftInput(BaseModel)`** — Input for post_shift tool.
- **`TransitionGigInput(BaseModel)`** — Input for transition_gig tool.
- **`ListEngagementsInput(BaseModel)`** — Input for list_engagements tool.
- **`GetEngagementInput(BaseModel)`** — Input for get_engagement tool.
- **`TransitionEngagementInput(BaseModel)`** — Input for transition_engagement tool.
- **`ListEngagementStatesInput(BaseModel)`** — Input for list_engagement_states tool.
- **`ListTimesheetsInput(BaseModel)`** — Input for list_timesheets tool.
- **`GetTimesheetInput(BaseModel)`** — Input for get_timesheet tool.
- **`ApproveTimesheetInput(BaseModel)`** — Input for approve_timesheet tool.
- **`RemoveTimesheetDisputeInput(BaseModel)`** — Input for remove_timesheet_dispute tool.
- **`AddConversationMessageInput(BaseModel)`** — Input for add_conversation_message tool.
- **`SearchGigsInput(BaseModel)`** — Input for search_gigs tool.
- **`GetGigSummaryInput(BaseModel)`** — Input for get_gig_summary tool.
