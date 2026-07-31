---
type: Wiki Summary
title: parrot.core.hooks.imap
id: mod:parrot.core.hooks.imap
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: IMAP watchdog hook — async email monitoring with optional tagged filtering.
relates_to:
- concept: class:parrot.core.hooks.imap.IMAPWatchdogHook
  rel: defines
- concept: mod:parrot.core.hooks.base
  rel: references
- concept: mod:parrot.core.hooks.models
  rel: references
---

# `parrot.core.hooks.imap`

IMAP watchdog hook — async email monitoring with optional tagged filtering.

## Classes

- **`IMAPWatchdogHook(BaseHook)`** — Monitors an IMAP mailbox for new emails using aioimaplib.
