---
type: Wiki Summary
title: parrot_tools.leadiq.tool
id: mod:parrot_tools.leadiq.tool
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: LeadIQToolkit - Agent-usable toolkit for the LeadIQ GraphQL API.
relates_to:
- concept: class:parrot_tools.leadiq.tool.LeadIQSearchInput
  rel: defines
- concept: class:parrot_tools.leadiq.tool.LeadIQToolkit
  rel: defines
- concept: mod:parrot.interfaces.http
  rel: references
- concept: mod:parrot_tools.abstract
  rel: references
- concept: mod:parrot_tools.decorators
  rel: references
- concept: mod:parrot_tools.toolkit
  rel: references
---

# `parrot_tools.leadiq.tool`

LeadIQToolkit - Agent-usable toolkit for the LeadIQ GraphQL API.

Ports the GraphQL query logic and response transforms from flowtask's
``LeadIQ`` ETL component
(``flowtask/components/LeadIQ.py``) into an ``AbstractToolkit`` exposing
three discrete tools:

- ``search_company``   -> structured company information (single company)
- ``search_employees`` -> people grouped under a company
- ``search_flat``      -> flat list of people at a company

Unlike the flowtask component, this toolkit does NOT inherit ``HTTPService``
(no ``FlowComponent`` coupling, no pandas DataFrame return). Transport is a
composed ``HTTPService`` member, and every tool returns a structured
``ToolResult``.

## Classes

- **`LeadIQSearchInput(AbstractToolArgsSchema)`** — Input schema shared by all LeadIQ search tools.
- **`LeadIQToolkit(AbstractToolkit)`** — Toolkit for querying the LeadIQ GraphQL API for company and people data.
