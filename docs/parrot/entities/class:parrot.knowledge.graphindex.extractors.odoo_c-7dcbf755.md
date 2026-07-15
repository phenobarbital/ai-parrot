---
type: Wiki Entity
title: OdooCodeExtractor
id: class:parrot.knowledge.graphindex.extractors.odoo_code.OdooCodeExtractor
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Extract Odoo model structure on top of the generic code extractor.
relates_to:
- concept: class:parrot.knowledge.graphindex.extractors.code.CodeExtractor
  rel: extends
---

# OdooCodeExtractor

Defined in [`parrot.knowledge.graphindex.extractors.odoo_code`](../summaries/mod:parrot.knowledge.graphindex.extractors.odoo_code.md).

```python
class OdooCodeExtractor(CodeExtractor)
```

Extract Odoo model structure on top of the generic code extractor.

Only ``_extract_class`` is overridden.  Non-Odoo classes delegate to the
base implementation, so mixing Odoo and plain Python in one repository is
transparent.

Emitted node types (in ``domain_tags["symbol_type"]``):
- ``odoo_model_class`` — the concrete Python class in the file
- ``odoo_model`` — canonical model node with synthetic ``source_uri``
- ``odoo_field`` — ``fields.X(...)`` declarations inside the class
- ``function`` — regular methods (unchanged from base); decorated ones
  carry ``domain_tags["decorators"]`` with ``@api.*`` metadata

Emitted edge kinds beyond the base extractor:
- ``EdgeKind.DEFINES`` — class → canonical model (when ``_name`` present)
- ``EdgeKind.EXTENDS`` — class → canonical model (for each ``_inherit`` /
  ``_inherits`` name that differs from ``_name``)
