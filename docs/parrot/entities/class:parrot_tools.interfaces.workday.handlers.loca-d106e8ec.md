---
type: Wiki Entity
title: LocationHierarchyAssignmentsType
id: class:parrot_tools.interfaces.workday.handlers.location_hierarchy_assignments.LocationHierarchyAssignmentsType
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Handler for Get_Location_Hierarchy_Organization_Assignments operation.
relates_to:
- concept: class:parrot_tools.interfaces.workday.handlers.base.WorkdayTypeBase
  rel: extends
---

# LocationHierarchyAssignmentsType

Defined in [`parrot_tools.interfaces.workday.handlers.location_hierarchy_assignments`](../summaries/mod:parrot_tools.interfaces.workday.handlers.locati-12e680b1.md).

```python
class LocationHierarchyAssignmentsType(WorkdayTypeBase)
```

Handler for Get_Location_Hierarchy_Organization_Assignments operation.

Retrieves organization assignments for location hierarchies.

## Methods

- `async def execute(self, **kwargs) -> pd.DataFrame` — Execute Get_Location_Hierarchy_Organization_Assignments operation.
- `async def get_assignments_by_location_hierarchy(self, location_hierarchy_id: str, id_type: str='Organization_Reference_ID') -> pd.DataFrame` — Get organization assignments for a specific location hierarchy.
- `async def get_all_assignments(self, **kwargs) -> pd.DataFrame` — Get all location hierarchy organization assignments.
