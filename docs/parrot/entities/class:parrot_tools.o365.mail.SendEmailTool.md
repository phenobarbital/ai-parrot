---
type: Wiki Entity
title: SendEmailTool
id: class:parrot_tools.o365.mail.SendEmailTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Tool for sending emails directly in Office365.
relates_to:
- concept: class:parrot_tools.o365.base.O365Tool
  rel: extends
---

# SendEmailTool

Defined in [`parrot_tools.o365.mail`](../summaries/mod:parrot_tools.o365.mail.md).

```python
class SendEmailTool(O365Tool)
```

Tool for sending emails directly in Office365.

This tool sends an email immediately without creating a draft.
The email is sent and optionally saved to the Sent Items folder.

Examples:
    # Send a simple email
    result = await tool.run(
        subject="Quick Update",
        body="Just wanted to let you know...",
        to_recipients=["colleague@company.com"]
    )

    # Send HTML email with CC
    result = await tool.run(
        subject="Newsletter",
        body="<h2>This Month's Updates</h2><p>Content here...</p>",
        to_recipients=["subscriber@email.com"],
        cc_recipients=["team@company.com"],
        importance="high",
        is_html=True
    )

    # Send without saving to Sent Items
    result = await tool.run(
        subject="Temporary Message",
        body="This won't be saved in Sent Items",
        to_recipients=["user@company.com"],
        save_to_sent_items=False
    )
