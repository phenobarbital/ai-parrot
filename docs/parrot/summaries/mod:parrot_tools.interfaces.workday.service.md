---
type: Wiki Summary
title: parrot_tools.interfaces.workday.service
id: mod:parrot_tools.interfaces.workday.service
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: WorkdayService — self-contained Workday operational interface.
relates_to:
- concept: class:parrot_tools.interfaces.workday.service.WorkdayService
  rel: defines
- concept: mod:parrot.interfaces.soap
  rel: references
- concept: mod:parrot_tools.interfaces.workday.config
  rel: references
- concept: mod:parrot_tools.interfaces.workday.handlers
  rel: references
- concept: mod:parrot_tools.interfaces.workday.handlers.location_hierarchy_assignments
  rel: references
- concept: mod:parrot_tools.interfaces.workday.handlers.organization_single
  rel: references
- concept: mod:parrot_tools.interfaces.workday.models.applicant
  rel: references
- concept: mod:parrot_tools.interfaces.workday.models.candidate
  rel: references
- concept: mod:parrot_tools.interfaces.workday.models.clock_event
  rel: references
- concept: mod:parrot_tools.interfaces.workday.models.cost_center
  rel: references
- concept: mod:parrot_tools.interfaces.workday.models.job_posting
  rel: references
- concept: mod:parrot_tools.interfaces.workday.models.job_posting_site
  rel: references
- concept: mod:parrot_tools.interfaces.workday.models.job_requisition
  rel: references
- concept: mod:parrot_tools.interfaces.workday.models.location
  rel: references
- concept: mod:parrot_tools.interfaces.workday.models.organizations
  rel: references
- concept: mod:parrot_tools.interfaces.workday.models.reference
  rel: references
- concept: mod:parrot_tools.interfaces.workday.models.time_block
  rel: references
- concept: mod:parrot_tools.interfaces.workday.models.time_off_balance
  rel: references
- concept: mod:parrot_tools.interfaces.workday.models.time_off_eligibility
  rel: references
- concept: mod:parrot_tools.interfaces.workday.models.time_request
  rel: references
- concept: mod:parrot_tools.interfaces.workday.models.worker
  rel: references
---

# `parrot_tools.interfaces.workday.service`

WorkdayService — self-contained Workday operational interface.

Usable without any ``FlowComponent`` (G2). Implements the operational core:
OAuth/Basic-auth lifecycle (via SOAPClient), WSDL routing, eager handler
registry, and the four public data methods.

Public API
----------
- ``fetch(operation_type, **params) -> pd.DataFrame``   — dispatch to handler
- ``fetch_models(operation_type, **params) -> list``    — typed Pydantic (C7)
- ``get_custom_report(report_name, ...) -> pd.DataFrame`` — RaaS custom report
- ``call_operation(operation, **kwargs)``               — raw SOAP (for handlers)
- ``start() / close()``                                 — lifecycle (from SOAPClient)

Auth branching
--------------
Reproduces ``workday.py:362-445`` exactly:
- REST custom report (``custom_report``, ``custom_punch_field_report_rest``,
  ``extract_*``) → Basic Auth (report_username / report_password).
- SOAP custom report (anything ending in ``_report`` that is not a REST
  custom report) → OAuth + Proxy_User_Name in SOAP body.
- Everything else → OAuth only.

## Classes

- **`WorkdayService(SOAPClient)`** — Workday operational interface — composable without a FlowComponent.
