---
type: Wiki Summary
title: parrot_tools.o365.events
id: mod:parrot_tools.o365.events
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Office365 Tools Implementation.
relates_to:
- concept: class:parrot_tools.o365.events.CreateEventArgs
  rel: defines
- concept: class:parrot_tools.o365.events.CreateEventTool
  rel: defines
- concept: class:parrot_tools.o365.events.GetEventArgs
  rel: defines
- concept: class:parrot_tools.o365.events.GetEventTool
  rel: defines
- concept: class:parrot_tools.o365.events.ListEventArgs
  rel: defines
- concept: class:parrot_tools.o365.events.ListEventsTool
  rel: defines
- concept: class:parrot_tools.o365.events.UpdateEventArgs
  rel: defines
- concept: class:parrot_tools.o365.events.UpdateEventTool
  rel: defines
- concept: mod:parrot_tools.o365.base
  rel: references
---

# `parrot_tools.o365.events`

Office365 Tools Implementation.

Specific tools for interacting with Office365 services:
- CreateDraftMessage: Create email drafts
- CreateEvent: Create calendar events
- SearchEmail: Search through emails
- SendEmail: Send emails directly

## Classes

- **`CreateEventArgs(O365ToolArgsSchema)`** — Arguments for creating a calendar event.
- **`CreateEventTool(O365Tool)`** — Tool for creating calendar events in Office365.
- **`ListEventArgs(O365ToolArgsSchema)`** — Arguments for listing calendar events.
- **`ListEventsTool(O365Tool)`** — Tool for listing events in the user's calendar.
- **`GetEventArgs(O365ToolArgsSchema)`** — Arguments for retrieving a single calendar event by ID.
- **`GetEventTool(O365Tool)`** — Tool for retrieving a single calendar event by its ID.
- **`UpdateEventArgs(O365ToolArgsSchema)`** — Arguments for updating a calendar event.
- **`UpdateEventTool(O365Tool)`** — Tool for updating an existing calendar event in Office365.
