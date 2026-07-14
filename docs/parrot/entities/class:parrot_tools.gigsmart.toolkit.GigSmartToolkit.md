---
type: Wiki Entity
title: GigSmartToolkit
id: class:parrot_tools.gigsmart.toolkit.GigSmartToolkit
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: LLM toolkit for interacting with the GigSmart staffing platform API.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# GigSmartToolkit

Defined in [`parrot_tools.gigsmart.toolkit`](../summaries/mod:parrot_tools.gigsmart.toolkit.md).

```python
class GigSmartToolkit(AbstractToolkit)
```

LLM toolkit for interacting with the GigSmart staffing platform API.

Exposes 23 async methods as tools. Write mutations are gated via
``confirming_tools`` for human-in-the-loop safety. Large list results
(>10 items) optionally spill to WorkingMemory DataFrames when a
``WorkingMemoryToolkit`` instance is provided.

Args:
    config: GigSmartConfig carrying client credentials and endpoint settings.
    wm: Optional WorkingMemoryToolkit for DataFrame spilling.
    **kwargs: Additional kwargs forwarded to AbstractToolkit.__init__.

Example::

    config = GigSmartConfig.from_env()
    toolkit = GigSmartToolkit(config=config)
    tools = toolkit.get_tools()

## Methods

- `async def start(self) -> None` — Open the underlying GigSmartClient session.
- `async def stop(self) -> None` — Close the underlying GigSmartClient session.
- `async def cleanup(self) -> None` — Alias for stop() — closes the client session.
- `async def list_organizations(self, first: int=25, after: str | None=None, filter_name: str | None=None) -> list[dict]` — List organizations accessible to the authenticated requester.
- `async def get_organization(self, organization_id: str) -> dict` — Get details for a specific organization by ID.
- `async def list_locations(self, organization_id: str, first: int=25, after: str | None=None) -> list[dict]` — List locations for an organization.
- `async def place_autocomplete(self, search_text: str) -> list[dict]` — Search for address suggestions using GigSmart place autocomplete.
- `async def add_organization_location(self, organization_id: str, name: str, place_id: str | None=None, address: str | None=None, arrival_instructions: str | None=None, location_instructions: str | None=None) -> dict` — Create a new location for an organization.
- `async def list_positions(self, organization_id: str, first: int=25, after: str | None=None) -> list[dict]` — List positions for an organization.
- `async def get_position(self, position_id: str) -> dict` — Get details for a specific position by ID.
- `async def add_organization_position(self, organization_id: str, name: str, category_id: str | None=None, description: str | None=None, pay_rate: str | None=None, pay_schedule: str | None=None) -> dict` — Create a new position for an organization.
- `async def list_gigs(self, organization_id: str, first: int=25, after: str | None=None, state_filter: str | None=None) -> list[dict]` — List gigs (shifts) for an organization with optional state filtering.
- `async def get_gig(self, gig_id: str) -> dict` — Get full details for a specific gig by ID.
- `async def post_shift(self, organization_id: str, position_id: str, location_id: str, starts_at: datetime, ends_at: datetime, slots_available: int=1, pay_rate: str | None=None, description: str | None=None) -> dict` — Post a new shift (gig) for an organization.
- `async def transition_gig(self, gig_id: str, action: str) -> dict` — Transition a gig to a new state.
- `async def list_engagements(self, gig_id: str, first: int=25, after: str | None=None, state_filter: str | None=None) -> list[dict]` — List engagements for a gig with optional state filtering.
- `async def get_engagement(self, engagement_id: str) -> dict` — Get full details for a specific engagement by ID.
- `async def transition_engagement(self, engagement_id: str, action: str, cancel_conflicting: bool | None=None) -> dict` — Transition an engagement to a new state.
- `async def list_engagement_states(self, engagement_id: str) -> list[dict]` — List the full state history for an engagement.
- `async def list_timesheets(self, engagement_id: str) -> list[dict]` — List timesheets for an engagement.
- `async def get_timesheet(self, timesheet_id: str) -> dict` — Get full details for a specific timesheet by ID.
- `async def approve_timesheet(self, timesheet_id: str, mutation_lock: str | None=None) -> dict` — Approve a worker's timesheet.
- `async def remove_timesheet_dispute(self, timesheet_id: str) -> dict` — Reject a timesheet and send it back to the worker for resubmission.
- `async def add_conversation_message(self, engagement_id: str, body: str) -> dict` — Send a message to a worker via the engagement conversation thread.
- `async def search_gigs(self, query: str, location: str | None=None, radius_miles: float | None=None, first: int=25) -> list[dict]` — Search for gigs matching a text query and optional location filter.
- `async def get_gig_summary(self, gig_id: str) -> dict` — Get an enriched summary of a gig including engagement counts and timesheet status.
