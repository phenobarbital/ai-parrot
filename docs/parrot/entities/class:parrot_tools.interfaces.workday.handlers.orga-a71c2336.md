---
type: Wiki Entity
title: OrganizationType
id: class:parrot_tools.interfaces.workday.handlers.organizations.OrganizationType
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Handler for the Workday Get_Organizations operation.
relates_to:
- concept: class:parrot_tools.interfaces.workday.handlers.base.WorkdayTypeBase
  rel: extends
---

# OrganizationType

Defined in [`parrot_tools.interfaces.workday.handlers.organizations`](../summaries/mod:parrot_tools.interfaces.workday.handlers.organizations.md).

```python
class OrganizationType(WorkdayTypeBase)
```

Handler for the Workday Get_Organizations operation.

## Methods

- `async def execute(self, **kwargs) -> pd.DataFrame` — Execute the Get_Organizations operation and return a pandas DataFrame.
- `async def get_organization_by_id(self, organization_id: str, id_type: str='Organization_Reference_ID') -> pd.DataFrame` — Get a specific organization by ID.
- `async def get_organizations_by_type(self, organization_type: str) -> pd.DataFrame` — Get organizations filtered by type.
- `async def get_active_organizations(self) -> pd.DataFrame` — Get only active organizations.
- `async def get_all_organizations(self, include_inactive: bool=True) -> pd.DataFrame` — Get all organizations (active and optionally inactive).
- `async def get_supervisory_organizations(self) -> pd.DataFrame` — Get only supervisory organizations.
- `async def get_cost_centers(self) -> pd.DataFrame` — Get only cost center organizations.
- `async def get_companies(self) -> pd.DataFrame` — Get only company organizations.
- `async def get_organization_by_wid(self, wid: str) -> pd.DataFrame` — Get a specific organization by WID.
- `async def get_organization_by_cost_center_id(self, cost_center_id: str) -> pd.DataFrame` — Get a specific organization by Cost Center Reference ID.
