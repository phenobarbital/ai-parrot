---
type: Wiki Summary
title: parrot.scheduler.functions
id: mod:parrot.scheduler.functions
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Module parrot.scheduler.functions
relates_to:
- concept: class:parrot.scheduler.functions.BaseSchedulerCallback
  rel: defines
- concept: class:parrot.scheduler.functions.CreateFileCallback
  rel: defines
- concept: class:parrot.scheduler.functions.SaveDataCallback
  rel: defines
- concept: class:parrot.scheduler.functions.SendEmailReportCallback
  rel: defines
- concept: class:parrot.scheduler.functions.SendNotifyReportCallback
  rel: defines
---

# `parrot.scheduler.functions`

## Classes

- **`BaseSchedulerCallback(NotificationMixin)`** — Base class for scheduler callbacks executed after successful jobs.
- **`SendEmailReportCallback(BaseSchedulerCallback)`**
- **`CreateFileCallback(BaseSchedulerCallback)`**
- **`SaveDataCallback(BaseSchedulerCallback)`**
- **`SendNotifyReportCallback(BaseSchedulerCallback)`**

## Functions

- `def list_supported_callbacks() -> List[Dict[str, Any]]`
- `def build_scheduler_callback(definition: Dict[str, Any], logger=None) -> BaseSchedulerCallback`
