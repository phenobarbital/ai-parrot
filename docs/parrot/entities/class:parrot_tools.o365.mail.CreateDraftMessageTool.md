---
type: Wiki Entity
title: CreateDraftMessageTool
id: class:parrot_tools.o365.mail.CreateDraftMessageTool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Tool for creating draft email messages in Office365.
relates_to:
- concept: class:parrot_tools.o365.base.O365Tool
  rel: extends
---

# CreateDraftMessageTool

Defined in [`parrot_tools.o365.mail`](../summaries/mod:parrot_tools.o365.mail.md).

```python
class CreateDraftMessageTool(O365Tool)
```

Tool for creating draft email messages in Office365.

This tool creates a draft email message that can be reviewed and sent later.
The draft is saved in the user's Drafts folder.

Examples:
    # Create a simple draft
    result = await tool.run(
        subject="Project Update",
        body="Here's the latest update on the project...",
        to_recipients=["colleague@company.com"]
    )

    # Create an HTML draft with CC
    result = await tool.run(
        subject="Monthly Report",
        body="<h1>Report</h1><p>Details here...</p>",
        to_recipients=["boss@company.com"],
        cc_recipients=["team@company.com"],
        importance="high",
        is_html=True
    )
