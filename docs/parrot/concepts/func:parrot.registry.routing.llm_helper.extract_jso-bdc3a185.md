---
type: Concept
title: extract_json_from_response()
id: func:parrot.registry.routing.llm_helper.extract_json_from_response
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Extract the first JSON object from an LLM response.
---

# extract_json_from_response

```python
def extract_json_from_response(response: Any) -> Optional[dict]
```

Extract the first JSON object from an LLM response.

Supports:
* Objects with a ``.output`` attribute (``AIMessage`` style).
* Objects with a ``.content`` attribute.
* Plain ``str`` — the first ``{...}`` block is extracted.
* Plain ``dict`` — returned as-is.
* Any other type / unparseable input → ``None``.

Args:
    response: Raw response from ``invoke()`` or a test fixture.

Returns:
    A parsed ``dict``, or ``None`` when parsing fails.
