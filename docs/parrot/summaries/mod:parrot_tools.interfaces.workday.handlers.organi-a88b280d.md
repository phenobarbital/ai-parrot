---
type: Wiki Summary
title: parrot_tools.interfaces.workday.handlers.organization_single
id: mod:parrot_tools.interfaces.workday.handlers.organization_single
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Get_Organization operation handler.
relates_to:
- concept: class:parrot_tools.interfaces.workday.handlers.organization_single.GetOrganization
  rel: defines
- concept: mod:parrot_tools.interfaces.workday.handlers.base
  rel: references
- concept: mod:parrot_tools.interfaces.workday.parsers.organization_parsers
  rel: references
---

# `parrot_tools.interfaces.workday.handlers.organization_single`

Get_Organization operation handler.

This module handles the Get_Organization operation which retrieves
a specific organization by its ID (singular, not plural).

## Classes

- **`GetOrganization(WorkdayTypeBase)`** — Handler for Get_Organization operation.
