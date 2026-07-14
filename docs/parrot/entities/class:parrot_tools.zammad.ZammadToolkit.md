---
type: Wiki Entity
title: ZammadToolkit
id: class:parrot_tools.zammad.ZammadToolkit
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Toolkit exposing Zammad helpdesk operations as agent tools.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# ZammadToolkit

Defined in [`parrot_tools.zammad`](../summaries/mod:parrot_tools.zammad.md).

```python
class ZammadToolkit(AbstractToolkit)
```

Toolkit exposing Zammad helpdesk operations as agent tools.

Example:
    toolkit = ZammadToolkit(
        instance_url="https://support.example.com",
        token="my-api-token",
        default_group="Support",
    )
    tools = toolkit.get_tools()
    ticket = await toolkit.create_ticket(
        title="Can't log in",
        group="Support",
        customer="jane@example.com",
        article_body="I forgot my password.",
    )

## Methods

- `async def start(self) -> None` — Create and open the underlying ``ZammadInterface`` session.
- `async def stop(self) -> None` — Close the underlying ``ZammadInterface`` session.
- `async def create_ticket(self, title: str, group: str, customer: str, article_body: str, article_subject: Optional[str]=None, article_type: str='note', article_internal: bool=False, priority_id: Optional[int]=None, state_id: Optional[int]=None, on_behalf_of: Optional[str]=None) -> dict[str, Any]` — Create a new support ticket in Zammad.
- `async def get_ticket(self, ticket_id: int, expand: bool=False) -> dict[str, Any]` — Retrieve a single Zammad ticket by ID.
- `async def list_tickets(self, state_ids: Optional[list[int]]=None, page: int=1, per_page: int=100) -> dict[str, Any]` — List Zammad tickets, optionally filtered by state.
- `async def update_ticket(self, ticket_id: int, title: Optional[str]=None, group: Optional[str]=None, state_id: Optional[int]=None, priority_id: Optional[int]=None, article_body: Optional[str]=None, article_type: str='note', article_internal: bool=True, on_behalf_of: Optional[str]=None) -> dict[str, Any]` — Update an existing Zammad ticket.
- `async def close_ticket(self, ticket_id: int) -> dict[str, Any]` — Close a Zammad ticket by setting its state to 'closed'.
- `async def search_tickets(self, query: str, page: int=1, per_page: int=100) -> dict[str, Any]` — Search Zammad tickets by query string.
- `async def delete_ticket(self, ticket_id: int) -> dict[str, Any]` — Delete a Zammad ticket by ID.
- `async def get_user(self, user_id: int, expand: bool=False) -> dict[str, Any]` — Retrieve a single Zammad user by ID.
- `async def search_users(self, query: str) -> list[dict[str, Any]]` — Search Zammad users by query string.
- `async def create_user(self, firstname: str, lastname: str, email: str, organization: Optional[str]=None, roles: Optional[list[str]]=None, active: bool=True) -> dict[str, Any]` — Create a new Zammad user.
- `async def get_articles(self, ticket_id: int) -> list[dict[str, Any]]` — List all articles for a Zammad ticket.
- `async def get_attachment(self, ticket_id: int, article_id: int, attachment_id: int) -> dict[str, Any]` — Download a Zammad attachment and return its content and metadata.
