---
type: Wiki Entity
title: CreateEventTool
id: class:parrot_tools.o365.events.CreateEventTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Tool for creating calendar events in Office365.
relates_to:
- concept: class:parrot_tools.o365.base.O365Tool
  rel: extends
---

# CreateEventTool

Defined in [`parrot_tools.o365.events`](../summaries/mod:parrot_tools.o365.events.md).

```python
class CreateEventTool(O365Tool)
```

Tool for creating calendar events in Office365.

This tool creates calendar events with support for:
- Attendees and invitations
- Online meetings (Teams)
- All-day events
- Timezone handling
- Location and descriptions

Examples:
    # Create a simple meeting
    result = await tool.run(
        subject="Team Standup",
        start_datetime="2025-01-20T09:00:00",
        end_datetime="2025-01-20T09:30:00",
        timezone="America/New_York",
        attendees=["team@company.com"]
    )

    # Create an online meeting
    result = await tool.run(
        subject="Client Presentation",
        start_datetime="2025-01-21T14:00:00",
        end_datetime="2025-01-21T15:00:00",
        body="Presenting Q4 results",
        attendees=["client@external.com"],
        is_online_meeting=True
    )

    # Create an all-day event
    result = await tool.run(
        subject="Company Holiday",
        start_datetime="2025-12-25T00:00:00",
        end_datetime="2025-12-25T23:59:59",
        is_all_day=True
    )
