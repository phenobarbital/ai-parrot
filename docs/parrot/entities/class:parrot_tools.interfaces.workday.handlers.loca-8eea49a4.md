---
type: Wiki Entity
title: LocationType
id: class:parrot_tools.interfaces.workday.handlers.locations.LocationType
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Handler for the Workday Get_Locations operation.
relates_to:
- concept: class:parrot_tools.interfaces.workday.handlers.base.WorkdayTypeBase
  rel: extends
---

# LocationType

Defined in [`parrot_tools.interfaces.workday.handlers.locations`](../summaries/mod:parrot_tools.interfaces.workday.handlers.locations.md).

```python
class LocationType(WorkdayTypeBase)
```

Handler for the Workday Get_Locations operation.

## Methods

- `async def execute(self, **kwargs) -> pd.DataFrame` — Execute the Get_Locations operation and return a pandas DataFrame.
- `async def get_location_by_id(self, location_id: str) -> pd.DataFrame` — Convenience method to get a specific location by ID.
- `async def get_location_by_name(self, location_name: str) -> pd.DataFrame` — Convenience method to get a specific location by name.
- `async def get_locations_by_type(self, location_type: str) -> pd.DataFrame` — Convenience method to get locations by type.
- `async def get_active_locations(self) -> pd.DataFrame` — Convenience method to get all active locations.
