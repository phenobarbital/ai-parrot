---
type: Concept
title: derive_concept_id()
id: func:parrot.knowledge.pageindex.okf.concept_id.derive_concept_id
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Derive a deterministic concept_id slug from a title.
---

# derive_concept_id

```python
def derive_concept_id(title: str, parent_path: str='') -> str
```

Derive a deterministic concept_id slug from a title.

The slug is scoped under ``parent_path`` using a ``/`` separator, encoding
the hierarchy level (e.g. ``controls/nist-800-53/ir-4``).

Note: forward slashes in ``parent_path`` are preserved and encode hierarchy;
they are NOT filesystem path separators here.  The projection layer handles
flattening for storage.

Args:
    title: Node title string (human-readable).
    parent_path: Optional parent scope prefix
        (e.g. ``"controls/nist-800-53"``).

Returns:
    Deterministic slug, e.g.  ``"aws-incident-response"``
    or ``"controls/nist-800-53/ir-4"``.

Examples:
    >>> derive_concept_id("AWS Incident Response")
    'aws-incident-response'
    >>> derive_concept_id("IR-4", "controls/nist-800-53")
    'controls/nist-800-53/ir-4'
