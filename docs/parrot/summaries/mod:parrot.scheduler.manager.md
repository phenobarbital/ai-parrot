---
type: Wiki Summary
title: parrot.scheduler.manager
id: mod:parrot.scheduler.manager
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Agent Scheduler Module for AI-Parrot.
relates_to:
- concept: class:parrot.scheduler.manager.AgentSchedulerManager
  rel: defines
- concept: class:parrot.scheduler.manager.ScheduleType
  rel: defines
- concept: class:parrot.scheduler.manager.SchedulerHandler
  rel: defines
- concept: func:parrot.scheduler.manager.schedule
  rel: defines
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.handlers.scheduler
  rel: references
- concept: mod:parrot.notifications
  rel: references
- concept: mod:parrot.scheduler.functions
  rel: references
- concept: mod:parrot.scheduler.models
  rel: references
---

# `parrot.scheduler.manager`

Agent Scheduler Module for AI-Parrot.

This module provides scheduling capabilities for agents using APScheduler,
allowing agents to execute operations at specified intervals.

## Classes

- **`ScheduleType(Enum)`** — Schedule execution types.
- **`AgentSchedulerManager`** — Manager for scheduling agent operations using APScheduler.
- **`SchedulerHandler(CorsViewMixin, web.View)`** — HTTP handler for schedule management.

## Functions

- `def schedule(schedule_type: ScheduleType=ScheduleType.DAILY, *, success_callback: Optional[Callable]=None, send_result: Optional[Dict[str, Any]]=None, callbacks: Optional[List[Dict[str, Any]]]=None, **schedule_config)` — Decorator to mark agent methods for scheduling.
