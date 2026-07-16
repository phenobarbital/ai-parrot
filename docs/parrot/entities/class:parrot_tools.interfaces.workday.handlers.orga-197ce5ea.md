---
type: Wiki Entity
title: GetOrganization
id: class:parrot_tools.interfaces.workday.handlers.organization_single.GetOrganization
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Handler for Get_Organization operation.
relates_to:
- concept: class:parrot_tools.interfaces.workday.handlers.base.WorkdayTypeBase
  rel: extends
---

# GetOrganization

Defined in [`parrot_tools.interfaces.workday.handlers.organization_single`](../summaries/mod:parrot_tools.interfaces.workday.handlers.organi-a88b280d.md).

```python
class GetOrganization(WorkdayTypeBase)
```

Handler for Get_Organization operation.

Retrieves a specific organization by its ID.

## Methods

- `async def execute(self, organization_id: str, organization_id_type: str='Organization_Reference_ID', **kwargs) -> pd.DataFrame` — Execute Get_Organization operation to retrieve a specific organization.
- `async def get_organization_by_wid(self, wid: str, **kwargs) -> pd.DataFrame` — Get organization by WID.
- `async def get_organization_by_reference_id(self, reference_id: str, **kwargs) -> pd.DataFrame` — Get organization by Organization_Reference_ID.
- `async def get_organization_by_custom_id(self, custom_id: str, **kwargs) -> pd.DataFrame` — Get organization by Custom_Organization_Reference_ID.
