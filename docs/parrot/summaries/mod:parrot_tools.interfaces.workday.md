---
type: Wiki Summary
title: parrot_tools.interfaces.workday
id: mod:parrot_tools.interfaces.workday
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: parrot_tools.interfaces.workday — Workday operational interface package.
---

# `parrot_tools.interfaces.workday`

parrot_tools.interfaces.workday — Workday operational interface package.

Intentionally lightweight: this __init__.py imports NOTHING heavy (no zeep,
httpx, redis) so that ``import parrot_tools.interfaces`` stays fast (G7).

Heavy symbols (WorkdayService, WorkdayConfig) are exposed via this package
only when explicitly imported by the caller:

    from parrot_tools.interfaces.workday.config import WorkdayConfig
    from parrot_tools.interfaces.workday.service import WorkdayService  # (TASK-103)

The lazy registration in ``parrot_tools/interfaces/__init__.py`` (TASK-106) will
make these available through ``parrot_tools.interfaces.WorkdayService`` without
eagerly loading zeep at startup.
