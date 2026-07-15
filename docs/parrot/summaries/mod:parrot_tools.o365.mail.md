---
type: Wiki Summary
title: parrot_tools.o365.mail
id: mod:parrot_tools.o365.mail
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Office365 Mails Tools.
relates_to:
- concept: class:parrot_tools.o365.mail.CreateDraftMessageArgs
  rel: defines
- concept: class:parrot_tools.o365.mail.CreateDraftMessageTool
  rel: defines
- concept: class:parrot_tools.o365.mail.DownloadAttachmentArgs
  rel: defines
- concept: class:parrot_tools.o365.mail.DownloadAttachmentTool
  rel: defines
- concept: class:parrot_tools.o365.mail.GetMessageArgs
  rel: defines
- concept: class:parrot_tools.o365.mail.GetMessageTool
  rel: defines
- concept: class:parrot_tools.o365.mail.ListMessagesArgs
  rel: defines
- concept: class:parrot_tools.o365.mail.ListMessagesTool
  rel: defines
- concept: class:parrot_tools.o365.mail.SearchEmailArgs
  rel: defines
- concept: class:parrot_tools.o365.mail.SearchEmailTool
  rel: defines
- concept: class:parrot_tools.o365.mail.SendEmailArgs
  rel: defines
- concept: class:parrot_tools.o365.mail.SendEmailTool
  rel: defines
- concept: mod:parrot_tools.o365.base
  rel: references
---

# `parrot_tools.o365.mail`

Office365 Mails Tools.

Specific tools for interacting with Office365 services:
- CreateDraftMessage: Create email drafts
- SearchEmail: Search through emails
- SendEmail: Send emails directly

## Classes

- **`CreateDraftMessageArgs(O365ToolArgsSchema)`** — Arguments for creating a draft email message.
- **`CreateDraftMessageTool(O365Tool)`** — Tool for creating draft email messages in Office365.
- **`SearchEmailArgs(O365ToolArgsSchema)`** — Arguments for searching emails.
- **`SearchEmailTool(O365Tool)`** — Tool for searching emails in Office365.
- **`SendEmailArgs(O365ToolArgsSchema)`** — Arguments for sending an email.
- **`SendEmailTool(O365Tool)`** — Tool for sending emails directly in Office365.
- **`ListMessagesArgs(O365ToolArgsSchema)`** — Arguments for listing email messages.
- **`ListMessagesTool(O365Tool)`** — Tool for listing email messages from a specified folder.
- **`GetMessageArgs(O365ToolArgsSchema)`** — Arguments for retrieving a specific message.
- **`GetMessageTool(O365Tool)`** — Tool for retrieving a specific email message by its ID.
- **`DownloadAttachmentArgs(O365ToolArgsSchema)`** — Arguments for downloading an email attachment.
- **`DownloadAttachmentTool(O365Tool)`** — Tool for downloading email attachments to local storage.
