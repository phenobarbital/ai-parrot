---
type: Wiki Summary
title: parrot_tools.navigator.toolkit
id: mod:parrot_tools.navigator.toolkit
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: NavigatorToolkit for AI-Parrot - Manage Navigator Programs, Modules, Dashboards
  & Widgets.
relates_to:
- concept: class:parrot_tools.navigator.toolkit.NavigatorToolkit
  rel: defines
- concept: mod:parrot.bots.database.toolkits.postgres
  rel: references
- concept: mod:parrot.tools.decorators
  rel: references
- concept: mod:parrot_tools.navigator.schemas
  rel: references
---

# `parrot_tools.navigator.toolkit`

NavigatorToolkit for AI-Parrot - Manage Navigator Programs, Modules, Dashboards & Widgets.

This toolkit provides tools for:
- Creating and updating Programs (auth.programs)
- Creating and updating Modules with menu hierarchy (navigator.modules)
- Creating, updating, and cloning Dashboards (navigator.dashboards)
- Creating and updating Widgets with template inheritance (navigator.widgets)
- Managing permissions (client_modules, modules_groups, program_clients, program_groups)
- Listing widget types, categories, clients, and groups
- Searching across all Navigator entities
- Retrieving full program structure (program → modules → dashboards → widgets)

Refactored (FEAT-106 / TASK-744): inherits PostgresToolkit instead of AbstractToolkit.
DB plumbing delegated to parent (asyncdb pool via _acquire_asyncdb_connection).

## Classes

- **`NavigatorToolkit(PostgresToolkit)`** — Toolkit for managing the Navigator platform.
