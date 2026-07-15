---
type: Wiki Summary
title: parrot.bots.database.toolkits
id: mod:parrot.bots.database.toolkits
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Database toolkits — per-database-type tool collections.
relates_to:
- concept: mod:parrot.bots.database
  rel: references
---

# `parrot.bots.database.toolkits`

Database toolkits — per-database-type tool collections.

Each toolkit inherits ``DatabaseToolkit`` (which itself inherits
``AbstractToolkit``) and exposes database-specific operations as
LLM-callable tools.
