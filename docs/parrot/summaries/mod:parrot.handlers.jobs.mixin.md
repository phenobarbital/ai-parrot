---
type: Wiki Summary
title: parrot.handlers.jobs.mixin
id: mod:parrot.handlers.jobs.mixin
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'JobManagerMixin: A mixin class to add asynchronous job execution capabilities
  to views.'
relates_to:
- concept: class:parrot.handlers.jobs.mixin.AsyncJobManagerMixin
  rel: defines
- concept: class:parrot.handlers.jobs.mixin.JobManagerMixin
  rel: defines
- concept: mod:parrot.handlers.jobs.job
  rel: references
---

# `parrot.handlers.jobs.mixin`

JobManagerMixin: A mixin class to add asynchronous job execution capabilities to views.

This mixin provides:
- A decorator to enqueue functions to be executed by a job manager
- GET method override to check and retrieve job results by job_id

## Classes

- **`JobManagerMixin`** — Mixin class to add job manager functionality to any BaseView.
- **`AsyncJobManagerMixin`** — Async-native mixin for aiohttp views with job manager functionality.
