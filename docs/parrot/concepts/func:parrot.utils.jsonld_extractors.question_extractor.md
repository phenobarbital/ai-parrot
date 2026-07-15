---
type: Concept
title: question_extractor()
id: func:parrot.utils.jsonld_extractors.question_extractor
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Extract a bare top-level ``Question`` node.
---

# question_extractor

```python
def question_extractor(node: Dict[str, Any]) -> List[JsonLdItem]
```

Extract a bare top-level ``Question`` node.

The JSON-LD spec permits a ``@type="Question"`` node to appear at the
top level of a block (i.e. not nested inside a ``FAQPage.mainEntity``).
This extractor preserves backward compatibility with the legacy
``_iter_faqpage_pairs`` behaviour that handled this case explicitly.

Produces one ``JsonLdItem`` with the same ``content_kind="faq"`` and
``source_type="faq-jsonld"`` as :func:`faq_extractor` so downstream
consumers see a uniform FAQ item regardless of nesting shape.

Args:
    node: Parsed JSON-LD dict with ``@type="Question"``.

Returns:
    List with one ``JsonLdItem`` (empty list if question or answer is
    absent or blank).
