---
type: Wiki Summary
title: parrot.handlers.scheduler
id: mod:parrot.handlers.scheduler
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: REST handlers for Parrot scheduler management.
relates_to:
- concept: class:parrot.handlers.scheduler.SchedulerCallbacksHandler
  rel: defines
- concept: class:parrot.handlers.scheduler.SchedulerCatalogHelper
  rel: defines
- concept: class:parrot.handlers.scheduler.SchedulerJobsHandler
  rel: defines
- concept: mod:parrot.scheduler
  rel: references
- concept: mod:parrot.scheduler.functions
  rel: references
---

# `parrot.handlers.scheduler`

REST handlers for Parrot scheduler management.

## Classes

- **`SchedulerCatalogHelper(BaseHandler)`** — Helper for scheduler metadata exposed through REST endpoints.
- **`SchedulerCallbacksHandler(BaseView)`** — List supported scheduler callbacks and scheduler types.
- **`SchedulerJobsHandler(BaseView)`** — CRUD handler for scheduler jobs persisted in APScheduler and Postgres.
