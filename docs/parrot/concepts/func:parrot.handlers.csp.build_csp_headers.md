---
type: Concept
title: build_csp_headers()
id: func:parrot.handlers.csp.build_csp_headers
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Build the full CSP + security header set.
---

# build_csp_headers

```python
def build_csp_headers(*, js_bundles: Iterable[object]=(), frame_ancestors: str="'self'") -> Mapping[str, str]
```

Build the full CSP + security header set.

Args:
    js_bundles: Iterable of ``JSBundle`` instances (may be empty).
        Only bundles with ``scope='cdn'`` and a non-empty ``url``
        contribute to ``script-src``.
    frame_ancestors: Space-separated ``frame-ancestors`` value.
        Defaults to ``'self'`` which prevents all embedding.
        Pass the value of ``INFOGRAPHIC_FRAME_ANCESTORS`` from env.

Returns:
    Dict mapping header name → header value.  All keys are ready to
    be passed to ``web.Response(headers=...)``.
