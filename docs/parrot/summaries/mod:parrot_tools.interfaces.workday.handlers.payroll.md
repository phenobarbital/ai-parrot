---
type: Wiki Summary
title: parrot_tools.interfaces.workday.handlers.payroll
id: mod:parrot_tools.interfaces.workday.handlers.payroll
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Workday Payroll read handlers (FEAT-232).
relates_to:
- concept: class:parrot_tools.interfaces.workday.handlers.payroll.CompanyPaymentDatesType
  rel: defines
- concept: class:parrot_tools.interfaces.workday.handlers.payroll.PayrollBalancesType
  rel: defines
- concept: class:parrot_tools.interfaces.workday.handlers.payroll.PayrollResultsType
  rel: defines
- concept: mod:parrot_tools.interfaces.workday.handlers.base
  rel: references
---

# `parrot_tools.interfaces.workday.handlers.payroll`

Workday Payroll read handlers (FEAT-232).

Single-call read handlers for the Workday Payroll WSDL, ported verbatim from the
former in-line ``WorkdaySOAPClient`` payroll methods in
``parrot_tools/workday/tool.py`` (operations + payload shapes preserved). Each
issues exactly one ``self.service.call_operation(operation=...)`` and returns a
JSON-serializable ``dict`` / ``list[dict]`` (no DataFrame) via zeep
``serialize_object`` — matching the legacy return shapes.

NOTE: operation names + payloads mirror the legacy implementation. The Payroll
WSDL (``payroll_v45_2.wsdl``) is not bundled in this checkout's ``env/workday/``;
unit tests mock ``call_operation`` and live calls require the WSDL to be present.

## Classes

- **`PayrollBalancesType(WorkdayTypeBase)`** — Get_Payroll_Balances — payroll balances for a worker.
- **`PayrollResultsType(WorkdayTypeBase)`** — Get_Payroll_Results — historical / off-cycle payroll results for a worker.
- **`CompanyPaymentDatesType(WorkdayTypeBase)`** — Get_Company_Payment_Dates — company payment dates in a window.
