---
type: Wiki Summary
title: parrot_tools.interfaces.workday.handlers.custom_report
id: mod:parrot_tools.interfaces.workday.handlers.custom_report
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Generic type handler for Workday RaaS (Reports as a Service) custom reports.
relates_to:
- concept: class:parrot_tools.interfaces.workday.handlers.custom_report.CustomReportType
  rel: defines
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.interfaces.http
  rel: references
- concept: mod:parrot_tools.interfaces.workday.handlers.base
  rel: references
- concept: mod:parrot_tools.interfaces.workday.utils
  rel: references
---

# `parrot_tools.interfaces.workday.handlers.custom_report`

Generic type handler for Workday RaaS (Reports as a Service) custom reports.

This handler can execute ANY Workday custom report without requiring
specific type implementations. It uses dynamic parameter passing and
automatic DataFrame generation from XML responses with dynamic parsing.

## Classes

- **`CustomReportType(WorkdayTypeBase)`** — Generic handler for ANY Workday RaaS custom report.
