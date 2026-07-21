---
type: Concept
title: walk_jsonld()
id: func:parrot.utils.jsonld_extractors.walk_jsonld
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Recursively walk a JSON-LD structure dispatching typed nodes to extractors.
---

# walk_jsonld

```python
def walk_jsonld(data: Any, items: List[JsonLdItem], allowed_types: Optional[set]=None) -> None
```

Recursively walk a JSON-LD structure dispatching typed nodes to extractors.

This is the single authoritative implementation of the JSON-LD graph
traversal algorithm, shared by ``WebScrapingLoader._walk_jsonld_node``
and the executor's ``_action_extract_jsonld``.  Both callers delegate
here so that any future fix or extension only needs to be applied once.

Handles:
- Top-level arrays of nodes.
- ``@graph`` containers (Google's recommended form).
- Single typed objects dispatched via :data:`EXTRACTOR_REGISTRY`.
- Nodes with ``@type`` as a list (valid per JSON-LD spec).

Declaration order of ``EXTRACTOR_REGISTRY`` determines priority: when a
node carries multiple ``@type`` values the first matching key wins.

Args:
    data: Parsed JSON-LD value (dict, list, or scalar).  Scalars are
        silently ignored.
    items: Accumulator list; extracted :class:`JsonLdItem` instances are
        appended in-place.
    allowed_types: Optional whitelist of ``@type`` strings.  ``None``
        (default) means all registered types are extracted.  An empty
        ``set()`` disables extraction for the subtree.
