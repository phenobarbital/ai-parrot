---
type: Wiki Summary
title: parrot_tools.odoo.models.entities
id: mod:parrot_tools.odoo.models.entities
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Pydantic entity models for the most-used Odoo objects.
relates_to:
- concept: class:parrot_tools.odoo.models.entities.AccountMove
  rel: defines
- concept: class:parrot_tools.odoo.models.entities.AccountMoveLine
  rel: defines
- concept: class:parrot_tools.odoo.models.entities.CrmLead
  rel: defines
- concept: class:parrot_tools.odoo.models.entities.HrEmployee
  rel: defines
- concept: class:parrot_tools.odoo.models.entities.HrLeave
  rel: defines
- concept: class:parrot_tools.odoo.models.entities.ProductProduct
  rel: defines
- concept: class:parrot_tools.odoo.models.entities.ProductTemplate
  rel: defines
- concept: class:parrot_tools.odoo.models.entities.ResPartner
  rel: defines
- concept: class:parrot_tools.odoo.models.entities.ResUsers
  rel: defines
- concept: class:parrot_tools.odoo.models.entities.SaleOrder
  rel: defines
- concept: class:parrot_tools.odoo.models.entities.SaleOrderLine
  rel: defines
- concept: class:parrot_tools.odoo.models.entities.StockPicking
  rel: defines
---

# `parrot_tools.odoo.models.entities`

Pydantic entity models for the most-used Odoo objects.

All models set ``extra='allow'`` so unknown Odoo fields round-trip cleanly:
this lets the toolkit support custom modules and minor schema drift without
requiring a model bump.

Many2one fields in Odoo serialise as ``[id, display_name]`` or ``False`` when
empty; we model them as ``Optional[Many2one]`` (a tuple/list of length 2).
One2many and Many2many serialise as lists of integer ids.

## Classes

- **`ResPartner(_OdooEntity)`** — Subset of ``res.partner`` fields most agents need.
- **`ResUsers(_OdooEntity)`** — Subset of ``res.users`` fields.
- **`ProductTemplate(_OdooEntity)`** — Subset of ``product.template`` fields.
- **`ProductProduct(_OdooEntity)`** — Subset of ``product.product`` fields (variants).
- **`SaleOrderLine(_OdooEntity)`** — Subset of ``sale.order.line`` fields.
- **`SaleOrder(_OdooEntity)`** — Subset of ``sale.order`` fields.
- **`AccountMoveLine(_OdooEntity)`** — Subset of ``account.move.line`` fields.
- **`AccountMove(_OdooEntity)`** — Subset of ``account.move`` fields (invoices, bills, journal entries).
- **`CrmLead(_OdooEntity)`** — Subset of ``crm.lead`` fields.
- **`StockPicking(_OdooEntity)`** — Subset of ``stock.picking`` fields (delivery / receipt orders).
- **`HrEmployee(_OdooEntity)`** — Subset of ``hr.employee`` fields most agents need.
- **`HrLeave(_OdooEntity)`** — Subset of ``hr.leave`` (leave allocation/request) fields.
