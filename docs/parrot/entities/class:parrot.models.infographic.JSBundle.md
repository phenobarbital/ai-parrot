---
type: Wiki Entity
title: JSBundle
id: class:parrot.models.infographic.JSBundle
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Declarative JavaScript bundle attached to an InfographicTemplate.
---

# JSBundle

Defined in [`parrot.models.infographic`](../summaries/mod:parrot.models.infographic.md).

```python
class JSBundle(BaseModel)
```

Declarative JavaScript bundle attached to an InfographicTemplate.

When ``scope='cdn'``, the ``url`` and ``sri_hash`` fields are required so
the HTML-serving CSP can whitelist the origin and SRI hash.  When
``scope='inline'``, the ``inline`` field must contain the JavaScript
source verbatim.

The enhance prompt lists the allowed bundles to the LLM; the
``build_csp_headers`` helper (parrot/handlers/csp.py) uses the ``url``
origins to build the ``script-src`` directive.

Example (CDN)::

    JSBundle(
        name="echarts",
        scope="cdn",
        url="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js",
        sri_hash="sha384-AAAA...",
    )

Example (inline)::

    JSBundle(name="sparkline", scope="inline", inline="/* sparkline js */")
