---
type: Wiki Summary
title: parrot_tools.odoo
id: mod:parrot_tools.odoo
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Odoo Toolkit for AI-Parrot.
relates_to:
- concept: mod:parrot_tools
  rel: references
- concept: mod:parrot_tools.toolkit
  rel: references
---

# `parrot_tools.odoo`

Odoo Toolkit for AI-Parrot.

Exposes Odoo ERP CRUD + business helpers (partner / sales / invoicing /
binary uploads) as agent tools, with auto-detected JSON-2 (Odoo 19+) or
XML-RPC (14-18) transport. Legacy JSON-RPC remains available explicitly for
compatibility.

Usage:
    from parrot_tools.odoo import OdooToolkit

    toolkit = OdooToolkit(
        url="https://my.odoo.com",
        database="prod",
        username="alice@acme.com",
        password="...",
        protocol="auto",
    )
    tools = toolkit.get_tools()
