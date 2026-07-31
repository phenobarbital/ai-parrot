---
type: Concept
title: build_head()
id: func:parrot.tools.interactive.catalog_registry.build_head
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Assemble the ``<head>`` injection for a skeleton's ``<!--HEAD-->`` marker.
---

# build_head

```python
def build_head(bundles: Iterable[JSBundle], theme: Optional[str]=None) -> str
```

Assemble the ``<head>`` injection for a skeleton's ``<!--HEAD-->`` marker.

Emits the base stylesheet, optional theme overrides, then the allow-listed
bundle tags (stylesheets first, then scripts) so the libraries are available
before any inline content runs.

Args:
    bundles: The resolved bundles to inject (script + stylesheet).
    theme: Optional theme name applied as CSS-variable overrides.

Returns:
    An HTML fragment safe to splice into a document ``<head>``.
