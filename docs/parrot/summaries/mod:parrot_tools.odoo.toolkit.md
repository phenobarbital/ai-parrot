---
type: Wiki Summary
title: parrot_tools.odoo.toolkit
id: mod:parrot_tools.odoo.toolkit
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: OdooToolkit — exposes Odoo ERP operations as agent tools.
relates_to:
- concept: class:parrot_tools.odoo.toolkit.OdooToolkit
  rel: defines
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.interfaces.odoointerface
  rel: references
- concept: mod:parrot.tools.decorators
  rel: references
- concept: mod:parrot.tools.toolkit
  rel: references
- concept: mod:parrot_tools.odoo.models.entities
  rel: references
- concept: mod:parrot_tools.odoo.models.envelopes
  rel: references
- concept: mod:parrot_tools.odoo.models.inputs
  rel: references
- concept: mod:parrot_tools.odoo.shell
  rel: references
- concept: mod:parrot_tools.odoo.smart_fields
  rel: references
- concept: mod:parrot_tools.odoo.transport
  rel: references
---

# `parrot_tools.odoo.toolkit`

OdooToolkit — exposes Odoo ERP operations as agent tools.

Composes an :class:`~parrot_tools.odoo.transport.AbstractOdooTransport`
(JSON-2 for Odoo 19+, XML-RPC for 14-18, or auto-detected) and turns
each public async method into a tool via :class:`AbstractToolkit`.

Inspired by:
- ``pantalytics/odoo-mcp-pro`` — for the result-envelope pattern, the bulk
  CRUD layout and the binary upload helper.
- ``phenobarbital/flowtask`` ``OdooInjector`` — for the ``import_records``
  upsert use case (Odoo's ``load`` with external IDs).

Configuration falls back to the ``ODOO_*`` keys in :mod:`parrot.conf` when
constructor arguments are omitted.

## Classes

- **`OdooToolkit(AbstractToolkit)`** — Toolkit exposing Odoo ERP CRUD + business helpers as agent tools.
