---
type: Wiki Entity
title: LeadIQToolkit
id: class:parrot_tools.leadiq.tool.LeadIQToolkit
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Toolkit for querying the LeadIQ GraphQL API for company and people data.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# LeadIQToolkit

Defined in [`parrot_tools.leadiq.tool`](../summaries/mod:parrot_tools.leadiq.tool.md).

```python
class LeadIQToolkit(AbstractToolkit)
```

Toolkit for querying the LeadIQ GraphQL API for company and people data.

Each public async method is automatically converted into a tool by
``AbstractToolkit`` (prefixed with ``leadiq_``). Methods:

1. Resolve ``LEADIQ_API_KEY`` (already Base64-encoded) and build the
   ``Authorization: Basic <key>`` header.
2. Build the GraphQL payload from the ported query constant + variables.
3. POST to ``https://api.leadiq.com/graphql`` via the composed
   ``HTTPService`` member.
4. Flatten the response using the ported ``_process_*_response``
   transforms.
5. Return a structured ``ToolResult``.

## Methods

- `async def search_company(self, company_name: str, **kwargs) -> ToolResult` — Search LeadIQ for a company and return structured company information.
- `async def search_employees(self, company_name: str, limit: int=100, **kwargs) -> ToolResult` — Search LeadIQ for employees grouped under a company.
- `async def search_flat(self, company_name: str, limit: int=100, **kwargs) -> ToolResult` — Flat search LeadIQ for people at a company (one record per person).
