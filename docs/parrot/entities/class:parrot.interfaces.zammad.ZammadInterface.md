---
type: Wiki Entity
title: ZammadInterface
id: class:parrot.interfaces.zammad.ZammadInterface
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Async interface for Zammad REST API v1.
---

# ZammadInterface

Defined in [`parrot.interfaces.zammad`](../summaries/mod:parrot.interfaces.zammad.md).

```python
class ZammadInterface
```

Async interface for Zammad REST API v1.

Supports Bearer token authentication and "On Behalf Of" impersonation
via a configurable HTTP header (defaults to ``From``, configurable to
``X-On-Behalf-Of`` for older Zammad instances).

Example:
    async with ZammadInterface(
        instance_url="https://support.example.com",
        token="my-api-token",
    ) as zammad:
        ticket = await zammad.get_ticket(42)

## Methods

- `async def close(self) -> None` — Close the underlying aiohttp session explicitly.
- `async def list_tickets(self, state_ids: list[int] | None=None, page: int=1, per_page: int=100) -> dict[str, Any]` — List tickets, optionally filtered by state.
- `async def get_ticket(self, ticket_id: int, expand: bool=False) -> dict[str, Any]` — Retrieve a single ticket by ID.
- `async def create_ticket(self, payload: TicketCreatePayload) -> dict[str, Any]` — Create a new ticket.
- `async def update_ticket(self, payload: TicketUpdatePayload) -> dict[str, Any]` — Update an existing ticket.
- `async def delete_ticket(self, ticket_id: int) -> None` — Delete a ticket by ID.
- `async def search_tickets(self, query: str, page: int=1, per_page: int=100) -> dict[str, Any]` — Search tickets by query string.
- `async def get_user(self, user_id: int, expand: bool=False) -> dict[str, Any]` — Retrieve a single user by ID.
- `async def get_current_user(self) -> dict[str, Any]` — Retrieve the authenticated user (the API token's owner).
- `async def search_users(self, query: str) -> list[dict[str, Any]]` — Search users by query string.
- `async def create_user(self, payload: UserCreatePayload) -> dict[str, Any]` — Create a new user.
- `async def update_user(self, user_id: int, data: dict) -> dict[str, Any]` — Update an existing user.
- `async def get_articles(self, ticket_id: int) -> list[dict[str, Any]]` — List all articles for a ticket.
- `async def get_attachment(self, ticket_id: int, article_id: int, attachment_id: int) -> tuple[bytes, str]` — Download an attachment and save it to ``attachment_dir``.
