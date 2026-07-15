---
type: Wiki Summary
title: parrot_tools.odoo.smart_fields
id: mod:parrot_tools.odoo.smart_fields
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Smart field selection heuristic for OdooToolkit.
relates_to:
- concept: func:parrot_tools.odoo.smart_fields.select_smart_fields
  rel: defines
---

# `parrot_tools.odoo.smart_fields`

Smart field selection heuristic for OdooToolkit.

When an agent omits ``fields`` in ``search_records`` or ``get_record``, Odoo
returns every field on the model — including binary blobs, HTML columns, audit
timestamps, and dozens of technical relational fields that flood the LLM context
with irrelevant noise.

This module provides :func:`select_smart_fields`, a **pure function** (no I/O,
no async) that scores a ``fields_get`` metadata dict and returns the top N most
"agent-useful" field names.

Inspired by the ``tuanle96/mcp-odoo`` project's scoring heuristic.

## Functions

- `def select_smart_fields(fields_metadata: dict[str, Any], max_fields: int=15, always_include: list[str] | None=None) -> list[str]` — Select the most LLM-useful fields from an Odoo ``fields_get`` response.
