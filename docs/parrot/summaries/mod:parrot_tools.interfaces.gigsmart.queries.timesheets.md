---
type: Wiki Summary
title: parrot_tools.interfaces.gigsmart.queries.timesheets
id: mod:parrot_tools.interfaces.gigsmart.queries.timesheets
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: GraphQL query and mutation strings for the GigSmart timesheets and disputes
  surfaces.
---

# `parrot_tools.interfaces.gigsmart.queries.timesheets`

GraphQL query and mutation strings for the GigSmart timesheets and disputes surfaces.

Key facts from schema introspection:
- Only two timesheet mutations: ``approveEngagementTimesheet`` (approve) and
  ``removeEngagementTimesheet`` (reject/send back — worker can resubmit).
- No ``editTimesheet`` mutation exists.
- Disputes are separate: ``addEngagementDispute`` and ``setEngagementDisputeApproval``.
