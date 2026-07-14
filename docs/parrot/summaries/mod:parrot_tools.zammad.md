---
type: Wiki Summary
title: parrot_tools.zammad
id: mod:parrot_tools.zammad
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: ZammadToolkit — exposes Zammad helpdesk operations as agent tools.
relates_to:
- concept: class:parrot_tools.zammad.CloseTicketInput
  rel: defines
- concept: class:parrot_tools.zammad.CreateTicketInput
  rel: defines
- concept: class:parrot_tools.zammad.CreateUserInput
  rel: defines
- concept: class:parrot_tools.zammad.DeleteTicketInput
  rel: defines
- concept: class:parrot_tools.zammad.GetArticlesInput
  rel: defines
- concept: class:parrot_tools.zammad.GetAttachmentInput
  rel: defines
- concept: class:parrot_tools.zammad.GetTicketInput
  rel: defines
- concept: class:parrot_tools.zammad.GetUserInput
  rel: defines
- concept: class:parrot_tools.zammad.ListTicketsInput
  rel: defines
- concept: class:parrot_tools.zammad.SearchTicketsInput
  rel: defines
- concept: class:parrot_tools.zammad.SearchUsersInput
  rel: defines
- concept: class:parrot_tools.zammad.UpdateTicketInput
  rel: defines
- concept: class:parrot_tools.zammad.ZammadToolkit
  rel: defines
- concept: mod:parrot.interfaces.zammad
  rel: references
- concept: mod:parrot_tools.decorators
  rel: references
- concept: mod:parrot_tools.toolkit
  rel: references
---

# `parrot_tools.zammad`

ZammadToolkit — exposes Zammad helpdesk operations as agent tools.

Composes a :class:`~parrot.interfaces.zammad.ZammadInterface` and turns each
public async method into a tool via :class:`AbstractToolkit`. ``delete_ticket``
is excluded from the generated tool set for safety (it remains callable
directly on the toolkit instance or on ``ZammadInterface``).

Configuration falls back to the ``ZAMMAD_*`` keys in :mod:`parrot.conf`
(via :class:`ZammadInterface`) when constructor arguments are omitted.

## Classes

- **`CreateTicketInput(BaseModel)`** — Input schema for ``zammad_create_ticket``.
- **`GetTicketInput(BaseModel)`** — Input schema for ``zammad_get_ticket``.
- **`ListTicketsInput(BaseModel)`** — Input schema for ``zammad_list_tickets``.
- **`UpdateTicketInput(BaseModel)`** — Input schema for ``zammad_update_ticket``.
- **`CloseTicketInput(BaseModel)`** — Input schema for ``zammad_close_ticket``.
- **`SearchTicketsInput(BaseModel)`** — Input schema for ``zammad_search_tickets``.
- **`GetUserInput(BaseModel)`** — Input schema for ``zammad_get_user``.
- **`SearchUsersInput(BaseModel)`** — Input schema for ``zammad_search_users``.
- **`CreateUserInput(BaseModel)`** — Input schema for ``zammad_create_user``.
- **`GetArticlesInput(BaseModel)`** — Input schema for ``zammad_get_articles``.
- **`GetAttachmentInput(BaseModel)`** — Input schema for ``zammad_get_attachment``.
- **`DeleteTicketInput(BaseModel)`** — Input schema for the (excluded) ``delete_ticket`` method.
- **`ZammadToolkit(AbstractToolkit)`** — Toolkit exposing Zammad helpdesk operations as agent tools.
