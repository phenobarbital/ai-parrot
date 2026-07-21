---
type: Concept
title: build_uri()
id: func:parrot.knowledge.okf.uri.build_uri
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Build a ``knowledge://`` URI for cross-index addressing.
---

# build_uri

```python
def build_uri(index_type: str, identifier: str) -> str
```

Build a ``knowledge://`` URI for cross-index addressing.

Args:
    index_type: Index namespace, e.g. ``"graphindex"`` or ``"pageindex"``.
    identifier: Node identifier within the index.  May contain slashes.

Returns:
    URI string of the form ``knowledge://<index_type>/<identifier>``.

Raises:
    ValueError: If ``index_type`` or ``identifier`` is empty.

Examples:
    >>> build_uri("graphindex", "node-123")
    'knowledge://graphindex/node-123'
    >>> build_uri("pageindex", "tree/concept-id")
    'knowledge://pageindex/tree/concept-id'
