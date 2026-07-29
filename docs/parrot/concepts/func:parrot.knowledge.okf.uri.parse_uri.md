---
type: Concept
title: parse_uri()
id: func:parrot.knowledge.okf.uri.parse_uri
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Parse a ``knowledge://`` or legacy ``pageindex://`` URI.
---

# parse_uri

```python
def parse_uri(uri: str) -> tuple[str, str]
```

Parse a ``knowledge://`` or legacy ``pageindex://`` URI.

Returns a ``(index_type, identifier)`` tuple:
- For ``knowledge://`` URIs: ``index_type`` is the first path segment;
  ``identifier`` is everything after the first ``/``.
- For ``pageindex://`` URIs: ``index_type = "pageindex"``;
  ``identifier`` is the entire path (``tree/node``).

Args:
    uri: URI string to parse.

Returns:
    Tuple of ``(index_type, identifier)``.

Raises:
    ValueError: If the URI has no scheme, a malformed path, or an
        unrecognised scheme.

Examples:
    >>> parse_uri("knowledge://graphindex/node-123")
    ('graphindex', 'node-123')
    >>> parse_uri("pageindex://my-tree/my-node")
    ('pageindex', 'my-tree/my-node')
