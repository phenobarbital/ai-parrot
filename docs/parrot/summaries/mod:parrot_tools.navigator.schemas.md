---
type: Wiki Summary
title: parrot_tools.navigator.schemas
id: mod:parrot_tools.navigator.schemas
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Pydantic input schemas for NavigatorToolkit methods.
relates_to:
- concept: class:parrot_tools.navigator.schemas.AssignModuleClientInput
  rel: defines
- concept: class:parrot_tools.navigator.schemas.AssignModuleGroupInput
  rel: defines
- concept: class:parrot_tools.navigator.schemas.CloneDashboardInput
  rel: defines
- concept: class:parrot_tools.navigator.schemas.DashboardCreateInput
  rel: defines
- concept: class:parrot_tools.navigator.schemas.DashboardUpdateInput
  rel: defines
- concept: class:parrot_tools.navigator.schemas.EntityLookupInput
  rel: defines
- concept: class:parrot_tools.navigator.schemas.ExecuteSqlInput
  rel: defines
- concept: class:parrot_tools.navigator.schemas.ModuleCreateInput
  rel: defines
- concept: class:parrot_tools.navigator.schemas.ModuleUpdateInput
  rel: defines
- concept: class:parrot_tools.navigator.schemas.ProgramCreateInput
  rel: defines
- concept: class:parrot_tools.navigator.schemas.ProgramUpdateInput
  rel: defines
- concept: class:parrot_tools.navigator.schemas.PublishDashboardInput
  rel: defines
- concept: class:parrot_tools.navigator.schemas.SearchInput
  rel: defines
- concept: class:parrot_tools.navigator.schemas.WidgetCreateInput
  rel: defines
- concept: class:parrot_tools.navigator.schemas.WidgetUpdateInput
  rel: defines
---

# `parrot_tools.navigator.schemas`

Pydantic input schemas for NavigatorToolkit methods.

Each schema maps to a @tool_schema decorator on a toolkit method.
Field descriptions are sent to the LLM as part of the tool definition.

## Classes

- **`ExecuteSqlInput(BaseModel)`** — Input for executing a raw SQL statement (DDL or DML).
- **`ProgramCreateInput(BaseModel)`** — Input for creating a new Navigator program.
- **`ProgramUpdateInput(BaseModel)`** — Input for updating an existing Program.
- **`ModuleCreateInput(BaseModel)`** — Input for creating a new module inside a Program.
- **`ModuleUpdateInput(BaseModel)`** — Input for updating an existing Module.
- **`DashboardCreateInput(BaseModel)`** — Input for creating a new dashboard.
- **`DashboardUpdateInput(BaseModel)`** — Input for updating an existing dashboard.
- **`CloneDashboardInput(BaseModel)`** — Input for cloning a dashboard with all its widgets.
- **`PublishDashboardInput(BaseModel)`** — Input for publishing a draft dashboard (promote to system-wide).
- **`WidgetCreateInput(BaseModel)`** — Input for creating a widget in a dashboard.
- **`WidgetUpdateInput(BaseModel)`** — Input for updating an existing widget.
- **`AssignModuleClientInput(BaseModel)`** — Input for assigning a module to a client.
- **`AssignModuleGroupInput(BaseModel)`** — Input for assigning a module to a group (permissions).
- **`EntityLookupInput(BaseModel)`** — Input for looking up an entity by ID or slug.
- **`SearchInput(BaseModel)`** — Input for searching across Navigator entities.
