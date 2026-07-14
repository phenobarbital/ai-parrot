---
type: Wiki Summary
title: parrot.tools.databasequery.tool
id: mod:parrot.tools.databasequery.tool
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Database Query Tool migrated to use AbstractTool framework.
relates_to:
- concept: class:parrot.tools.databasequery.tool.DatabaseQueryArgs
  rel: defines
- concept: class:parrot.tools.databasequery.tool.DatabaseQueryTool
  rel: defines
- concept: class:parrot.tools.databasequery.tool.DriverInfo
  rel: defines
- concept: mod:parrot.auth.context
  rel: references
- concept: mod:parrot.auth.exceptions
  rel: references
- concept: mod:parrot.interfaces.database
  rel: references
- concept: mod:parrot.security
  rel: references
- concept: mod:parrot.tools.abstract
  rel: references
- concept: mod:parrot.tools.databasequery.base
  rel: references
- concept: mod:parrot.tools.databasequery.sources
  rel: references
- concept: mod:parrot.tools.dataset_manager.sources.dialects
  rel: references
- concept: mod:parrot.tools.dataset_manager.sources.resolver
  rel: references
- concept: mod:parrot.tools.dataset_manager.sources.rls
  rel: references
- concept: mod:parrot.tools.dataset_manager.sources.sql
  rel: references
---

# `parrot.tools.databasequery.tool`

Database Query Tool migrated to use AbstractTool framework.

## Classes

- **`DriverInfo`** — Driver metadata wrapper preserved for back-compat (FEAT-105).
- **`DatabaseQueryArgs(BaseModel)`** — Arguments schema for DatabaseQueryTool.
- **`DatabaseQueryTool(AbstractTool)`** — Multi-language Database Query Tool for executing queries across multiple database systems.
