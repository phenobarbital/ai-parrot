---
type: Wiki Summary
title: parrot.knowledge.graphindex.extractors.odoo_code
id: mod:parrot.knowledge.graphindex.extractors.odoo_code
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Odoo-aware code extractor for GraphIndex (FEAT-240).
relates_to:
- concept: class:parrot.knowledge.graphindex.extractors.odoo_code.OdooCodeExtractor
  rel: defines
- concept: mod:parrot.knowledge.graphindex.extractors.code
  rel: references
- concept: mod:parrot.knowledge.graphindex.schema
  rel: references
---

# `parrot.knowledge.graphindex.extractors.odoo_code`

Odoo-aware code extractor for GraphIndex (FEAT-240).

Subclasses CodeExtractor to capture Odoo model semantics — ``_name`` /
``_inherit`` / ``_inherits``, ``fields.*`` declarations and ``@api.*``
decorators — emitting ``EXTENDS`` edges to canonical model nodes.

All Odoo specifics live in ``domain_tags``; the only schema-level addition
is ``EdgeKind.EXTENDS`` (added by TASK-1571).  Non-Odoo classes fall back
transparently to the base ``CodeExtractor``.

## Classes

- **`OdooCodeExtractor(CodeExtractor)`** — Extract Odoo model structure on top of the generic code extractor.
